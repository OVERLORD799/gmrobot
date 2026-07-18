"""Programmable human hand trajectory for simulation (paper IV-J)."""

from __future__ import annotations

import numpy as np
import torch

from .config import HumanTrajectoryConfig, SafetyConfig


class HumanMotionController:
    """Drive kinematic human_hand root state along a scripted trajectory."""

    def __init__(self, config: SafetyConfig, num_envs: int, device: str | torch.device):
        self.config = config
        self.num_envs = num_envs
        self.device = device
        self._prev_pos: np.ndarray | None = None
        self._prev_step: int | None = None

    @property
    def traj(self) -> HumanTrajectoryConfig:
        return self.config.human_trajectory

    def compute_pose(self, step_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (pos, quat_wxyz, lin_vel) for all envs (hand)."""
        pos, vel = self._compute_trajectory(step_index)
        quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        pos_batch = np.tile(pos, (self.num_envs, 1))
        quat_batch = np.tile(quat, (self.num_envs, 1))
        vel_batch = np.tile(vel, (self.num_envs, 1))
        return pos_batch, quat_batch, vel_batch

    def compute_torso_pose(
        self, step_index: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Return (pos, quat_wxyz, lin_vel) for the torso, or None if disabled."""
        cfg = self.config
        if cfg.human_torso_radius <= 0.0:
            return None
        hand_pos, hand_vel = self._compute_trajectory(step_index)
        offset = np.asarray(cfg.human_torso_offset, dtype=np.float64)
        torso_pos = hand_pos + offset
        quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        pos_batch = np.tile(torso_pos, (self.num_envs, 1))
        quat_batch = np.tile(quat, (self.num_envs, 1))
        vel_batch = np.tile(hand_vel, (self.num_envs, 1))
        return pos_batch, quat_batch, vel_batch

    def _compute_trajectory(
        self, step_index: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (pos, vel) for the scripted trajectory at step_index.

        Delegates to ``HumanTrajectoryConfig.compute_pose`` — the single source
        of truth for scripted hand motion.
        """
        return self.traj.compute_pose(
            step_index,
            control_dt=self.config.control_dt,
            eps=self.config.eps,
        )

    def apply_to_env(self, env, step_index: int) -> None:
        """Write human_hand (and optionally torso) root state before env.step()."""
        if not self.config.human_enabled:
            return

        unwrapped = env.unwrapped

        # --- hand ---
        try:
            human_hand = unwrapped.scene["human_hand"]
        except KeyError:
            return
        pos, quat, lin_vel = self.compute_pose(step_index)
        self._write_rigid_root_state(human_hand, pos, quat, lin_vel, unwrapped.scene.env_origins)

        # --- torso (if configured and present in scene) ---
        torso_pose = self.compute_torso_pose(step_index)
        if torso_pose is not None:
            try:
                human_torso = unwrapped.scene["human_torso"]
                t_pos, t_quat, t_vel = torso_pose
                self._write_rigid_root_state(human_torso, t_pos, t_quat, t_vel, unwrapped.scene.env_origins)
            except KeyError:
                pass  # torso not in scene — skip silently

    @staticmethod
    def _write_rigid_root_state(
        rigid_obj, pos: np.ndarray, quat: np.ndarray,
        lin_vel: np.ndarray, env_origins: torch.Tensor,
    ) -> None:
        root_state = rigid_obj.data.default_root_state.clone()
        pos_t = torch.as_tensor(pos, device=rigid_obj.device, dtype=torch.float32)
        quat_t = torch.as_tensor(quat, device=rigid_obj.device, dtype=torch.float32)
        vel_t = torch.as_tensor(lin_vel, device=rigid_obj.device, dtype=torch.float32)
        root_state[:, :3] = pos_t + env_origins
        root_state[:, 3:7] = quat_t
        root_state[:, 7:10] = vel_t
        root_state[:, 10:13] = 0.0
        rigid_obj.write_root_state_to_sim(root_state)
