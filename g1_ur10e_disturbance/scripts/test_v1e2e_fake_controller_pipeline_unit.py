#!/usr/bin/env python3
"""Fake controller pipeline test for UR10 freeze semantics."""

from __future__ import annotations

import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motion_isolation import build_ur10_hold_action, compute_ur10_freeze_metrics  # noqa: E402


class _FakeUr10Controller:
    def __init__(self) -> None:
        self._proposed = np.array([0.4, -0.2, 0.1, -1.2, 1.0, 0.2, -0.3, 0.8], dtype=np.float32)

    def get_action(self) -> np.ndarray:
        return self._proposed.copy()


def test_freeze_overrides_fake_controller_proposed_action() -> None:
    ctrl = _FakeUr10Controller()
    initial_joint = np.array([0.1, -0.1, 0.0, -1.0, 1.1, 0.0, -0.2], dtype=np.float32)
    hold = build_ur10_hold_action(initial_joint, initial_gripper=0.8)
    proposed = ctrl.get_action()
    assert not np.allclose(proposed[:7], hold[:7])
    effective = hold.copy()  # mirrors run_phase3 freeze override before env.step(action)
    m = compute_ur10_freeze_metrics(
        effective_action=effective,
        current_joint_pose=initial_joint.copy(),
        initial_joint_pose=initial_joint,
    )
    assert abs(m["ur10_action_norm"] - float(np.linalg.norm(initial_joint))) < 1e-6
    assert m["ur10_joint_delta_max_abs"] == 0.0


if __name__ == "__main__":
    test_freeze_overrides_fake_controller_proposed_action()
    print("PASS test_v1e2e_fake_controller_pipeline_unit")
