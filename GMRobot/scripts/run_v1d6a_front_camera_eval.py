#!/usr/bin/env python3
"""V1-D6A: front-view camera grounding probe + conditional production chain.

Phase G: GDINO probe on front-view frames (4 prompts x steps {170,249}),
classified against GT projected boxes (projection empirically calibrated for
this camera pose on two landmarks: UR10e gripper and G1 torso).
Phase T (only if phase G hits at step 170): production-like chain with NO GT
seeding — GDINO text seed -> SAM2 dense tracking (17 frames) -> D4A drift
assessment -> evidence validation -> D5A evidence-gated rule (offline) ->
one VLM analyze for annotation only.

Budget: 8 ground + (17 track + 1 analyze) POSTs. Single run, no retry.
GT is used ONLY for evaluation labels, never for seeding in phase T.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import types
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

if "torch" not in sys.modules:  # host stub for GMRobot.safety.__init__
    _t = types.ModuleType("torch")
    _t.device = lambda *_a, **_k: "cpu"
    _t.tensor = lambda *a, **k: a
    _t.float32 = "float32"
    _t.no_grad = lambda: type("NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None})()
    sys.modules["torch"] = _t
    sys.modules["torch.nn"] = types.ModuleType("torch.nn")

from GMRobot.perception.client import PerceptionClient, PerceptionClientConfig  # noqa: E402
from GMRobot.safety.evidence_gated_rule import decide_dynamic_from_evidence  # noqa: E402
from GMRobot.vlm.client import VLMClient, VLMClientConfig  # noqa: E402
from GMRobot.vlm.prompt_v2 import build_temporal_prompt_v2  # noqa: E402
from GMRobot.vlm.task_context import TaskSemanticContext  # noqa: E402
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    build_temporal_evidence_from_track_result,
    validate_temporal_evidence,
)
from GMRobot.vlm.track_drift import assess_box_drift  # noqa: E402

RUN = "v1d6a_dyn_c_front_camera_capture_20260724"
PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
CAM_POS = (-2.0, -0.15, -0.05)
IMG_W, IMG_H = 640, 480
FX = (18.0 / 20.955) * IMG_W  # same TiledCamera intrinsics as top-down
STEPS = list(range(170, 246, 5)) + [249]
PROMPTS = {
    "P0_baseline": "white humanoid robot",
    "P1_spatial": "small white humanoid robot at the bottom edge of the image",
    "P2_shape": "bipedal humanoid robot with two legs",
    "P3_multiclass": "humanoid robot . robotic arm",
}


def project_front(xyz: Any) -> tuple[float, float] | None:
    """Empirically calibrated projector for the D6A front camera.

    forward=+X (depth), u = W/2 - FX*rel_y/depth, v = H/2 - FX*rel_z/depth.
    Sign of the u term validated on UR10e gripper and G1 torso landmarks.
    """
    rel = [float(xyz[i]) - CAM_POS[i] for i in range(3)]
    depth = rel[0]
    if depth <= 1e-6:
        return None
    u = IMG_W * 0.5 - FX * (rel[1] / depth)
    v = IMG_H * 0.5 - FX * (rel[2] / depth)
    return float(u), float(v)


def _records() -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in (PD / RUN / "meta/body_poses.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[int(r["step"])] = r
    return out


def gt_bbox(recs: dict[int, dict[str, Any]], step: int, pad: float = 30.0) -> list[float]:
    """Upper-body GT bbox (only 8 upper links are recorded; legs excluded)."""
    pts = [project_front(p) for p in recs[step]["g1_bodies"].values()]
    pts = [p for p in pts if p is not None]
    us, vs = [p[0] for p in pts], [p[1] for p in pts]
    return [max(0.0, min(us) - pad), max(0.0, min(vs) - pad),
            min(IMG_W - 1.0, max(us) + pad), min(IMG_H - 1.0, max(vs) + pad)]


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def classify(box: list[float], gt: list[float], ee_uv: tuple[float, float] | None,
             *, pad: float = 40.0, ee_radius: float = 120.0) -> str:
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    if (gt[0] - pad) <= cx <= (gt[2] + pad) and (gt[1] - pad) <= cy <= (gt[3] + pad):
        return "g1_hit"
    if ee_uv and math.hypot(cx - ee_uv[0], cy - ee_uv[1]) <= ee_radius:
        return "ur10e_region"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D6A front camera eval")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    (out / "raw").mkdir(parents=True)

    recs = _records()
    frames: dict[int, np.ndarray] = {}
    for s in STEPS:
        frames[s] = np.array(
            Image.open(PD / RUN / f"scene/frame_{s:06d}_env0.png").convert("RGB"), dtype=np.uint8
        )

    pclient = PerceptionClient(PerceptionClientConfig(
        base_url=args.perception_base_url, timeout_s=300.0, track_target_label="robot",
    ))
    post = 0

    # ---- Phase G: grounding probe
    matrix: list[dict[str, Any]] = []
    for step in (170, 249):
        gt = gt_bbox(recs, step)
        ee_uv = project_front(recs[step]["ur10e_ee"])
        for pid, prompt in PROMPTS.items():
            res = pclient.ground(frames[step], text_prompt=prompt, request_id=f"v1d6a_G_{step}_{pid}")
            post += 1
            (out / "raw" / f"G_{step}_{pid}.json").write_text(json.dumps(res, indent=2) + "\n")
            dets = []
            for d in res.get("detections") or []:
                box = _det_box(d)
                if box is None:
                    continue
                dets.append({
                    "label": d.get("label"), "score": d.get("score", d.get("confidence")),
                    "box": box, "class": classify(box, gt, ee_uv),
                })
            top = max(dets, key=lambda c: float(c["score"] or 0.0)) if dets else None
            sel = top
            if pid == "P3_multiclass" and dets:
                non_arm = [c for c in dets if "arm" not in str(c["label"]).lower()]
                if non_arm:
                    sel = max(non_arm, key=lambda c: float(c["score"] or 0.0))
            matrix.append({
                "step": step, "prompt_id": pid, "n_detections": len(dets),
                "top_class": (top or {}).get("class", "none"),
                "selected_class": (sel or {}).get("class", "none"),
                "selected_score": (sel or {}).get("score"),
                "selected_box": (sel or {}).get("box"),
                "g1_gt_bbox": gt, "detections": dets,
            })

    summary: dict[str, dict[str, int]] = {}
    for row in matrix:
        s = summary.setdefault(row["prompt_id"], {"g1_hit": 0, "ur10e_region": 0, "other": 0, "none": 0})
        s[row["selected_class"]] = s.get(row["selected_class"], 0) + 1
    hits_170 = {r["prompt_id"]: r for r in matrix if r["step"] == 170 and r["selected_class"] == "g1_hit"}

    # ---- Phase T: production-like chain (no GT seed) if grounding works at 170
    phase_t: dict[str, Any] | None = None
    if hits_170:
        best_pid = max(hits_170, key=lambda k: float(hits_170[k]["selected_score"] or 0.0))
        best_prompt = PROMPTS[best_pid]
        session = None
        per_frame: list[dict[str, Any]] = []
        boxes: list[list[float] | None] = []
        last_track: dict[str, Any] | None = None
        prev = STEPS[0]
        for s in STEPS:
            dt_s = max((s - prev) / 60.0, 1.0 / 60.0)
            res, session = pclient.track_frame(
                frames[s], session,
                text_prompt=best_prompt if s == STEPS[0] else None,
            )
            post += 1
            (out / "raw" / f"T_track_{s:06d}.json").write_text(json.dumps(res, indent=2) + "\n")
            t = pclient.pick_primary_track(res, target_label="robot") if res.get("tracks") else None
            gt = gt_bbox(recs, s)
            if t is not None:
                t = pclient.enrich_track_kinematics(t, session=session, dt_s=dt_s)
                box = _det_box(t)
                boxes.append(box)
                per_frame.append({
                    "step": s, "box": box, "speed_px_s": t.get("speed_px_s"),
                    "class": classify(box, gt, project_front(recs[s]["ur10e_ee"])) if box else "none",
                    "g1_gt_bbox": gt,
                })
                last_track = t
            else:
                boxes.append(None)
                per_frame.append({"step": s, "box": None, "class": "none", "g1_gt_bbox": gt})
            prev = s

        drift = assess_box_drift(boxes)
        if last_track is None:
            track_result: dict[str, Any] = {"ok": False}
        else:
            last_track.setdefault("track_state", "tracking")
            last_track.setdefault("label", best_prompt)
            track_result = {
                "ok": True, "tracks": [last_track],
                "session_ref": "session_local",
                "session_continuity_verified": bool(session and session.session_id),
            }
        ev = build_temporal_evidence_from_track_result(
            track_result, source_request_id="v1d6a_T", source_frame_id="v1d6a_T_249",
            drift_suspect=bool(drift["drift_suspect"]),
        )
        ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
        (out / "raw" / "T_evidence_249.json").write_text(json.dumps(ev.to_dict(), indent=2) + "\n")

        # VLM annotation only (prompt v2; the decision is the rule's)
        vclient = VLMClient(VLMClientConfig(
            base_url=args.vlm_base_url, timeout_s=60.0, contract_mode="legacy_v2",
        ))
        ctx = TaskSemanticContext(
            task_name="pick_place", task_phase="idle",
            task_goal_type="place_into_container",
            source_container="container_a", target_container="container_b",
            held_object_class="none", transport_active="false",
            placement_target_occupied="unknown",
            context_source="scenario_protocol", context_sim_step=249,
        )
        prompt2, _ = build_temporal_prompt_v2(task_context=ctx, track_evidence=ev)
        vlm_res = vclient.analyze(frames[249], prompt=prompt2, request_id="v1d6a_T_vlm", frame_id="v1d6a_T_vlm_frm")
        post += 1
        (out / "raw" / "T_vlm_249.json").write_text(json.dumps(vlm_res, indent=2) + "\n")

        decision = decide_dynamic_from_evidence(ev, vlm_annotation=vlm_res)
        n_on = sum(1 for r in per_frame if r["class"] == "g1_hit")
        phase_t = {
            "seed_prompt_id": best_pid, "seed_prompt": best_prompt,
            "no_gt_seeding": True,
            "per_frame": per_frame,
            "on_target": f"{n_on}/{len(per_frame)}",
            "drift_assessment": drift,
            "evidence": ev.to_dict(),
            "rule_decision": decision.to_dict(),
            "end_to_end_dynamic_true_positive": bool(
                decision.dynamic_triggered and n_on / len(per_frame) >= 0.8
            ),
        }

    report = {
        "milestone": "V1-D6A",
        "date": time.strftime("%Y-%m-%d"),
        "capture_run": RUN,
        "camera": {"pos": list(CAM_POS), "rot": [1.0, 0.0, 0.0, 0.0], "view": "front, +X forward"},
        "phase_g_matrix": {"rows": matrix, "summary_by_prompt": summary,
                           "baseline_topdown_d3b": "0/24 g1 hits"},
        "phase_t_production_chain": phase_t,
        "post_count": post,
        "retry_count": 0,
        "boundary": {
            "gt_used_only_for_eval_labels": True,
            "phase_t_seeding_is_text_only_no_gt": True,
            "projection_empirically_calibrated_two_landmarks": True,
            "gt_bbox_upper_body_links_only": True,
        },
    }
    (out / "v1d6a_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "G_summary": summary,
        "T": None if phase_t is None else {
            "seed": phase_t["seed_prompt_id"], "on_target": phase_t["on_target"],
            "drift": phase_t["drift_assessment"]["drift_suspect"],
            "evidence_valid": phase_t["evidence"]["valid"],
            "rule_triggered": phase_t["rule_decision"]["dynamic_triggered"],
            "action": phase_t["rule_decision"]["recommended_action"],
            "vlm_annotation": phase_t["rule_decision"]["vlm_annotation"].get("risk_type"),
            "END_TO_END_TRUE_POSITIVE": phase_t["end_to_end_dynamic_true_positive"],
        },
        "post_count": post,
    }, indent=1))


if __name__ == "__main__":
    main()
