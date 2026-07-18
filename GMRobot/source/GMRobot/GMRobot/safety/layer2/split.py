"""Episode-level train/validation/test splits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .dataset import SafetyEpisode


@dataclass
class EpisodeSplit:
    train: list[SafetyEpisode]
    val: list[SafetyEpisode]
    test: list[SafetyEpisode]


def split_episodes(
    episodes: Sequence[SafetyEpisode],
    *,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> EpisodeSplit:
    """Split episodes (not individual rows) into train/val/test."""
    total_ratio = train_ratio + val_ratio + test_ratio
    if not np.isclose(total_ratio, 1.0):
        raise ValueError(f"Split ratios must sum to 1.0, got {total_ratio}")

    items = list(episodes)
    if not items:
        return EpisodeSplit(train=[], val=[], test=[])

    rng = np.random.default_rng(seed)
    indices = rng.permutation(len(items))

    n = len(items)
    if n >= 3:
        n_train = max(1, int(round(n * train_ratio)))
        n_val = max(1, int(round(n * val_ratio)))
        n_test = n - n_train - n_val
    else:
        # Small-n fallback: round-robin assignment ensures every split gets >=1
        # episode when possible, and train is never empty.
        n_test = max(1, int(round(n * test_ratio)))
        n_val = max(1, int(round(n * val_ratio)))
        n_train = n - n_test - n_val
        if n_train <= 0 and n >= 2:
            n_train = 1
            if n_test > 1:
                n_test -= 1
            elif n_val > 1:
                n_val -= 1
        if n_train <= 0:
            n_train = 1
            n_test = n_val = 0
    if n_test <= 0 and n >= 2:
        n_test = 1
        if n_train > 1:
            n_train -= 1
        elif n_val > 1:
            n_val -= 1

    train_idx = indices[:n_train]
    val_idx = indices[n_train : n_train + n_val]
    test_idx = indices[n_train + n_val : n_train + n_val + n_test]

    return EpisodeSplit(
        train=[items[i] for i in train_idx],
        val=[items[i] for i in val_idx],
        test=[items[i] for i in test_idx],
    )
