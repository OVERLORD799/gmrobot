#!/usr/bin/env python3
"""VLM service contract tests without FastAPI/models."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))

from vlm.service_handlers import analyze_request_dict  # noqa: E402


def test_stub_never_ok_true():
    out = analyze_request_dict(
        {"image_b64": "aaa", "request_id": "r1", "frame_id": "f1"},
        use_stub=True,
        model_id_default="m",
    )
    assert out["ok"] is False
    assert out["error_type"] == "stub_mode"
    assert out.get("synthetic") is True
    assert out.get("suggested_action") != "slow_down"


def test_empty_image_schema_error():
    out = analyze_request_dict(
        {"image_b64": "", "request_id": "r2", "frame_id": "f2"},
        use_stub=False,
        model_id_default="m",
    )
    assert out["ok"] is False
    assert out["error_type"] == "schema_error"


def test_model_text_parsed_not_hardcoded():
    def runner(_req):
        return (
            '{"scene_summary":"s","keywords":["hand"],"risk_type":"dynamic",'
            '"risk_confidence":0.7,"affected_entities":["hand"],'
            '"predicted_consequence":"c","prediction_horizon_s":1.0,'
            '"explanation":"e","suggested_action":"stop","spatial_hint":"left"}'
        )

    out = analyze_request_dict(
        {"image_b64": "abc", "request_id": "r3", "frame_id": "f3"},
        use_stub=False,
        model_id_default="m",
        run_model=runner,
    )
    assert out["ok"] is True
    assert out["risk_type"] == "dynamic"
    assert out["suggested_action"] == "stop"
    assert out["keywords"] == ["hand"]


def test_no_hardcoded_literals_in_service_file():
    src = (ROOT / "deploy" / "ai_server" / "vlm_service.py").read_text(encoding="utf-8")
    assert '"vlm_risk_type": "static"' not in src
    assert '"vlm_severity": "medium"' not in src
    assert '"vlm_suggested_action": "slow_down"' not in src


if __name__ == "__main__":
    test_stub_never_ok_true()
    test_empty_image_schema_error()
    test_model_text_parsed_not_hardcoded()
    test_no_hardcoded_literals_in_service_file()
    print("All VLM service contract unit tests passed.")
