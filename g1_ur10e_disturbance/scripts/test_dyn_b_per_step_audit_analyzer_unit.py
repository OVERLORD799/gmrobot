#!/usr/bin/env python3
"""Unit tests for Dyn-B per-step attribution analyzer."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_per_step_audit_analyzer import analyze_dyn_b_per_step_window  # noqa: E402


LEGACY_FIELDNAMES = [
    "sim_step",
    "policy_step",
    "phase",
    "gate_evaluated",
    "gate_effective",
    "trigger_rule",
    "stop_flag",
    "slow_flag",
    "replan_flag",
    "dist_min_g1_body_m",
    "margin_to_gate_m",
    "g1_fell_flag",
    "g1_root_x",
    "g1_root_y",
    "g1_root_z",
    "g1_tilt_rad",
    "motion_source_label",
    "camera_capture_marker",
    "body_pose_marker",
]


M1Z7_EXTRA = [
    "protocol_phase",
    "ur10e_stage",
    "trigger_reason",
    "dist_min_for_gating_m",
    "dist_min_proxy_m",
    "closest_g1_body",
    "safe_dist_warn_active_m",
    "safe_dist_hard_stop_active_m",
    "ttc_observed_s",
    "ttc_forecast_s",
    "approach_rate_mps",
    "relative_velocity_mps",
    "proxy_surface_velocity_mps",
    "proxy_surface_velocity_x_mps",
    "proxy_surface_velocity_y_mps",
    "proxy_surface_velocity_z_mps",
    "robot_ee_velocity_mps",
    "robot_ee_velocity_x_mps",
    "robot_ee_velocity_y_mps",
    "robot_ee_velocity_z_mps",
    "disturbance_active",
    "disturbance_source",
    "disturbance_attempt_id",
    "ttc_observed_availability",
    "ttc_observed_source",
    "ttc_forecast_availability",
    "ttc_forecast_source",
    "approach_rate_availability",
    "approach_rate_source",
    "relative_velocity_availability",
    "relative_velocity_source",
    "proxy_surface_velocity_availability",
    "proxy_surface_velocity_source",
    "robot_ee_velocity_availability",
    "robot_ee_velocity_source",
]

FIELDNAMES = LEGACY_FIELDNAMES + M1Z7_EXTRA


def _legacy_row(step: int, *, phase: str | None = None, gate: str = "ALLOW", margin: float = 0.12) -> dict[str, str]:
    if phase is None:
        phase = "lateral_positive_sweep" if step <= 329 else "lateral_negative_sweep"
    return {
        "sim_step": str(step),
        "policy_step": str(step),
        "phase": phase,
        "gate_evaluated": gate,
        "gate_effective": gate,
        "trigger_rule": "",
        "stop_flag": "0",
        "slow_flag": "0",
        "replan_flag": "0",
        "dist_min_g1_body_m": f"{margin + 0.10:.6f}",
        "margin_to_gate_m": f"{margin:.6f}",
        "g1_fell_flag": "0",
        "g1_root_x": "0.0",
        "g1_root_y": "0.0",
        "g1_root_z": "1.0",
        "g1_tilt_rad": "0.0",
        "motion_source_label": "scripted_g1_outer_lateral_patrol",
        "camera_capture_marker": "0",
        "body_pose_marker": "0",
    }


def _m1z7_row(step: int, *, gate: str = "ALLOW") -> dict[str, str]:
    row = {k: "" for k in FIELDNAMES}
    row.update(_legacy_row(step, gate=gate))
    row.update(
        {
            "protocol_phase": "transit",
            "ur10e_stage": "approach",
            "trigger_reason": "ttc",
            "dist_min_for_gating_m": "0.300000",
            "dist_min_proxy_m": "0.300000",
            "closest_g1_body": "head_link",
            "safe_dist_warn_active_m": "0.2800",
            "safe_dist_hard_stop_active_m": "0.2500",
            "ttc_observed_s": "0.450000",
            "ttc_forecast_s": "0.430000",
            "approach_rate_mps": "0.720000",
            "relative_velocity_mps": "null",
            "proxy_surface_velocity_mps": "0.100000",
            "proxy_surface_velocity_x_mps": "0.100000",
            "proxy_surface_velocity_y_mps": "0.000000",
            "proxy_surface_velocity_z_mps": "0.000000",
            "robot_ee_velocity_mps": "0.200000",
            "robot_ee_velocity_x_mps": "0.200000",
            "robot_ee_velocity_y_mps": "0.000000",
            "robot_ee_velocity_z_mps": "0.000000",
            "disturbance_active": "1",
            "disturbance_source": "scripted_virtual_hand",
            "disturbance_attempt_id": "2",
            "ttc_observed_availability": "present",
            "ttc_observed_source": "gate_result.metadata.ttc",
            "ttc_forecast_availability": "present",
            "ttc_forecast_source": "gate_result.metadata.ttc_forecast_s",
            "approach_rate_availability": "present",
            "approach_rate_source": "gate_result.metadata.approach_rate",
            "relative_velocity_availability": "missing",
            "relative_velocity_source": "not_exposed_in_runtime_gate_metadata",
            "proxy_surface_velocity_availability": "present",
            "proxy_surface_velocity_source": "adapter.human_hand_vel",
            "robot_ee_velocity_availability": "present",
            "robot_ee_velocity_source": "obs.safety.ee_vel",
        }
    )
    return row


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def test_complete_pass_fixture() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ok.csv"
        rows = [_m1z7_row(s) for s in range(190, 341)]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is True, rep["errors"]


def test_missing_rows_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "missing.csv"
        rows = [_m1z7_row(s) for s in range(190, 341) if s != 237]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert any("missing" in e for e in rep["errors"])


def test_duplicate_rows_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "dup.csv"
        rows = [_m1z7_row(s) for s in range(190, 341)] + [_m1z7_row(250)]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert 250 in rep["duplicate_steps"]


def test_legacy_old_schema_non_allow_is_insufficient() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "legacy.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LEGACY_FIELDNAMES)
            w.writeheader()
            w.writerow(_legacy_row(212, gate="SLOW_DOWN"))
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert rep["schema_version"] == "legacy_pre_m1z7"
        assert rep["non_allow_points"][0]["attribution_status"] == "INSUFFICIENT"


def test_ttc_non_allow_explained_with_runtime_fields() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ttc_explained.csv"
        rows = [_m1z7_row(s) for s in range(190, 341)]
        rows[10]["gate_effective"] = "SLOW_DOWN"
        rows[10]["trigger_rule"] = "ttc"
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        point = rep["non_allow_points"][0]
        assert point["attribution_status"] == "EXPLAINED"
        assert point["reason"] == "ttc_rule_with_runtime_ttc_and_approach_rate"


def test_ttc_non_allow_missing_fields_is_insufficient() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ttc_insufficient.csv"
        rows = [_m1z7_row(s) for s in range(190, 341)]
        rows[5]["gate_effective"] = "STOP"
        rows[5]["trigger_rule"] = "ttc"
        rows[5]["ttc_observed_s"] = "null"
        rows[5]["ttc_forecast_s"] = "null"
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        point = rep["non_allow_points"][0]
        assert point["attribution_status"] == "INSUFFICIENT"


def test_non_allow_contiguous_ranges() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ranges.csv"
        rows = [_m1z7_row(s) for s in range(190, 341)]
        for idx in (0, 1, 5):
            rows[idx]["gate_effective"] = "SLOW_DOWN"
            rows[idx]["trigger_rule"] = "static_warn"
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["non_allow_ranges"] == [
            {"start": 190, "end": 191, "length": 2, "continuity": "contiguous"},
            {"start": 195, "end": 195, "length": 1, "continuity": "contiguous"},
        ]


def main() -> None:
    test_complete_pass_fixture()
    test_missing_rows_fail()
    test_duplicate_rows_fail()
    test_legacy_old_schema_non_allow_is_insufficient()
    test_ttc_non_allow_explained_with_runtime_fields()
    test_ttc_non_allow_missing_fields_is_insufficient()
    test_non_allow_contiguous_ranges()
    print("PASS test_dyn_b_per_step_audit_analyzer_unit")


if __name__ == "__main__":
    main()
