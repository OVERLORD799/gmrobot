"""Route-aware proactive replan: forecast EE carry path vs scripted hand motion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np

from ..envelope import surface_gap_sphere
from ..types import GateDecision, GateResult, SafetyState

from .types import ReplanHint, ReplanRequest

if TYPE_CHECKING:
    from ..config import SafetyConfig


def compute_scripted_hand_pose(
    step_index: int, safety_config: SafetyConfig
) -> tuple[np.ndarray, np.ndarray]:
    """Return (pos, vel) for the scripted hand at ``step_index``.

    Thin wrapper around ``HumanTrajectoryConfig.compute_pose`` — the single
    source of truth shared with ``HumanMotionController``.
    """
    return safety_config.human_trajectory.compute_pose(
        step_index,
        control_dt=safety_config.control_dt,
        eps=safety_config.eps,
    )


def point_to_segment_distance_3d(
    point: np.ndarray | Sequence[float],
    seg_a: np.ndarray | Sequence[float],
    seg_b: np.ndarray | Sequence[float],
) -> float:
    """Shortest distance from ``point`` to segment ``seg_a``–``seg_b``."""
    p = np.asarray(point, dtype=np.float64).reshape(3)
    a = np.asarray(seg_a, dtype=np.float64).reshape(3)
    b = np.asarray(seg_b, dtype=np.float64).reshape(3)
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom < 1e-12:
        return float(np.linalg.norm(p - a))
    t = float(np.clip(np.dot(p - a, ab) / denom, 0.0, 1.0))
    closest = a + t * ab
    return float(np.linalg.norm(p - closest))


def sphere_segment_surface_gap(
    hand_pos: np.ndarray,
    hand_radius: float,
    seg_a: np.ndarray,
    seg_b: np.ndarray,
    prim_radius: float,
) -> float:
    center_dist = point_to_segment_distance_3d(hand_pos, seg_a, seg_b)
    return max(0.0, center_dist - hand_radius - prim_radius)


def sample_policy_ee_pos(policy: Any, step: int) -> np.ndarray | None:
    """Interpolate EE XYZ from the policy trajectory at ``step``."""
    if policy.time_stamps is None or policy.pos_traj is None:
        return None
    if step < 0 or step > int(policy.time_stamps[-1]):
        return None
    return np.array(
        [
            np.interp(step, policy.time_stamps, policy.pos_traj[:, 0]),
            np.interp(step, policy.time_stamps, policy.pos_traj[:, 1]),
            np.interp(step, policy.time_stamps, policy.pos_traj[:, 2]),
        ],
        dtype=np.float64,
    )


@dataclass(frozen=True)
class RouteConflictResult:
    min_gap_m: float
    conflict_task_step: int
    conflict_sim_step: int
    steps_ahead: int


def evaluate_route_conflict(
    policy: Any,
    safety_config: SafetyConfig,
    *,
    task_time_step: int,
    sim_step_index: int,
    horizon_steps: int = 80,
) -> RouteConflictResult | None:
    """Min surface gap between scripted hand and future EE/held path over horizon."""
    if horizon_steps <= 0:
        return None
    if policy.time_stamps is None or policy.pos_traj is None:
        return None

    hand_r = float(safety_config.human_hand_radius)
    held_r = float(safety_config.envelope.effective_held_box_radius())
    traj_end = int(policy.time_stamps[-1])

    min_gap = float("inf")
    best_task = task_time_step
    best_sim = sim_step_index
    best_ahead = 0

    prev_ee: np.ndarray | None = None
    for offset in range(1, horizon_steps + 1):
        task_s = task_time_step + offset
        sim_s = sim_step_index + offset
        if task_s > traj_end:
            break

        ee = sample_policy_ee_pos(policy, task_s)
        if ee is None:
            continue

        carrying = False
        if hasattr(policy, "is_carrying_object"):
            carrying = bool(policy.is_carrying_object(task_s))
        if not carrying:
            prev_ee = ee
            continue

        hand_pos, _ = compute_scripted_hand_pose(sim_s, safety_config)
        prim_r = held_r

        gap_point = surface_gap_sphere(hand_pos, hand_r, ee, prim_r)
        gap = gap_point
        if prev_ee is not None:
            gap_seg = sphere_segment_surface_gap(
                hand_pos, hand_r, prev_ee, ee, prim_r
            )
            gap = min(gap, gap_seg)

        if gap < min_gap:
            min_gap = gap
            best_task = task_s
            best_sim = sim_s
            best_ahead = offset
        prev_ee = ee

    if not math.isfinite(min_gap):
        return None
    return RouteConflictResult(
        min_gap_m=min_gap,
        conflict_task_step=best_task,
        conflict_sim_step=best_sim,
        steps_ahead=best_ahead,
    )


def route_conflict_transport_ok(transport_phase: str, policy: Any, task_time_step: int) -> bool:
    if transport_phase == "transit":
        return True
    if transport_phase != "approach":
        return False
    if hasattr(policy, "is_carrying_object"):
        # Grasp/lift approach while carrying only — not close_gripper pre-grasp.
        return bool(policy.is_carrying_object(max(task_time_step, 0)))
    return False


def build_proactive_route_replan_request(
    state: SafetyState,
    gate_result: GateResult,
    policy: Any,
    safety_config: SafetyConfig,
    *,
    task_time_step: int,
    sim_step_index: int,
    transport_phase: str,
    warn_gap_m: float,
    hard_gap_m: float,
    horizon_steps: int,
    lateral_offset_m: float,
    detour_stage_duration: int,
    request_id: str,
    created_at_s: float,
) -> ReplanRequest | None:
    """Emit ``route_conflict`` replan when forecast path gap falls below threshold."""
    if not route_conflict_transport_ok(transport_phase, policy, task_time_step):
        return None

    conflict = evaluate_route_conflict(
        policy,
        safety_config,
        task_time_step=task_time_step,
        sim_step_index=sim_step_index,
        horizon_steps=horizon_steps,
    )
    if conflict is None:
        return None

    if conflict.min_gap_m >= warn_gap_m:
        return None

    dist_meta = gate_result.metadata.get("dist_min_envelope")
    if dist_meta is None:
        dist_meta = gate_result.metadata.get("dist_min")
    dist_f = float(dist_meta) if dist_meta not in (None, "") else conflict.min_gap_m

    hand_speed = math.sqrt(
        sum(float(v) ** 2 for v in state.human_hand_vel[:3])
    )
    dist_min_held = gate_result.metadata.get("dist_min_held")

    g_rule = int(gate_result.g_t)
    # Report actual gate severity; trigger_rule="route_conflict" + min_gap
    # already signal that this is a forecast-based replan.  Do not inflate
    # g_rule — callers that read g_rule must see the current gate decision,
    # not a predicted future severity.

    return ReplanRequest(
        request_id=request_id,
        step_index=state.step_index,
        task_time_step=task_time_step,
        trigger_source="route_forecast",
        trigger_rule="route_conflict",
        dist_ee_human=dist_f,  # deprecated; use dist_min
        dist_min=dist_f,
        g_rule=g_rule,
        ee_pos=tuple(float(x) for x in state.ee_pos[:3]),
        human_hand_pos=tuple(float(x) for x in state.human_hand_pos[:3]),
        hint=ReplanHint(
            lateral_offset_m=lateral_offset_m,
            detour_stage_duration=detour_stage_duration,
        ),
        created_at_s=created_at_s,
        dist_min_held=(
            float(dist_min_held) if dist_min_held not in (None, "") else None
        ),
        dist_min_envelope=conflict.min_gap_m,
        closest_primitive_id="held:fixed_box",
        hand_speed_mps=hand_speed,
    )
