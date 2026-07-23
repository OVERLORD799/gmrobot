#!/usr/bin/env python3
"""Unit tests for UR10 freeze helpers."""

from __future__ import annotations

import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motion_isolation import (  # noqa: E402
    build_ur10_hold_action,
    hold_action_hash,
    compute_ur10_freeze_metrics,
)


def test_build_hold_action_and_hash_stable() -> None:
    joint0 = np.array([0.1, -0.2, 0.3, -1.0, 1.1, -0.7, 0.05], dtype=np.float32)
    hold = build_ur10_hold_action(joint0, initial_gripper=0.2)
    assert hold.shape == (8,)
    assert np.allclose(hold[:7], joint0)
    assert abs(float(hold[7]) - 0.2) < 1e-6
    assert hold_action_hash(hold) == hold_action_hash(hold.copy())


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
    test_freeze_metrics_joint_delta_and_action_norm()
    print("PASS test_motion_isolation_unit")
