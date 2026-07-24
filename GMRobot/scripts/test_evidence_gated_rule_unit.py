#!/usr/bin/env python3
"""Unit tests for the evidence-gated dynamic rule (V1-D5A, path B)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

# Torch stub so GMRobot.safety.__init__ (Isaac-facing modules) imports on host.
if "torch" not in sys.modules:
    torch = types.ModuleType("torch")
    torch.device = lambda *_a, **_k: "cpu"
    torch.tensor = lambda *a, **k: a
    torch.float32 = "float32"
    torch.no_grad = lambda: type(
        "NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None}
    )()
    sys.modules["torch"] = torch
    sys.modules["torch.nn"] = types.ModuleType("torch.nn")

from GMRobot.safety.evidence_gated_rule import (
    EvidenceGatedDecision,
    decide_dynamic_from_evidence,
)
from GMRobot.vlm.temporal_evidence import TemporalTrackEvidence

VLM_STATIC_LOWCONF = {
    "risk_type": "static", "risk_confidence": 0.7,
    "keywords": ["robotic arm", "containers"], "suggested_action": "continue",
}


def _ev(**kw) -> TemporalTrackEvidence:
    base = dict(
        source_request_id="t", source_frame_id="f", track_id="1",
        canonical_entity="humanoid", selected_label="small humanoid robot",
        track_state="tracking", session_continuity_verified=True,
        score=0.95, speed_px_s=35.0, direction_deg=180.0, motion_bucket="L",
        evidence_age_s=0.1, evidence_source="sam2_track", valid=False,
        session_ref="session_local", rejection_reason="pending_validation",
    )
    base.update(kw)
    return TemporalTrackEvidence(**base)


def test_valid_evidence_triggers_despite_vlm_static_lowconf():
    d = decide_dynamic_from_evidence(_ev(), vlm_annotation=VLM_STATIC_LOWCONF)
    assert d.dynamic_triggered is True
    assert d.gate_confidence == 0.95  # tracker score, not VLM 0.7
    assert d.recommended_action == "slow_down"
    assert d.action_source == "rule_floor"
    assert d.vlm_annotation["risk_type"] == "static"  # annotation preserved, no veto


def test_vlm_cannot_mint_trigger_without_evidence():
    vlm_dynamic = {"risk_type": "dynamic", "risk_confidence": 0.99, "suggested_action": "stop"}
    d = decide_dynamic_from_evidence(None, vlm_annotation=vlm_dynamic)
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "no_track_evidence"


def test_drift_suspect_evidence_rejected():
    d = decide_dynamic_from_evidence(_ev(drift_suspect=True), vlm_annotation=VLM_STATIC_LOWCONF)
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "track_drift_suspect"
    assert d.drift_suspect is True


def test_low_score_evidence_rejected():
    d = decide_dynamic_from_evidence(_ev(score=0.26))
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "score_below_threshold"


def test_low_speed_evidence_rejected():
    d = decide_dynamic_from_evidence(_ev(speed_px_s=5.0))
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "speed_below_threshold"


def test_vlm_can_escalate_action_but_not_relax():
    stop = dict(VLM_STATIC_LOWCONF, suggested_action="stop")
    d = decide_dynamic_from_evidence(_ev(), vlm_annotation=stop)
    assert d.recommended_action == "stop"
    assert d.action_source == "vlm_escalation"

    relax = dict(VLM_STATIC_LOWCONF, suggested_action="continue")
    d2 = decide_dynamic_from_evidence(_ev(), vlm_annotation=relax)
    assert d2.recommended_action == "slow_down"
    assert d2.action_source == "rule_floor"


def test_decision_serializable_and_versioned():
    d = decide_dynamic_from_evidence(_ev())
    assert isinstance(d, EvidenceGatedDecision)
    dd = d.to_dict()
    assert dd["rule_version"] == "evidence_gated_dynamic_rule_v1"
    assert dd["trigger_source"] == "evidence_gated_rule"


def test_lost_track_rejected():
    d = decide_dynamic_from_evidence(_ev(track_state="lost"))
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "track_state_lost"


# ---- rule v2 (D8A window motion) ----

from GMRobot.safety.evidence_gated_rule import decide_dynamic_from_window_motion  # noqa: E402


def _wm(**over):
    base = {
        "valid": True,
        "translation_rate_px_s": 45.0,
        "scale_rate_px_s": 5.0,
        "dynamic_by_translation": True,
        "reason": "",
    }
    base.update(over)
    return base


def test_v2_window_translation_triggers():
    d = decide_dynamic_from_window_motion(_wm(), track_score=0.9, canonical_entity="humanoid")
    assert d.dynamic_triggered is True
    assert d.rule_version == "evidence_gated_dynamic_rule_v2_window"
    assert d.motion_bucket == "window_translation"
    assert d.recommended_action == "slow_down"


def test_v2_sway_below_threshold_not_triggered():
    d = decide_dynamic_from_window_motion(
        _wm(translation_rate_px_s=14.7, dynamic_by_translation=False),
        track_score=0.9, canonical_entity="humanoid",
    )
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "translation_below_threshold"


def test_v2_depth_motion_scale_dominant_fail_closed():
    d = decide_dynamic_from_window_motion(
        _wm(translation_rate_px_s=14.5, scale_rate_px_s=28.8, dynamic_by_translation=False),
        track_score=0.9, canonical_entity="humanoid",
    )
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "translation_below_threshold_scale_dominant"


def test_v2_missing_or_invalid_metrics_fail_closed():
    assert decide_dynamic_from_window_motion(None).dynamic_triggered is False
    d = decide_dynamic_from_window_motion(
        _wm(valid=False, reason="insufficient_boxes_lt_3"), track_score=0.9,
    )
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "insufficient_boxes_lt_3"


def test_v2_low_track_score_rejected():
    d = decide_dynamic_from_window_motion(_wm(), track_score=0.3)
    assert d.dynamic_triggered is False
    assert d.rejection_reason == "track_score_below_min"


def test_v21_depth_path_triggers_when_enabled():
    wm = _wm(translation_rate_px_s=14.5, dynamic_by_translation=False,
             scale_rate_px_s=28.8, depth_motion_suspect=True)
    off = decide_dynamic_from_window_motion(wm, track_score=0.9)
    assert off.dynamic_triggered is False  # v2 default: depth stays fail-closed
    on = decide_dynamic_from_window_motion(wm, track_score=0.9, enable_depth_path=True)
    assert on.dynamic_triggered is True
    assert on.motion_bucket == "window_depth_scale"
    assert on.rule_version == "evidence_gated_dynamic_rule_v2_1_depth"


def test_v21_depth_path_static_sway_still_rejected():
    wm = _wm(translation_rate_px_s=16.0, dynamic_by_translation=False,
             scale_rate_px_s=14.7, depth_motion_suspect=False)
    d = decide_dynamic_from_window_motion(wm, track_score=0.9, enable_depth_path=True)
    assert d.dynamic_triggered is False


def test_v2_vlm_escalates_but_cannot_veto():
    d = decide_dynamic_from_window_motion(
        _wm(), track_score=0.9,
        vlm_annotation={"risk_type": "static", "suggested_action": "stop"},
    )
    assert d.dynamic_triggered is True
    assert d.recommended_action == "stop"
    assert d.action_source == "vlm_escalation"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                fails += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if fails else 0)
