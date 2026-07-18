#!/usr/bin/env python3
"""Unit tests for HumanMotionController phased trajectories."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _safety_import import load_safety_module

config_mod = load_safety_module("config")
human_mod = load_safety_module("human_motion")
HumanTrajectoryConfig = config_mod.HumanTrajectoryConfig
SafetyConfig = config_mod.SafetyConfig
HumanMotionController = human_mod.HumanMotionController


def _controller(traj: HumanTrajectoryConfig) -> HumanMotionController:
    cfg = SafetyConfig(human_trajectory=traj, control_dt=0.02)
    return HumanMotionController(cfg, num_envs=1, device="cpu")


def test_hold_far_before_start():
    traj = HumanTrajectoryConfig(
        start_pos=[0.0, 0.0, 0.5],
        end_pos=[1.0, 0.0, 0.2],
        start_step=100,
        duration_steps=50,
    )
    ctrl = _controller(traj)
    pos, _, vel = ctrl.compute_pose(50)
    assert abs(pos[0, 0] - 0.0) < 1e-6
    assert abs(vel[0, 0]) < 1e-6


def test_approach_hold_retreat_phases():
    traj = HumanTrajectoryConfig(
        start_pos=[0.0, 0.0, 0.5],
        end_pos=[1.0, 0.0, 0.2],
        start_step=100,
        duration_steps=50,
        hold_steps=1000,
        retreat_pos=[0.0, 0.0, 0.5],
        retreat_duration_steps=50,
    )
    ctrl = _controller(traj)
    pos, _, vel = ctrl.compute_pose(125)
    assert 0.0 < pos[0, 0] < 1.0
    assert abs(vel[0, 0]) > 0.01
    pos, _, vel = ctrl.compute_pose(200)
    assert abs(pos[0, 0] - 1.0) < 1e-6
    assert abs(vel[0, 0]) < 1e-6
    pos, _, vel = ctrl.compute_pose(1175)
    assert 0.0 < pos[0, 0] < 1.0
    assert vel[0, 0] < -0.01
    pos, _, vel = ctrl.compute_pose(1300)
    assert abs(pos[0, 0] - 0.0) < 1e-6
    assert abs(vel[0, 0]) < 1e-6


def test_legacy_permanent_block_without_hold():
    traj = HumanTrajectoryConfig(
        start_pos=[0.0, 0.0, 0.5],
        end_pos=[1.0, 0.0, 0.2],
        start_step=10,
        duration_steps=10,
        hold_steps=0,
        retreat_pos=None,
    )
    ctrl = _controller(traj)
    pos, _, _ = ctrl.compute_pose(100)
    assert abs(pos[0, 0] - 1.0) < 1e-6


if __name__ == "__main__":
    test_hold_far_before_start()
    test_approach_hold_retreat_phases()
    test_legacy_permanent_block_without_hold()
    print("test_human_motion: OK")
