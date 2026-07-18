# Copyright (c) 2022-2024, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Custom termination terms for the pressure-mat walking task."""

from __future__ import annotations

import torch
from typing import TYPE_CHECKING

from omni.isaac.lab.assets import Articulation, RigidObject
from omni.isaac.lab.managers import SceneEntityCfg

if TYPE_CHECKING:
    from omni.isaac.lab.envs import ManagerBasedRLEnv


def root_out_of_mat_bounds(
    env: "ManagerBasedRLEnv",
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
    bounds_x: tuple[float, float] = (-1.5, 1.5),
    bounds_y: tuple[float, float] = (-1.5, 1.5),
) -> torch.Tensor:
    """Terminate if the asset's root XY position is outside the given bounds.

    Used for the walking env so episodes end when the robot walks off the
    finite tactile mat (preventing garbage data where the feet are on the
    ground plane instead of the taxels).

    Args:
        env: the manager-based RL environment.
        asset_cfg: scene entity (default: "robot").
        bounds_x: (min_x, max_x) in env-local frame. Outside this → terminate.
        bounds_y: (min_y, max_y) in env-local frame.

    Returns:
        Bool tensor of shape ``(num_envs,)`` -- True where the asset is out.
    """
    asset: Articulation | RigidObject = env.scene[asset_cfg.name]
    # Root XY in WORLD frame; convert to env-local by subtracting env origin.
    pos_w = asset.data.root_pos_w[:, :2]
    env_origins_xy = env.scene.env_origins[:, :2]
    pos_local = pos_w - env_origins_xy

    out_x = (pos_local[:, 0] < bounds_x[0]) | (pos_local[:, 0] > bounds_x[1])
    out_y = (pos_local[:, 1] < bounds_y[0]) | (pos_local[:, 1] > bounds_y[1])
    return out_x | out_y
