"""Simulation ground-truth collision/intrusion detection for safety logging."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from .config import SafetyConfig
from .types import GateDecision, SafetyState

# Matches human_hand SphereCfg radius in gmrobot_env_cfg.py.
HUMAN_HAND_RADIUS_M = 0.05

# v1.1: EE envelope sphere at wrist_3_link (policy ee_pos); gripper mesh not included.
EE_DEFAULT_RADIUS_M = 0.08


def dist_ee_human(
    ee_pos: np.ndarray | Mapping[str, Any] | list[float],
    hand_pos: np.ndarray | Mapping[str, Any] | list[float],
) -> float:
    """Euclidean distance between EE point and human-hand sphere center."""
    ee = np.asarray(ee_pos, dtype=np.float64).reshape(-1)[:3]
    hand = np.asarray(hand_pos, dtype=np.float64).reshape(-1)[:3]
    return float(math.dist(ee.tolist(), hand.tolist()))


def collision_threshold_m(
    *,
    human_hand_radius: float = HUMAN_HAND_RADIUS_M,
    ee_radius: float = EE_DEFAULT_RADIUS_M,
    collision_threshold: float | None = None,
) -> float:
    """Return intrusion distance threshold (center-to-center)."""
    if collision_threshold is not None:
        return float(collision_threshold)
    return float(human_hand_radius + ee_radius)


def is_intrusion(
    ee_pos: np.ndarray | Mapping[str, Any] | list[float],
    hand_pos: np.ndarray | Mapping[str, Any] | list[float],
    *,
    human_hand_radius: float = HUMAN_HAND_RADIUS_M,
    ee_radius: float = EE_DEFAULT_RADIUS_M,
    collision_threshold: float | None = None,
) -> bool:
    """True when human_hand sphere overlaps the EE envelope sphere (v1.1 distance GT)."""
    dist = dist_ee_human(ee_pos, hand_pos)
    return dist < collision_threshold_m(
        human_hand_radius=human_hand_radius,
        ee_radius=ee_radius,
        collision_threshold=collision_threshold,
    )


def compute_ground_truth(
    ee_pos: np.ndarray | Mapping[str, Any] | list[float],
    hand_pos: np.ndarray | Mapping[str, Any] | list[float],
    *,
    human_hand_radius: float = HUMAN_HAND_RADIUS_M,
    ee_radius: float = EE_DEFAULT_RADIUS_M,
    collision_threshold: float | None = None,
) -> tuple[int, float]:
    """Return (g_ground_truth, dist).

    The returned distance is written to both ``dist_ee_human_gt`` (legacy)
    and ``dist_min_gt`` (v1.2 semantic — may be full-envelope dist_min).
    g_ground_truth: 0=ALLOW (no physical intrusion), 1=STOP (intrusion).
    """
    dist = dist_ee_human(ee_pos, hand_pos)
    threshold = collision_threshold_m(
        human_hand_radius=human_hand_radius,
        ee_radius=ee_radius,
        collision_threshold=collision_threshold,
    )
    g_gt = int(GateDecision.STOP) if dist < threshold else int(GateDecision.ALLOW)
    return g_gt, dist


def compute_ground_truth_from_state(
    state: SafetyState,
    config: SafetyConfig | None = None,
) -> tuple[int, float]:
    """Compute GT label from a SafetyState snapshot.

    When a torso is present, returns the tighter of hand→EE and torso→EE distances.
    """
    cfg = config or SafetyConfig()
    g_gt_hand, dist_hand = compute_ground_truth(
        state.ee_pos,
        state.human_hand_pos,
        human_hand_radius=cfg.human_hand_radius,
        ee_radius=cfg.ee_radius,
        collision_threshold=cfg.collision_threshold,
    )
    if not (hasattr(state, "has_torso") and state.has_torso and cfg.human_torso_radius > 0):
        return g_gt_hand, dist_hand

    g_gt_torso, dist_torso = compute_ground_truth(
        state.ee_pos,
        state.human_torso_pos,
        human_hand_radius=cfg.human_torso_radius,
        ee_radius=cfg.ee_radius,
        collision_threshold=cfg.collision_threshold,
    )
    if dist_torso < dist_hand:
        return g_gt_torso, dist_torso
    return g_gt_hand, dist_hand


def compute_ground_truth_v12(
    dist_min_envelope: float,
    *,
    intrusion_threshold: float | None = None,
    config: SafetyConfig | None = None,
) -> tuple[int, float]:
    """Return (g_ground_truth, dist_min_envelope_gt) using full-envelope surface gap.

    g_ground_truth: 0=ALLOW, 1=STOP when dist_min_envelope < intrusion_threshold.
    Threshold defaults to ``effective_hard_stop`` (0.13 m on production presets).
    """
    cfg = config or SafetyConfig()
    threshold = (
        float(intrusion_threshold)
        if intrusion_threshold is not None
        else cfg.effective_hard_stop
    )
    dist = float(dist_min_envelope)
    g_gt = int(GateDecision.STOP) if dist < threshold else int(GateDecision.ALLOW)
    return g_gt, dist


def compute_ground_truth_v12_from_envelope(
    dist_min_envelope: float,
    config: SafetyConfig | None = None,
) -> tuple[int, float]:
    """GT v1.2 wrapper for runtime envelope audit distance."""
    return compute_ground_truth_v12(dist_min_envelope, config=config)


def episode_outcome_from_ground_truth(
    *,
    had_collision: bool,
    policy_success: bool,
    timed_out: bool = False,
) -> str:
    """Map episode flags to outcome string for CSV backfill.

    ``policy_success`` reflects scripted trajectory completion (``is_success()``),
    not physical placement of all 20 parts. Under heavy STOP/SLOW_DOWN the agent
    may append ``@task_time_step/expected_task_steps`` for progress context.
    """
    if had_collision:
        return "collision"
    if policy_success:
        return "success"
    if timed_out:
        return "timeout"
    return "incomplete"
