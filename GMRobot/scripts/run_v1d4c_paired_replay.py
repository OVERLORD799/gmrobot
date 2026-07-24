#!/usr/bin/env python3
"""V1-D4C: paired D4A-drift-rejection + prompt-v3 replay (3 VLM POSTs).

Reuses the recorded D3C dense-replay track data offline (no new perception
POSTs). Three arms on the fixed E2K/D3C step-249 frame:

P1 paired stack:    real drifted SAM2 evidence + D4A drift flag -> evidence
                    rejected -> prompt v3 -> expect NO dynamic claim
                    (specificity: directive must not create false positives).
P2 ablation control: same drifted evidence WITHOUT D4A -> evidence valid
                    (as in D3C) -> prompt v3 -> expected dynamic claim would
                    be a FALSE POSITIVE, demonstrating D4A is necessary.
P3 capability probe: perfect-tracker evidence derived from GT projected boxes
                    (diagnostic_only, synthetic probe) + D4A no-flag ->
                    prompt v3 -> expect dynamic >= 0.85 (sensitivity).

Single run, no retry. GT is used only for the P3 probe and evaluation labels.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))
sys.path.insert(0, str(REPO / "g1_ur10e_disturbance"))

from GMRobot.vlm.client import VLMClient, VLMClientConfig  # noqa: E402
from GMRobot.vlm.prompt_v3 import build_temporal_prompt_v3  # noqa: E402
from GMRobot.vlm.task_context import TaskSemanticContext  # noqa: E402
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    TemporalTrackEvidence,
    validate_temporal_evidence,
)
from GMRobot.vlm.track_drift import assess_box_drift  # noqa: E402
from scene_camera_override import g1_roi_from_body_points  # noqa: E402

D3C_EVAL = REPO / "g1_ur10e_disturbance/results/paper_demo/v1d3c_dense_replay_eval_20260724"
CAPTURE = REPO / "g1_ur10e_disturbance/results/paper_demo/v1d3c_dyn_c_dense_capture_20260724"
FRAME_249 = CAPTURE / "scene/frame_000249_env0.png"
CAM_POS = [0.45, 0.0, 2.7]
CONF_GATE = 0.85
WINDOW_S = (249 - 170) / 60.0


def _ctx() -> TaskSemanticContext:
    return TaskSemanticContext(
        task_name="pick_place", task_phase="idle",
        task_goal_type="place_into_container",
        source_container="container_a", target_container="container_b",
        held_object_class="none", transport_active="false",
        placement_target_occupied="unknown",
        context_source="scenario_protocol", context_sim_step=249,
    )


def _gt_boxes() -> tuple[list[list[float]], list[int]]:
    recs: dict[int, dict[str, Any]] = {}
    for line in (CAPTURE / "meta/body_poses.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            recs[int(r["step"])] = r
    steps = json.loads((D3C_EVAL / "v1d3c_report.json").read_text())["steps"]
    boxes = []
    for s in steps:
        roi = g1_roi_from_body_points(
            list(recs[s]["g1_bodies"].values()), cam_pos=CAM_POS,
            image_w=640, image_h=480, pad_px=12.0,
        )
        boxes.append([float(x) for x in roi["bbox_xyxy"]])
    return boxes, steps


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D4C paired drift-rejection + prompt v3 replay")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: result dir exists: {out}")
    (out / "raw").mkdir(parents=True)

    report_d3c = json.loads((D3C_EVAL / "v1d3c_report.json").read_text())
    track_boxes = [f["box"] for f in report_d3c["per_frame"]]
    drift_track = assess_box_drift(track_boxes)
    assert drift_track["drift_suspect"] is True

    ev_dict = json.loads((D3C_EVAL / "raw/evidence_249.json").read_text())
    ev_dict.setdefault("drift_suspect", False)
    base_ev = TemporalTrackEvidence(**ev_dict)

    gt_boxes, steps = _gt_boxes()
    drift_gt = assess_box_drift(gt_boxes)
    assert drift_gt["drift_suspect"] is False

    # Perfect-tracker probe evidence: kinematics honestly derived from GT boxes.
    c0 = ((gt_boxes[0][0] + gt_boxes[0][2]) / 2, (gt_boxes[0][1] + gt_boxes[0][3]) / 2)
    c1 = ((gt_boxes[-1][0] + gt_boxes[-1][2]) / 2, (gt_boxes[-1][1] + gt_boxes[-1][3]) / 2)
    disp = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
    gt_speed = disp / WINDOW_S
    probe_ev = TemporalTrackEvidence(
        source_request_id="v1d4c_p3_probe", source_frame_id="v1d4c_p3_frm",
        track_id="probe", canonical_entity="humanoid",
        selected_label="small humanoid robot", track_state="tracking",
        session_continuity_verified=True, score=0.95, speed_px_s=gt_speed,
        direction_deg=180.0, motion_bucket="L", evidence_age_s=0.1,
        evidence_source="sam2_track", valid=False,
        session_ref="session_local", rejection_reason="pending_validation",
        drift_suspect=False,
    )

    cfg = TemporalEvidenceConfig()
    p1_ev = validate_temporal_evidence(replace(base_ev, drift_suspect=True), config=cfg)
    p2_ev = validate_temporal_evidence(replace(base_ev, drift_suspect=False), config=cfg)
    p3_ev = validate_temporal_evidence(probe_ev, config=cfg)

    frame = np.array(Image.open(FRAME_249).convert("RGB"), dtype=np.uint8)
    client = VLMClient(VLMClientConfig(
        base_url=args.vlm_base_url, timeout_s=60.0, contract_mode="legacy_v2",
    ))

    arms = [
        ("P1_paired_drift_rejected", p1_ev,
         "drifted evidence + D4A flag; expect no dynamic claim"),
        ("P2_control_no_drift_gate", p2_ev,
         "drifted evidence without D4A; a dynamic claim here is a demonstrated false positive"),
        ("P3_perfect_tracker_probe", p3_ev,
         "GT-derived probe evidence (diagnostic_only); expect dynamic >= 0.85"),
    ]
    rows: list[dict[str, Any]] = []
    for arm_id, ev, note in arms:
        prompt, sha = build_temporal_prompt_v3(task_context=_ctx(), track_evidence=ev)
        res = client.analyze(frame, prompt=prompt, request_id=f"v1d4c_{arm_id}",
                             frame_id=f"v1d4c_{arm_id}_frm")
        (out / "raw" / f"{arm_id}.json").write_text(json.dumps(res, indent=2) + "\n")
        (out / "raw" / f"{arm_id}_evidence.json").write_text(
            json.dumps(ev.to_dict(), indent=2) + "\n"
        )
        try:
            conf = float(res.get("risk_confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        rows.append({
            "arm": arm_id, "note": note, "prompt_sha256": sha,
            "evidence_valid": ev.valid, "evidence_rejection": ev.rejection_reason,
            "risk_type": res.get("risk_type"), "risk_confidence": conf,
            "keywords": res.get("keywords"),
            "dynamic_ge_gate": res.get("risk_type") == "dynamic" and conf >= CONF_GATE,
        })

    r1, r2, r3 = rows
    gates = {
        "G1_specificity_no_false_positive_when_paired": not r1["dynamic_ge_gate"],
        "G2_control_shows_directive_alone_is_unsafe": r2["dynamic_ge_gate"],
        "G3_sensitivity_true_positive_capability": r3["dynamic_ge_gate"],
        "G4_evidence_layer_rejected_drift": r1["evidence_rejection"] == "track_drift_suspect",
    }
    verdict = (
        "D4C_PAIRED_STACK_PASS"
        if gates["G1_specificity_no_false_positive_when_paired"]
        and gates["G3_sensitivity_true_positive_capability"]
        and gates["G4_evidence_layer_rejected_drift"]
        else "D4C_PAIRED_STACK_FAIL"
    )
    report = {
        "milestone": "V1-D4C",
        "date": time.strftime("%Y-%m-%d"),
        "image": str(FRAME_249.relative_to(REPO)),
        "drift_assessment_track": drift_track,
        "drift_assessment_gt": drift_gt,
        "gt_probe_speed_px_s": gt_speed,
        "rows": rows,
        "gates": gates,
        "verdict": verdict,
        "post_count": len(rows),
        "retry_count": 0,
        "boundary": {
            "no_new_perception_posts_track_data_replayed_from_d3c": True,
            "p3_probe_diagnostic_only_gt_derived": True,
            "confidence_gate_0_85_unchanged": True,
            "evidence_thresholds_unchanged": True,
        },
    }
    (out / "v1d4c_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "rows": [{k: r[k] for k in ("arm", "evidence_valid", "evidence_rejection", "risk_type", "risk_confidence")} for r in rows],
        "gates": gates, "verdict": verdict,
    }, indent=1))


if __name__ == "__main__":
    main()
