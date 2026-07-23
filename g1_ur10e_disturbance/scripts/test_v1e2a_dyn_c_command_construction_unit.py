#!/usr/bin/env python3
"""Unit tests for V1-E2A Dyn-C command construction."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    build_e2a_dyn_c_prebuild_inner_command,
    build_e2a_dyn_c_prebuild_outer_argv,
)


def test_inner_command_has_dyn_c_contract() -> None:
    inner = build_e2a_dyn_c_prebuild_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e2a_dyn_c_formal_capture_20260723"
    )
    assert "--seed 44 --scenario mirrored_outer_lateral_patrol" in inner
    assert "--motion_source_label scripted_g1_mirrored_outer_lateral_patrol" in inner
    assert "--camera_save_steps 239,240,241,309,310,311" in inner
    assert "GMDISTURB_SCENE_CAMERA_POS=0.45,0.0,2.7" in inner


def test_outer_argv_shape_is_canonical() -> None:
    argv = build_e2a_dyn_c_prebuild_outer_argv(
        run_sh_path="/repo/g1_ur10e_disturbance/docker/run.sh",
        image_tag="gmdisturb:e01-dyn-c-prebuild-20260723",
        host_results_dir="/repo/g1_ur10e_disturbance/results",
    )
    assert argv[:5] == [
        "/repo/g1_ur10e_disturbance/docker/run.sh",
        "--tag",
        "gmdisturb:e01-dyn-c-prebuild-20260723",
        "--results",
        "/repo/g1_ur10e_disturbance/results",
    ]
    assert argv[5] == "bash"
    assert argv[6] == "-lc"
    assert "mirrored_outer_lateral_patrol" in argv[7]


if __name__ == "__main__":
    test_inner_command_has_dyn_c_contract()
    test_outer_argv_shape_is_canonical()
    print("PASS test_v1e2a_dyn_c_command_construction_unit")
