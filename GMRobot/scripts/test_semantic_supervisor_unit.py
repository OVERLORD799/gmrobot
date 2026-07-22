#!/usr/bin/env python3
"""V1-B SemanticSafetySupervisor unit tests (offline, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import types

ROOT = Path(__file__).resolve().parents[1]
_SAFETY = ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))
# Avoid safety/__init__.py (torch) for offline host tests.
_pkg = types.ModuleType("safety")
_pkg.__path__ = [str(_SAFETY)]
sys.modules["safety"] = _pkg

from safety.semantic_supervisor import (  # noqa: E402
    GATE_ALLOW,
    GATE_SLOW_DOWN,
    GATE_STOP,
    REASON_ACTION_NOT_ALLOWED,
    REASON_CONSISTENCY_PENDING,
    REASON_DISABLED,
    REASON_DUPLICATE_REQUEST,
    REASON_GEOMETRY_ALREADY_STRICTER,
    REASON_INVALID_HORIZON,
    REASON_INVALID_MODE,
    REASON_LOW_CONFIDENCE,
    REASON_MISSING_CONSEQUENCE,
    REASON_MISSING_ENTITIES,
    REASON_MISSING_ID,
    REASON_RESULT_TOO_OLD,
    REASON_RISK_TYPE_NOT_ALLOWED,
    REASON_SCHEMA_INVALID,
    REASON_STALE,
    REASON_UNKNOWN_GATE,
    REASON_VLM_ERROR,
    SemanticAdvisoryInput,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
    UnknownGateError,
    fuse_monotonic_gate,
)


def _cfg(**kw) -> SemanticSupervisorConfig:
    base = dict(
        enabled=True,
        enforcement_mode="shadow",
        allowed_actions=("slow_down",),
        allowed_risk_types=("dynamic", "functional"),
        min_risk_confidence=0.85,
        max_result_age_s=2.0,
        min_prediction_horizon_s=0.0,
        max_prediction_horizon_s=3.0,
        min_consistent_results=2,
        consistency_window_s=10.0,
        cooldown_s=5.0,
        limited_active_speed_scale=0.5,
        reject_static_risk_in_v1=True,
        allow_stop=False,
        allow_replan=False,
    )
    base.update(kw)
    return SemanticSupervisorConfig.from_dict(base)


def _good(**kw) -> SemanticAdvisoryInput:
    data = dict(
        episode_id="0",
        sim_step=0,
        current_time_s=1.0,
        request_id="req-a",
        frame_id="frm-a",
        result_age_s=0.1,
        schema_version="five_stage_vlm_v1",
        prompt_version="five_stage_safety_v1",
        model_id="synthetic",
        gateway_parse_ok=True,
        risk_type="dynamic",
        risk_confidence=0.92,
        affected_entities=["human", "ee"],
        predicted_consequence="potential collision with human",
        prediction_horizon_s=1.5,
        suggested_action="slow_down",
        spatial_hint="left",
        current_geometry_gate=GATE_ALLOW,
        stale=False,
        error_type="",
        synthetic=True,
    )
    data.update(kw)
    return SemanticAdvisoryInput(**data)


def test_disabled_reject():
    s = SemanticSafetySupervisor(_cfg(enabled=False))
    d = s.evaluate(_good())
    assert d.accepted is False and d.rejection_reason == REASON_DISABLED
    assert d.intentional_control_effect is False


def test_non_shadow_mode_reject():
    s = SemanticSafetySupervisor(_cfg(enforcement_mode="live"))
    d = s.evaluate(_good())
    assert d.rejection_reason == REASON_INVALID_MODE


def test_schema_invalid():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(gateway_parse_ok=False))
    assert d.rejection_reason == REASON_SCHEMA_INVALID
    d2 = s.evaluate(_good(request_id="req-b", frame_id="frm-b", schema_version=""))
    assert d2.rejection_reason == REASON_SCHEMA_INVALID


def test_vlm_error():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(error_type="timeout"))
    assert d.rejection_reason == REASON_VLM_ERROR


def test_stale():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(stale=True))
    assert d.rejection_reason == REASON_STALE


def test_result_too_old():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(result_age_s=5.0))
    assert d.rejection_reason == REASON_RESULT_TOO_OLD


def test_missing_ids():
    s = SemanticSafetySupervisor(_cfg())
    assert s.evaluate(_good(request_id="")).rejection_reason == REASON_MISSING_ID
    assert s.evaluate(_good(frame_id="")).rejection_reason == REASON_MISSING_ID


def test_duplicate_request():
    s = SemanticSafetySupervisor(_cfg())
    d1 = s.evaluate(_good())
    assert d1.rejection_reason == REASON_CONSISTENCY_PENDING
    d2 = s.evaluate(_good())  # same request_id
    assert d2.rejection_reason == REASON_DUPLICATE_REQUEST


def test_action_not_allowed():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(suggested_action="stop"))
    assert d.rejection_reason == REASON_ACTION_NOT_ALLOWED
    d2 = s.evaluate(_good(request_id="r2", frame_id="f2", suggested_action="replan"))
    assert d2.rejection_reason == REASON_ACTION_NOT_ALLOWED
    assert d2.would_replan is False


def test_risk_type_not_allowed_static():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(risk_type="static"))
    assert d.rejection_reason == REASON_RISK_TYPE_NOT_ALLOWED


def test_low_confidence():
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(risk_confidence=0.5))
    assert d.rejection_reason == REASON_LOW_CONFIDENCE


def test_horizon_bounds():
    s = SemanticSafetySupervisor(_cfg())
    assert s.evaluate(_good(prediction_horizon_s=-0.1)).rejection_reason == REASON_INVALID_HORIZON
    assert (
        s.evaluate(_good(request_id="r2", frame_id="f2", prediction_horizon_s=9.0)).rejection_reason
        == REASON_INVALID_HORIZON
    )


def test_missing_consequence_entities():
    s = SemanticSafetySupervisor(_cfg())
    assert (
        s.evaluate(_good(predicted_consequence="")).rejection_reason == REASON_MISSING_CONSEQUENCE
    )
    assert (
        s.evaluate(_good(request_id="r2", frame_id="f2", affected_entities=[])).rejection_reason
        == REASON_MISSING_ENTITIES
    )


def test_consistency_then_accept():
    s = SemanticSafetySupervisor(_cfg())
    d1 = s.evaluate(_good(request_id="r1", frame_id="f1", current_time_s=1.0))
    assert d1.accepted is False and d1.rejection_reason == REASON_CONSISTENCY_PENDING
    assert d1.consistency_count == 1
    d2 = s.evaluate(_good(request_id="r2", frame_id="f2", current_time_s=1.5, sim_step=1))
    assert d2.accepted is True
    assert d2.requested_gate == GATE_SLOW_DOWN
    assert d2.effective_gate_shadow == GATE_SLOW_DOWN
    assert d2.would_slow is True
    assert d2.would_stop is False
    assert d2.would_replan is False
    assert d2.intentional_control_effect is False
    assert d2.synthetic is True


def test_key_change_resets_consistency():
    s = SemanticSafetySupervisor(_cfg())
    s.evaluate(_good(request_id="r1", frame_id="f1", spatial_hint="left"))
    d = s.evaluate(
        _good(request_id="r2", frame_id="f2", spatial_hint="right", current_time_s=1.2)
    )
    assert d.rejection_reason == REASON_CONSISTENCY_PENDING
    assert d.consistency_count == 1


def test_window_timeout_resets():
    s = SemanticSafetySupervisor(_cfg(consistency_window_s=1.0))
    s.evaluate(_good(request_id="r1", frame_id="f1", current_time_s=0.0))
    d = s.evaluate(_good(request_id="r2", frame_id="f2", current_time_s=5.0))
    assert d.rejection_reason == REASON_CONSISTENCY_PENDING
    assert d.consistency_count == 1


def test_geometry_stop_not_downgraded():
    assert fuse_monotonic_gate(GATE_STOP, GATE_SLOW_DOWN) == GATE_STOP
    s = SemanticSafetySupervisor(_cfg())
    s.evaluate(_good(request_id="r1", frame_id="f1", current_geometry_gate=GATE_STOP))
    d = s.evaluate(
        _good(request_id="r2", frame_id="f2", current_time_s=1.2, current_geometry_gate=GATE_STOP)
    )
    assert d.rejection_reason == REASON_GEOMETRY_ALREADY_STRICTER
    assert d.effective_gate_shadow == GATE_STOP
    assert d.monotonicity_ok is True


def test_geometry_slow_not_downgraded_by_empty():
    assert fuse_monotonic_gate(GATE_SLOW_DOWN, None) == GATE_SLOW_DOWN
    assert fuse_monotonic_gate(GATE_SLOW_DOWN, "") == GATE_SLOW_DOWN


def test_allow_to_shadow_slow():
    assert fuse_monotonic_gate(GATE_ALLOW, GATE_SLOW_DOWN) == GATE_SLOW_DOWN


def test_unknown_gate_fails():
    try:
        fuse_monotonic_gate("MAYBE", GATE_SLOW_DOWN)
        assert False
    except UnknownGateError:
        pass
    s = SemanticSafetySupervisor(_cfg())
    d = s.evaluate(_good(current_geometry_gate="NOT_A_GATE"))
    assert d.rejection_reason == REASON_UNKNOWN_GATE
    assert d.monotonicity_ok is False


def test_would_stop_replan_effect_always_false_on_accept():
    s = SemanticSafetySupervisor(_cfg())
    s.evaluate(_good(request_id="r1", frame_id="f1"))
    d = s.evaluate(_good(request_id="r2", frame_id="f2", current_time_s=1.2))
    assert d.accepted
    assert d.would_stop is False
    assert d.would_replan is False
    assert d.intentional_control_effect is False


def test_same_request_not_double_counted_for_consistency():
    s = SemanticSafetySupervisor(_cfg())
    s.evaluate(_good(request_id="r1", frame_id="f1"))
    # duplicate should not bump count to 2
    d = s.evaluate(_good(request_id="r1", frame_id="f1", current_time_s=1.1))
    assert d.rejection_reason == REASON_DUPLICATE_REQUEST
    # still need a second distinct request
    d2 = s.evaluate(_good(request_id="r2", frame_id="f2", current_time_s=1.2))
    assert d2.accepted is True
    assert d2.consistency_count == 2


def test_default_config_file_disabled_shadow():
    from safety.semantic_supervisor import load_semantic_supervisor_config

    cfg = load_semantic_supervisor_config(ROOT / "configs" / "semantic_safety_supervisor.yaml")
    assert cfg.enabled is False
    assert cfg.enforcement_mode == "shadow"


def test_int_gate_mapping():
    # GateDecision ints: ALLOW=0 STOP=1 SLOW_DOWN=2
    assert fuse_monotonic_gate(0, GATE_SLOW_DOWN) == GATE_SLOW_DOWN
    assert fuse_monotonic_gate(1, GATE_SLOW_DOWN) == GATE_STOP
    assert fuse_monotonic_gate(2, None) == GATE_SLOW_DOWN


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("OK", t.__name__)
    print(f"PASS {len(tests)}")
