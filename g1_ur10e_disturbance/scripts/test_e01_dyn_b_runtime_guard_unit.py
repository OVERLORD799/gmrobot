#!/usr/bin/env python3
"""Offline tests for E01-Dyn-B runtime guard command construction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    canonical_dyn_b_smoke_shell,
    import_preflight_command,
    run_phase3_command,
)


def test_no_mixed_numpy_path_injection_in_runtime_guard():
    cmd = canonical_dyn_b_smoke_shell()
    assert "pip_prebundle" not in cmd
    assert "omni.kit.pip_archive" not in cmd
    assert "PYTHONPATH" not in cmd


def test_preflight_command_points_to_script():
    cmd = import_preflight_command()
    assert cmd.startswith("/isaac-sim/python.sh ")
    assert "isaac_abi_import_preflight.py" in cmd


def test_run_phase3_command_has_dyn_b_contract():
    cmd = run_phase3_command(output_csv="/tmp/out.csv")
    assert "run_phase3.py" in cmd
    assert "--scenario outer_lateral_patrol" in cmd
    assert "--seed 43" in cmd
    assert "--max_steps 1" in cmd
    assert "--output_csv /tmp/out.csv" in cmd


def test_canonical_shell_contains_numpy_origin_and_app_launcher_smoke():
    cmd = canonical_dyn_b_smoke_shell(
        output_csv="/tmp/phase3.csv",
        numpy_origin_json="/tmp/numpy.json",
    )
    assert "/isaac-sim/python.sh -c " in cmd
    assert "numpy_random_file" in cmd
    assert "--scenario outer_lateral_patrol" in cmd
    assert "--max_steps 1" in cmd
    assert "--output_csv /tmp/phase3.csv" in cmd
    assert "/tmp/numpy.json" in cmd


def main() -> None:
    test_no_mixed_numpy_path_injection_in_runtime_guard()
    test_preflight_command_points_to_script()
    test_run_phase3_command_has_dyn_b_contract()
    test_canonical_shell_contains_numpy_origin_and_app_launcher_smoke()
    print("PASS test_e01_dyn_b_runtime_guard_unit")


if __name__ == "__main__":
    main()
