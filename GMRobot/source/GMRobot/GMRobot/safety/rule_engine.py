"""Rule-based safety evaluation (Layer 1)."""

from __future__ import annotations

import math

import numpy as np

from .config import SafetyConfig
from .types import GateDecision, GateResult, HELD_CRITICAL_STOP_M, SafetyState


class RuleEngine:
    """Evaluate static, TTC, and workspace rules with STOP > SLOW_DOWN > ALLOW priority."""

    def __init__(self, config: SafetyConfig | None = None):
        self.config = config or SafetyConfig()
        self._prev_dist_min: float | None = None
        self._prev_sim_time: float | None = None

    def evaluate(
        self,
        state: SafetyState,
        *,
        dist_for_gating: float | None = None,
        dist_min_held: float | None = None,
        held_object_active: bool = False,
        closest_primitive_pos: np.ndarray | None = None,
        closest_primitive_id: str = "",
        functional_risk_info: dict | None = None,
        skip_ttc: bool = False,
        proposed_ee_pos: np.ndarray | None = None,
    ) -> GateResult:
        cfg = self.config
        metadata: dict = {}

        dist_ee = float(
            math.dist(state.ee_pos.tolist(), state.human_hand_pos.tolist())
        )
        metadata["dist_ee_human"] = dist_ee  # legacy; prefer dist_min_for_gating

        use_envelope = cfg.envelope.gating_enabled and dist_for_gating is not None
        dist = float(dist_for_gating) if use_envelope else dist_ee
        # F1: guard against empty-primitive inf propagation.
        if not math.isfinite(dist):
            dist = dist_ee
            use_envelope = False
        if use_envelope:
            metadata["dist_min_envelope"] = dist
        # Canonical: the distance actually used for gate threshold comparisons.
        # When envelope gating is on this is dist_min_envelope; otherwise dist_ee_human.
        metadata["dist_min_for_gating"] = dist

        # ADR O5 / S7 Option B: default TTC distance = dist_min under envelope gating.
        # block_place preset may set ttc_dist_source=ee to avoid over-trigger vs S1 ref.
        if use_envelope and cfg.ttc_dist_source == "ee":
            ttc_dist = dist_ee
        else:
            ttc_dist = dist
        # S7 Option C: use closest envelope primitive position for the radial
        # approach direction instead of EE position — closes the tangential
        # blind spot where hand approaches the held box / arm from the side
        # but EE→hand radial velocity ≈ 0 → TTC=∞.
        if skip_ttc:
            ttc = float("inf")
            approach_rate = 0.0
        else:
            ttc, approach_rate = self._compute_ttc(
                state, ttc_dist,
                closest_primitive_pos=closest_primitive_pos,
                closest_primitive_id=closest_primitive_id,
            )
        metadata["ttc"] = ttc
        metadata["approach_rate"] = approach_rate

        if state.step_index == 0:
            self._prev_dist_min = None
            self._prev_sim_time = None
        forecast_rate = self._compute_forecast_approach_rate(state, dist, metadata)
        metadata["ttc_forecast_s"] = self._forecast_ttc(ttc_dist, forecast_rate)
        self._prev_dist_min = dist
        self._prev_sim_time = float(state.sim_time)

        decisions: list[tuple[GateDecision, str, str]] = []

        hard_stop = cfg.effective_hard_stop
        warn_dist = cfg.effective_warn
        # Audit: thresholds actually used this step (dynamic warn may override).
        metadata["safe_dist_hard_stop_active"] = float(hard_stop)
        metadata["safe_dist_warn_active"] = float(warn_dist)
        if dist_min_held is not None:
            metadata["dist_min_held"] = float(dist_min_held)
        # Option A static_far: use envelope-specific threshold under envelope gating
        # (ADR O2 / W16), falling back to disabled when neither is configured.
        if use_envelope:
            slow_far = cfg.safe_dist_slow_far_envelope
        else:
            slow_far = cfg.safe_dist_slow_far
        # H1 (revised): SLOW_DOWN uses dist_min for warn band, but only when
        # dist_ee is also within 2× warn — prevents distant shoulder from
        # triggering SLOW_DOWN while still catching forearm/wrist proximity.
        dist_hard = dist
        if use_envelope and dist_ee < warn_dist * 2.0:
            dist_slow = dist
        elif use_envelope:
            dist_slow = max(dist, dist_ee)
        else:
            dist_slow = dist

        if (
            held_object_active
            and dist_min_held is not None
            and float(dist_min_held) < HELD_CRITICAL_STOP_M
        ):
            decisions.append(
                (
                    GateDecision.STOP,
                    f"held_critical: held envelope inside hard zone "
                    f"(dist_min_held={float(dist_min_held):.3f}m < {HELD_CRITICAL_STOP_M:.3f}m)",
                    "held_critical",
                )
            )
        elif dist_hard < hard_stop:
            # 2.5b: 包络进 Tier0 但 EE 仍远 → 不提前后退（用户目视：离手尚远即避让过保守）
            if not (use_envelope and dist_ee >= warn_dist):
                decisions.append(
                    (
                        GateDecision.STOP,
                        f"static_collision: hand inside hard zone (dist={dist_hard:.3f}m < {hard_stop:.3f}m)",
                        "static",
                    )
                )
        elif dist_slow < warn_dist:
            decisions.append(
                (
                    GateDecision.SLOW_DOWN,
                    f"static_warning: hand in caution zone (dist={dist:.3f}m < {warn_dist:.3f}m)",
                    "static",
                )
            )
        elif slow_far is not None and dist_slow < slow_far:
            decisions.append(
                (
                    GateDecision.SLOW_DOWN,
                    f"static_far: hand in far caution zone (dist={dist:.3f}m < {slow_far:.3f}m)",
                    "static_far",
                )
            )

        if math.isfinite(ttc):
            if ttc < cfg.ttc_threshold:
                decisions.append(
                    (
                        GateDecision.STOP,
                        f"dynamic_ttc: {ttc:.3f}s to potential contact",
                        "ttc",
                    )
                )
            elif ttc < cfg.ttc_warn_threshold:
                decisions.append(
                    (
                        GateDecision.SLOW_DOWN,
                        f"dynamic_ttc_warning: {ttc:.3f}s",
                        "ttc",
                    )
                )

        # Check the PROPOSED EE position, not the current one.
        # Checking current position creates a one-way trap: once the EE is
        # outside (e.g. pushed by a detour waypoint), every subsequent step
        # produces STOP because the gate zeros all actions — including actions
        # that would bring the EE back inside.
        _probe_pos = proposed_ee_pos if proposed_ee_pos is not None else state.ee_pos
        if not cfg.workspace.contains(_probe_pos):
            decisions.append(
                (GateDecision.STOP, "workspace_boundary_violation", "workspace")
            )

        # --- G5a: Functional risk checks ---
        if functional_risk_info:
            _rewinds = functional_risk_info.get("rewind_attempts", 0)
            _release_ok = functional_risk_info.get("release_in_zone", True)
            _max_rewinds = functional_risk_info.get("max_rewinds", 2)
            # Repeated re-grasp failures → functional (gripping/tool misuse).
            if _rewinds >= _max_rewinds:
                decisions.append(
                    (
                        GateDecision.STOP,
                        f"functional_grip: {_rewinds} re-grasp failures "
                        f"(max {_max_rewinds}) — gripping or part defect",
                        "functional",
                    )
                )
            # Release outside placement zone → functional placement error.
            if not _release_ok:
                decisions.append(
                    (
                        GateDecision.SLOW_DOWN,
                        "functional_placement: EE outside target zone during release",
                        "functional",
                    )
                )

        if not decisions:
            return GateResult(
                g_t=GateDecision.ALLOW,
                reason="allow",
                metadata=metadata,
            )

        priority = {GateDecision.STOP: 2, GateDecision.SLOW_DOWN: 1, GateDecision.ALLOW: 0}
        best = max(decisions, key=lambda item: priority[item[0]])
        g_t, reason, trigger = best
        metadata["trigger_rule"] = trigger
        if g_t == GateDecision.SLOW_DOWN:
            # When multiple SLOW_DOWN triggers fire (e.g. static + ttc), pick
            # the most conservative alpha rather than the first in insertion
            # order.  A fast hand that triggers both static_warn and ttc_warn
            # should get ttc's stronger braking (alpha 0.50), not static's
            # default (0.30).
            slow_decisions = [d for d in decisions if d[0] == GateDecision.SLOW_DOWN]
            max_alpha = cfg.slow_down_alpha
            best_trigger = trigger
            best_reason = reason
            for _, r, trig in slow_decisions:
                if trig == "static_far":
                    alpha = cfg.slow_down_alpha_far
                elif trig == "ttc":
                    alpha = (
                        cfg.slow_down_alpha_ttc
                        if cfg.slow_down_alpha_ttc is not None
                        else cfg.slow_down_alpha
                    )
                else:
                    alpha = cfg.slow_down_alpha
                if alpha > max_alpha:
                    max_alpha = alpha
                    best_trigger = trig
                    best_reason = r
            metadata["trigger_rule"] = best_trigger
            metadata["slow_down_alpha"] = max_alpha
            reason = best_reason
        return GateResult(g_t=g_t, reason=reason, metadata=metadata)

    def _compute_ttc(
        self,
        state: SafetyState,
        dist: float,
        *,
        closest_primitive_pos: np.ndarray | None = None,
        closest_primitive_id: str = "",
    ) -> tuple[float, float]:
        """Compute TTC using envelope-relative approach direction when available.

        S7 Option C: when ``closest_primitive_pos`` is provided, the radial
        approach direction is measured from the closest envelope primitive to
        the human hand (not EE→hand).  This closes the tangential-motion
        blind spot where the hand approaches the held box / arm link from the
        side but EE radial velocity ≈ 0.

        F2: when ``ttc_primitive_vel_mode == "finite_diff"`` and the closest
        primitive is an arm link (not gripper/held), the primitive's own
        linear velocity is computed via FK finite differences using
        ``joint_vel``.  This is kinematically correct to first order,
        whereas the legacy ``"ee_proxy"`` mode re-uses ``ee_vel`` for all
        primitives (a reasonable approximation for wrist-mounted primitives,
        but inexact for shoulder / upper-arm / forearm links).
        """
        cfg = self.config
        if dist < cfg.eps:
            return 0.0, float("inf")

        # Use the closest envelope primitive as the reference point for
        # approach direction when available; fall back to EE position.
        use_primitive = closest_primitive_pos is not None
        ref_pos = closest_primitive_pos if use_primitive else state.ee_pos
        rel = state.human_hand_pos - ref_pos
        norm = float(math.sqrt(sum(float(x) ** 2 for x in rel)))
        if norm < cfg.eps:
            return 0.0, float("inf")

        # Compute the velocity of the reference point.
        if (
            use_primitive
            and cfg.ttc_primitive_vel_mode == "finite_diff"
            and closest_primitive_id
        ):
            from .gt_branches import ur10e_primitive_velocity_fd

            prim_vel = ur10e_primitive_velocity_fd(
                state.joint_pos,
                state.joint_vel,
                closest_primitive_id,
            )
            if prim_vel is not None:
                ref_vel = prim_vel
            else:
                # Gripper / held primitive — EE velocity is exact.
                ref_vel = state.ee_vel
        else:
            ref_vel = state.ee_vel

        v_rel = state.human_hand_vel - ref_vel
        approach_rate = -float(sum(v_rel[i] * rel[i] for i in range(3))) / norm

        if approach_rate <= cfg.eps:
            return float("inf"), approach_rate

        return dist / approach_rate, approach_rate

    def _compute_forecast_approach_rate(
        self,
        state: SafetyState,
        dist: float,
        metadata: dict,
    ) -> float:
        """S13 P0 shadow: hand constant-velocity radial rate + dist_min slope."""
        cfg = self.config
        rates: list[float] = []

        rel = state.human_hand_pos - state.ee_pos
        norm = float(math.sqrt(sum(float(x) ** 2 for x in rel)))
        if norm >= cfg.eps:
            hand_radial = -float(
                sum(state.human_hand_vel[i] * rel[i] for i in range(3))
            ) / norm
            metadata["hand_radial_approach_rate"] = hand_radial
            if hand_radial > cfg.eps:
                rates.append(hand_radial)

        if self._prev_dist_min is not None and self._prev_sim_time is not None:
            dt = float(state.sim_time) - self._prev_sim_time
            if dt <= cfg.eps:
                # F3: configurable dt-fallback.  "skip" is the default because
                # using control_dt when the real physics step is smaller
                # underestimates the approach rate (false negative for forecast
                # warnings).  "control_dt" preserves legacy behaviour for
                # backward-compatible replay of existing logs.
                if cfg.forecast_dt_fallback_mode == "control_dt":
                    dt = cfg.control_dt
                else:
                    dt = 0.0  # skip — rate stays 0, no forecast this step
            if dt > cfg.eps:
                dist_rate = -(dist - self._prev_dist_min) / dt
                metadata["dist_min_slope_rate"] = dist_rate
                if dist_rate > cfg.eps:
                    rates.append(dist_rate)

        return max(rates) if rates else 0.0

    def _forecast_ttc(self, dist: float, forecast_rate: float) -> float:
        cfg = self.config
        if forecast_rate <= cfg.eps:
            return float("inf")
        margin = max(dist - cfg.effective_hard_stop, 0.0)
        if margin <= cfg.eps:
            return 0.0
        return margin / forecast_rate
