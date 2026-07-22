#!/usr/bin/env python3
"""Offline unit tests for VLM five-stage schema (no network/Isaac)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Import leaf packages without GMRobot/__init__.py (avoids IsaacLab).
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from vlm.schema import (  # noqa: E402
    SchemaValidationError,
    extract_json_object,
    keywords_to_text_prompt,
    make_error_result,
    normalize_keywords,
    parse_model_text_to_success,
    validate_success_payload,
)


def _ok_payload(**overrides):
    base = {
        "ok": True,
        "request_id": "r1",
        "frame_id": "f1",
        "scene_summary": "hand near gripper",
        "keywords": ["bare human hand", "robot gripper"],
        "risk_type": "static",
        "risk_confidence": 0.8,
        "affected_entities": ["hand"],
        "predicted_consequence": "collision",
        "prediction_horizon_s": 1.5,
        "explanation": "close proximity",
        "suggested_action": "slow_down",
        "spatial_hint": "left",
        "prompt_version": "five_stage_safety_v1",
        "schema_version": "five_stage_vlm_v1",
        "model_id": "test-model",
        "latency_ms": 12.0,
    }
    base.update(overrides)
    return base


def test_round_trip():
    out = validate_success_payload(_ok_payload())
    assert out["ok"] is True
    assert out["keywords"] == ["bare human hand", "robot gripper"]


def test_fenced_json_parse():
    text = """Here you go:\n```json\n{"risk_type":"dynamic","keywords":["a"],"suggested_action":"stop","spatial_hint":"none","risk_confidence":0.9,"affected_entities":[],"predicted_consequence":"x","prediction_horizon_s":1.0,"explanation":"e","scene_summary":"s"}\n```"""
    obj = extract_json_object(text)
    assert obj["risk_type"] == "dynamic"
    parsed = parse_model_text_to_success(
        text, request_id="r", frame_id="f", model_id="m", latency_ms=1.0
    )
    assert parsed["ok"] is True
    assert parsed["suggested_action"] == "stop"


def test_missing_field_parse_error():
    bad = _ok_payload()
    del bad["predicted_consequence"]
    try:
        validate_success_payload(bad)
        assert False, "expected failure"
    except SchemaValidationError as exc:
        assert exc.error_type == "schema_error"


def test_invalid_enums_and_confidence():
    for kwargs in (
        {"risk_type": "weird"},
        {"suggested_action": "dash"},
        {"risk_confidence": 1.5},
        {"spatial_hint": "diagonal"},
    ):
        try:
            validate_success_payload(_ok_payload(**kwargs))
            assert False, kwargs
        except SchemaValidationError:
            pass


def test_no_silent_static_fallback_on_error():
    err = make_error_result(
        request_id="r",
        frame_id="f",
        error_type="parse_error",
        error="boom",
    )
    assert err["ok"] is False
    assert "risk_type" not in err or err.get("risk_type") != "static"
    assert err.get("suggested_action") != "slow_down"


def test_keyword_normalize():
    assert normalize_keywords([" Hand ", "hand", "", "Gripper"]) == ["Hand", "Gripper"]
    assert keywords_to_text_prompt(["a", "b"]) == "a . b"


if __name__ == "__main__":
    test_round_trip()
    test_fenced_json_parse()
    test_missing_field_parse_error()
    test_invalid_enums_and_confidence()
    test_no_silent_static_fallback_on_error()
    test_keyword_normalize()
    print("All VLM schema unit tests passed.")
