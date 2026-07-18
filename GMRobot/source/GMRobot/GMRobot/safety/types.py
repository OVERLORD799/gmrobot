"""Data types for Layer 1 safety gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Mapping

import numpy as np


class GateDecision(IntEnum):
    """Safety gate output. Maps to paper g_t: ALLOW=execute, STOP=hold."""

    ALLOW = 0
    STOP = 1
    SLOW_DOWN = 2


# Shared integer constants — single source of truth for severity comparisons.
# Use these instead of int(GateDecision.X) to avoid repeated enum-to-int conversion.
GATE_ALLOW: int = int(GateDecision.ALLOW)
GATE_STOP: int = int(GateDecision.STOP)
GATE_SLOW_DOWN: int = int(GateDecision.SLOW_DOWN)

# Severity ranking for max_severity / tier-fusion comparisons (higher = more conservative).
GATE_SEVERITY: dict[int, int] = {
    GATE_ALLOW: 0,
    GATE_SLOW_DOWN: 1,
    GATE_STOP: 2,
}

# Held-object critical stop threshold (m) — tighter than safe_dist_hard_stop (0.13 m)
# because the held box envelope already includes a conservative bounding sphere.
HELD_CRITICAL_STOP_M: float = 0.10


@dataclass
class SafetyState:
    """Snapshot of privileged safety inputs at control step t."""

    ee_pos: np.ndarray
    ee_vel: np.ndarray
    human_hand_pos: np.ndarray
    human_hand_vel: np.ndarray
    joint_pos: np.ndarray
    joint_vel: np.ndarray
    sim_time: float
    step_index: int
    # Optional torso: zero-length arrays when disabled (backward compatible).
    human_torso_pos: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    human_torso_vel: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))

    @property
    def has_torso(self) -> bool:
        return self.human_torso_pos.size >= 3

    @classmethod
    def from_runtime(
        cls,
        policy_obs: Mapping[str, np.ndarray],
        safety_obs: Mapping[str, np.ndarray],
        *,
        human_hand_pos: np.ndarray,
        human_hand_vel: np.ndarray,
        human_torso_pos: np.ndarray | None = None,
        human_torso_vel: np.ndarray | None = None,
        sim_time: float,
        step_index: int,
        prev_ee_pos: np.ndarray | None = None,
        control_dt: float = 0.02,
    ) -> SafetyState:
        """Build state using explicit human pose (avoids stale obs after kinematic writes)."""
        ee_pose = np.asarray(policy_obs["ee_pos"], dtype=np.float64).reshape(-1)
        ee_pos = ee_pose[:3].copy()

        ee_vel = np.asarray(safety_obs.get("ee_vel", np.zeros(3)), dtype=np.float64).reshape(-1)[:3]
        if prev_ee_pos is not None and np.linalg.norm(ee_vel) < 1e-9:
            ee_vel = (ee_pos - np.asarray(prev_ee_pos, dtype=np.float64)[:3]) / control_dt

        joint_pos = np.asarray(safety_obs["joint_pos"], dtype=np.float64).reshape(-1)
        joint_vel = np.asarray(safety_obs["joint_vel"], dtype=np.float64).reshape(-1)

        return cls(
            ee_pos=ee_pos,
            ee_vel=ee_vel,
            human_hand_pos=np.asarray(human_hand_pos, dtype=np.float64).reshape(-1)[:3],
            human_hand_vel=np.asarray(human_hand_vel, dtype=np.float64).reshape(-1)[:3],
            human_torso_pos=(
                np.asarray(human_torso_pos, dtype=np.float64).reshape(-1)[:3]
                if human_torso_pos is not None and len(human_torso_pos) >= 3
                else np.zeros(0, dtype=np.float64)
            ),
            human_torso_vel=(
                np.asarray(human_torso_vel, dtype=np.float64).reshape(-1)[:3]
                if human_torso_vel is not None and len(human_torso_vel) >= 3
                else np.zeros(0, dtype=np.float64)
            ),
            joint_pos=joint_pos,
            joint_vel=joint_vel,
            sim_time=sim_time,
            step_index=step_index,
        )

    @classmethod
    def from_obs(
        cls,
        policy_obs: Mapping[str, np.ndarray],
        safety_obs: Mapping[str, np.ndarray],
        *,
        sim_time: float,
        step_index: int,
        prev_safety_obs: Mapping[str, np.ndarray] | None = None,
        control_dt: float = 0.02,
    ) -> SafetyState:
        """Build state from env observation dicts for a single environment."""
        ee_pose = np.asarray(policy_obs["ee_pos"], dtype=np.float64).reshape(-1)
        ee_pos = ee_pose[:3].copy()

        ee_vel = np.asarray(safety_obs.get("ee_vel", np.zeros(3)), dtype=np.float64).reshape(-1)[:3]
        human_hand_pos = np.asarray(safety_obs["human_hand_pos"], dtype=np.float64).reshape(-1)[:3]
        human_hand_vel = np.asarray(safety_obs.get("human_hand_vel", np.zeros(3)), dtype=np.float64).reshape(-1)[:3]

        if prev_safety_obs is not None and np.linalg.norm(ee_vel) < 1e-9:
            prev_ee = np.asarray(prev_safety_obs.get("ee_vel", np.zeros(3)), dtype=np.float64)
            if "ee_pos" in prev_safety_obs:
                prev_pos = np.asarray(prev_safety_obs["ee_pos"], dtype=np.float64).reshape(-1)[:3]
                ee_vel = (ee_pos - prev_pos) / control_dt
            elif prev_ee.size >= 3:
                ee_vel = prev_ee[:3]

        if prev_safety_obs is not None and np.linalg.norm(human_hand_vel) < 1e-9:
            prev_hand = np.asarray(prev_safety_obs.get("human_hand_pos", human_hand_pos), dtype=np.float64)
            if prev_hand.size >= 3:
                human_hand_vel = (human_hand_pos - prev_hand.reshape(-1)[:3]) / control_dt

        joint_pos = np.asarray(safety_obs["joint_pos"], dtype=np.float64).reshape(-1)
        joint_vel = np.asarray(safety_obs["joint_vel"], dtype=np.float64).reshape(-1)

        torso_pos = safety_obs.get("human_torso_pos")
        torso_vel = safety_obs.get("human_torso_vel")
        return cls(
            ee_pos=ee_pos,
            ee_vel=ee_vel,
            human_hand_pos=human_hand_pos,
            human_hand_vel=human_hand_vel,
            human_torso_pos=(
                np.asarray(torso_pos, dtype=np.float64).reshape(-1)[:3]
                if torso_pos is not None and getattr(torso_pos, "size", 0) >= 3
                else np.zeros(0, dtype=np.float64)
            ),
            human_torso_vel=(
                np.asarray(torso_vel, dtype=np.float64).reshape(-1)[:3]
                if torso_vel is not None and getattr(torso_vel, "size", 0) >= 3
                else np.zeros(0, dtype=np.float64)
            ),
            joint_pos=joint_pos,
            joint_vel=joint_vel,
            sim_time=sim_time,
            step_index=step_index,
        )

    def to_log_dict(self) -> dict[str, Any]:
        out = {
            "timestamp": self.sim_time,
            "ee_pos": self.ee_pos.tolist(),
            "ee_vel": self.ee_vel.tolist(),
            "human_hand_pos": self.human_hand_pos.tolist(),
            "human_hand_vel": self.human_hand_vel.tolist(),
            "joint_positions": self.joint_pos.tolist(),
            "joint_velocities": self.joint_vel.tolist(),
        }
        if self.has_torso:
            out["human_torso_pos"] = self.human_torso_pos.tolist()
            out["human_torso_vel"] = self.human_torso_vel.tolist()
        return out


@dataclass
class GateResult:
    """Output of rule engine evaluation."""

    g_t: GateDecision
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def paper_g_t(self) -> int:
        """Paper IV-F mapping: 1=execute, 0=hold."""
        return 0 if self.g_t == GateDecision.STOP else 1
