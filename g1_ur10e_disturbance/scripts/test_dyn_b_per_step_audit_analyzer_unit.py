#!/usr/bin/env python3
"""Unit tests for Dyn-B per-step audit analyzer."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_per_step_audit_analyzer import analyze_dyn_b_per_step_window  # noqa: E402


FIELDNAMES = [
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


def _row(step: int, *, phase: str | None = None, gate: str = "ALLOW", margin: float = 0.12) -> dict[str, str]:
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


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def test_complete_pass_fixture() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ok.csv"
        rows = [_row(s) for s in range(190, 341)]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is True, rep["errors"]


def test_missing_rows_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "missing.csv"
        rows = [_row(s) for s in range(190, 341) if s != 237]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert any("missing" in e for e in rep["errors"])


def test_duplicate_rows_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "dup.csv"
        rows = [_row(s) for s in range(190, 341)] + [_row(250)]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert 250 in rep["duplicate_steps"]


def test_sparse_three_row_historical_shape_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sparse.csv"
        rows = [_row(200), _row(250), _row(300)]
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert rep["observed_count"] == 3
        assert len(rep["missing_steps"]) == 148


def test_non_allow_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "nonallow.csv"
        rows = [_row(s) for s in range(190, 341)]
        rows[10]["gate_effective"] = "STOP"
        rows[10]["stop_flag"] = "1"
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert rep["non_allow_steps"]


def test_low_margin_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lowmargin.csv"
        rows = [_row(s) for s in range(190, 341)]
        rows[0]["margin_to_gate_m"] = "0.050000"
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert rep["low_margin_steps"] == [190]


def test_wrong_phase_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "phase.csv"
        rows = [_row(s) for s in range(190, 341)]
        rows[220 - 190]["phase"] = "wrong_phase"
        _write_csv(p, rows)
        rep = analyze_dyn_b_per_step_window(p)
        assert rep["pass"] is False
        assert any("220 phase" in e for e in rep["errors"])


def main() -> None:
    test_complete_pass_fixture()
    test_missing_rows_fail()
    test_duplicate_rows_fail()
    test_sparse_three_row_historical_shape_fail()
    test_non_allow_fail()
    test_low_margin_fail()
    test_wrong_phase_fail()
    print("PASS test_dyn_b_per_step_audit_analyzer_unit")


if __name__ == "__main__":
    main()
