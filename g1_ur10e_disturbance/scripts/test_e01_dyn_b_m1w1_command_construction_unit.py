#!/usr/bin/env python3
"""Offline regression test for Dyn-B M1W1 command construction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    assert_canonical_run_sh_payload,
    build_m1y_dyn_b_preflight_inner_command,
    build_m1y_dyn_b_preflight_outer_argv,
    build_m1z_dyn_b_preflight_inner_command,
    build_m1z_dyn_b_preflight_outer_argv,
    build_m1v1_dyn_b_preflight_inner_command,
    build_m1v1_dyn_b_preflight_outer_argv,
)


def test_inner_command_has_exact_prefix_and_entrypoint() -> None:
    inner = build_m1v1_dyn_b_preflight_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w1_20260723"
    )
    assert inner.startswith("set -euo pipefail; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py ")
    assert "--dyn-b-per-step-audit-csv /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w1_20260723/safety_logs/phase3_dyn_b_per_step_audit.csv" in inner


def test_outer_command_uses_exact_m1v1_shape() -> None:
    argv = build_m1v1_dyn_b_preflight_outer_argv(
        run_sh_path="/repo/g1_ur10e_disturbance/docker/run.sh",
        image_tag="gmdisturb:e01-dyn-b-clean-m1v1-20260723",
        host_results_dir="/repo/g1_ur10e_disturbance/results",
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w1_20260723",
    )
    assert argv[:5] == [
        "/repo/g1_ur10e_disturbance/docker/run.sh",
        "--tag",
        "gmdisturb:e01-dyn-b-clean-m1v1-20260723",
        "--results",
        "/repo/g1_ur10e_disturbance/results",
    ]
    assert argv[5] == "bash"
    assert argv[6] == "-lc"
    assert argv[7].startswith("set -euo pipefail; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py ")


def test_reject_direct_python_payload() -> None:
    try:
        assert_canonical_run_sh_payload(
            [
                "/isaac-sim/python.sh",
                "/opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py",
            ]
        )
    except AssertionError as exc:
        assert "forbidden payload" in str(exc)
    else:
        raise AssertionError("expected direct python payload rejection")


def test_m1y_inner_command_wires_camera_override_and_new_audit_path() -> None:
    inner = build_m1y_dyn_b_preflight_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1y_20260723",
        camera_pos=(0.55, 0.0, 3.2),
        camera_rot=(0.7071, 0.0, 0.7071, 0.0),
    )
    assert "export GMDISTURB_SCENE_CAMERA_OVERRIDE=1" in inner
    assert "export GMDISTURB_SCENE_CAMERA_POS=0.55,0.0,3.2" in inner
    assert "export GMDISTURB_SCENE_CAMERA_ROT=0.7071,0.0,0.7071,0.0" in inner
    assert "--dyn-b-per-step-audit-csv /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1y_20260723/safety_logs/phase3_dyn_b_per_step_audit_m1y.csv" in inner


def test_m1y_outer_command_shape_stays_canonical() -> None:
    argv = build_m1y_dyn_b_preflight_outer_argv(
        run_sh_path="/repo/g1_ur10e_disturbance/docker/run.sh",
        image_tag="gmdisturb:e01-dyn-b-clean-m1v1-20260723",
        host_results_dir="/repo/g1_ur10e_disturbance/results",
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1y_20260723",
        camera_pos=(0.55, 0.0, 3.2),
        camera_rot=(0.7071, 0.0, 0.7071, 0.0),
    )
    assert argv[:5] == [
        "/repo/g1_ur10e_disturbance/docker/run.sh",
        "--tag",
        "gmdisturb:e01-dyn-b-clean-m1v1-20260723",
        "--results",
        "/repo/g1_ur10e_disturbance/results",
    ]
    assert argv[5] == "bash"
    assert argv[6] == "-lc"
    assert "GMDISTURB_SCENE_CAMERA_OVERRIDE=1" in argv[7]


def test_m1z_inner_command_uses_m1y_pose_and_dedicated_audit_csv() -> None:
    inner = build_m1z_dyn_b_preflight_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z_20260723",
        camera_pos=(0.45, 0.0, 2.7),
        camera_rot=(0.7071, 0.0, 0.7071, 0.0),
    )
    assert "export GMDISTURB_SCENE_CAMERA_OVERRIDE=1" in inner
    assert "export GMDISTURB_SCENE_CAMERA_POS=0.45,0.0,2.7" in inner
    assert "export GMDISTURB_SCENE_CAMERA_ROT=0.7071,0.0,0.7071,0.0" in inner
    assert "--camera_save_steps 219,220,221,329,330,331" in inner
    assert "--dyn-b-per-step-audit-csv /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z_20260723/safety_logs/phase3_dyn_b_per_step_audit_m1z.csv" in inner


def test_m1z_outer_command_shape_stays_canonical() -> None:
    argv = build_m1z_dyn_b_preflight_outer_argv(
        run_sh_path="/repo/g1_ur10e_disturbance/docker/run.sh",
        image_tag="gmdisturb:e01-dyn-b-clean-m1z-20260723",
        host_results_dir="/repo/g1_ur10e_disturbance/results",
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z_20260723",
    )
    assert argv[:5] == [
        "/repo/g1_ur10e_disturbance/docker/run.sh",
        "--tag",
        "gmdisturb:e01-dyn-b-clean-m1z-20260723",
        "--results",
        "/repo/g1_ur10e_disturbance/results",
    ]
    assert argv[5] == "bash"
    assert argv[6] == "-lc"
    assert "outer_lateral_patrol" in argv[7]


def main() -> None:
    test_inner_command_has_exact_prefix_and_entrypoint()
    test_outer_command_uses_exact_m1v1_shape()
    test_reject_direct_python_payload()
    test_m1y_inner_command_wires_camera_override_and_new_audit_path()
    test_m1y_outer_command_shape_stays_canonical()
    test_m1z_inner_command_uses_m1y_pose_and_dedicated_audit_csv()
    test_m1z_outer_command_shape_stays_canonical()
    print("PASS test_e01_dyn_b_m1w1_command_construction_unit")


if __name__ == "__main__":
    main()
