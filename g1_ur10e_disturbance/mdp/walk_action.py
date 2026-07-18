# Leg-only joint-action term — migrated from pressure_mat_repro for Isaac Lab 2.x.
#
# Originally at: pressure_mat_repro/.../mdp/walk_action.py
# Import paths rewired: omni.isaac.lab.* → isaaclab.*
# Logic UNCHANGED: 12D leg action → full 29-DOF target buffer.

from __future__ import annotations

import torch
from typing import TYPE_CHECKING

from isaaclab.envs.mdp.actions.joint_actions import JointAction
from isaaclab.envs.mdp.actions.actions_cfg import JointActionCfg
from isaaclab.managers.action_manager import ActionTerm
from isaaclab.utils import configclass

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv


class WalkJointAction(JointAction):
    """Leg-only joint-position action that maintains a full 29-DOF target buffer.

    The matched (leg) joints receive ``default + action * scale``; all other
    joints stay at their default position. The full buffer is sent to the
    articulation each step.
    """

    cfg: "WalkJointActionCfg"

    def __init__(self, cfg: "WalkJointActionCfg", env: "ManagerBasedEnv"):
        super().__init__(cfg, env)
        num_dof = self._asset.data.default_joint_pos.shape[1]
        self._processed_actions = torch.zeros(self.num_envs, num_dof, device=self.device)
        self.last_processed_actions = torch.zeros(self.num_envs, num_dof, device=self.device)
        if cfg.use_default_offset:
            self._offset = self._asset.data.default_joint_pos.clone()

    def process_actions(self, actions: torch.Tensor):
        self._raw_actions[:] = actions
        self.last_processed_actions = self.processed_actions.clone()
        if self.cfg.clip is not None:
            actions = torch.clamp(
                self._raw_actions[:], min=self._clip[:, :, 0], max=self._clip[:, :, 1]
            )
        self._processed_actions[:] = self._offset[:]
        self._processed_actions[:, self._joint_ids] += actions * self._scale

    def apply_actions(self):
        # Preserve non-leg joint targets (arms, waist) set by external
        # controllers.  Only overwrite the leg joint portion of the buffer.
        current_targets = self._asset.data.joint_pos_target.clone()
        current_targets[:, self._joint_ids] = self.processed_actions[:, self._joint_ids]
        self._asset.set_joint_position_target(current_targets)


@configclass
class WalkJointActionCfg(JointActionCfg):
    """Config for :class:`WalkJointAction`. Defaults match the deploy task."""

    class_type: type[ActionTerm] = WalkJointAction

    use_default_offset: bool = True
    """Use the articulation's default joint positions as the action offset."""

    clip: dict[str, tuple] = {".*": (-100.0, 100.0)}
