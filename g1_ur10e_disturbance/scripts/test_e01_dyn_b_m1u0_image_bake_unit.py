#!/usr/bin/env python3
"""Offline tests for V1-M1U0 Dyn-B image bake + canonical smoke constraints."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    M1U1_BAKE_FILES,
    M1U1_DOCKERFILE,
    M1U1_IMAGE_TAG,
    assert_no_host_code_bind_mount,
    canonical_dyn_b_smoke_shell,
    dockerfile_bake_mentions_outer_lateral,
    host_bake_sources_include_outer_lateral,
    smoke_enables_network_models,
)


def test_dockerfile_exists_and_copies_dyn_b_sources():
    df = ROOT / M1U1_DOCKERFILE
    assert df.is_file(), df
    text = df.read_text(encoding="utf-8")
    assert "FROM gmdisturb:e01-func-c-m1j-20260723" in text
    assert "e01-dyn-b-m1u1" in M1U1_IMAGE_TAG
    assert dockerfile_bake_mentions_outer_lateral(text)
    for rel in (
        "scripts/run_phase3.py",
        "g1_disturbance_controller.py",
        "e01_dyn_b_runtime_guard.py",
        "configs/e01_dyn_b_capture.yaml",
    ):
        assert f"COPY {rel}" in text, rel


def test_build_context_sources_contain_outer_lateral_patrol():
    flags = host_bake_sources_include_outer_lateral(ROOT)
    assert flags["scripts/run_phase3.py"] is True
    assert flags["g1_disturbance_controller.py"] is True
    assert flags["configs/e01_dyn_b_capture.yaml"] is True
    assert flags["e01_dyn_b_runtime_guard.py"] is True
    # offline readiness labels motion source
    assert flags["e01_dyn_b_offline_readiness.py"] is True
    assert all(rel in flags for rel in M1U1_BAKE_FILES)


def test_canonical_smoke_no_pip_prebundle_and_no_network_models():
    cmd = canonical_dyn_b_smoke_shell(
        output_csv="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/safety_logs/phase3.csv",
        numpy_origin_pre_json="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/numpy_origin_pre.json",
        numpy_origin_post_json="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/numpy_origin_post.json",
    )
    assert "pip_prebundle" not in cmd
    assert "PYTHONPATH" not in cmd
    assert "omni.kit.pip_archive" not in cmd
    assert "--numpy-origin-pre-json" in cmd
    assert "--numpy-origin-post-json" in cmd
    assert smoke_enables_network_models(cmd) is False
    assert "--scenario outer_lateral_patrol" in cmd
    assert "--max_steps 1" in cmd


def test_canonical_host_docker_argv_does_not_mount_code():
    # Mirrors docker/run.sh volume policy: results + caches only.
    argv = [
        "docker",
        "run",
        "--gpus",
        "all",
        "--rm",
        "-v",
        "/home/czz/GMrobot/g1_ur10e_disturbance/results:/opt/projects/g1_ur10e_disturbance/results",
        "-v",
        "/home/czz/.cache/gmdisturb-docker/kit:/isaac-sim/kit/cache",
        M1U1_IMAGE_TAG,
        "bash",
        "-lc",
        canonical_dyn_b_smoke_shell(),
    ]
    assert_no_host_code_bind_mount(argv)
    # Explicitly reject full project bind-mount
    bad = list(argv)
    bad[6:8] = [
        "-v",
        "/home/czz/GMrobot/g1_ur10e_disturbance:/opt/projects/g1_ur10e_disturbance",
    ]
    try:
        assert_no_host_code_bind_mount(bad)
        raise AssertionError("expected host code mount to be rejected")
    except AssertionError as exc:
        assert "forbidden" in str(exc)


def main() -> None:
    test_dockerfile_exists_and_copies_dyn_b_sources()
    test_build_context_sources_contain_outer_lateral_patrol()
    test_canonical_smoke_no_pip_prebundle_and_no_network_models()
    test_canonical_host_docker_argv_does_not_mount_code()
    print("PASS test_e01_dyn_b_m1u0_image_bake_unit")


if __name__ == "__main__":
    main()
