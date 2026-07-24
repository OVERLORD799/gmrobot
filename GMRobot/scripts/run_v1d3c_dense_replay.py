#!/usr/bin/env python3
"""V1-D3C: dense-frame GT-seeded SAM2 replay on the D3C dense capture.

Seeds SAM2 once with the G1 GT projected bbox at step 170 (diagnostic_only),
then propagates through every captured frame (170..245 step 5, plus 249).
Builds SAM2-only temporal evidence at step 249 and POSTs one VLM analyze.
Evidence thresholds and the 0.85 confidence gate are unchanged.
Single run, no retry. POST budget: 17 track + 1 analyze = 18.
"""

from __future__ import annotations

import argparse
import json
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
from scene_camera_override import g1_roi_from_body_points  # noqa: E402

RUN = "v1d3c_dyn_c_dense_capture_20260724"
PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
CAM_POS = [0.45, 0.0, 2.7]
IMG_W, IMG_H = 640, 480
STEPS = list(range(170, 246, 5)) + [249]
CONF_GATE = 0.85


def _body_records() -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in (PD / RUN / "meta/body_poses.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[int(r["step"])] = r
    return out


def _gt_bbox(records: dict[int, dict[str, Any]], step: int) -> list[float]:
    roi = g1_roi_from_body_points(
        list(records[step]["g1_bodies"].values()), cam_pos=CAM_POS,
        image_w=IMG_W, image_h=IMG_H, pad_px=12.0,
    )
    return [float(x) for x in roi["bbox_xyxy"]]


def _center_in(box: list[float], gt: list[float], pad: float = 20.0) -> bool:
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    return (gt[0] - pad) <= cx <= (gt[2] + pad) and (gt[1] - pad) <= cy <= (gt[3] + pad)


def _iou(a: list[float], b: list[float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D3C dense GT-seeded SAM2 replay")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: result dir exists: {out}")
    (out / "raw").mkdir(parents=True)

    records = _body_records()
    frames: dict[int, np.ndarray] = {}
    for s in STEPS:
        p = PD / RUN / f"scene/frame_{s:06d}_env0.png"
        frames[s] = np.array(Image.open(p).convert("RGB"), dtype=np.uint8)

    pclient = PerceptionClient(PerceptionClientConfig(
        base_url=args.perception_base_url, timeout_s=300.0, track_target_label="robot",
    ))
    vclient = VLMClient(VLMClientConfig(
        base_url=args.vlm_base_url, timeout_s=60.0, contract_mode="legacy_v2",
    ))
    post_count = 0

    seed = _gt_bbox(records, 170)
    session = None
    per_frame: list[dict[str, Any]] = []
    last_track: dict[str, Any] | None = None
    prev_step = STEPS[0]
    for s in STEPS:
        dt_s = max((s - prev_step) / 60.0, 1.0 / 60.0)
        res, session = pclient.track_frame(
            frames[s], session,
            box_xyxy=seed if s == STEPS[0] else None,
            text_prompt=None if s == STEPS[0] else None,
        )
        post_count += 1
        (out / "raw" / f"track_{s:06d}.json").write_text(json.dumps(res, indent=2) + "\n")
        tracks = res.get("tracks") or []
        t = pclient.pick_primary_track(res, target_label="robot") if tracks else None
        gt = _gt_bbox(records, s)
        if t is not None:
            t = pclient.enrich_track_kinematics(t, session=session, dt_s=dt_s)
            box = _det_box(t)
            per_frame.append({
                "step": s,
                "box": box,
                "score": t.get("score"),
                "speed_px_s": t.get("speed_px_s"),
                "center_in_gt": _center_in(box, gt) if box else False,
                "iou_gt": _iou(box, gt) if box else 0.0,
                "g1_gt_bbox": gt,
            })
            last_track = t
        else:
            per_frame.append({
                "step": s, "box": None, "score": None, "speed_px_s": None,
                "center_in_gt": False, "iou_gt": 0.0, "g1_gt_bbox": gt,
            })
        prev_step = s

    n_on_target = sum(1 for r in per_frame if r["center_in_gt"])
    if last_track is None:
        track_result: dict[str, Any] = {"ok": False}
    else:
        last_track.setdefault("track_state", "tracking")
        last_track.setdefault("label", "robot")
        track_result = {
            "ok": True, "tracks": [last_track],
            "session_ref": "session_local",
            "session_continuity_verified": bool(session and session.session_id),
        }
    ev = build_temporal_evidence_from_track_result(
        track_result, source_request_id="v1d3c_dense", source_frame_id="v1d3c_step249"
    )
    ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
    (out / "raw" / "evidence_249.json").write_text(json.dumps(ev.to_dict(), indent=2) + "\n")

    ctx = TaskSemanticContext(
        task_name="pick_place", task_phase="idle",
        task_goal_type="place_into_container",
        source_container="container_a", target_container="container_b",
        held_object_class="none", transport_active="false",
        placement_target_occupied="unknown",
        context_source="scenario_protocol", context_sim_step=249,
    )
    prompt, _sha = build_temporal_prompt_v2(task_context=ctx, track_evidence=ev)
    res_v = vclient.analyze(frames[249], prompt=prompt, request_id="v1d3c_p249", frame_id="v1d3c_p249_frm")
    post_count += 1
    (out / "raw" / "analyze_249.json").write_text(json.dumps(res_v, indent=2) + "\n")
    try:
        conf = float(res_v.get("risk_confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0

    gates = {
        "G1_tracking_on_target_ge_80pct": n_on_target / len(per_frame) >= 0.8,
        "G2_evidence_valid": bool(ev.valid),
        "G3_vlm_dynamic_conf_ge_085": res_v.get("risk_type") == "dynamic" and conf >= CONF_GATE,
        "FC_no_dynamic_claim_without_valid_evidence": bool(ev.valid) or not (
            res_v.get("risk_type") == "dynamic" and conf >= CONF_GATE
        ),
    }
    report = {
        "milestone": "V1-D3C",
        "date": time.strftime("%Y-%m-%d"),
        "capture_run": RUN,
        "steps": STEPS,
        "seed_box_gt_170": seed,
        "diagnostic_only_gt_seed": True,
        "per_frame": per_frame,
        "on_target_frames": f"{n_on_target}/{len(per_frame)}",
        "evidence": ev.to_dict(),
        "vlm_output": {"risk_type": res_v.get("risk_type"), "risk_confidence": conf},
        "gates": gates,
        "verdict": (
            "D3C_DENSE_TEMPORAL_CHAIN_PASS"
            if gates["G1_tracking_on_target_ge_80pct"] and gates["G2_evidence_valid"] and gates["G3_vlm_dynamic_conf_ge_085"]
            else "D3C_DENSE_TEMPORAL_CHAIN_FAIL"
        ),
        "post_count": post_count,
        "retry_count": 0,
        "boundary": {
            "gt_used_only_for_initial_seed_and_labels": True,
            "motion_evidence_sam2_only": True,
            "evidence_thresholds_unchanged": {"min_track_score": 0.5, "min_speed_px_s": 10.0},
            "confidence_gate_0_85_unchanged": True,
        },
    }
    (out / "v1d3c_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "on_target": report["on_target_frames"],
        "final_score": (last_track or {}).get("score"),
        "final_speed_px_s": (last_track or {}).get("speed_px_s"),
        "evidence_valid": ev.valid,
        "rejection": ev.rejection_reason,
        "vlm": [res_v.get("risk_type"), conf],
        "gates": gates,
        "verdict": report["verdict"],
        "post_count": post_count,
    }))


if __name__ == "__main__":
    main()
