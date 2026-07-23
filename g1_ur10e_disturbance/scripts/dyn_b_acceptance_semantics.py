#!/usr/bin/env python3
"""Shared Dyn-B acceptance semantics helpers for offline auditors."""

from __future__ import annotations

from typing import Any


def _is_nonzero_proxy_value(value: Any) -> bool:
    text = str(value).strip()
    return text not in {"", "0", "0.0", "nan", "NaN", "inf", "-inf", "None", "null"}


def derive_step_completion(total_steps: int, policy_steps: int, max_steps: int, task_completed: Any) -> dict[str, Any]:
    """Step completion is based on total sim steps, policy is diagnostics only."""
    total_reached = total_steps >= max_steps
    return {
        "total_steps": int(total_steps),
        "policy_steps_last": int(policy_steps),
        "max_steps": int(max_steps),
        "steps_completed_by_total": bool(total_reached),
        "policy_step_lag": int(total_steps - policy_steps),
        "task_completed": task_completed,
        "termination_reason": "MAX_STEPS_REACHED" if total_reached else "EARLY_TERMINATION",
        "policy_steps_role": "diagnostic_only",
    }


def derive_proxy_semantics(
    steps_rows: list[dict[str, Any]],
    window_start: int,
    window_end: int,
    legacy_red_proxy_any: Any | None = None,
    visual_red_proxy_detected: bool | None = None,
) -> dict[str, Any]:
    """Migrate red proxy semantics to telemetry-presence with legacy compatibility."""
    telemetry_present = False
    telemetry_rows = 0
    for row in steps_rows:
        step = int(row["step"])
        if window_start <= step <= window_end:
            vals = (row.get("proxy_center_x", ""), row.get("proxy_center_y", ""), row.get("proxy_center_z", ""))
            if any(_is_nonzero_proxy_value(v) for v in vals):
                telemetry_present = True
                telemetry_rows += 1
    if legacy_red_proxy_any is True:
        telemetry_present = True

    # Without explicit visual segmentation/asset-id evidence, visual flag is not evaluated.
    visual_status = "not_evaluated" if visual_red_proxy_detected is None else "evaluated"
    return {
        "proxy_telemetry_present": bool(telemetry_present),
        "proxy_telemetry_rows_nonzero": int(telemetry_rows),
        "red_proxy_any_legacy_compat": bool(telemetry_present),
        "visual_red_proxy_detected": visual_red_proxy_detected,
        "visual_red_proxy_evaluation": visual_status,
    }


def fail_closed_nonallow_geometry(nonallow_points: int, raw_historical_verdict: str | None = None) -> dict[str, Any]:
    """Keep TTC non-ALLOW fail-closed semantics intact."""
    fail_closed = int(nonallow_points) > 0
    overall = "FAIL_NONALLOW_GEOMETRY" if fail_closed else "PASS_CANDIDATE"
    return {
        "nonallow_points": int(nonallow_points),
        "fail_closed_triggered": fail_closed,
        "overall": overall,
        "raw_historical_verdict": raw_historical_verdict,
    }
