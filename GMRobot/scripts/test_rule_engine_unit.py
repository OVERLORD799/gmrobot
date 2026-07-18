"""Unit tests for Layer 1 RuleEngine."""

from __future__ import annotations

import sys
from pathlib import Path

import math
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _safety_import import bootstrap_safety, load_safety_module

safety = bootstrap_safety()
load_safety_module("rule_engine")
SafetyConfig = safety.config.SafetyConfig
RuleEngine = safety.rule_engine.RuleEngine
GateDecision = safety.types.GateDecision
SafetyState = safety.types.SafetyState


def _state(dist_offset: float) -> SafetyState:
    hand = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    ee = hand + np.array([dist_offset, 0.0, 0.0], dtype=np.float32)
    return SafetyState(
        ee_pos=ee,
        ee_vel=np.zeros(3, dtype=np.float32),
        human_hand_pos=hand,
        human_hand_vel=np.zeros(3, dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.0,
        step_index=0,
    )


def test_static_hard_stop():
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    result = RuleEngine(cfg).evaluate(_state(0.10))
    assert result.g_t == GateDecision.STOP
    assert result.metadata["trigger_rule"] == "static"


def test_static_warn_slow():
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    result = RuleEngine(cfg).evaluate(_state(0.15))
    assert result.g_t == GateDecision.SLOW_DOWN
    assert result.metadata["trigger_rule"] == "static"
    assert abs(result.metadata["slow_down_alpha"] - 0.3) < 1e-6


def test_static_far_slow_when_enabled():
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        safe_dist_slow_far=0.35,
        slow_down_alpha_far=0.55,
    )
    result = RuleEngine(cfg).evaluate(_state(0.25))
    assert result.g_t == GateDecision.SLOW_DOWN
    assert result.metadata["trigger_rule"] == "static_far"
    assert abs(result.metadata["slow_down_alpha"] - 0.55) < 1e-6


def test_static_far_disabled_allows():
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        safe_dist_slow_far=None,
    )
    result = RuleEngine(cfg).evaluate(_state(0.25))
    assert result.g_t == GateDecision.ALLOW


def test_far_allow_beyond_slow_far():
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        safe_dist_slow_far=0.35,
    )
    result = RuleEngine(cfg).evaluate(_state(0.50))
    assert result.g_t == GateDecision.ALLOW


