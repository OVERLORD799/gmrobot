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


if __name__ == "__main__":
    test_build_hold_action_and_hash_stable()
    test_extract_pose7_from_real_obs_fixture()
    test_resolve_freeze_seed_prefers_runtime_state_8d_action()
    test_resolve_freeze_seed_missing_schema_fails_closed()
    test_freeze_metrics_joint_delta_and_action_norm()
    print("PASS test_motion_isolation_unit")
