"""Safety observation terms for Layer 1 privileged inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from isaaclab.assets import Articulation
from isaaclab.managers import SceneEntityCfg

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv


def ee_lin_vel_w(
    env: ManagerBasedEnv,
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot", body_names="wrist_3_link"),
) -> torch.Tensor:
    """End-effector linear velocity in world frame, shape (num_envs, 3)."""
    robot: Articulation = env.scene[asset_cfg.name]
    return robot.data.body_link_vel_w[:, asset_cfg.body_ids, :3].reshape(env.num_envs, 3)


def arm_joint_pos(
    env: ManagerBasedEnv,
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot", joint_names=[
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    ]),
) -> torch.Tensor:
    """Six UR10e arm joint positions relative to default, shape (num_envs, 6)."""
    robot: Articulation = env.scene[asset_cfg.name]
    return robot.data.joint_pos[:, asset_cfg.joint_ids] - robot.data.default_joint_pos[:, asset_cfg.joint_ids]


def arm_joint_vel(
    env: ManagerBasedEnv,
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot", joint_names=[
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    ]),
) -> torch.Tensor:
    """Six UR10e arm joint velocities, shape (num_envs, 6)."""
    robot: Articulation = env.scene[asset_cfg.name]
    return robot.data.joint_vel[:, asset_cfg.joint_ids]
