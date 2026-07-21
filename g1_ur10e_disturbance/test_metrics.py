"""Episode-level test metrics for GMDisturb co-simulation runs."""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass, field
from typing import Optional

from protocol_vhand import (
    AttemptRecovery,
    CollisionEpisodeTracker,
    KnockOffTracker,
    ReplanAttribution,
    find_open_attempt_id,
    is_b2_proactive_trigger_rule,
    is_held_critical_trigger_rule,
    validate_attempt_recoveries,
)


@dataclass
class EpisodeMetrics:
    """Aggregated metrics for one disturbance-test episode."""

    episode_id: int = 0

    # Timing
    total_steps: int = 0
    policy_steps: int = 0           # UR10e policy clock

    # UR10e task
    parts_placed: int = 0
    parts_total: int = 20
    task_completed: bool = False

    # G1 state
    g1_fell: bool = False
    g1_root_z_min: float = 0.0
    g1_root_z_final: float = 0.0
    # Spawn evidence (B1 paper — set from env cfg + first-step root pose)
    g1_spawn_requested_x: float = float("nan")
    g1_spawn_requested_y: float = float("nan")
    g1_spawn_requested_yaw: float = float("nan")
    g1_root_initial_x: float = float("nan")
    g1_root_initial_y: float = float("nan")
    g1_root_initial_z: float = float("nan")
    g1_root_x: float = float("nan")
    g1_root_y: float = float("nan")
    g1_root_z: float = float("nan")
    g1_tilt_rad: float = 0.0
    g1_tilt_rad_max: float = 0.0
    spawn_pose_error: float = float("nan")

    # Interventions (safety gate — populated in Phase 3+)
    tier0_stop_count: int = 0
    slowdown_count: int = 0
    replan_count: int = 0
    stuck_count: int = 0

    # D-group: disturbance effects (causal links from disturbance → response)
    d_stop_caused: int = 0    # disturbance attempts that resulted in STOP
    d_slow_caused: int = 0    # disturbance attempts that resulted in SLOW_DOWN
    d_replan_caused: int = 0  # disturbance attempts that triggered replan
    d_knock_off: int = 0      # unique parts knocked off (deduped by part_id)

    # Mat events
    footstep_count: int = 0
    collision_count: int = 0          # rising-edge collision episodes (alias)
    collision_episode_count: int = 0  # same as collision_count (explicit name)
    raw_collision_frame_count: int = 0
    robot_object_collision_count: int = 0
    # Virtual/proxy hand has no PhysX body — always 0 by modelling, independent
    # of real G1/UR10e/part mat collisions in the same episode.
    proxy_physical_contact_count: int = 0
    object_drop_count: int = 0        # unique knock-offs (alias of d_knock_off for CSV compat)
    object_drop_frame_count: int = 0  # raw per-frame drop detections (NOT part count)

    # Proximity
    min_g1_ur10e_distance_m: float = float("inf")
    min_surface_distance_m: float = float("inf")
    mean_g1_ur10e_distance_m: float = 0.0

    # F-group
    f_consecutive_stop_max: int = 0
    f_replan_success: bool = False
    f_replan_failure_reason: str = ""

    # H-group
    h_vlm_action: str = ""
    h_vlm_latency_ms: float = 0.0
    h_vlm_reason: str = ""

    # Disturbance attribution (§6.1)
    disturbance_source: str = ""
    disturbance_scenario: str = ""
    disturbance_attempt_id: int = 0
    gate_trigger_source: str = ""
    replan_trigger_source: str = ""
    closest_g1_body: str = ""
    dist_min_g1_body: float = float("inf")
    dist_min_proxy: float = float("inf")

    # Retreat recovery (§6.3 B1)
    progress_after_retreat: bool = False
    policy_steps_after_retreat: int = 0
    parts_placed_after_retreat: int = 0
    retreat_attempt_count: int = 0
    recovered_attempt_count: int = 0

    # TRANSIT-phase telemetry (B1 occupancy / replan diagnosis)
    transit_min_proxy_distance: float = float("inf")
    transit_slow_count: int = 0
    transit_consecutive_slow_max: int = 0
    transit_replan_count: int = 0
    _transit_slow_streak: int = field(default=0, repr=False)

    # B2 / B4-Dynamic
    safety_enforcement_mode: str = "active"
    disturbance_trajectory_id: str = ""
    pre_hard_stop_replan_count: int = 0
    held_critical_replan_count: int = 0
    shadow_stop_would_count: int = 0
    shadow_slow_would_count: int = 0
    shadow_replan_would_count: int = 0
    # B4 control-isolation leakage counters (must stay 0 under shadow).
    shadow_nonallow_evaluated_steps: int = 0
    shadow_clock_blocked_steps: int = 0
    shadow_action_modified_steps: int = 0
    shadow_replan_applied_count: int = 0
    shadow_retreat_count: int = 0
    first_b2_intervention_step: int = -1
    b2_proactive_trigger_count: int = 0

    # Accumulators
    _distance_sum: float = field(default=0.0, repr=False)
    _consecutive_stop_cur: int = field(default=0, repr=False)
    _last_counted_stop_attempt: int = field(default=-1, repr=False)
    _last_counted_slow_attempt: int = field(default=-1, repr=False)
    _last_counted_replan_event: int = field(default=-1, repr=False)
    _last_counted_shadow_stop_attempt: int = field(default=-1, repr=False)
    _last_counted_shadow_slow_attempt: int = field(default=-1, repr=False)
    _last_counted_shadow_replan_event: int = field(default=-1, repr=False)
    _retreat_step: int = field(default=-1, repr=False)
    _policy_step_at_retreat: int = field(default=0, repr=False)
    _parts_at_retreat: int = field(default=0, repr=False)
    _knock_tracker: KnockOffTracker = field(default_factory=KnockOffTracker, repr=False)
    _collision_tracker: CollisionEpisodeTracker = field(
        default_factory=CollisionEpisodeTracker, repr=False
    )
    _attempt_recoveries: dict = field(default_factory=dict, repr=False)

    # T1: latest safety gate
    last_gate_decision: str = "N/A"
    last_gate_trigger: str = ""
    last_gate_distance: float = float("inf")
    last_closest_body: str = ""

    def note_retreat(
        self,
        *,
        attempt_id: int,
        sim_step: int,
        policy_step: int,
        parts_placed: int,
    ) -> None:
        """Record a retreat edge for *attempt_id* (replan or protocol)."""
        if attempt_id <= 0:
            return
        rec = self._attempt_recoveries.get(attempt_id)
        if rec is None:
            rec = AttemptRecovery(attempt_id=attempt_id)
            self._attempt_recoveries[attempt_id] = rec
        if rec.retreat_step < 0:
            rec.retreat_step = int(sim_step)
            rec.policy_at_retreat = int(policy_step)
            rec.parts_at_retreat = int(parts_placed)
        # Keep first-retreat episode fields for backward-compatible boolean.
        if self._retreat_step < 0:
            self._retreat_step = int(sim_step) if sim_step > 0 else self.total_steps
            self._policy_step_at_retreat = int(policy_step)
            self._parts_at_retreat = int(parts_placed)

    def note_transit_observation(
        self,
        *,
        proxy_distance: float,
        is_slow: bool,
    ) -> int:
        """Accumulate TRANSIT-only proximity / SLOW stats.

        Returns the streak length that just ended (0 if streak continues or
        was already idle).  Caller may emit a slow_streak_end event.
        """
        d = float(proxy_distance)
        if d < self.transit_min_proxy_distance:
            self.transit_min_proxy_distance = d
        ended = 0
        if is_slow:
            self.transit_slow_count += 1
            self._transit_slow_streak += 1
            if self._transit_slow_streak > self.transit_consecutive_slow_max:
                self.transit_consecutive_slow_max = self._transit_slow_streak
        elif self._transit_slow_streak > 0:
            ended = self._transit_slow_streak
            self._transit_slow_streak = 0
        return ended

    def note_transit_replan(self) -> None:
        """Count a replan that was accepted while protocol phase == TRANSIT."""
        self.transit_replan_count += 1

    def end_transit_slow_streak(self) -> int:
        """Force-close an open TRANSIT SLOW streak (e.g. leaving TRANSIT)."""
        ended = self._transit_slow_streak
        self._transit_slow_streak = 0
        return ended

    def note_redeploy(
        self,
        *,
        attempt_id: int,
        sim_step: int,
        policy_step: int,
        parts_placed: int,
    ) -> None:
        """Record redeploy and compute per-attempt recovery deltas.

        If *attempt_id* has no open retreat, attach to the newest open attempt.
        """
        aid = int(attempt_id)
        if aid <= 0:
            aid = find_open_attempt_id(self._attempt_recoveries)
        if aid <= 0:
            return
        rec = self._attempt_recoveries.get(aid)
        if rec is None or rec.retreat_step < 0:
            # Prefer pairing with an open retreated attempt.
            open_id = find_open_attempt_id(self._attempt_recoveries)
            if open_id > 0:
                aid = open_id
                rec = self._attempt_recoveries[aid]
            else:
                return
        if rec.redeploy_step < 0:
            rec.redeploy_step = int(sim_step)
            rec.close_reason = "redeploy"
        if rec.retreat_step >= 0:
            rec.policy_delta_after_retreat = max(
                0, int(policy_step) - int(rec.policy_at_retreat)
            )
            rec.parts_delta_after_retreat = max(
                0, int(parts_placed) - int(rec.parts_at_retreat)
            )
            rec.recovered = (
                rec.redeploy_step >= 0
                and (
                    rec.policy_delta_after_retreat > 0
                    or rec.parts_delta_after_retreat > 0
                )
            )

    def record_step(
        self,
        *,
        g1_root_z: float,
        g1_ur10e_distance: float,
        surface_distance: float = float("inf"),
        mat_events: Optional[list] = None,
        gate_decision: Optional[str] = None,
        gate_trigger: str = "",
        gate_distance: float = float("inf"),
        closest_body: str = "",
        disturbance_active: bool = False,
        consecutive_stop_count: int = 0,
        replan_success: Optional[bool] = None,
        replan_failure_reason: str = "",
        replan_event_id: int = 0,
        replan_attribution: Optional[ReplanAttribution] = None,
        vlm_action: str = "",
        vlm_latency_ms: float = 0.0,
        vlm_reason: str = "",
        disturbance_source: str = "",
        disturbance_scenario: str = "",
        disturbance_attempt_id: int = 0,
        gate_trigger_source: str = "",
        replan_trigger_source: str = "",
        closest_g1_body_name: str = "",
        dist_min_g1_body: float = float("inf"),
        dist_min_proxy: float = float("inf"),
        vhand_retreated: bool = False,
        retreat_event_this_step: bool = False,
        redeploy_event_this_step: bool = False,
        policy_step: int = 0,
        parts_placed_now: Optional[int] = None,
        enforcement_mode: str = "active",
        shadow_gate_decision: Optional[str] = None,
        shadow_replan_would_trigger: bool = False,
        replan_trigger_rule: str = "",
        dist_min_at_replan_trigger: float = float("inf"),
        safe_dist_hard_stop_at_trigger: float = float("inf"),
        gate_decision_at_trigger: str = "",
    ):
        """Update per-step accumulators."""
        self.total_steps += 1
        self.g1_root_z_min = min(self.g1_root_z_min, g1_root_z)
        self.g1_root_z_final = g1_root_z
        _parts_now = (
            int(parts_placed_now)
            if parts_placed_now is not None
            else int(self.parts_placed)
        )

        if g1_ur10e_distance < self.min_g1_ur10e_distance_m:
            self.min_g1_ur10e_distance_m = g1_ur10e_distance
        self._distance_sum += g1_ur10e_distance

        if surface_distance < self.min_surface_distance_m:
            self.min_surface_distance_m = surface_distance

        if gate_decision is not None:
            self.last_gate_decision = str(gate_decision)
        if gate_trigger:
            self.last_gate_trigger = str(gate_trigger)
        if gate_distance != float("inf"):
            self.last_gate_distance = float(gate_distance)
        if closest_body:
            self.last_closest_body = str(closest_body)

        _mode = (enforcement_mode or self.safety_enforcement_mode or "active").lower()
        if enforcement_mode:
            self.safety_enforcement_mode = _mode

        # STOP/SLOW attribution still uses the live disturbance window.
        _dsrc = disturbance_source if disturbance_source else ""
        _gts = gate_trigger_source if gate_trigger_source else ""
        _attributed = (
            disturbance_active and _dsrc and _gts == _dsrc and disturbance_attempt_id > 0
        )
        if _mode == "shadow":
            if _attributed:
                if gate_decision == "STOP" and disturbance_attempt_id != self._last_counted_shadow_stop_attempt:
                    self.shadow_stop_would_count += 1
                    self._last_counted_shadow_stop_attempt = disturbance_attempt_id
                elif gate_decision == "SLOW_DOWN" and disturbance_attempt_id != self._last_counted_shadow_slow_attempt:
                    self.shadow_slow_would_count += 1
                    self._last_counted_shadow_slow_attempt = disturbance_attempt_id
            if shadow_gate_decision:
                self.last_gate_decision = str(shadow_gate_decision)
        elif _attributed:
            if gate_decision == "STOP" and disturbance_attempt_id != self._last_counted_stop_attempt:
                self.d_stop_caused += 1
                self._last_counted_stop_attempt = disturbance_attempt_id
            elif gate_decision == "SLOW_DOWN" and disturbance_attempt_id != self._last_counted_slow_attempt:
                self.d_slow_caused += 1
                self._last_counted_slow_attempt = disturbance_attempt_id

        self._consecutive_stop_cur = consecutive_stop_count
        if consecutive_stop_count > self.f_consecutive_stop_max:
            self.f_consecutive_stop_max = consecutive_stop_count

        # Replan attribution: consume immutable trigger-step attribution.
        # Do NOT require disturbance_active at apply time (TTC may fire after
        # the simple warn window has already closed).
        if replan_success is not None:
            self.f_replan_success = replan_success
            self.f_replan_failure_reason = replan_failure_reason
        if _mode == "shadow" and shadow_replan_would_trigger:
            _shadow_evt = disturbance_attempt_id if disturbance_attempt_id > 0 else self.total_steps
            if _shadow_evt != self._last_counted_shadow_replan_event:
                self.shadow_replan_would_count += 1
                self._last_counted_shadow_replan_event = _shadow_evt
        if replan_success and replan_event_id > 0:
            attr = replan_attribution
            if attr is None and replan_trigger_source:
                # Backward-compatible fallback from apply-step fields.
                attr = ReplanAttribution.from_trigger(
                    attempt_id=disturbance_attempt_id,
                    trigger_rule=gate_trigger or replan_trigger_source,
                    trigger_source=replan_trigger_source,
                )
            _rule = (replan_trigger_rule or (attr.trigger_rule if attr else "") or "").strip()
            _dist_trig = float(dist_min_at_replan_trigger)
            _hard = float(safe_dist_hard_stop_at_trigger)
            if _mode == "shadow":
                pass  # counted above via shadow_replan_would_trigger
            elif (
                attr is not None
                and attr.counts_as_disturbance_replan(_dsrc or attr.trigger_source)
                and replan_event_id != self._last_counted_replan_event
            ):
                self.d_replan_caused += 1
                self._last_counted_replan_event = replan_event_id
                if is_held_critical_trigger_rule(_rule):
                    self.held_critical_replan_count += 1
                if (
                    is_b2_proactive_trigger_rule(_rule)
                    and math.isfinite(_dist_trig)
                    and math.isfinite(_hard)
                    and _dist_trig > _hard
                ):
                    self.pre_hard_stop_replan_count += 1
                    self.b2_proactive_trigger_count += 1
                    if self.first_b2_intervention_step < 0:
                        self.first_b2_intervention_step = int(self.total_steps)

        if vlm_action:
            self.h_vlm_action = vlm_action
        if vlm_latency_ms > 0:
            self.h_vlm_latency_ms = vlm_latency_ms
        if vlm_reason:
            self.h_vlm_reason = vlm_reason

        if disturbance_source:
            self.disturbance_source = disturbance_source
        if disturbance_scenario:
            self.disturbance_scenario = disturbance_scenario
        if disturbance_attempt_id:
            self.disturbance_attempt_id = disturbance_attempt_id
        self.gate_trigger_source = gate_trigger_source
        self.replan_trigger_source = replan_trigger_source
        if closest_g1_body_name:
            self.closest_g1_body = closest_g1_body_name
        if dist_min_g1_body < self.dist_min_g1_body:
            self.dist_min_g1_body = dist_min_g1_body
        if dist_min_proxy < self.dist_min_proxy:
            self.dist_min_proxy = dist_min_proxy

        # Retreat / redeploy edges
        _aid = int(disturbance_attempt_id) if disturbance_attempt_id else 0
        if retreat_event_this_step:
            if _aid <= 0:
                # Do not invent attempt IDs — skip malformed edges.
                pass
            else:
                self.note_retreat(
                    attempt_id=_aid,
                    sim_step=self.total_steps,
                    policy_step=policy_step,
                    parts_placed=_parts_now,
                )
        elif vhand_retreated and self._retreat_step < 0:
            # Legacy rising-edge fallback
            self.note_retreat(
                attempt_id=_aid or 1,
                sim_step=self.total_steps,
                policy_step=policy_step,
                parts_placed=_parts_now,
            )
        if redeploy_event_this_step:
            self.note_redeploy(
                attempt_id=_aid,
                sim_step=self.total_steps,
                policy_step=policy_step,
                parts_placed=_parts_now,
            )
        # Keep open attempts' deltas updated, but do NOT mark recovered
        # until a redeploy (or terminal_success in finalise).
        for rec in self._attempt_recoveries.values():
            if rec.retreat_step >= 0 and rec.redeploy_step < 0:
                rec.policy_delta_after_retreat = max(
                    0, int(policy_step) - int(rec.policy_at_retreat)
                )
                rec.parts_delta_after_retreat = max(
                    0, int(_parts_now) - int(rec.parts_at_retreat)
                )

        if mat_events:
            collision_this_frame = False
            robot_object_this_frame = False
            for ev in mat_events:
                et = getattr(ev, "event_type", "")
                if et.startswith("footstep"):
                    self.footstep_count += 1
                elif et in ("collision_impact", "collision_impact_robot"):
                    collision_this_frame = True
                    if et == "collision_impact_robot":
                        robot_object_this_frame = True
                elif et == "object_drop":
                    part_id = int(getattr(ev, "part_id", -1))
                    self._knock_tracker.observe_drop(
                        part_id, disturbance_active=disturbance_active
                    )
            self._collision_tracker.observe(
                collision_this_frame, robot_object=robot_object_this_frame
            )

        # Publish deduped counters every step so CSV finalise is consistent.
        self.d_knock_off = self._knock_tracker.d_knock_off
        self.object_drop_frame_count = self._knock_tracker.object_drop_frame_count
        self.object_drop_count = self.d_knock_off  # CSV field = unique parts
        self.collision_count = self._collision_tracker.count
        self.collision_episode_count = self._collision_tracker.count
        self.raw_collision_frame_count = self._collision_tracker.raw_frame_count
        self.robot_object_collision_count = self._collision_tracker.robot_object_count

    def finalise(self):
        """Compute derived fields after the episode ends."""
        if self.total_steps > 0:
            self.mean_g1_ur10e_distance_m = self._distance_sum / self.total_steps
        self.task_completed = self.parts_placed >= self.parts_total

        # Clamp knock-off to parts_total (hard invariant).
        if self.d_knock_off > self.parts_total:
            self.d_knock_off = self.parts_total
        self.object_drop_count = self.d_knock_off

        # Per-attempt recovery rollup
        self.retreat_attempt_count = sum(
            1 for r in self._attempt_recoveries.values() if r.retreat_step >= 0
        )
        # Close paired attempts; optionally terminal-close the last open one.
        # Redeployed attempts keep deltas frozen at note_redeploy(); only
        # still-open attempts may be closed against episode-end progress.
        open_after = []
        for rec in self._attempt_recoveries.values():
            if rec.retreat_step < 0:
                continue
            if rec.redeploy_step >= 0:
                # Already closed at redeploy — do NOT recompute against episode end.
                rec.close_reason = rec.close_reason or "redeploy"
                rec.recovered = (
                    rec.policy_delta_after_retreat > 0
                    or rec.parts_delta_after_retreat > 0
                )
            else:
                open_after.append(rec)
                rec.recovered = False
        if self.task_completed and open_after:
            # Episode completed: allow the newest open attempt to close as
            # terminal_success (still requires progress after retreat).
            last = max(open_after, key=lambda r: r.attempt_id)
            last.policy_delta_after_retreat = max(
                0, int(self.policy_steps) - int(last.policy_at_retreat)
            )
            last.parts_delta_after_retreat = max(
                0, int(self.parts_placed) - int(last.parts_at_retreat)
            )
            last.terminal_success = True
            last.close_reason = "terminal_success"
            last.recovered = (
                last.policy_delta_after_retreat > 0
                or last.parts_delta_after_retreat > 0
            )
        self.recovered_attempt_count = sum(
            1 for r in self._attempt_recoveries.values() if r.recovered
        )
        if self._retreat_step > 0 or self.retreat_attempt_count > 0:
            self.policy_steps_after_retreat = max(
                0, int(self.policy_steps) - int(self._policy_step_at_retreat)
            )
            self.parts_placed_after_retreat = max(
                0, int(self.parts_placed) - int(self._parts_at_retreat)
            )
            self.progress_after_retreat = (
                self.policy_steps_after_retreat > 0
                or self.parts_placed_after_retreat > 0
                or self.recovered_attempt_count > 0
            )
        # Keep collision aliases in sync after finalise.
        self.collision_episode_count = self.collision_count
        self.raw_collision_frame_count = self._collision_tracker.raw_frame_count
        self.robot_object_collision_count = self._collision_tracker.robot_object_count

        # Proxy hand has no PhysX contact by construction.  This does NOT
        # zero real mat collision fields (G1/UR10e/parts may still collide).
        _src = (self.disturbance_source or "").lower()
        if "virtual_hand" in _src or "proxy" in _src:
            self.proxy_physical_contact_count = 0
        else:
            # Non-proxy scenes: leave at 0 (field is proxy-specific).
            self.proxy_physical_contact_count = 0

    def attempt_recovery_rows(self) -> list[dict]:
        """Serialize per-attempt recovery for sidecar CSV / JSONL."""
        rows = []
        for aid in sorted(self._attempt_recoveries):
            r = self._attempt_recoveries[aid]
            rows.append({
                "attempt_id": r.attempt_id,
                "retreat_step": r.retreat_step,
                "redeploy_step": r.redeploy_step,
                "policy_delta_after_retreat": r.policy_delta_after_retreat,
                "parts_delta_after_retreat": r.parts_delta_after_retreat,
                "recovered": r.recovered,
                "terminal_success": r.terminal_success,
                "close_reason": r.close_reason,
            })
        return rows

    def attempt_invariant_errors(self) -> list[str]:
        """Validate recovery pairing invariants after finalise()."""
        return validate_attempt_recoveries(
            self._attempt_recoveries.values(),
            task_completed=self.task_completed,
        )

    _CSV_FIELDS = [
        "episode_id", "total_steps", "policy_steps",
        "parts_placed", "parts_total", "task_completed",
        "g1_fell", "g1_root_z_min", "g1_root_z_final",
        "g1_spawn_requested_x", "g1_spawn_requested_y", "g1_spawn_requested_yaw",
        "g1_root_initial_x", "g1_root_initial_y", "g1_root_initial_z",
        "g1_root_x", "g1_root_y", "g1_root_z",
        "g1_tilt_rad", "g1_tilt_rad_max", "spawn_pose_error",
        "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
        "d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off",
        "footstep_count", "collision_count",
        "collision_episode_count", "raw_collision_frame_count",
        "robot_object_collision_count", "proxy_physical_contact_count",
        "object_drop_count",
        "object_drop_frame_count",
        "min_g1_ur10e_distance_m", "min_surface_distance_m", "mean_g1_ur10e_distance_m",
        "last_gate_decision", "last_gate_trigger",
        "last_gate_distance", "last_closest_body",
        "f_consecutive_stop_max", "f_replan_success", "f_replan_failure_reason",
        "h_vlm_action", "h_vlm_latency_ms", "h_vlm_reason",
        "disturbance_source", "disturbance_scenario", "disturbance_attempt_id",
        "gate_trigger_source", "replan_trigger_source",
        "closest_g1_body", "dist_min_g1_body", "dist_min_proxy",
        "progress_after_retreat",
        "policy_steps_after_retreat", "parts_placed_after_retreat",
        "retreat_attempt_count", "recovered_attempt_count",
        "transit_min_proxy_distance", "transit_slow_count",
        "transit_consecutive_slow_max", "transit_replan_count",
        "safety_enforcement_mode", "disturbance_trajectory_id",
        "pre_hard_stop_replan_count", "held_critical_replan_count",
        "shadow_stop_would_count", "shadow_slow_would_count",
        "shadow_replan_would_count",
        "shadow_nonallow_evaluated_steps", "shadow_clock_blocked_steps",
        "shadow_action_modified_steps", "shadow_replan_applied_count",
        "shadow_retreat_count",
        "first_b2_intervention_step",
        "b2_proactive_trigger_count",
    ]

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self._CSV_FIELDS}

    def to_json_dict(self) -> dict:
        d = self.as_dict()
        d["task_completed"] = bool(d.get("task_completed", False))
        d["g1_fell"] = bool(d.get("g1_fell", False))
        d["progress_after_retreat"] = bool(d.get("progress_after_retreat", False))
        d["attempt_recoveries"] = self.attempt_recovery_rows()
        return d


class MetricsWriter:
    """Appends episode metrics to CSV and JSON files."""

    def __init__(self, path: str):
        self._path = path
        self._json_path = path.replace(".csv", ".jsonl")
        self._attempts_path = path.replace(".csv", "_attempts.csv")
        self._header_written = os.path.exists(path) and os.path.getsize(path) > 0

    def write(self, metrics: EpisodeMetrics):
        metrics.finalise()
        row = metrics.as_dict()
        with open(self._path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not self._header_written:
                writer.writeheader()
                self._header_written = True
            writer.writerow(row)
        import json
        with open(self._json_path, "a") as f:
            f.write(json.dumps(metrics.to_json_dict(), default=str) + "\n")
        # Per-attempt recovery sidecar
        attempts = metrics.attempt_recovery_rows()
        if attempts:
            with open(self._attempts_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(attempts[0].keys()))
                w.writeheader()
                w.writerows(attempts)
