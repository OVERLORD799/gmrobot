"""Dict→flat observation wrapper for skrl PPO training (G6a).

GM task observations are nested Dicts (policy/camera/safety groups
each containing multiple tensors).  skrl neural networks require a
single flat Box observation space.

This wrapper:
1. Recursively collects all leaf tensors from the observation dict.
2. Concatenates them in a fixed, deterministic order (sorted keys).
3. Exposes a single ``Box(low=-inf, high=inf, shape=(total_dim,))``.
4. Handles batched observations (shape (num_envs, ...) → (num_envs, total_dim)).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import gymnasium as gym
import numpy as np
import torch
from gymnasium import spaces


def _collect_leaf_tensors(obs: dict[str, Any], prefix: str = "") -> list[tuple[str, np.ndarray | torch.Tensor]]:
    """Walk a nested dict; return [(full_key, tensor), ...] for all leaf arrays."""
    leaves: list[tuple[str, np.ndarray | torch.Tensor]] = []
    for key in sorted(obs.keys()):
        full_key = f"{prefix}/{key}" if prefix else key
        value = obs[key]
        if isinstance(value, dict):
            leaves.extend(_collect_leaf_tensors(value, full_key))
        elif isinstance(value, (np.ndarray, torch.Tensor)):
            leaves.append((full_key, value))
        # skip non-tensor values (strings, etc.)
    return leaves


def _compute_total_dim(obs: dict[str, Any]) -> int:
    """Total number of scalar elements across all leaf tensors in an observation."""
    leaves = _collect_leaf_tensors(obs)
    total = 0
    for _, tensor in leaves:
        arr = np.asarray(tensor.detach().cpu() if hasattr(tensor, "detach") else tensor)
        total += int(np.prod(arr.shape[1:])) if arr.ndim > 1 else 1
    return total


def _flatten_obs(obs: dict[str, Any], total_dim: int, device: torch.device | None = None) -> torch.Tensor:
    """Recursively collect and concatenate leaf tensors into a flat vector.

    Args:
        obs: Nested observation dict.  Batch dimension is dim 0.
        total_dim: Expected total scalar dimension (per env).
        device: Target device.

    Returns:
        Float tensor of shape (num_envs, total_dim).
    """
    leaves = _collect_leaf_tensors(obs)
    parts: list[torch.Tensor] = []
    for _, tensor in leaves:
        t = torch.as_tensor(tensor, dtype=torch.float32)
        if t.ndim >= 2:
            t = t.reshape(t.shape[0], -1)  # (num_envs, ...)
        else:
            t = t.unsqueeze(0)  # scalar → (1,)
        if device is not None:
            t = t.to(device)
        parts.append(t)
    result = torch.cat(parts, dim=-1)
    # Safety: clip to expected dimension (first call determines it).
    if result.shape[-1] != total_dim:
        result = result[..., :total_dim]
    return result


class FlatObsWrapper(gym.ObservationWrapper):
    """Flatten a Dict observation space into a single Box.

    Usage::

        env = gym.make("gm", cfg=env_cfg)
        env = FlatObsWrapper(env)
        env = SkrlVecEnvWrapper(env)
    """

    def __init__(self, env: gym.Env):
        super().__init__(env)
        # Compute total_dim from the first observation.
        obs_sample = env.observation_space.sample()
        self._total_dim = _compute_total_dim(obs_sample)
        self._leaf_keys: list[str] = []
        self._first_obs: bool = True
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self._total_dim,),
            dtype=np.float32,
        )

    def observation(self, observation: dict[str, Any]) -> torch.Tensor:
        if self._first_obs:
            leaves = _collect_leaf_tensors(observation)
            self._leaf_keys = [k for k, _ in leaves]
            self._first_obs = False
        return _flatten_obs(observation, self._total_dim)