def test_envelope_gating_uses_dist_for_gating_keeps_ee_log():
    """EE far outside warn while envelope in hard zone → ALLOW; EE close → STOP."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    result = RuleEngine(cfg).evaluate(_state(0.25), dist_for_gating=0.10)
    assert result.g_t == GateDecision.ALLOW
    assert abs(result.metadata["dist_ee_human"] - 0.25) < 1e-6
    assert abs(result.metadata["dist_min_envelope"] - 0.10) < 1e-6
    result = RuleEngine(cfg).evaluate(_state(0.15), dist_for_gating=0.10)
    assert result.g_t == GateDecision.STOP


def test_envelope_gating_disabled_ignores_dist_for_gating():
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    result = RuleEngine(cfg).evaluate(_state(0.25), dist_for_gating=0.10)
    assert result.g_t == GateDecision.ALLOW
    assert "dist_min_envelope" not in result.metadata


def test_envelope_gating_disables_static_far_by_default():
    """Without safe_dist_slow_far_envelope, static_far stays off under envelope gating."""
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        safe_dist_slow_far=0.35,
    )
    cfg.envelope.gating_enabled = True
    result = RuleEngine(cfg).evaluate(_state(0.25), dist_for_gating=0.25)
    assert result.g_t == GateDecision.ALLOW
    assert result.metadata.get("trigger_rule") is None


def test_envelope_gating_static_far_with_envelope_threshold():
    """W16: safe_dist_slow_far_envelope enables static_far under envelope gating."""
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        safe_dist_slow_far=0.35,
        safe_dist_slow_far_envelope=0.32,
    )
    cfg.envelope.gating_enabled = True
    # dist_for_gating=0.22, EE=0.30 → dist_slow=max(0.22,0.30)=0.30
    # 0.19 ≤ 0.30 < 0.32 → SLOW_DOWN static_far (envelope).
    result = RuleEngine(cfg).evaluate(_state(0.30), dist_for_gating=0.22)
    assert result.g_t == GateDecision.SLOW_DOWN
    assert result.metadata["trigger_rule"] == "static_far"
    # dist_for_gating=0.40, EE=0.30 → dist_slow=max(0.40,0.30)=0.40 > 0.32 → ALLOW.
    result2 = RuleEngine(cfg).evaluate(_state(0.30), dist_for_gating=0.40)
    assert result2.g_t == GateDecision.ALLOW


def test_envelope_gating_ttc_uses_dist_min_distance():
    """TTC uses dist_min distance under envelope gating (ADR O5 / S7 Option B)."""
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        ttc_threshold=0.5,
        ttc_warn_threshold=1.5,
    )
    cfg.envelope.gating_enabled = True
    hand = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    ee = hand + np.array([0.40, 0.0, 0.0], dtype=np.float32)
    state = SafetyState(
        ee_pos=ee,
        ee_vel=np.array([-0.5, 0.0, 0.0], dtype=np.float32),
        human_hand_pos=hand,
        human_hand_vel=np.zeros(3, dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.0,
        step_index=0,
    )
    # dist_min 0.20 / approach_rate 0.5 → ttc=0.4 < 0.5 → STOP (EE dist 0.40 alone → 0.8 SLOW).
    result = RuleEngine(cfg).evaluate(state, dist_for_gating=0.20)
    assert result.g_t == GateDecision.STOP
    assert result.metadata["trigger_rule"] == "ttc"
    assert abs(result.metadata["ttc"] - 0.4) < 1e-6


def test_envelope_gating_ttc_dist_source_ee_overrides_envelope():
    """ttc_dist_source=ee restores EE distance for TTC under envelope gating."""
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        ttc_threshold=0.5,
        ttc_warn_threshold=1.5,
        ttc_dist_source="ee",
    )
    cfg.envelope.gating_enabled = True
    hand = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    ee = hand + np.array([0.40, 0.0, 0.0], dtype=np.float32)
    state = SafetyState(
        ee_pos=ee,
        ee_vel=np.array([-0.5, 0.0, 0.0], dtype=np.float32),
        human_hand_pos=hand,
        human_hand_vel=np.zeros(3, dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.0,
        step_index=0,
    )
    # dist_min 0.20 would STOP with envelope TTC; EE dist 0.40 → ttc=0.8 → no STOP.
    result = RuleEngine(cfg).evaluate(state, dist_for_gating=0.20)
    assert result.g_t != GateDecision.STOP
    assert result.metadata["trigger_rule"] != "ttc" or result.g_t == GateDecision.SLOW_DOWN


def test_envelope_gating_slow_band_uses_dist_min():
    """H1 (revised): SLOW_DOWN uses dist_min when EE is within 2× warn (0.38m)."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    # EE 0.30 < 0.38 (2× warn), dist_min=0.17 < 0.19 → SLOW_DOWN.
    result = RuleEngine(cfg).evaluate(_state(0.30), dist_for_gating=0.17)
    assert result.g_t == GateDecision.SLOW_DOWN
    # EE 0.40 > 0.38 (2× warn), dist_min=0.17 → ALLOW (EE too far, shoulder only).
    result = RuleEngine(cfg).evaluate(_state(0.40), dist_for_gating=0.17)
    assert result.g_t == GateDecision.ALLOW
    # EE 0.15 + dist_min 0.10 → STOP (EE in hard zone).
    result = RuleEngine(cfg).evaluate(_state(0.15), dist_for_gating=0.10)
    assert result.g_t == GateDecision.STOP
    # EE 0.17 + dist_min 0.15 → SLOW_DOWN.
    result = RuleEngine(cfg).evaluate(_state(0.17), dist_for_gating=0.15)
    assert result.g_t == GateDecision.SLOW_DOWN


