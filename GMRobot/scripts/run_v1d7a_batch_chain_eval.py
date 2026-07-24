#!/usr/bin/env python3
"""V1-D7A: boundary-phase batch production-chain eval (4 front-camera captures).

Per capture: GDINO text seed (P3 multiclass, D6A-validated) -> SAM2 dense
tracking -> D4A drift assessment -> evidence validation -> D5A evidence-gated
rule (offline). No GT seeding; GT projections are used ONLY for eval labels.
No VLM calls (annotation role already validated in D6A).

Preregistered expectations (written before running):
  b1_reverse_sweep: rule triggers; motion bucket flips vs D6A (opposite vy).
  b2_retreat_depth: boundary probe -- G1 approaches camera; box legitimately
    grows, so D4A v1 (size-ratio heuristic) may flag it as drift and cause a
    fail-closed miss. Outcome recorded either way; not counted as regression.
  b3_static_idle: rule must NOT trigger (true negative, speed ~ 0).
  b4_outer_traj: rule triggers (different trajectory family, Dyn-B outer lane).

Budget: 14+16+10+17 = 57 track POSTs. Single run, no retry.
"""

from __future__ import annotations

import argparse
import json
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
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    build_temporal_evidence_from_track_result,
    validate_temporal_evidence,
)
from GMRobot.vlm.track_drift import assess_box_drift  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
CAM_POS = (-2.0, -0.15, -0.05)
IMG_W, IMG_H = 640, 480
FX = (18.0 / 20.955) * IMG_W
SEED_PROMPT = "humanoid robot . robotic arm"  # D6A best (P3_multiclass)

CAPTURES: dict[str, dict[str, Any]] = {
    "b1_reverse_sweep": {
        "run": "v1d7a_b1_reverse_sweep_20260724",
        "steps": list(range(250, 316, 5)),
        "expect": "trigger_with_reversed_bucket",
        "gt_dynamic": True,
    },
    "b2_retreat_depth": {
        "run": "v1d7a_b2_retreat_depth_20260724",
        "steps": list(range(325, 401, 5)),
        "expect": "boundary_probe_depth_motion_d4a_blindspot",
        "gt_dynamic": True,
    },
    "b3_static_idle": {
        "run": "v1d7a_b3_static_idle_20260724",
        "steps": list(range(420, 466, 5)),
        "expect": "no_trigger_true_negative",
        "gt_dynamic": False,
    },
    "b4_outer_traj": {
        "run": "v1d7a_b4_outer_traj_20260724",
        "steps": list(range(165, 246, 5)),
        "expect": "trigger_cross_trajectory",
        "gt_dynamic": True,
    },
}


def project_front(xyz: Any) -> tuple[float, float] | None:
    rel = [float(xyz[i]) - CAM_POS[i] for i in range(3)]
    depth = rel[0]
    if depth <= 1e-6:
        return None
    u = IMG_W * 0.5 - FX * (rel[1] / depth)
    v = IMG_H * 0.5 - FX * (rel[2] / depth)
    return float(u), float(v)


