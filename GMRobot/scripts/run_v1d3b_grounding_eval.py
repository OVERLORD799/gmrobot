#!/usr/bin/env python3
"""V1-D3B: grounding target-selection evaluation (user-approved, 3 sub-phases).

Order: (B) GT-bbox-seeded diagnostic -> (C) probe-set grounding accuracy matrix
-> (A) best-prompt full-chain repair attempt.

Boundaries: GT bbox is used ONLY for target seeding in (B) (diagnostic_only,
never an end-to-end claim) and as evaluation labels in (C). Motion evidence is
always SAM2-derived. Confidence gate 0.85 and evidence thresholds unchanged.
Single run per sub-phase, no retry.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))
sys.path.insert(0, str(REPO / "g1_ur10e_disturbance"))

from GMRobot.perception.client import PerceptionClient, PerceptionClientConfig  # noqa: E402
from GMRobot.vlm.client import VLMClient, VLMClientConfig  # noqa: E402
from GMRobot.vlm.prompt_v2 import build_temporal_prompt_v2  # noqa: E402
from GMRobot.vlm.task_context import TaskSemanticContext  # noqa: E402
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    build_temporal_evidence_from_track_result,
    validate_temporal_evidence,
)
from scene_camera_override import g1_roi_from_body_points, project_world_to_pixel  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
CAM_POS = [0.45, 0.0, 2.7]
IMG_W, IMG_H = 640, 480
DT_S = (249 - 170) / 60.0
CONF_GATE = 0.85

# Probe frames: run -> steps (unique frames of the v1e04 quadrant pairs).
PROBE = {
    "v1e2k_dyn_c_formal_capture_20260724": [170, 249],
    "v1e2d_dyn_c_mirrored_capture_20260723": [240, 310],
    "v1e01_dyn_b_formal_m1z9_20260723": [220, 330],
}
PROMPTS = {
    "P0_baseline": "white humanoid robot",
    "P1_spatial": "small white humanoid robot at the bottom edge of the image",
    "P2_shape": "bipedal humanoid robot with two legs",
    "P3_multiclass": "humanoid robot . robotic arm",
}


def _body_records(run: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in (PD / run / "meta/body_poses.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[int(r["step"])] = r
    return out


def gt_g1_bbox(run: str, step: int, pad_px: float = 12.0) -> list[float]:
    rec = _body_records(run)[step]
    roi = g1_roi_from_body_points(
        list(rec["g1_bodies"].values()), cam_pos=CAM_POS,
        image_w=IMG_W, image_h=IMG_H, pad_px=pad_px,
    )
    return [float(x) for x in roi["bbox_xyxy"]]


def gt_ee_uv(run: str, step: int) -> list[float] | None:
    rec = _body_records(run)[step]
    uv = project_world_to_pixel(rec["ur10e_ee"], cam_pos=CAM_POS, image_w=IMG_W, image_h=IMG_H)
    return [float(uv[0]), float(uv[1])] if uv is not None else None


def _load_rgb(run: str, step: int) -> np.ndarray:
    p = PD / run / f"scene/frame_{step:06d}_env0.png"
    return np.array(Image.open(p).convert("RGB"), dtype=np.uint8)


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def classify_detection(
    box: list[float], g1_bbox: list[float], ee_uv: list[float] | None,
    *, pad: float = 20.0, ee_radius: float = 90.0,
) -> str:
    """Classify a detection box against GT: g1_hit / ur10e_region / other."""
    cx = (box[0] + box[2]) / 2.0
    cy = (box[1] + box[3]) / 2.0
    if (g1_bbox[0] - pad) <= cx <= (g1_bbox[2] + pad) and (g1_bbox[1] - pad) <= cy <= (g1_bbox[3] + pad):
        return "g1_hit"
    if ee_uv is not None and math.hypot(cx - ee_uv[0], cy - ee_uv[1]) <= ee_radius:
        return "ur10e_region"
    return "other"


def _task_context(step: int) -> TaskSemanticContext:
    return TaskSemanticContext(
        task_name="pick_place", task_phase="idle",
        task_goal_type="place_into_container",
        source_container="container_a", target_container="container_b",
        held_object_class="none", transport_active="false",
        placement_target_occupied="unknown",
        context_source="scenario_protocol", context_sim_step=int(step),
    )


def run_track_chain(
    pclient: PerceptionClient, vclient: VLMClient, out: Path, tag: str,
    *, seed_box: list[float] | None, text_prompt: str | None,
) -> dict[str, Any]:
    """Track E2K 170->249 (box- or prompt-seeded), build evidence, POST analyze.

    Returns chain report; increments no global state. 3 POSTs.
    """
    f170 = _load_rgb("v1e2k_dyn_c_formal_capture_20260724", 170)
    f249 = _load_rgb("v1e2k_dyn_c_formal_capture_20260724", 249)
    res_a, session = pclient.track_frame(f170, None, box_xyxy=seed_box, text_prompt=text_prompt)
    (out / f"{tag}_track170.json").write_text(json.dumps(res_a, indent=2) + "\n")

    def _primary(res: dict[str, Any]) -> dict[str, Any] | None:
        if res.get("tracks"):
            return pclient.pick_primary_track(res, target_label="robot")
        return res if _det_box(res) else None

    t_a = _primary(res_a)
    if t_a is not None:
        pclient.enrich_track_kinematics(t_a, session=session, dt_s=DT_S)
    res_b, session = pclient.track_frame(f249, session)
    (out / f"{tag}_track249.json").write_text(json.dumps(res_b, indent=2) + "\n")
    t_b = _primary(res_b)
    continuity = bool(
        res_a.get("ok", True) and res_b.get("ok", True) and session.session_id
        and str(res_b.get("session_id", session.session_id)) == str(session.session_id)
    )
    if t_b is None:
        track_result: dict[str, Any] = {"ok": False}
        tracked_box = None
    else:
        t_b = pclient.enrich_track_kinematics(t_b, session=session, dt_s=DT_S)
        t_b.setdefault("track_state", "tracking")
        t_b.setdefault("label", text_prompt or "robot")
        tracked_box = _det_box(t_b)
        track_result = {
            "ok": True, "tracks": [t_b],
            "session_ref": "session_local",
            "session_continuity_verified": continuity,
        }
    ev = build_temporal_evidence_from_track_result(
        track_result, source_request_id=f"v1d3b_{tag}", source_frame_id=f"v1d3b_{tag}_frm170"
    )
    ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
    (out / f"{tag}_evidence.json").write_text(json.dumps(ev.to_dict(), indent=2) + "\n")
    prompt, _sha = build_temporal_prompt_v2(task_context=_task_context(249), track_evidence=ev)
    res_v = vclient.analyze(f249, prompt=prompt, request_id=f"v1d3b_{tag}", frame_id=f"v1d3b_{tag}_frm")
    (out / f"{tag}_analyze.json").write_text(json.dumps(res_v, indent=2) + "\n")
    try:
        conf = float(res_v.get("risk_confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    g1_box = gt_g1_bbox("v1e2k_dyn_c_formal_capture_20260724", 249)
    ee = gt_ee_uv("v1e2k_dyn_c_formal_capture_20260724", 249)
    return {
        "tracked_box_249": tracked_box,
        "tracked_box_class": classify_detection(tracked_box, g1_box, ee) if tracked_box else "none",
        "speed_px_s": float(ev.speed_px_s),
        "evidence_valid": bool(ev.valid),
        "evidence_rejection": ev.rejection_reason,
        "session_continuity": continuity,
        "vlm_risk_type": res_v.get("risk_type"),
        "vlm_confidence": conf,
        "chain_pass": bool(ev.valid and res_v.get("risk_type") == "dynamic" and conf >= CONF_GATE),
        "post_count": 3,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D3B grounding target-selection eval")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: result dir exists: {out}")
    (out / "raw").mkdir(parents=True)
    raw = out / "raw"

    pclient = PerceptionClient(PerceptionClientConfig(
        base_url=args.perception_base_url, timeout_s=300.0, track_target_label="robot",
    ))
    vclient = VLMClient(VLMClientConfig(
        base_url=args.vlm_base_url, timeout_s=60.0, contract_mode="legacy_v2",
    ))
    post_count = 0

    # ---- Phase B: GT-bbox-seeded diagnostic (diagnostic_only, never end-to-end claim)
    seed = gt_g1_bbox("v1e2k_dyn_c_formal_capture_20260724", 170)
    phase_b = run_track_chain(pclient, vclient, raw, "B_gtseed", seed_box=seed, text_prompt=None)
    phase_b["seed_box_gt_170"] = seed
    phase_b["diagnostic_only"] = True
    post_count += phase_b["post_count"]

    # ---- Phase C: probe-set grounding accuracy matrix
    matrix: list[dict[str, Any]] = []
    for run, steps in PROBE.items():
        for step in steps:
            rgb = _load_rgb(run, step)
            g1_box = gt_g1_bbox(run, step)
            ee = gt_ee_uv(run, step)
            for pid, prompt in PROMPTS.items():
                res = pclient.ground(rgb, text_prompt=prompt, request_id=f"v1d3b_C_{run[:6]}_{step}_{pid}")
                post_count += 1
                (raw / f"C_ground_{run[:12]}_{step}_{pid}.json").write_text(json.dumps(res, indent=2) + "\n")
                dets = res.get("detections") or []
                classified = []
                for d in dets:
                    box = _det_box(d)
                    if box is None:
                        continue
                    cls = classify_detection(box, g1_box, ee)
                    classified.append({
                        "label": d.get("label"), "score": d.get("score", d.get("confidence")),
                        "box": box, "class": cls,
                    })
                top = max(classified, key=lambda c: float(c["score"] or 0.0)) if classified else None
                # P3 multiclass post-selection: best non-arm-labeled detection
                selected = top
                if pid == "P3_multiclass" and classified:
                    non_arm = [c for c in classified if "arm" not in str(c["label"]).lower()]
                    if non_arm:
                        selected = max(non_arm, key=lambda c: float(c["score"] or 0.0))
                matrix.append({
                    "run": run, "step": step, "prompt_id": pid,
                    "n_detections": len(classified),
                    "top_class": (top or {}).get("class", "none"),
                    "selected_class": (selected or {}).get("class", "none"),
                    "selected_label": (selected or {}).get("label"),
                    "selected_box": (selected or {}).get("box"),
                    "g1_gt_bbox": g1_box,
                })

    summary: dict[str, dict[str, int]] = {}
    for row in matrix:
        s = summary.setdefault(row["prompt_id"], {"g1_hit": 0, "ur10e_region": 0, "other": 0, "none": 0})
        s[row["selected_class"]] = s.get(row["selected_class"], 0) + 1
    best_pid = max(summary, key=lambda k: summary[k]["g1_hit"])

    # ---- Phase A: best-prompt full-chain repair attempt (pure perception path)
    phase_a: dict[str, Any] | None = None
    if summary[best_pid]["g1_hit"] > 0:
        best_prompt = PROMPTS[best_pid]
        phase_a = run_track_chain(pclient, vclient, raw, "A_bestprompt", seed_box=None, text_prompt=best_prompt)
        phase_a["prompt_id"] = best_pid
        phase_a["prompt"] = best_prompt
        phase_a["end_to_end_eligible"] = True
        post_count += phase_a["post_count"]

    report = {
        "milestone": "V1-D3B",
        "date": time.strftime("%Y-%m-%d"),
        "order_executed": ["B_gt_seed_diagnostic", "C_probe_matrix", "A_best_prompt_chain"],
        "phase_b_gt_seed_diagnostic": phase_b,
        "phase_c_grounding_matrix": {"rows": matrix, "summary_by_prompt": summary, "best_prompt_id": best_pid},
        "phase_a_best_prompt_chain": phase_a,
        "post_count_total": post_count,
        "retry_count": 0,
        "boundary": {
            "gt_used_only_for_seeding_and_labels": True,
            "motion_evidence_sam2_only": True,
            "confidence_gate_0_85_unchanged": True,
            "phase_b_diagnostic_only": True,
        },
    }
    (out / "v1d3b_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "B_chain_pass": phase_b["chain_pass"],
        "B_evidence": phase_b["evidence_rejection"] or "valid",
        "B_vlm": [phase_b["vlm_risk_type"], phase_b["vlm_confidence"]],
        "C_summary": summary,
        "A": None if phase_a is None else {
            "prompt": phase_a["prompt_id"], "chain_pass": phase_a["chain_pass"],
            "vlm": [phase_a["vlm_risk_type"], phase_a["vlm_confidence"]],
        },
        "post_count": post_count,
    }))


if __name__ == "__main__":
    main()
