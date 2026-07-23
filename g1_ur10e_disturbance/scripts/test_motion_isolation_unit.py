#!/usr/bin/env python3
"""Unit tests for UR10 freeze helpers."""

from __future__ import annotations

import json
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motion_isolation import (  # noqa: E402
    build_ur10_hold_action,
    hold_action_hash,
    compute_ur10_freeze_metrics,
    resolve_ur10_freeze_action_seed,
    extract_ur10_pose7_from_policy_obs,
    resolve_ur10_hold_target_from_articulation,
)


class _FakeTensor:
    def __init__(self, value: object) -> None:
        self._value = np.asarray(value, dtype=np.float32)

    def detach(self) -> "_FakeTensor":
        return self

    def cpu(self) -> "_FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self._value


class _FakeArticulationData:
    def __init__(self, joint_pos: np.ndarray) -> None:
        self.joint_pos = np.asarray(joint_pos, dtype=np.float32)


class _FakeArticulation:
    def __init__(self, joint_names: list[str], joint_pos_1xN: np.ndarray) -> None:
        self.joint_names = list(joint_names)
        self.data = _FakeArticulationData(np.asarray(joint_pos_1xN, dtype=np.float32))


def _load_obs_fixture() -> dict:
    fixture = ROOT / "scripts" / "fixtures" / "ur10_observation_manager_snapshot.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


def test_build_hold_action_and_hash_stable() -> None:
    joint0 = np.array([0.1, -0.2, 0.3, -1.0, 1.1, -0.7, 0.05], dtype=np.float32)
    hold = build_ur10_hold_action(joint0, initial_gripper=0.2)
    assert hold.shape == (8,)
    assert np.allclose(hold[:7], joint0)
    assert abs(float(hold[7]) - 0.2) < 1e-6
    assert hold_action_hash(hold) == hold_action_hash(hold.copy())


def test_extract_pose7_from_real_obs_fixture() -> None:
    obs = _load_obs_fixture()["ur10e_policy"]
    pose7, source = extract_ur10_pose7_from_policy_obs(
        {"ee_pos": _FakeTensor(obs["ee_pos"])}
    )
    assert pose7.shape == (7,)
    assert np.allclose(
        pose7,
        np.array([0.4125, -0.108, 0.365, 0.0, -0.70711, 0.70711, 0.0], dtype=np.float32),
    )
    assert "ur10_policy_obs.ee_pos" in source


def test_resolve_freeze_seed_prefers_runtime_state_8d_action() -> None:
    fixture = _load_obs_fixture()
    runtime_action = np.array(
        [0.4125, -0.108, 0.365, 0.0, -0.70711, 0.70711, 0.0, 0.8], dtype=np.float32
    )
    pose7, gripper, source = resolve_ur10_freeze_action_seed(
        ur10_state_action=runtime_action,
        ur10_policy_obs={"ee_pos": _FakeTensor(fixture["ur10e_policy"]["ee_pos"])},
    )
    assert np.allclose(pose7, runtime_action[:7])
    assert abs(gripper - 0.8) < 1e-6
    assert source == "ur10_state_action.pose7+gripper"


def test_resolve_freeze_seed_missing_schema_fails_closed() -> None:
    try:
        resolve_ur10_freeze_action_seed(
            ur10_state_action=None,
            ur10_policy_obs={"slot_A_1_T": np.eye(4, dtype=np.float32)},
        )
        raise AssertionError("expected KeyError when ee_pos schema is missing")
    except KeyError as exc:
        assert "ee_pos" in str(exc)


def test_freeze_metrics_joint_delta_and_action_norm() -> None:
    joint0 = np.zeros(7, dtype=np.float32)
    cur = np.array([0.0, 0.0, 0.01, 0.0, -0.02, 0.0, 0.0], dtype=np.float32)
    eff = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5], dtype=np.float32)
    m = compute_ur10_freeze_metrics(
        effective_action=eff,
        current_joint_pose=cur,
        initial_joint_pose=joint0,
    )
    assert abs(m["ur10_action_norm"]) < 1e-12
    assert m["ur10_joint_delta_norm"] > 0.0
    assert abs(m["ur10_joint_delta_max_abs"] - 0.02) < 1e-6


def test_articulation_hold_mapping_by_joint_name_order() -> None:
    names = [
        "dummy0",
        "wrist_2_joint",
        "finger_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "shoulder_pan_joint",
        "wrist_3_joint",
    ]
    vals = np.array([[9.0, 1.2, 0.33, -0.4, 0.5, -1.1, 0.7, 2.2]], dtype=np.float32)
    art = _FakeArticulation(names, vals)
    hold7, prov, grip = resolve_ur10_hold_target_from_articulation(art)
    assert np.allclose(hold7, np.array([0.7, -0.4, 0.5, -1.1, 1.2, 2.2, 0.33], dtype=np.float32))
    assert abs(grip - 0.33) < 1e-6
    assert [row["joint_name"] for row in prov[:6]] == [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    ]


def test_articulation_hold_missing_arm_joint_fails_closed() -> None:
    names = ["shoulder_pan_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint", "finger_joint"]
    vals = np.zeros((1, len(names)), dtype=np.float32)
    art = _FakeArticulation(names, vals)
    try:
        resolve_ur10_hold_target_from_articulation(art)
        raise AssertionError("expected KeyError for missing shoulder_lift_joint")
    except KeyError as exc:
        assert "shoulder_lift_joint" in str(exc)


def test_articulation_hold_gripper_mapping_prefers_first_available_gripper_joint() -> None:
    names = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
        "right_outer_knuckle_joint",
    ]
    vals = np.array([[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.88]], dtype=np.float32)
    hold7, prov, grip = resolve_ur10_hold_target_from_articulation(_FakeArticulation(names, vals))
    assert abs(grip - 0.88) < 1e-6
    assert abs(float(hold7[-1]) - 0.88) < 1e-6
    assert prov[-1]["joint_name"] == "right_outer_knuckle_joint"


def test_controller_action_differs_but_hold_uses_actual_articulation() -> None:
    proposed = np.array([99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 0.0], dtype=np.float32)
    pose7, grip, _ = resolve_ur10_freeze_action_seed(
        ur10_state_action=proposed,
        ur10_policy_obs={"ee_pos": np.zeros((1, 7), dtype=np.float32)},
    )
    assert np.allclose(pose7, proposed[:7])
    names = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
        "finger_joint",
    ]
    vals = np.array([[0.11, -0.22, 0.33, -0.44, 0.55, -0.66, 0.77]], dtype=np.float32)
    hold7, _, grip2 = resolve_ur10_hold_target_from_articulation(_FakeArticulation(names, vals))
    assert not np.allclose(hold7[:6], pose7[:6])
    assert abs(grip2 - 0.77) < 1e-6
    assert abs(grip - 0.0) < 1e-6


if __name__ == "__main__":
    test_build_hold_action_and_hash_stable()
    test_extract_pose7_from_real_obs_fixture()
    test_resolve_freeze_seed_prefers_runtime_state_8d_action()
    test_resolve_freeze_seed_missing_schema_fails_closed()
    test_freeze_metrics_joint_delta_and_action_norm()
    test_articulation_hold_mapping_by_joint_name_order()
    test_articulation_hold_missing_arm_joint_fails_closed()
    test_articulation_hold_gripper_mapping_prefers_first_available_gripper_joint()
    test_controller_action_differs_but_hold_uses_actual_articulation()
    print("PASS test_motion_isolation_unit")
