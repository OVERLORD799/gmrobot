#!/usr/bin/env python3
"""Offline unit tests for V1-M1F12.1 dual-reference camera enable flag fix."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from func_c_dual_reference_smoke_guard import (  # noqa: E402
    assert_required_switches,
    assert_single_camera_flag,
    assert_single_launcher_and_entrypoint,
    build_dual_reference_smoke_inner_command,
    preflight_camera_flag_or_fail,
)


def test_canonical_command_has_single_enable_cameras() -> None:
    inner = build_dual_reference_smoke_inner_command(
        camera_output_dir="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f12_20260723/scene",
        runtime_assertions_json="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f12_20260723/meta/runtime_scene_assertions.json",
    )
    assert inner.count("--enable_cameras") == 1
    assert_single_camera_flag(inner)
    assert_single_launcher_and_entrypoint(inner)
    assert_required_switches(inner)


def test_missing_camera_flag_must_fail_preflight() -> None:
    broken = (
        "set -euo pipefail; /isaac-sim/python.sh "
        "/opt/projects/GMRobot/scripts/gm_state_machine_agent.py "
        "--task gm --headless --save_camera --camera_output_dir /tmp/x --max_steps 1"
    )
    try:
        preflight_camera_flag_or_fail(broken)
    except SystemExit as exc:
        assert "camera_flag_missing" in str(exc)
    else:
        raise AssertionError("expected preflight camera flag failure")


def test_duplicate_python_launcher_or_entrypoint_rejected() -> None:
    bad_launcher = (
        "set -euo pipefail; /isaac-sim/python.sh /isaac-sim/python.sh "
        "/opt/projects/GMRobot/scripts/gm_state_machine_agent.py "
        "--task gm --headless --enable_cameras --save_camera --camera_output_dir /tmp/x --max_steps 1"
    )
    bad_entrypoint = (
        "set -euo pipefail; /isaac-sim/python.sh "
        "/opt/projects/GMRobot/scripts/gm_state_machine_agent.py "
        "/opt/projects/GMRobot/scripts/gm_state_machine_agent.py "
        "--task gm --headless --enable_cameras --save_camera --camera_output_dir /tmp/x --max_steps 1"
    )
    for command in (bad_launcher, bad_entrypoint):
        try:
            assert_single_launcher_and_entrypoint(command)
        except AssertionError:
            pass
        else:
            raise AssertionError("expected duplicate launcher/entrypoint rejection")


def main() -> None:
    test_canonical_command_has_single_enable_cameras()
    test_missing_camera_flag_must_fail_preflight()
    test_duplicate_python_launcher_or_entrypoint_rejected()
    print("PASS test_v1m1f121_dual_camera_flag_unit")


if __name__ == "__main__":
    main()
