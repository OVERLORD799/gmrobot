"""Geometry replan v0 — raise + lateral offset (v2: held-aware multi-strategy)."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .strategy import DetourPlan, DetourStrategy, select_detour_strategy
from .types import MotionReplanExecutor, ReplanHint, ReplanRequest, ReplanResult

DETOUR_STAGE_DURATION = 55
MAX_DETOUR_STAGE_DURATION = 65


def _transit_detour_duration(hint: ReplanHint) -> int:
    if hint.detour_stage_duration is not None:
        return int(hint.detour_stage_duration)
    return DETOUR_STAGE_DURATION


def _phase_detour_params(stage_name: str, hint: ReplanHint, policy=None, at_step: int = 0) -> tuple[float, float, int]:
    """Phase-aware caps (ADR §12.3): place is smallest raise/lateral, slowest detour.

    Descent avoidance: approach/place caps are widened slightly so the EE can
    offset laterally before descending through the obstacle's Z level.  Without
    this, a table-height hand forces STOP during every descent.  (ponytail:
    these are still conservative — 0.15/0.08 m lateral is enough to clear a
    hand at table centre while staying within placement-zone tolerance.)
    """
    phase = "transit"
    if policy is not None and hasattr(policy, "transport_phase_at_step"):
        phase = policy.transport_phase_at_step(at_step)
    elif stage_name.startswith("descend_to_box_with_") or stage_name.startswith(
        "open_gripper_to_release_"
    ):
        phase = "place"
    elif stage_name.startswith("move_above_box_with_"):
        phase = "approach"

    if phase == "place":
        return (
            min(hint.raise_approach_m, 0.04),   # was 0.02 — descent avoidance
            min(hint.lateral_offset_m, 0.08),    # was 0.05 — descent avoidance
            MAX_DETOUR_STAGE_DURATION,
        )
    if phase == "approach":
        return (
            min(hint.raise_approach_m, 0.06),   # was 0.04 — descent avoidance
            min(hint.lateral_offset_m, 0.15),    # was 0.10 — descent avoidance
            50,
        )
    return (
        min(hint.raise_approach_m, 0.30),  # R7: 0.06→0.30 for virtual-hand clearance
        hint.lateral_offset_m,
        _transit_detour_duration(hint),
    )


@dataclass
class GeometryReplanV0(MotionReplanExecutor):
    """同步几何绕行：抬高 + 横向偏移后接回原轨迹尾段。"""

    _pending: deque[ReplanRequest] = field(default_factory=deque)
    _completed: deque[tuple[ReplanRequest, ReplanResult]] = field(default_factory=deque)
    _last_pairs: dict[str, tuple[ReplanRequest, ReplanResult]] = field(default_factory=dict)

    def submit(self, request: ReplanRequest) -> str:
        self._pending.append(request)
        return request.request_id

    def poll(self) -> ReplanResult | None:
        """Return a ready result or None.  Synchronous: produces a success
        wrapper immediately on first call after submit(); the actual trajectory
        mutation happens in apply().  This two-phase API (submit→poll→apply)
        exists so the async VLM executor can share the same contract."""
        if self._completed:
            _, result = self._completed.popleft()
            return result
        if not self._pending:
            return None

        request = self._pending.popleft()
        t0 = time.monotonic()
        advance_until = request.task_time_step + 3 * MAX_DETOUR_STAGE_DURATION
        result = ReplanResult(
            request_id=request.request_id,
            status="success",
            new_trajectory_len=0,
            resume_time_step=request.task_time_step,
            latency_ms=(time.monotonic() - t0) * 1000.0,
            post_replan_advance_until=advance_until,
            failure_reason=None,
        )
        self._last_pairs[request.request_id] = (request, result)
        return result

    def result_after_apply(self, request_id: str) -> ReplanResult | None:
        pair = self._last_pairs.get(request_id)
        return pair[1] if pair is not None else None

    def apply(self, result: ReplanResult, policy, *, runtime_state: ReplanRuntimeState | None = None) -> bool:
        if result.status != "success":
            return False
        pair = self._last_pairs.get(result.request_id)
        if pair is None:
            return False
        request, _ = pair

        hint = request.hint if request.hint is not None else ReplanHint()
        at_step = result.resume_time_step
        stage_name = (
            policy.stage_name_at_step(at_step)
            if hasattr(policy, "stage_name_at_step")
            else ""
        )

        # Reset cumulative offset when entering a new part cycle.
        if runtime_state is not None:
            runtime_state.try_reset_for_new_part(stage_name)

        raise_m, lateral_m, detour_duration = _phase_detour_params(
            stage_name, hint, policy=policy, at_step=at_step
        )

        # Cap lateral offset so cumulative drift across multiple replans
        # stays within the placement zone tolerance.
        lateral_applied_m = lateral_m
        raise_applied_m = raise_m
        if runtime_state is not None:
            budget = runtime_state.remaining_lateral_budget()
            if lateral_m > budget:
                lateral_applied_m = max(runtime_state.MIN_LATERAL_M, budget)
                # If budget is exhausted, force conservative strategy.
                if lateral_applied_m <= runtime_state.MIN_LATERAL_M:
                    hint = ReplanHint(
                        raise_approach_m=hint.raise_approach_m,
                        lateral_offset_m=lateral_applied_m,
                        side=hint.side,
                        detour_strategy="raise_then_lateral",
                    )
            # Signal exhaustion to the caller — after this replan the
            # part cannot create meaningful lateral separation and should
            # be abandoned if still held (checked at the call site).
            if runtime_state.remaining_lateral_budget() <= 0.0:
                runtime_state._budget_exhausted = True

        place_target_xy = None
        if hasattr(policy, "place_target_xy_at_step"):
            place_target_xy = policy.place_target_xy_at_step(at_step)

        transport_phase = (
            policy.transport_phase_at_step(at_step)
            if hasattr(policy, "transport_phase_at_step")
            else "transit"
        )

        ee_z = float(request.ee_pos[2])
        hand_speed = float(request.hand_speed_mps or 0.0)
        # Apply the cumulative lateral cap to the strategy parameters.
        capped_raise = raise_applied_m
        capped_lateral = lateral_applied_m

        plan: DetourPlan = select_detour_strategy(
            transport_phase=transport_phase,
            ee_z=ee_z,
            raise_m=capped_raise,
            lateral_m=capped_lateral,
            dist_min_held=request.dist_min_held,
            closest_primitive_id=request.closest_primitive_id,
            hand_speed=hand_speed,
            trigger_rule=request.trigger_rule,
            ee_pos=request.ee_pos,
            human_hand_pos=request.human_hand_pos,
            use_perception_track_strategy=request.use_perception_track_strategy,
            perception_track_speed_px_s=request.perception_track_speed_px_s,
            perception_track_direction_deg=request.perception_track_direction_deg,
        )
        # R7: when raise is large enough to clear the obstacle, use raise_high.
        if plan.raise_m >= 0.15 and plan.strategy == DetourStrategy.RAISE_THEN_LATERAL:
            plan = DetourPlan(
                strategy=DetourStrategy("raise_high"),
                raise_m=plan.raise_m,
                lateral_m=plan.lateral_m,
                retreat_m=plan.retreat_m,
                lateral_first_raise_m=plan.lateral_first_raise_m,
                score=plan.score,
                reason=f"raise_high:{plan.reason}",
            )
        if hint.detour_strategy is not None:
            try:
                forced = DetourStrategy(hint.detour_strategy)
                plan = DetourPlan(
                    strategy=forced,
                    raise_m=plan.raise_m,
                    lateral_m=plan.lateral_m,
                    retreat_m=plan.retreat_m,
                    lateral_first_raise_m=plan.lateral_first_raise_m,
                    score=plan.score,
                    reason=f"hint_override:{forced.value}",
                )
            except ValueError:
                pass

        # Record the actual lateral applied for cumulative tracking.
        actual_lateral = plan.lateral_m
        actual_raise = plan.raise_m

        ok = policy.splice_replan_detour(
            at_step=at_step,
            ee_pos=np.array(request.ee_pos, dtype=np.float32),
            human_hand_pos=np.array(request.human_hand_pos, dtype=np.float32),
            raise_m=plan.raise_m,
            lateral_m=plan.lateral_m,
            detour_duration=detour_duration,
            place_target_xy=place_target_xy,
            detour_strategy=plan.strategy.value,
            retreat_m=plan.retreat_m,
            lateral_first_raise_m=plan.lateral_first_raise_m,
        )
        if ok:
            # Approach/place: no aggressive post_replan_advance (ADR §12.4 / P1-C).
            # H5 fix (2026-07-13): compute the phase-aware advance window BEFORE
            # calling apply_result, so ReplanRuntimeState stores the corrected
            # value rather than the poll()-time default (which used a fixed
            # MAX_DETOUR_STAGE_DURATION regardless of phase).
            post_advance_until = (
                -1
                if transport_phase in ("approach", "place")
                else at_step + 3 * detour_duration
            )
            updated = ReplanResult(
                request_id=result.request_id,
                status=result.status,
                new_trajectory_len=result.new_trajectory_len,
                resume_time_step=at_step,
                latency_ms=result.latency_ms,
                post_replan_advance_until=post_advance_until,
                failure_reason=result.failure_reason,
            )
            # Accumulate the applied lateral offset for multi-replan tracking,
            # using the phase-corrected ReplanResult.
            if runtime_state is not None:
                runtime_state.apply_result(
                    updated,
                    lateral_applied_m=actual_lateral,
                    raise_applied_m=actual_raise,
                )
            self._last_pairs[request.request_id] = (request, updated)
        return ok


@dataclass
class ReplanRuntimeState:
    """Per-env post-replan advance window (SLOW 下也推进 time_step).

    Tracks cumulative detour offsets across replan events within a single
    part cycle so lateral drift doesn't push the EE outside the placement
    zone after multiple detours (§12.8 / ADR multi-replan safety).
    """

    post_replan_advance_until: int = -1
    last_result: ReplanResult | None = None
    last_trigger_rule: str = ""  # W13: carried forward to applied row in CSV
    cumulative_lateral_m: float = 0.0
    cumulative_raise_m: float = 0.0
    _last_part_stage: str = ""  # heuristic: new part = reset cumulative

    # Max total lateral drift across all detours in one part cycle.
    # Beyond this, further detours use raise-only (no lateral).
    MAX_CUMULATIVE_LATERAL_M: float = 0.40  # R7: was 0.20 — too tight for G1+virtual-hand
    # Min lateral for a detour to still be useful.
    MIN_LATERAL_M: float = 0.02

    # ── Replan failure tracking ─────────────────────────────────────
    # Incremented when a detour window ends and the gate is still
    # STOP or SLOW_DOWN (obstacle not cleared).  Reset per part cycle.
    replan_fail_count: int = 0
    # Max consecutive failed detours before part abandonment.
    MAX_REPLAN_FAILS: int = 2
    # Tracks the previous step's detour state for transition detection
    # (True→False = detour window just closed).
    _was_in_detour: bool = False
    # Set by apply() when remaining_lateral_budget() hits zero — the
    # caller (gm_state_machine_agent.py) reads this and decides whether
    # to abort the part based on held_object_active.
    _budget_exhausted: bool = False

    def allows_advance(self, task_time_step: int) -> bool:
        return (
            self.post_replan_advance_until >= 0
            and task_time_step < self.post_replan_advance_until
        )

    def apply_result(self, result: ReplanResult, *, lateral_applied_m: float = 0.0, raise_applied_m: float = 0.0) -> None:
        self.last_result = result
        self.post_replan_advance_until = result.post_replan_advance_until
        self.cumulative_lateral_m += lateral_applied_m
        self.cumulative_raise_m += raise_applied_m

    def remaining_lateral_budget(self) -> float:
        """How much lateral offset is left before hitting the cumulative cap."""
        return max(0.0, self.MAX_CUMULATIVE_LATERAL_M - self.cumulative_lateral_m)

    def try_reset_for_new_part(self, stage_name: str) -> None:
        """Reset cumulative offsets when entering a new part's pick stage.

        Heuristic: 'lift_slot_A_' or 'grasp_slot_A_' means a fresh part cycle.
        When the stage prefix changes part number, reset the counters.
        """
        import re as _re
        m = _re.search(r'(lift_slot_A_|grasp_slot_A_)(\d+)', stage_name)
        if m:
            current = m.group(0)
            if current != self._last_part_stage:
                self.cumulative_lateral_m = 0.0
                self.cumulative_raise_m = 0.0
                self._last_part_stage = current
                self.replan_fail_count = 0
                self._budget_exhausted = False
