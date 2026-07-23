#!/usr/bin/env python3
"""Fake controller pipeline test for UR10 freeze semantics."""

from __future__ import annotations

import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motion_isolation import (  # noqa: E402
    compose_ur10_hold_action,
    compute_ur10_freeze_metrics,
    hold_action_hash,
    resolve_ur10_freeze_action_seed,
)


class _FakeUr10Controller:
    def __init__(self) -> None:
        self._proposed = np.array([0.4, -0.2, 0.1, -1.2, 1.0, 0.2, -0.3, 0.8], dtype=np.float32)

    def get_action(self) -> np.ndarray:
        return self._proposed.copy()


def test_freeze_overrides_fake_controller_proposed_action() -> None:
    ctrl = _FakeUr10Controller()
    proposed = ctrl.get_action()
    initial_joint, gripper, source = resolve_ur10_freeze_action_seed(
        ur10_state_action=proposed,
        ur10_policy_obs={"ee_pos": np.zeros((1, 7), dtype=np.float32)},
    )
    hold = compose_ur10_hold_action(initial_joint, gripper_raw_sign=1.0 if gripper >= 0.0 else -1.0)
    assert source == "ur10_state_action.pose7+gripper"
    assert np.allclose(proposed[:7], hold[:7])
    effective = hold.copy()  # mirrors run_phase3 freeze override before env.step(action)
    m = compute_ur10_freeze_metrics(
        effective_action=effective,
        current_joint_pose=initial_joint.copy(),
        initial_joint_pose=initial_joint,
    )
    assert abs(m["ur10_action_norm"] - float(np.linalg.norm(initial_joint))) < 1e-6
    assert m["ur10_joint_delta_max_abs"] == 0.0
    assert hold_action_hash(hold) == hold_action_hash(hold.copy())


def test_freeze_metrics_arm_static_gripper_binary_settling_isolated() -> None:
    initial_joint = np.zeros(7, dtype=np.float32)
    current_joint = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.314159], dtype=np.float32)
    m = compute_ur10_freeze_metrics(
        effective_action=np.zeros(8, dtype=np.float32),
        current_joint_pose=current_joint,
        initial_joint_pose=initial_joint,
    )
    assert m["ur10_arm_joint_delta_max_abs"] == 0.0
    assert abs(m["ur10_gripper_joint_delta"] - 0.314159) < 1e-6
    # Legacy aggregate keeps the historical semantics for backward compatibility.
    assert abs(m["ur10_joint_delta_max_abs"] - 0.314159) < 1e-6
    assert m["ur10_joint_delta_semantics"] == "legacy_aggregate_arm6_plus_gripper1"


if __name__ == "__main__":
    test_freeze_overrides_fake_controller_proposed_action()
    test_freeze_metrics_arm_static_gripper_binary_settling_isolated()
    print("PASS test_v1e2e_fake_controller_pipeline_unit")
