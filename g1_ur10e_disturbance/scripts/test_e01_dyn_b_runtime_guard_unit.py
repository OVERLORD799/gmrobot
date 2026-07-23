#!/usr/bin/env python3
"""Offline tests for E01-Dyn-B runtime guard command construction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    import_preflight_command,
    pythonpath_guard_prologue,
    run_phase3_command,
)


def test_pythonpath_guard_uses_pip_archive_prebundle():
    s = pythonpath_guard_prologue()
    assert "omni.usd.libs" in s
    assert "LD_LIBRARY_PATH" in s
    assert "omni.kit.pip_archive" in s
    assert "pip_prebundle" in s
    assert "PYTHONPATH" in s


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


def main() -> None:
    test_pythonpath_guard_uses_pip_archive_prebundle()
    test_preflight_command_points_to_script()
    test_run_phase3_command_has_dyn_b_contract()
    print("PASS test_e01_dyn_b_runtime_guard_unit")


if __name__ == "__main__":
    main()
