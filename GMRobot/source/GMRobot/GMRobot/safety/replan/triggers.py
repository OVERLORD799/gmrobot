"""L1 warn 监测 → ReplanRequest（Phase 4a v0）。"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)

from ..types import GateDecision, GateResult, SafetyState

from .route_conflict import build_proactive_route_replan_request
from .strategy import should_defer_for_held_critical
from .types import ReplanHint, ReplanRequest

_ENVELOPE_AUDIT_METADATA_KEYS = (
    "dist_min_envelope",
    "dist_min_arm",
    "dist_min_gripper",
    "dist_min_held",
    "closest_primitive_id",
)

_PERCEPTION_TRACK_METADATA_KEYS = (
    "perception_track_speed_px_s",
    "perception_track_direction_deg",
    "perception_track_center_x",
    "perception_track_center_y",
)


def enrich_gate_metadata_from_envelope(metadata: dict, envelope_fields: dict | None) -> None:
    """Merge envelope audit fields into gate metadata for held-aware replan."""
    if not envelope_fields:
        return
    for key in _ENVELOPE_AUDIT_METADATA_KEYS:
        val = envelope_fields.get(key)
        if val is not None and val != "":
            metadata[key] = val


def enrich_gate_metadata_from_perception_track(
    metadata: dict, perception_fields: dict | None
) -> None:
    """Merge SAM2 /track shadow fields into gate metadata for replan strategy."""
    if not perception_fields:
        return
    for key in _PERCEPTION_TRACK_METADATA_KEYS:
        val = perception_fields.get(key)
        if val is not None and val != "":
            metadata[key] = val


def _parse_perception_track_float(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class ReplanTriggerConfig:
    safe_dist_hard_stop: float = 0.13
    safe_dist_warn: float = 0.16
    replan_defer_dist_m: float = 0.15
    replan_trigger_threshold: int = 50
    # Fast dynamic hand sweeps (e.g. ivj_dynamic_fast_sweep) may only sustain TTC warn
    # SLOW for ~6 steps; use a lower bar only while the hand is actually moving.
    ttc_replan_trigger_threshold: int = 6
    ttc_replan_hand_speed_min: float = 0.05
    # S13 P0 phase 2: early replan when shadow forecast crosses threshold (None = disabled).
    ttc_forecast_replan_threshold: float | None = None
    replan_cooldown_steps: int = 265
    # ponytail: cooldown must exceed the max detour window (3 × max detour
    # duration = 3×55=165 for transit) plus a 100-step observation margin so
    # the system can detect whether the detour actually cleared the obstacle
    # before the next replan can fire.  265 = 3×55 + 100.
    tier0_proximity_margin_m: float = 0.02
    defer_replan_in_place_window: bool = True
    lateral_offset_m: float = 0.10
    detour_stage_duration: int = 55
    # S13 P1: opt-in bonus from SAM2 /track kinematics in select_detour_strategy.
    use_perception_track_strategy: bool = False
    # ivj_intrusion_positive v8: transit replan on held_critical STOP / early warn.
    # NOTE: held_critical paths require dist_min_held in gate metadata, which is
    # only populated when RuleEngine.evaluate() receives dist_min_held != None.
    # In GMDisturb, dist_min_held is not yet wired through safety_adapter.py,
    # so held_critical_replan_enabled is dead code in that context.
    held_critical_replan_enabled: bool = False
    # Route-aware proactive splice before gate STOP (opt-in per scenario yaml).
    proactive_route_replan_enabled: bool = False
    proactive_route_horizon_steps: int = 80
    proactive_route_warn_gap_m: float = 0.19
    proactive_route_hard_gap_m: float = 0.13


@dataclass
class L1WarnReplanTrigger:
    """在 warn / SLOW 区持续触发 replan；Tier0 硬 STOP 禁止。"""

    config: ReplanTriggerConfig = field(default_factory=ReplanTriggerConfig)
    _sustained_slow_steps: int = 0
    _prev_dist_min: float | None = None
    _last_replan_step: int = -10_000
    _last_replan_task_step: int = -1

    def reset(self) -> None:
        self._sustained_slow_steps = 0
        self._prev_dist_min = None
        self._last_replan_step = -10_000
        self._last_replan_task_step = -1

    def update(
        self,
        state: SafetyState,
        gate_result: GateResult,
        *,
        task_time_step: int,
        in_place_window: bool = False,
        defer_late_approach: bool = False,
        transport_phase: str = "transit",
        policy=None,
        safety_config=None,
        sim_step_index: int | None = None,
    ) -> ReplanRequest | None:
        proactive = self._proactive_route_replan(
            state,
            gate_result,
            policy=policy,
            safety_config=safety_config,
            task_time_step=task_time_step,
            sim_step_index=sim_step_index,
            transport_phase=transport_phase,
            in_place_window=in_place_window,
            defer_late_approach=defer_late_approach,
        )
        if proactive is not None:
            return proactive

        # F24: canonical distance field — dist_min_for_gating is the distance
        # actually compared against thresholds by the rule engine.  Fall back
        # through dist_min_envelope → dist_ee_human for backward compat with
        # pre-F24 logs.
        dist = gate_result.metadata.get("dist_min_for_gating")
        if dist is None:
            dist = gate_result.metadata.get("dist_min_envelope")
        if dist is None:
            # Legacy fallback (EE-only presets / pre-2.5b logs).
            dist = gate_result.metadata.get("dist_ee_human")
            if dist is not None:
                _log.warning(
                    "Replan trigger using dist_ee_human (%.3f m) as fallback — "
                    "dist_min_for_gating is missing from gate metadata.  "
                    "Thresholds may be mismatched.",
                    float(dist),
                )
        if dist is None:
            self._sustained_slow_steps = 0
            return None

        dist_f = float(dist)
        hard_stop = self.config.safe_dist_hard_stop
        dist_decreasing = (
            self._prev_dist_min is not None
            and dist_f < self._prev_dist_min - 1e-9
        )
        self._prev_dist_min = dist_f

        trigger_rule_raw = str(gate_result.metadata.get("trigger_rule", ""))

        hand_speed = math.sqrt(
            sum(float(v) ** 2 for v in state.human_hand_vel[:3])
        )

        dist_min_held_raw = gate_result.metadata.get("dist_min_held")
        held_carry_active = dist_min_held_raw not in (None, "")

        held_critical_transit_early = (
            self.config.held_critical_replan_enabled
            and gate_result.g_t == GateDecision.STOP
            and dist_f < hard_stop
            and trigger_rule_raw == "held_critical"
            and transport_phase == "transit"
        )
        # Part 5 grasp/lift: fast ball may intrude before lift_slot (still "approach").
        held_critical_carry_early = (
            self.config.held_critical_replan_enabled
            and held_carry_active
            and gate_result.g_t == GateDecision.STOP
            and dist_f < hard_stop
            and trigger_rule_raw == "held_critical"
            and transport_phase == "approach"
        )
        ttc_transit_early = (
            gate_result.g_t == GateDecision.STOP
            and trigger_rule_raw == "ttc"
            and transport_phase == "transit"
            and hand_speed >= self.config.ttc_replan_hand_speed_min
        )

        if gate_result.g_t == GateDecision.STOP and dist_f < hard_stop:
            self._sustained_slow_steps = 0
            if not (held_critical_transit_early or held_critical_carry_early):
                return None

        forecast_early = self._forecast_early_trigger(
            gate_result, hand_speed, dist_decreasing
        )

        held_transit_early_warn = (
            self.config.held_critical_replan_enabled
            and gate_result.g_t == GateDecision.SLOW_DOWN
            and transport_phase == "transit"
            and dist_min_held_raw is not None
            and float(dist_min_held_raw) < self.config.safe_dist_warn
            and hand_speed >= self.config.ttc_replan_hand_speed_min
            and (dist_decreasing or forecast_early)
        )

        if held_critical_transit_early or held_critical_carry_early:
            trigger_rule = "held_critical"
        elif ttc_transit_early:
            trigger_rule = "ttc"
        elif held_transit_early_warn:
            trigger_rule = "held_critical_early"
        elif gate_result.g_t != GateDecision.SLOW_DOWN:
            self._sustained_slow_steps = 0
            # 8.5: forecast replan only during transit.
            if not forecast_early or transport_phase not in ("transit",):
                return None
            trigger_rule = "ttc_forecast"
        else:
            trigger_rule = trigger_rule_raw or "static_warn"
            # static_far is EE-era Option A; do not trigger replan on it (especially pre-O2 retune).
            if trigger_rule == "static_far":
                self._sustained_slow_steps = 0
                return None

            self._sustained_slow_steps += 1
            if trigger_rule == "ttc" and hand_speed >= self.config.ttc_replan_hand_speed_min:
                threshold = self.config.ttc_replan_trigger_threshold
            else:
                threshold = self.config.replan_trigger_threshold
            skip_sustained = held_transit_early_warn or forecast_early
            if not skip_sustained and self._sustained_slow_steps < threshold:
                return None
            if forecast_early and trigger_rule != "held_critical_early" and transport_phase == "transit":
                trigger_rule = "ttc_forecast"

        defer_dist = self.config.replan_defer_dist_m
        dist_ee = float(gate_result.metadata.get("dist_ee_human", dist_f))
        # Approach / late-approach defer intentionally uses EE point distance: splice
        # waypoints are EE-centric and shoulder-pass can shrink dist_min while EE remains
        # outside the defer zone. Place / Tier0 defer below still use dist_min (dist_f).
        dist_defer = dist_ee

        # R7: was blocking ALL static/ttc replans during place/approach.
        # With raise_high strategy (vertical detour), the EE goes OVER the
        # obstacle and descends to the container from above — no misalignment
        # issue.  Only defer when held_critical is tight (knock-off risk).
        # Original: blocked all replans in place/approach except held_critical.
        # if transport_phase in ("place", "approach") and trigger_rule not in ("held_critical", "held_critical_early"):
        #     return None

        dist_min_held = gate_result.metadata.get("dist_min_held")
        if should_defer_for_held_critical(transport_phase, dist_min_held):
            return None

        if (
            self.config.defer_replan_in_place_window
            and transport_phase == "approach"
            and dist_defer < defer_dist
        ):
            return None

        if (
            self.config.defer_replan_in_place_window
            and in_place_window
            and dist_f < hard_stop + self.config.tier0_proximity_margin_m
        ):
            return None

        if (
            self.config.defer_replan_in_place_window
            and defer_late_approach
            and dist_defer < defer_dist
        ):
            return None

        if state.step_index - self._last_replan_step < self.config.replan_cooldown_steps:
            return None
        if task_time_step == self._last_replan_task_step:
            return None

        return ReplanRequest(
            request_id=str(uuid.uuid4()),
            step_index=state.step_index,
            task_time_step=task_time_step,
            trigger_source="l1_warn",
            trigger_rule=trigger_rule,
            dist_ee_human=dist_f,  # deprecated; use dist_min
            dist_min=dist_f,
            g_rule=int(gate_result.g_t),
            ee_pos=tuple(float(x) for x in state.ee_pos[:3]),
            human_hand_pos=tuple(float(x) for x in state.human_hand_pos[:3]),
            hint=ReplanHint(
                lateral_offset_m=self.config.lateral_offset_m,
                detour_stage_duration=self.config.detour_stage_duration,
            ),
            created_at_s=time.monotonic(),
            dist_min_held=(
                float(dist_min_held) if dist_min_held is not None else None
            ),
            dist_min_envelope=(
                float(gate_result.metadata["dist_min_envelope"])
                if gate_result.metadata.get("dist_min_envelope") is not None
                else None
            ),
            closest_primitive_id=gate_result.metadata.get("closest_primitive_id"),
            hand_speed_mps=hand_speed,
            perception_track_speed_px_s=_parse_perception_track_float(
                gate_result.metadata.get("perception_track_speed_px_s")
            ),
            perception_track_direction_deg=_parse_perception_track_float(
                gate_result.metadata.get("perception_track_direction_deg")
            ),
            use_perception_track_strategy=self.config.use_perception_track_strategy,
        )

    def _proactive_route_replan(
        self,
        state: SafetyState,
        gate_result: GateResult,
        *,
        policy,
        safety_config,
        task_time_step: int,
        sim_step_index: int | None,
        transport_phase: str,
        in_place_window: bool,
        defer_late_approach: bool,
    ) -> ReplanRequest | None:
        if not self.config.proactive_route_replan_enabled:
            return None
        if policy is None or safety_config is None:
            return None
        if in_place_window:
            return None
        if (
            self.config.defer_replan_in_place_window
            and transport_phase == "place"
        ):
            return None
        if (
            self.config.defer_replan_in_place_window
            and transport_phase == "approach"
            and float(gate_result.metadata.get("dist_ee_human", 1.0))
            < self.config.replan_defer_dist_m
        ):
            return None
        if (
            self.config.defer_replan_in_place_window
            and defer_late_approach
            and float(gate_result.metadata.get("dist_ee_human", 1.0))
            < self.config.replan_defer_dist_m
        ):
            return None
        dist_min_held = gate_result.metadata.get("dist_min_held")
        if should_defer_for_held_critical(transport_phase, dist_min_held):
            return None
        if state.step_index - self._last_replan_step < self.config.replan_cooldown_steps:
            return None
        if task_time_step == self._last_replan_task_step:
            return None

        sim_idx = sim_step_index if sim_step_index is not None else state.step_index
        req = build_proactive_route_replan_request(
            state,
            gate_result,
            policy,
            safety_config,
            task_time_step=task_time_step,
            sim_step_index=sim_idx,
            transport_phase=transport_phase,
            warn_gap_m=self.config.proactive_route_warn_gap_m,
            hard_gap_m=self.config.proactive_route_hard_gap_m,
            horizon_steps=self.config.proactive_route_horizon_steps,
            lateral_offset_m=self.config.lateral_offset_m,
            detour_stage_duration=self.config.detour_stage_duration,
            request_id=str(uuid.uuid4()),
            created_at_s=time.monotonic(),
        )
        return req

    def _forecast_early_trigger(
        self,
        gate_result: GateResult,
        hand_speed: float,
        dist_decreasing: bool,
    ) -> bool:
        """S13 P0: gated early replan from shadow ttc_forecast_s (L1-only, opt-in).

        Default behaviour: only fires when the gate is SLOW_DOWN.
        When held_critical_replan_enabled is True, also fires from STOP+ttc
        when a part is being carried — the robot should retreat from a
        fast-approaching hand even if it is already stopped.
        """
        threshold = self.config.ttc_forecast_replan_threshold
        if threshold is None or not dist_decreasing:
            return False
        if hand_speed < self.config.ttc_replan_hand_speed_min:
            return False
        trigger_rule = str(gate_result.metadata.get("trigger_rule", ""))
        if gate_result.g_t == GateDecision.STOP:
            # F5: fast scripted hand can jump TTC warn → STOP while robot is
            # carrying.  Allow forecast replan to retreat the robot away from
            # the approaching hand (gated behind held_critical_replan_enabled).
            if not (
                trigger_rule == "ttc"
                and self.config.held_critical_replan_enabled
                and gate_result.metadata.get("dist_min_held") not in (None, "")
            ):
                return False
        elif gate_result.g_t != GateDecision.SLOW_DOWN:
            return False
        fc_raw = gate_result.metadata.get("ttc_forecast_s")
        if fc_raw in (None, "", "inf", "Infinity"):
            return False
        try:
            fc = float(fc_raw)
        except (TypeError, ValueError):
            return False
        return math.isfinite(fc) and fc < threshold

    def on_replan_applied(self, step_index: int, task_time_step: int) -> None:
        """Record cooldown only after splice succeeds (not on request emit)."""
        self._last_replan_step = step_index
        self._last_replan_task_step = task_time_step
        self._sustained_slow_steps = 0