def records(run: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in (PD / run / "meta/body_poses.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[int(r["step"])] = r
    return out


def gt_bbox(recs: dict[int, dict[str, Any]], step: int, pad: float = 30.0) -> list[float] | None:
    pts = [project_front(p) for p in recs[step]["g1_bodies"].values()]
    pts = [p for p in pts if p is not None]
    if not pts:
        return None
    us, vs = [p[0] for p in pts], [p[1] for p in pts]
    return [max(0.0, min(us) - pad), max(0.0, min(vs) - pad),
            min(IMG_W - 1.0, max(us) + pad), min(IMG_H - 1.0, max(vs) + pad)]


def gt_centroid(recs: dict[int, dict[str, Any]], step: int) -> tuple[float, float] | None:
    pts = [project_front(p) for p in recs[step]["g1_bodies"].values()]
    pts = [p for p in pts if p is not None]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def on_gt(box: list[float] | None, gt: list[float] | None, pad: float = 40.0) -> bool:
    if box is None or gt is None:
        return False
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    return (gt[0] - pad) <= cx <= (gt[2] + pad) and (gt[1] - pad) <= cy <= (gt[3] + pad)


def eval_capture(pclient: PerceptionClient, name: str, cfg: dict[str, Any],
                 raw: Path) -> tuple[dict[str, Any], int]:
    recs = records(cfg["run"])
    steps: list[int] = cfg["steps"]
    frames = {
        s: np.array(Image.open(PD / cfg["run"] / f"scene/frame_{s:06d}_env0.png").convert("RGB"),
                    dtype=np.uint8)
        for s in steps
    }
    c0, c1 = gt_centroid(recs, steps[0]), gt_centroid(recs, steps[-1])
    gt_disp_px = (
        None if (c0 is None or c1 is None)
        else float(((c1[0] - c0[0]) ** 2 + (c1[1] - c0[1]) ** 2) ** 0.5)
    )

    session = None
    per_frame: list[dict[str, Any]] = []
    boxes: list[list[float] | None] = []
    last_track: dict[str, Any] | None = None
    post = 0
    prev = steps[0]
    for s in steps:
        dt_s = max((s - prev) / 60.0, 1.0 / 60.0)
        res, session = pclient.track_frame(
            frames[s], session, text_prompt=SEED_PROMPT if s == steps[0] else None,
        )
        post += 1
        (raw / f"{name}_track_{s:06d}.json").write_text(json.dumps(res, indent=2) + "\n")
        t = pclient.pick_primary_track(res, target_label="robot") if res.get("tracks") else None
        gt = gt_bbox(recs, s)
        if t is not None:
            t = pclient.enrich_track_kinematics(t, session=session, dt_s=dt_s)
            box = _det_box(t)
            boxes.append(box)
            per_frame.append({"step": s, "box": box, "speed_px_s": t.get("speed_px_s"),
                              "on_gt": on_gt(box, gt), "g1_gt_bbox": gt})
            last_track = t
        else:
            boxes.append(None)
            per_frame.append({"step": s, "box": None, "on_gt": False, "g1_gt_bbox": gt})
        prev = s

    drift = assess_box_drift(boxes)
    if last_track is None:
        track_result: dict[str, Any] = {"ok": False}
    else:
        last_track.setdefault("track_state", "tracking")
        last_track.setdefault("label", SEED_PROMPT)
        track_result = {
            "ok": True, "tracks": [last_track], "session_ref": "session_local",
            "session_continuity_verified": bool(session and session.session_id),
        }
    ev = build_temporal_evidence_from_track_result(
        track_result, source_request_id=f"v1d7a_{name}",
        source_frame_id=f"v1d7a_{name}_{steps[-1]}",
        drift_suspect=bool(drift["drift_suspect"]),
    )
    ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
    decision = decide_dynamic_from_evidence(ev, vlm_annotation=None)

    n_on = sum(1 for r in per_frame if r["on_gt"])
    triggered = bool(decision.dynamic_triggered)
    gt_dyn = bool(cfg["gt_dynamic"])
    if gt_dyn and triggered:
        outcome = "true_positive"
    elif gt_dyn and not triggered:
        outcome = "miss_fail_closed"
    elif not gt_dyn and not triggered:
        outcome = "true_negative"
    else:
        outcome = "false_positive"

    return {
        "capture": cfg["run"],
        "preregistered_expectation": cfg["expect"],
        "gt_dynamic": gt_dyn,
        "gt_centroid_disp_px_first_to_last": gt_disp_px,
        "on_target": f"{n_on}/{len(per_frame)}",
        "per_frame": per_frame,
        "drift_assessment": drift,
        "evidence": ev.to_dict(),
        "rule_decision": decision.to_dict(),
        "outcome": outcome,
    }, post


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D7A batch chain eval")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    raw = out / "raw"
    raw.mkdir(parents=True)

    pclient = PerceptionClient(PerceptionClientConfig(
        base_url=args.perception_base_url, timeout_s=300.0, track_target_label="robot",
    ))

    results: dict[str, dict[str, Any]] = {}
    post_total = 0
    for name, cfg in CAPTURES.items():
        r, post = eval_capture(pclient, name, cfg, raw)
        results[name] = r
        post_total += post

    report = {
        "milestone": "V1-D7A",
        "date": time.strftime("%Y-%m-%d"),
        "seed_prompt": SEED_PROMPT,
        "captures": results,
        "post_count": post_total,
        "retry_count": 0,
        "boundary": {
            "no_gt_seeding": True,
            "gt_used_only_for_eval_labels": True,
            "no_vlm_calls": True,
            "occlusion_phase_unavailable": "no scripted scenario passes G1 behind the workbench from the front view",
        },
    }
    (out / "v1d7a_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        name: {
            "on_target": r["on_target"],
            "gt_disp_px": r["gt_centroid_disp_px_first_to_last"],
            "last_speed_px_s": r["evidence"].get("speed_px_s"),
            "drift": r["drift_assessment"]["drift_suspect"],
            "evidence_valid": r["evidence"]["valid"],
            "rule_triggered": r["rule_decision"]["dynamic_triggered"],
            "outcome": r["outcome"],
        }
        for name, r in results.items()
    } | {"post_count": post_total}, indent=1))


if __name__ == "__main__":
    main()
