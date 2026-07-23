#!/usr/bin/env python3
"""Offline policy checks for V1-M1Z2 copy-only Dockerfile + canonical smoke argv."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    M1Z2_BASE_IMAGE,
    M1Z2_DOCKERFILE,
    M1Z2_IMAGE_TAG,
    assert_canonical_run_sh_payload,
    assert_no_host_code_bind_mount,
    build_m1z2_smoke_outer_argv,
    dockerfile_is_copy_only_m1z2,
    smoke_enables_network_models,
)


def test_m1z2_dockerfile_is_copy_only() -> None:
    text = (ROOT / M1Z2_DOCKERFILE).read_text(encoding="utf-8")
    flags = dockerfile_is_copy_only_m1z2(text)
    assert all(flags.values()), flags
    assert M1Z2_BASE_IMAGE in text
    assert "e01-dyn-b-clean-m1z2" in M1Z2_IMAGE_TAG


def test_m1z2_smoke_outer_is_canonical_run_sh_bash_lc() -> None:
    run_sh = str(ROOT / "docker" / "run.sh")
    argv = build_m1z2_smoke_outer_argv(
        run_sh_path=run_sh,
        host_results_dir=str(ROOT / "results"),
    )
    assert argv[0] == run_sh
    assert argv[1:5] == ["--tag", M1Z2_IMAGE_TAG, "--results", str(ROOT / "results")]
    assert argv[5:7] == ["bash", "-lc"]
    assert_canonical_run_sh_payload(argv[5:])
    assert argv[7].startswith("set -euo pipefail;")
    assert "/isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py" in argv[7]
    assert "--scenario outer_lateral_patrol" in argv[7]
    assert "--max_steps 1" in argv[7]
    assert "--save_camera" not in argv[7]
    assert smoke_enables_network_models(argv[7]) is False
    # Simulated docker argv must not mount host project source.
    docker_like = [
        "docker",
        "run",
        "-v",
        f"{ROOT / 'results'}:/opt/projects/g1_ur10e_disturbance/results",
        M1Z2_IMAGE_TAG,
        "bash",
        "-lc",
        argv[7],
    ]
    assert_no_host_code_bind_mount(docker_like)


def main() -> None:
    test_m1z2_dockerfile_is_copy_only()
    test_m1z2_smoke_outer_is_canonical_run_sh_bash_lc()
    print("PASS test_e01_dyn_b_m1z2_dockerfile_policy_unit")


if __name__ == "__main__":
    main()
