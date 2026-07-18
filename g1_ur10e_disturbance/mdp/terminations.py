# Custom termination terms — migrated from pressure_mat_repro for Isaac Lab 2.x.
#
# Import paths rewired: omni.isaac.lab.* → isaaclab.*
# Logic UNCHANGED.

from __future__ import annotations

import torch
from typing import TYPE_CHECKING

from isaaclab.assets import Articulation, RigidObject
from isaaclab.managers import SceneEntityCfg

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv


def root_out_of_mat_bounds(
    env: "ManagerBasedRLEnv",
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot_g1"),
    bounds_x: tuple[float, float] = (-1.5, 1.5),
    bounds_y: tuple[float, float] = (-1.5, 1.5),
) -> torch.Tensor:
    """Terminate if the asset's root XY position is outside the given bounds.

    Args:
        env: Manager-based RL environment.
        asset_cfg: Scene entity (default: "robot_g1").
        bounds_x: (min_x, max_x) in env-local frame.
        bounds_y: (min_y, max_y) in env-local frame.

    Returns:
        Bool tensor of shape ``(num_envs,)`` — True where the asset is out.
    """
    asset: Articulation | RigidObject = env.scene[asset_cfg.name]
    pos_w = asset.data.root_pos_w[:, :2]
    env_origins_xy = env.scene.env_origins[:, :2]
    pos_local = pos_w - env_origins_xy
    out_x = (pos_local[:, 0] < bounds_x[0]) | (pos_local[:, 0] > bounds_x[1])
    out_y = (pos_local[:, 1] < bounds_y[0]) | (pos_local[:, 1] > bounds_y[1])
    return out_x | out_y
