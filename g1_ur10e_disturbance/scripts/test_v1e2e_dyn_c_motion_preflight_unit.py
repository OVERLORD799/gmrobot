#!/usr/bin/env python3
"""Unit tests for V1-E2E Dyn-C motion-isolation preflight command wiring."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    build_e2a_dyn_c_prebuild_inner_command,
    build_e2e_dyn_c_motion_preflight_inner_command,
    build_e2e_dyn_c_motion_preflight_outer_argv,
    build_m1v1_dyn_b_preflight_inner_command,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_e2e_preflight_inner_contains_freeze_and_short_budget() -> None:
    inner = build_e2e_dyn_c_motion_preflight_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e2e_dyn_c_motion_preflight_20260723"
    )
    assert "--scenario mirrored_outer_lateral_patrol" in inner
    assert "--freeze-ur10e" in inner
    assert "--max_steps 260" in inner


def test_e2e_preflight_outer_argv_shape_is_canonical() -> None:
    argv = build_e2e_dyn_c_motion_preflight_outer_argv(
        run_sh_path="/repo/g1_ur10e_disturbance/docker/run.sh",
        image_tag="gmdisturb:e01-dyn-c-motion-preflight-20260723",
        host_results_dir="/repo/g1_ur10e_disturbance/results",
    )
    assert argv[:5] == [
        "/repo/g1_ur10e_disturbance/docker/run.sh",
        "--tag",
        "gmdisturb:e01-dyn-c-motion-preflight-20260723",
        "--results",
        "/repo/g1_ur10e_disturbance/results",
    ]
    assert argv[5] == "bash"
    assert argv[6] == "-lc"
    assert "--freeze-ur10e" in argv[7]


def test_default_off_hashes_unchanged_for_b0b4_contracts() -> None:
    # Guardrail: introducing freeze must not mutate default B0-B4 command payloads.
    b0 = build_m1v1_dyn_b_preflight_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1v1_dyn_b_clean_runtime_20260723"
    )
    b4 = build_e2a_dyn_c_prebuild_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e2a_dyn_c_formal_capture_20260723"
    )
    assert "--freeze-ur10e" not in b0
    assert "--freeze-ur10e" not in b4
    assert _sha(b0) == "d0ec77ab52f6aa82480a712caf9e84bfa51f556887a1dafce6ceeebed2e24b0b"
    assert _sha(b4) == "191847f08ad6ce40bd417d8f2db43e505d28a03724969ebdfdc6022bb30b3d38"


if __name__ == "__main__":
    test_e2e_preflight_inner_contains_freeze_and_short_budget()
    test_e2e_preflight_outer_argv_shape_is_canonical()
    test_default_off_hashes_unchanged_for_b0b4_contracts()
    print("PASS test_v1e2e_dyn_c_motion_preflight_unit")
