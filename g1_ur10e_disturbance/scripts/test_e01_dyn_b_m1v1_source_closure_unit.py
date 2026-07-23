#!/usr/bin/env python3
"""Offline source-closure tests for V1-M1V1 clean-base runtime."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_source_closure import compute_local_import_closure  # noqa: E402


def test_run_phase3_local_closure_resolves_and_contains_scene_camera_override() -> None:
    report = compute_local_import_closure(
        entry_file=ROOT / "scripts" / "run_phase3.py",
        project_root=ROOT,
    )
    assert report["unresolved_local_imports"] == []
    members = set(report["closure_members"])
    assert "scene_camera_override.py" in members
    assert "g1_disturbance_controller.py" in members
    assert "scripts/run_phase3.py" in members


def main() -> None:
    test_run_phase3_local_closure_resolves_and_contains_scene_camera_override()
    print("PASS test_e01_dyn_b_m1v1_source_closure_unit")


if __name__ == "__main__":
    main()
