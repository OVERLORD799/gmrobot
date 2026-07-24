#!/usr/bin/env python3
"""Unit tests for V1-D3A preregistered gate evaluation (offline)."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_v1d3a_dyn_c_fixed_frame_replay import evaluate_phase1, evaluate_phase2  # noqa: E402


def test_phase1_pass_when_no_dynamic_guess() -> None:
    res = {
        170: {"gateway_parse_ok": True, "risk_type": "static", "risk_confidence": 0.8},
        249: {"gateway_parse_ok": True, "risk_type": "none", "risk_confidence": 0.5},
    }
    out = evaluate_phase1(res)
    assert out["verdict"] == "D3A_NATIVE_DISCIPLINE_PASS"


def test_phase1_fail_on_dynamic_guess_without_evidence() -> None:
    res = {
        170: {"gateway_parse_ok": True, "risk_type": "dynamic", "risk_confidence": 0.9},
        249: {"gateway_parse_ok": True, "risk_type": "static", "risk_confidence": 0.8},
    }
    out = evaluate_phase1(res)
    assert out["verdict"] == "D3A_NATIVE_DISCIPLINE_FAIL"
    assert out["gates"]["dynamic_guess_steps"] == [170]


def test_phase1_fail_on_parse_error() -> None:
    res = {170: {"gateway_parse_ok": False, "risk_type": "static"}}
    out = evaluate_phase1(res)
    assert out["verdict"] == "D3A_NATIVE_DISCIPLINE_FAIL"


def test_phase2_pass_requires_valid_evidence_dynamic_and_conf() -> None:
    ok = evaluate_phase2({"risk_type": "dynamic", "risk_confidence": 0.9}, evidence_valid=True)
    assert ok["verdict"] == "D3A_TEMPORAL_DYNAMIC_PASS"
    low = evaluate_phase2({"risk_type": "dynamic", "risk_confidence": 0.8}, evidence_valid=True)
    assert low["verdict"] == "D3A_TEMPORAL_DYNAMIC_FAIL"
    stat = evaluate_phase2({"risk_type": "static", "risk_confidence": 0.9}, evidence_valid=True)
    assert stat["verdict"] == "D3A_TEMPORAL_DYNAMIC_FAIL"
    noev = evaluate_phase2({"risk_type": "dynamic", "risk_confidence": 0.9}, evidence_valid=False)
    assert noev["verdict"] == "D3A_TEMPORAL_DYNAMIC_FAIL"


if __name__ == "__main__":
    test_phase1_pass_when_no_dynamic_guess()
    test_phase1_fail_on_dynamic_guess_without_evidence()
    test_phase1_fail_on_parse_error()
    test_phase2_pass_requires_valid_evidence_dynamic_and_conf()
    print("PASS test_v1d3a_gate_eval_unit")
