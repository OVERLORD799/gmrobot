#!/usr/bin/env python3
"""Unit tests for V1-E2G.1 postrun analyzer."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v1e2g1_postrun_analyzer import analyze_postrun  # noqa: E402


def _write_runtime_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_postrun_analyzer_projects_visibility_roi_and_arm_freeze_with_gripper_settling() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "run"
        meta = d / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "frame_inventory.json").write_text(
            json.dumps(
                {
                    "frames": [
                        {"step": 10, "path": "scene/frame_000010_env0.png"},
                        {"step": 20, "path": "scene/frame_000020_env0.png"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (meta / "camera_pose.json").write_text(
            json.dumps({"pos": [0.45, 0.0, 2.7], "rot": [0.7071, 0.0, 0.7071, 0.0]}),
            encoding="utf-8",
        )
        rows = [
            {
                "step": 10,
                "g1_bodies": {
                    "torso_link": [0.0, 0.0, 0.3],
                    "head_link": [0.0, 0.0, 0.5],
                },
                "ur10e_ee": [0.3, -0.1, 0.6],
            },
            {
                "step": 20,
                "g1_bodies": {
                    "torso_link": [0.1, 0.0, 0.3],
                    "head_link": [0.1, 0.0, 0.5],
                },
                "ur10e_ee": [0.3, -0.1, 0.6000003],
            },
        ]
        (meta / "body_poses.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        _write_runtime_csv(
            d / "safety_logs" / "phase3_runtime_telemetry.csv",
            [
                {
                    "sim_step": "10",
                    "ur10_gripper_selected_state": "open",
                    "ur10_arm_joint_delta_norm": "0.0",
                    "ur10_arm_joint_delta_max_abs": "0.0",
                    "ur10_arm_joint_delta_max_abs_joint_name": "wrist_3_joint",
                    "ur10_arm_joint_delta_max_abs_joint_value": "0.0",
                    "ur10_arm_joint_delta_abs_by_name_json": "{\"wrist_3_joint\": 0.0}",
                    "ur10_gripper_joint_delta": "0.314159",
                    "ur10_joint_delta_norm": "0.314159",
                    "ur10_joint_delta_max_abs": "0.314159",
                    "ur10_joint_delta_semantics": "legacy_aggregate_arm6_plus_gripper1",
                    "ur10_arm_joint_delta_max_abs_settled": "0.0",
                    "ur10_arm_joint_delta_max_abs_settled_joint_name": "wrist_3_joint",
                    "ur10_arm_joint_delta_max_abs_settled_joint_value": "0.0",
                    "ur10_gripper_joint_delta_settled": "0.314159",
                    "ur10_joint_delta_max_abs_settled": "0.314159",
                },
                {
                    "sim_step": "20",
                    "ur10_gripper_selected_state": "open",
                    "ur10_arm_joint_delta_norm": "0.0",
                    "ur10_arm_joint_delta_max_abs": "0.0",
                    "ur10_arm_joint_delta_max_abs_joint_name": "wrist_3_joint",
                    "ur10_arm_joint_delta_max_abs_joint_value": "0.0",
                    "ur10_arm_joint_delta_abs_by_name_json": "{\"wrist_3_joint\": 0.0}",
                    "ur10_gripper_joint_delta": "0.314159",
                    "ur10_joint_delta_norm": "0.314159",
                    "ur10_joint_delta_max_abs": "0.314159",
                    "ur10_joint_delta_semantics": "legacy_aggregate_arm6_plus_gripper1",
                    "ur10_arm_joint_delta_max_abs_settled": "0.0",
                    "ur10_arm_joint_delta_max_abs_settled_joint_name": "wrist_3_joint",
                    "ur10_arm_joint_delta_max_abs_settled_joint_value": "0.0",
                    "ur10_gripper_joint_delta_settled": "0.314159",
                    "ur10_joint_delta_max_abs_settled": "0.314159",
                },
            ],
        )
        rep = analyze_postrun(d)
        assert rep["frame_count"] == 2
        assert rep["frames"][0]["visible_link_count"] >= 1
        assert rep["frames"][0]["roi_area_fraction"] > 0.0
        assert rep["frames"][1]["projected_actual_displacement_px"] >= 0.0
        assert rep["ur10"]["arm_freeze_qualified"] is True
        assert rep["ur10"]["gripper_selected_state"] == "open"
        assert abs(rep["ur10"]["gripper_joint_delta_settled_abs_max"] - 0.314159) < 1e-6
        assert abs(rep["ur10"]["legacy_joint_delta_max_abs_settled_max"] - 0.314159) < 1e-6
        assert rep["ur10"]["arm_joint_delta_max_abs_settled_joint_name"] == "wrist_3_joint"


def test_postrun_analyzer_arm_motion_breaks_arm_freeze_gate() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "run"
        meta = d / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "frame_inventory.json").write_text(
            json.dumps({"frames": [{"step": 10, "path": "scene/frame_000010_env0.png"}, {"step": 20, "path": "scene/frame_000020_env0.png"}]}),
            encoding="utf-8",
        )
        (meta / "camera_pose.json").write_text(
            json.dumps({"pos": [0.45, 0.0, 2.7], "rot": [0.7071, 0.0, 0.7071, 0.0]}),
            encoding="utf-8",
        )
        (meta / "body_poses.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"step": 10, "g1_bodies": {"torso_link": [0.0, 0.0, 0.3]}, "ur10e_ee": [0.2, 0.1, 0.6]}),
                    json.dumps({"step": 20, "g1_bodies": {"torso_link": [0.1, 0.0, 0.3]}, "ur10e_ee": [0.2, 0.1, 0.6]}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        _write_runtime_csv(
            d / "safety_logs" / "phase3_runtime_telemetry.csv",
            [
                {
                    "sim_step": "20",
                    "ur10_gripper_selected_state": "close",
                    "ur10_arm_joint_delta_norm": "0.05",
                    "ur10_arm_joint_delta_max_abs": "0.05",
                    "ur10_arm_joint_delta_max_abs_joint_name": "elbow_joint",
                    "ur10_arm_joint_delta_max_abs_joint_value": "0.05",
                    "ur10_arm_joint_delta_abs_by_name_json": "{\"elbow_joint\": 0.05}",
                    "ur10_gripper_joint_delta": "0.0",
                    "ur10_joint_delta_norm": "0.05",
                    "ur10_joint_delta_max_abs": "0.05",
                    "ur10_joint_delta_semantics": "legacy_aggregate_arm6_plus_gripper1",
                    "ur10_arm_joint_delta_max_abs_settled": "0.05",
                    "ur10_arm_joint_delta_max_abs_settled_joint_name": "elbow_joint",
                    "ur10_arm_joint_delta_max_abs_settled_joint_value": "0.05",
                    "ur10_gripper_joint_delta_settled": "0.0",
                    "ur10_joint_delta_max_abs_settled": "0.05",
                }
            ],
        )
        rep = analyze_postrun(d)
        assert rep["ur10"]["arm_freeze_qualified"] is False
        assert rep["ur10"]["arm_joint_delta_max_abs_settled_max"] > 5e-4
        assert rep["ur10"]["arm_joint_delta_max_abs_settled_joint_name"] == "elbow_joint"


def test_postrun_analyzer_e2j1_residual_qualifies_under_relaxed_threshold() -> None:
    """0.00015 rad PD-hold residual (E2J.1 observed) must pass under the 5e-4 gate."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "run"
        meta = d / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "frame_inventory.json").write_text(
            json.dumps({"frames": [{"step": 10, "path": "scene/frame_000010_env0.png"}, {"step": 20, "path": "scene/frame_000020_env0.png"}]}),
            encoding="utf-8",
        )
        (meta / "camera_pose.json").write_text(
            json.dumps({"pos": [0.45, 0.0, 2.7], "rot": [0.7071, 0.0, 0.7071, 0.0]}),
            encoding="utf-8",
        )
        (meta / "body_poses.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"step": 10, "g1_bodies": {"torso_link": [0.0, 0.0, 0.3]}, "ur10e_ee": [0.2, 0.1, 0.6]}),
                    json.dumps({"step": 20, "g1_bodies": {"torso_link": [0.1, 0.0, 0.3]}, "ur10e_ee": [0.2, 0.1, 0.6]}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        _write_runtime_csv(
            d / "safety_logs" / "phase3_runtime_telemetry.csv",
            [
                {
                    "sim_step": "20",
                    "ur10_gripper_selected_state": "open",
                    "ur10_arm_joint_delta_norm": "0.00015",
                    "ur10_arm_joint_delta_max_abs": "0.00015",
                    "ur10_arm_joint_delta_max_abs_joint_name": "shoulder_lift_joint",
                    "ur10_arm_joint_delta_max_abs_joint_value": "-0.00015",
                    "ur10_arm_joint_delta_abs_by_name_json": "{\"shoulder_lift_joint\": 0.00015}",
                    "ur10_gripper_joint_delta": "0.314159",
                    "ur10_joint_delta_norm": "0.314159",
                    "ur10_joint_delta_max_abs": "0.314159",
                    "ur10_joint_delta_semantics": "legacy_aggregate_arm6_plus_gripper1",
                    "ur10_arm_joint_delta_max_abs_settled": "0.00015",
                    "ur10_arm_joint_delta_max_abs_settled_joint_name": "shoulder_lift_joint",
                    "ur10_arm_joint_delta_max_abs_settled_joint_value": "-0.00015",
                    "ur10_gripper_joint_delta_settled": "0.314159",
                    "ur10_joint_delta_max_abs_settled": "0.314159",
                }
            ],
        )
        rep = analyze_postrun(d)
        assert rep["ur10"]["arm_freeze_qualified"] is True
        assert rep["ur10"]["arm_freeze_thresholds"]["arm_joint_delta_max_abs_settled_max"] == 5e-4
        assert rep["ur10"]["arm_freeze_thresholds"]["ee_disp_settled_max_m"] == 1e-6
        assert rep["ur10"]["arm_freeze_thresholds"]["decision_doc"]


if __name__ == "__main__":
    test_postrun_analyzer_projects_visibility_roi_and_arm_freeze_with_gripper_settling()
    test_postrun_analyzer_arm_motion_breaks_arm_freeze_gate()
    test_postrun_analyzer_e2j1_residual_qualifies_under_relaxed_threshold()
    print("PASS test_v1e2g1_postrun_analyzer_unit")