def test_envelope_gating_tier0_allow_when_ee_far():
    """dist_min in hard zone but EE outside warn → ALLOW (no early retreat)."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    result = RuleEngine(cfg).evaluate(_state(0.30), dist_for_gating=0.12)
    assert result.g_t == GateDecision.ALLOW
    result = RuleEngine(cfg).evaluate(_state(0.15), dist_for_gating=0.10)
    assert result.g_t == GateDecision.STOP


def test_held_critical_stops_when_tier0_allow_would_apply():
    """Carrying: dist_min_held in hard zone → STOP even if EE outside warn band."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    result = RuleEngine(cfg).evaluate(
        _state(0.30),
        dist_for_gating=0.12,
        dist_min_held=0.05,
        held_object_active=True,
    )
    assert result.g_t == GateDecision.STOP
    assert result.metadata["trigger_rule"] == "held_critical"
    result_allow = RuleEngine(cfg).evaluate(
        _state(0.30),
        dist_for_gating=0.12,
        dist_min_held=0.20,
        held_object_active=True,
    )
    assert result_allow.g_t == GateDecision.ALLOW


def test_held_critical_allows_normal_carry_geometry():
    """Carry transit dist_min_held ~0.12m must not Tier0 STOP (block_place S1)."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    result = RuleEngine(cfg).evaluate(
        _state(0.30),
        dist_for_gating=0.12,
        dist_min_held=0.128,
        held_object_active=True,
    )
    assert result.g_t == GateDecision.ALLOW


def test_held_critical_stops_at_grasp_knockoff_geometry():
    """Part 5 knock-off: EE co-located with hand, held gap zero → STOP."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    hand = np.array([0.645, 0.147, 0.24], dtype=np.float32)
    ee = np.array([0.645, 0.147, 0.238], dtype=np.float32)
    state = SafetyState(
        ee_pos=ee,
        ee_vel=np.zeros(3, dtype=np.float32),
        human_hand_pos=hand,
        human_hand_vel=np.zeros(3, dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=33.1,
        step_index=1655,
    )
    result = RuleEngine(cfg).evaluate(
        state,
        dist_for_gating=0.0,
        dist_min_held=0.0,
        held_object_active=True,
    )
    assert result.g_t == GateDecision.STOP
    assert result.metadata["trigger_rule"] in ("held_critical", "static")


def test_ttc_forecast_s_from_hand_vel_and_dist_slope():
    """S13 P0 shadow: ttc_forecast_s uses hand radial rate and dist_min trend."""
    cfg = SafetyConfig(safe_dist_hard_stop=0.13, safe_dist_warn=0.19)
    cfg.envelope.gating_enabled = True
    hand = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    ee = hand + np.array([0.30, 0.0, 0.0], dtype=np.float32)
    engine = RuleEngine(cfg)
    state0 = SafetyState(
        ee_pos=ee,
        ee_vel=np.zeros(3, dtype=np.float32),
        human_hand_pos=hand,
        human_hand_vel=np.zeros(3, dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.0,
        step_index=0,
    )
    r0 = engine.evaluate(state0, dist_for_gating=0.25)
    assert r0.metadata["ttc_forecast_s"] == float("inf")

    state1 = SafetyState(
        ee_pos=ee,
        ee_vel=np.zeros(3, dtype=np.float32),
        human_hand_pos=hand,
        human_hand_vel=np.array([0.5, 0.0, 0.0], dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.02,
        step_index=1,
    )
    r1 = engine.evaluate(state1, dist_for_gating=0.24)
    forecast = float(r1.metadata["ttc_forecast_s"])
    assert math.isfinite(forecast)
    assert 0.15 < forecast < 0.30
    assert "hand_radial_approach_rate" in r1.metadata
    assert "dist_min_slope_rate" in r1.metadata


def test_ttc_option_c_envelope_relative_approach():
    """S7 Option C: approach rate uses closest primitive pos, not EE pos.

    Tangential approach: hand moves sideways toward the held box.
    EE→hand radial velocity ≈ 0 → legacy TTC=∞ (blind spot).
    With closest_primitive_pos (= held box), radial velocity > 0 → finite TTC.
    """
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        ttc_threshold=0.5,
        ttc_warn_threshold=1.5,
    )
    cfg.envelope.gating_enabled = True

    # EE is far away (0.5m X) with zero approach velocity.
    # Hand is near the held box and moving toward it sideways.
    ee = np.array([0.5, 0.0, 0.3], dtype=np.float32)
    hand = np.array([0.15, 0.0, 0.3], dtype=np.float32)
    held_box_pos = np.array([0.10, 0.0, 0.3], dtype=np.float32)  # near hand

    hand_vel = np.array([-0.3, 0.0, 0.0], dtype=np.float32)  # moving toward box
    ee_vel = np.zeros(3, dtype=np.float32)  # EE stationary

    state = SafetyState(
        ee_pos=ee,
        ee_vel=ee_vel,
        human_hand_pos=hand,
        human_hand_vel=hand_vel,
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.0,
        step_index=0,
    )

    # Without closest_primitive_pos: EE→hand radial vel ≈ 0 → TTC=∞.
    result_ee = RuleEngine(cfg).evaluate(state, dist_for_gating=0.05)
    ttc_ee = float(result_ee.metadata["ttc"])
    assert not math.isfinite(ttc_ee)  # blind spot — TTC=∞

    # With closest_primitive_pos (= held box): hand→box radial vel ≈ 0.3 m/s.
    result_env = RuleEngine(cfg).evaluate(
        state, dist_for_gating=0.05,
        closest_primitive_pos=held_box_pos,
    )
    ttc_env = float(result_env.metadata["ttc"])
    # dist=0.05, approach_rate ≈ 0.3 → TTC ≈ 0.17s → triggers STOP (< 0.5s).
    assert math.isfinite(ttc_env)
    assert ttc_env < 0.5
    assert result_env.g_t == GateDecision.STOP
    assert result_env.metadata["trigger_rule"] == "ttc"


def test_ttc_option_c_fallback_to_ee_when_no_primitive():
    """Without closest_primitive_pos, TTC uses EE position (backward compatible)."""
    cfg = SafetyConfig(
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        ttc_threshold=0.5,
        ttc_warn_threshold=1.5,
    )
    ee = np.array([0.3, 0.0, 0.3], dtype=np.float32)
    hand = np.array([0.0, 0.0, 0.3], dtype=np.float32)
    hand_vel = np.array([0.5, 0.0, 0.0], dtype=np.float32)  # toward EE
    state = SafetyState(
        ee_pos=ee, ee_vel=np.zeros(3, dtype=np.float32),
        human_hand_pos=hand, human_hand_vel=hand_vel,
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=0.0, step_index=0,
    )
    # EE-only: hand approaches EE at 0.5 m/s, dist=0.3 → TTC≈0.6s → SLOW_DOWN.
    result = RuleEngine(cfg).evaluate(state, dist_for_gating=0.3)
    assert math.isfinite(float(result.metadata["ttc"]))
    assert float(result.metadata["ttc"]) < 1.0


if __name__ == "__main__":
    test_static_hard_stop()
    test_static_warn_slow()
    test_static_far_slow_when_enabled()
    test_static_far_disabled_allows()
    test_far_allow_beyond_slow_far()
    test_envelope_gating_uses_dist_for_gating_keeps_ee_log()
    test_envelope_gating_disabled_ignores_dist_for_gating()
    test_envelope_gating_disables_static_far_by_default()
    test_envelope_gating_static_far_with_envelope_threshold()
    test_envelope_gating_ttc_uses_dist_min_distance()
    test_envelope_gating_ttc_dist_source_ee_overrides_envelope()
    test_envelope_gating_slow_band_uses_dist_min()
    test_envelope_gating_tier0_allow_when_ee_far()
    test_held_critical_stops_when_tier0_allow_would_apply()
    test_held_critical_allows_normal_carry_geometry()
    test_held_critical_stops_at_grasp_knockoff_geometry()
    test_ttc_forecast_s_from_hand_vel_and_dist_slope()
    test_ttc_option_c_envelope_relative_approach()
    test_ttc_option_c_fallback_to_ee_when_no_primitive()
    print("test_rule_engine_unit: OK")
