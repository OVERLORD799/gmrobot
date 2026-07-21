"""Apply G1 spawn pose to Isaac Lab env cfg *before* ``gym.make``.

Paper B1 must spawn G1 at the configured pose via ``init_state`` + zero
(or small) ``reset_g1_base.pose_range`` jitter — never post-reset
``write_root_state_to_sim`` teleports (state / obs history inconsistency).
"""

from __future__ import annotations

import math
from typing import Any


# Match dual_env_cfg.G1_INIT_POS[2] — keep feet on the same ground plane.
DEFAULT_G1_SPAWN_Z = -0.25


def yaw_to_quat_wxyz(yaw: float) -> tuple[float, float, float, float]:
    """Yaw about +Z → (w, x, y, z) quaternion (Isaac Lab convention)."""
    half = 0.5 * float(yaw)
    return (math.cos(half), 0.0, 0.0, math.sin(half))


def apply_g1_spawn_to_env_cfg(
    env_cfg: Any,
    *,
    spawn_x: float,
    spawn_y: float = 0.0,
    spawn_z: float = DEFAULT_G1_SPAWN_Z,
    spawn_yaw: float = 0.0,
    spawn_jitter_xy: float = 0.0,
) -> dict[str, Any]:
    """Set ``robot_g1.init_state`` and ``events.reset_g1_base.pose_range``.

    Returns a record of the requested spawn for stdout / sidecar / CSV.
    """
    x = float(spawn_x)
    y = float(spawn_y)
    z = float(spawn_z)
    yaw = float(spawn_yaw)
    jitter = max(0.0, float(spawn_jitter_xy))
    quat = yaw_to_quat_wxyz(yaw)

    robot_g1 = env_cfg.scene.robot_g1
    init_state = robot_g1.init_state
    # ArticulationCfg.InitialStateCfg fields are mutable on the instance.
    init_state.pos = (x, y, z)
    init_state.rot = quat

    # pose_range is *added* to default root on reset — zero = exact spawn.
    # Only XY jitter is configured; yaw stays fixed for paper stability gates.
    pose_range = {
        "x": (-jitter, jitter),
        "y": (-jitter, jitter),
        "yaw": (0.0, 0.0),
    }
    try:
        env_cfg.events.reset_g1_base.params["pose_range"] = pose_range
    except Exception as exc:  # pragma: no cover — structure varies by Lab version
        raise RuntimeError(
            "Failed to set events.reset_g1_base.params['pose_range']; "
            "check DualRobotEventsCfg wiring"
        ) from exc

    return {
        "g1_spawn_requested_x": x,
        "g1_spawn_requested_y": y,
        "g1_spawn_requested_z": z,
        "g1_spawn_requested_yaw": yaw,
        "g1_spawn_jitter_xy": jitter,
        "g1_spawn_requested_quat_wxyz": quat,
        "reset_g1_pose_range": pose_range,
    }


def spawn_pose_error(
    root_xy: tuple[float, float] | list[float],
    *,
    requested_x: float,
    requested_y: float,
) -> float:
    """XY distance between measured root and requested spawn (metres)."""
    dx = float(root_xy[0]) - float(requested_x)
    dy = float(root_xy[1]) - float(requested_y)
    return math.hypot(dx, dy)
