"""Apply safety gate decisions to proposed actions."""

from __future__ import annotations

import numpy as np

from .config import SafetyConfig
from .types import GateDecision, GateResult


class SafetyGate:
    """Transform proposed 8D actions based on gate decision."""

    def __init__(self, config: SafetyConfig | None = None):
        self.config = config or SafetyConfig()

    def apply(
        self,
        result: GateResult,
        proposed: np.ndarray,
        prev_action: np.ndarray,
    ) -> np.ndarray:
        proposed = np.asarray(proposed, dtype=np.float32).reshape(-1)
        prev_action = np.asarray(prev_action, dtype=np.float32).reshape(-1)

        if result.g_t == GateDecision.STOP:
            return prev_action.copy()

        if result.g_t == GateDecision.SLOW_DOWN:
            alpha = float(
                result.metadata.get("slow_down_alpha", self.config.slow_down_alpha)
            )
            return (prev_action + alpha * (proposed - prev_action)).astype(np.float32)

        return proposed.copy()
