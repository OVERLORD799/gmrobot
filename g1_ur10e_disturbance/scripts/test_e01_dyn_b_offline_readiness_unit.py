#!/usr/bin/env python3
"""Offline unit tests for E01-Dyn-B readiness (no Isaac / no Docker / no POST)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_offline_readiness import (  # noqa: E402
    E01_DYN_B_CAPTURE_STEPS,
    E01_DYN_B_MOTION_SOURCE,
    E01_DYN_B_SCENARIO,
    E01_DYN_B_SEED,
    OUTER_LATERAL_PATROL_PHASES,
    capture_steps_inside_moving_phase,
    conservative_separation_margin_m,
    default_off_flags_ok,
    full_readiness_report,
    geometry_precheck,
    no_red_proxy_ok,
    phase_at_step,
    predicted_capture_displacement_px,
    select_capture_steps,
    trajectory_xy,
    visibility_assumption_ok,
)


def test_phase_schedule_and_label():
    assert E01_DYN_B_SCENARIO == "outer_lateral_patrol"
    assert E01_DYN_B_MOTION_SOURCE == "scripted_g1_outer_lateral_patrol"
    assert phase_at_step(220).name == "lateral_positive_sweep"
    assert phase_at_step(330).name == "lateral_negative_sweep"
    assert OUTER_LATERAL_PATROL_PHASES[-1].name == "idle"


def test_seed_determinism_and_trajectory():
    assert E01_DYN_B_SEED == 43
    a = trajectory_xy(300)
    b = trajectory_xy(300)
    assert a == b


def test_displacement_prediction_gate():
    disp = predicted_capture_displacement_px()
    assert disp is not None
    assert disp >= 20.0


def test_no_red_proxy():
    assert no_red_proxy_ok(virtual_hand=False, mention_red_ball=False) is True
    assert no_red_proxy_ok(virtual_hand=True, mention_red_ball=False) is False
    assert no_red_proxy_ok(virtual_hand=False, mention_red_ball=True) is False


def test_camera_visibility_assumption():
    roots = [trajectory_xy(s) for s in E01_DYN_B_CAPTURE_STEPS]
    assert all(visibility_assumption_ok(r) for r in roots)


def test_geometry_separation_and_fail_closed():
    g = geometry_precheck()
    assert g["ok"] is True
    assert g["min_separation_margin_m"] >= g["required_margin_m"]
    # If we move near the envelope center, margin must become unsafe.
    unsafe_margin = conservative_separation_margin_m((0.75, 0.0))
    assert unsafe_margin < 0.0


def test_default_off_and_capture_selection():
    assert default_off_flags_ok(enable_capture=False, execute_capture=False) is True
    assert default_off_flags_ok(enable_capture=True, execute_capture=False) is False
    sel = select_capture_steps()
    assert sel["steps"] == list(E01_DYN_B_CAPTURE_STEPS)
    assert sel["inside_moving_phase"] is True
    assert sel["meets_displacement_gate"] is True
    assert capture_steps_inside_moving_phase(E01_DYN_B_CAPTURE_STEPS) is True


def test_full_readiness_report_go_nogo():
    go = full_readiness_report(enable_capture=False, execute_capture=False)
    assert go["verdict"] == "GO_PRECHECK_ONLY"
    assert go["default_off"]["ok"] is True
    nogo = full_readiness_report(enable_capture=True, execute_capture=False)
    assert nogo["verdict"] == "NO_GO"


def main() -> None:
    test_phase_schedule_and_label()
    test_seed_determinism_and_trajectory()
    test_displacement_prediction_gate()
    test_no_red_proxy()
    test_camera_visibility_assumption()
    test_geometry_separation_and_fail_closed()
    test_default_off_and_capture_selection()
    test_full_readiness_report_go_nogo()
    print("PASS test_e01_dyn_b_offline_readiness_unit")


if __name__ == "__main__":
    main()
