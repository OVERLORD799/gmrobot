#!/usr/bin/env python3
"""Unit tests for Dyn-B acceptance semantics helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_acceptance_semantics import (  # noqa: E402
    derive_proxy_semantics,
    derive_step_completion,
    fail_closed_nonallow_geometry,
)


def test_total_steps_primary_policy_lag_no_misclassify() -> None:
    out = derive_step_completion(total_steps=341, policy_steps=335, max_steps=341, task_completed=False)
    assert out["steps_completed_by_total"] is True
    assert out["termination_reason"] == "MAX_STEPS_REACHED"
    assert out["policy_step_lag"] == 6
    assert out["task_completed"] is False


def test_true_early_termination() -> None:
    out = derive_step_completion(total_steps=300, policy_steps=299, max_steps=341, task_completed=False)
    assert out["steps_completed_by_total"] is False
    assert out["termination_reason"] == "EARLY_TERMINATION"


def test_proxy_telemetry_vs_visual_not_evaluated() -> None:
    rows = [{"step": "200", "proxy_center_x": "0.1", "proxy_center_y": "0", "proxy_center_z": "0"}]
    out = derive_proxy_semantics(rows, 159, 338, legacy_red_proxy_any=None, visual_red_proxy_detected=None)
    assert out["proxy_telemetry_present"] is True
    assert out["visual_red_proxy_detected"] is None
    assert out["visual_red_proxy_evaluation"] == "not_evaluated"


def test_old_schema_compat_legacy_red_proxy_any() -> None:
    out = derive_proxy_semantics([], 159, 338, legacy_red_proxy_any=True, visual_red_proxy_detected=None)
    assert out["proxy_telemetry_present"] is True
    assert out["red_proxy_any_legacy_compat"] is True


def test_nonallow_fail_closed_cannot_be_washed() -> None:
    out = fail_closed_nonallow_geometry(nonallow_points=3, raw_historical_verdict="DYN_B_FORMAL_M1Z9_FAIL_FINAL")
    assert out["fail_closed_triggered"] is True
    assert out["overall"] == "FAIL_NONALLOW_GEOMETRY"


if __name__ == "__main__":
    test_total_steps_primary_policy_lag_no_misclassify()
    test_true_early_termination()
    test_proxy_telemetry_vs_visual_not_evaluated()
    test_old_schema_compat_legacy_red_proxy_any()
    test_nonallow_fail_closed_cannot_be_washed()
    print("ok")
