"""G1 walking controller — loads torchscript policy and produces leg actions."""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import torch


class G1WalkController:
    """Loads the Unitree deploy_walk torchscript policy and runs inference.

    The policy expects a 588-dim observation (8 terms × 6-step history) and
    outputs 12-dim leg joint position OFFSETS.  WalkJointAction applies these
    as ``target = default + action * scale`` (scale=0.25, use_default_offset=True).
    """

    def __init__(self, policy_path: Optional[str] = None):
        if policy_path is None:
            policy_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "assets", "0121_walk.pt",
            )

        if not os.path.exists(policy_path):
            raise FileNotFoundError(
                f"G1 walk policy not found at '{policy_path}'. "
                f"Copy it from pressure_mat_repro or set GMDISTURB_ROOT."
            )

        self._device = "cpu"
        self._model = torch.jit.load(policy_path, map_location=self._device)
        self._model.eval()

    def to(self, device: str) -> "G1WalkController":
        """Move model to a different device (e.g. 'cuda:0')."""
        self._device = device
        self._model = self._model.to(device)
        return self

    def get_action(self, walker_obs: np.ndarray) -> np.ndarray:
        """Run the walking policy.

        Args:
            walker_obs: (588,) numpy float32 observation from obs["g1_walker"].
                        This is the concatenated 8-term × 6-step history
                        produced by _G1WalkerObsCfg.

        Returns:
            (12,) numpy float32 — leg joint position OFFSETS (not absolute
            positions).  WalkJointAction applies scale=0.25 to these.
        """
        if walker_obs.shape != (588,):
            raise ValueError(
                f"Expected walker obs shape (588,), got {walker_obs.shape}"
            )

        x = torch.from_numpy(walker_obs.astype(np.float32)).unsqueeze(0).to(self._device)

        with torch.inference_mode():
            action = self._model(x)  # (1, 12)

        return action[0].cpu().numpy().astype(np.float32)

    @property
    def action_dim(self) -> int:
        return 12

    @property
    def obs_dim(self) -> int:
        return 588
