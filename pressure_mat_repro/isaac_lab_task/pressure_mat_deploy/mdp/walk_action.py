# Self-contained "walk" joint-action term for the pressure-mat deploy task.
#
# Vendored from the project's custom additions to
#   omni/isaac/lab/envs/mdp/actions/{joint_actions.py, actions_cfg.py}
# so the task imports on STOCK IsaacLab 1.3.0 with no core edits.
#
# Behaviour: the policy outputs a 12-dim leg action (hip/knee/ankle). This term
# keeps a FULL 29-dim joint-position target buffer: the 12 leg targets are
# written at the matched joint ids (default + action*scale); every other joint
# (waist + arms) is held at its default angle. ``apply_actions`` then commands
# all 29 joints. This matches how the unitree deploy_walk policy was trained.
#
# Subclasses the STOCK JointAction / JointActionCfg, using only stock fields
# (joint_names, scale, clip, use_default_offset). No dependence on any custom
# core symbol.

from __future__ import annotations

import torch
from typing import TYPE_CHECKING

from omni.isaac.lab.envs.mdp.actions.joint_actions import JointAction
from omni.isaac.lab.envs.mdp.actions.actions_cfg import JointActionCfg
from omni.isaac.lab.managers.action_manager import ActionTerm
from omni.isaac.lab.utils import configclass

if TYPE_CHECKING:
    from omni.isaac.lab.envs import ManagerBasedEnv


class WalkJointAction(JointAction):
    """Leg-only joint-position action that maintains a full 29-DOF target buffer.

    The matched (leg) joints receive ``default + action * scale``; all other
    joints stay at their default position. The full buffer is sent to the
    articulation each step.
    """

    cfg: "WalkJointActionCfg"

    def __init__(self, cfg: "WalkJointActionCfg", env: "ManagerBasedEnv"):
        super().__init__(cfg, env)
        # NOTE: 29 = total DOF of the G1-29dof robot. The base class sized
        # _processed_actions to the number of MATCHED joints (12 legs); here we
        # widen it to the full DOF so arms/waist are commanded to default too.
        num_dof = self._asset.data.default_joint_pos.shape[1]
        self._processed_actions = torch.zeros(self.num_envs, num_dof, device=self.device)
        self.last_processed_actions = torch.zeros(self.num_envs, num_dof, device=self.device)
        if cfg.use_default_offset:
            self._offset = self._asset.data.default_joint_pos.clone()

    def process_actions(self, actions: torch.Tensor):
        self._raw_actions[:] = actions
        self.last_processed_actions = self.processed_actions
        # clip
        if self.cfg.clip is not None:
            actions = torch.clamp(
                self._raw_actions[:], min=self._clip[:, :, 0], max=self._clip[:, :, 1]
            )
        # full-DOF default offset, then write leg targets at the matched ids
        self._processed_actions[:] = self._offset[:]
        self._processed_actions[:, self._joint_ids] += actions * self._scale

    def apply_actions(self):
        # command ALL joints (full 29-DOF buffer)
        self._asset.set_joint_position_target(self.processed_actions)


@configclass
class WalkJointActionCfg(JointActionCfg):
    """Config for :class:`WalkJointAction`. Defaults match the deploy task."""

    class_type: type[ActionTerm] = WalkJointAction

    use_default_offset: bool = True
    """Use the articulation's default joint positions as the action offset."""

    clip: dict[str, tuple] = {".*": (-100.0, 100.0)}
