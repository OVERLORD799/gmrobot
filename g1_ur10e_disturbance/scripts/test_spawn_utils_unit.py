"""Unit tests for pre-make G1 spawn wiring."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spawn_utils import (
    apply_g1_spawn_to_env_cfg,
    spawn_pose_error,
    yaw_to_quat_wxyz,
)
from config_loader import load_config


def test_yaw_to_quat_identity_and_pi():
    assert yaw_to_quat_wxyz(0.0)[0] == math.cos(0.0)
    q = yaw_to_quat_wxyz(math.pi)
    assert abs(q[0]) < 1e-9
    assert abs(q[3] - 1.0) < 1e-9 or abs(q[3] + 1.0) < 1e-9


def test_apply_g1_spawn_sets_init_and_zero_jitter():
    init_state = SimpleNamespace(pos=(-1.5, 0.0, -0.25), rot=(1.0, 0.0, 0.0, 0.0))
    robot_g1 = SimpleNamespace(init_state=init_state)
    scene = SimpleNamespace(robot_g1=robot_g1)
    reset_g1 = SimpleNamespace(params={"pose_range": {"x": (-0.1, 0.1)}})
    events = SimpleNamespace(reset_g1_base=reset_g1)
    env_cfg = SimpleNamespace(scene=scene, events=events)

    rec = apply_g1_spawn_to_env_cfg(
        env_cfg, spawn_x=-1.45, spawn_y=0.0, spawn_yaw=0.0, spawn_jitter_xy=0.0,
    )
    assert init_state.pos == (-1.45, 0.0, -0.25)
    assert init_state.rot[0] == yaw_to_quat_wxyz(0.0)[0]
    assert reset_g1.params["pose_range"]["x"] == (0.0, 0.0)
    assert reset_g1.params["pose_range"]["y"] == (0.0, 0.0)
    assert reset_g1.params["pose_range"]["yaw"] == (0.0, 0.0)
    assert rec["g1_spawn_requested_x"] == -1.45


def test_spawn_pose_error_and_yaml():
    assert abs(spawn_pose_error((-1.45, 0.0), requested_x=-1.45, requested_y=0.0)) < 1e-9
    assert abs(spawn_pose_error((-1.40, 0.0), requested_x=-1.45, requested_y=0.0) - 0.05) < 1e-9
    cfg = load_config(str(_ROOT / "paper_scenarios/static_occupancy_proxy_1part.yaml"))
    assert cfg.disturbance.g1_spawn_x == -1.45
    assert cfg.disturbance.g1_spawn_jitter_xy == 0.0
    assert cfg.virtual_hand.reach_radius == 0.55


if __name__ == "__main__":
    test_yaw_to_quat_identity_and_pi()
    test_apply_g1_spawn_sets_init_and_zero_jitter()
    test_spawn_pose_error_and_yaml()
    print("OK")
