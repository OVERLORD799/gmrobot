#!/usr/bin/env python3
"""Offline tests for V1-M1V clean-base Dyn-B runtime image policy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from e01_dyn_b_runtime_guard import (  # noqa: E402
    M1V_BASE_IMAGE,
    M1V_BAKE_FILES,
    M1V_DOCKERFILE,
    M1V_IMAGE_TAG,
    assert_no_host_code_bind_mount,
    canonical_dyn_b_smoke_shell,
    dockerfile_bake_mentions_outer_lateral,
    dockerfile_is_clean_m1v,
    host_bake_sources_include_outer_lateral,
    smoke_enables_network_models,
)
from numpy_abi_guard import verify_typing_extensions_paramspec  # noqa: E402


def test_dockerfile_from_clean_b4_and_no_package_mutation():
    df = ROOT / M1V_DOCKERFILE
    assert df.is_file(), df
    text = df.read_text(encoding="utf-8")
    flags = dockerfile_is_clean_m1v(text)
    assert flags["from_b4"] is True
    assert M1V_BASE_IMAGE in text
    assert all(flags.values()), flags
    assert dockerfile_bake_mentions_outer_lateral(text)
    assert "e01-dyn-b-clean-m1v" in M1V_IMAGE_TAG
    for rel in (
        "scripts/run_phase3.py",
        "g1_disturbance_controller.py",
        "scripts/numpy_abi_guard.py",
        "configs/e01_dyn_b_capture.yaml",
    ):
        assert f"COPY {rel}" in text, rel
    # Must not bake the M1U dedup/quarantine tooling into this clean image.
    assert "pip_prebundle_numpy_dedup.py" not in text
    assert "assert_numpy_dedup_report.py" not in text


def test_bake_sources_include_outer_lateral_and_paramspec_guard():
    flags = host_bake_sources_include_outer_lateral(ROOT, bake_files=M1V_BAKE_FILES)
    assert flags["scripts/run_phase3.py"] is True
    assert flags["g1_disturbance_controller.py"] is True
    assert flags["configs/e01_dyn_b_capture.yaml"] is True
    guard = (ROOT / "scripts" / "numpy_abi_guard.py").read_text(encoding="utf-8")
    assert "verify_typing_extensions_paramspec" in guard
    assert "ParamSpec" in guard
    rp = (ROOT / "scripts" / "run_phase3.py").read_text(encoding="utf-8")
    assert "--typing-extensions-pre-json" in rp
    assert "--typing-extensions-post-json" in rp


def test_canonical_smoke_no_code_mount_no_network_no_prebundle_injection():
    cmd = canonical_dyn_b_smoke_shell()
    assert "pip_prebundle" not in cmd
    assert "PYTHONPATH" not in cmd
    assert smoke_enables_network_models(cmd) is False
    assert "--scenario outer_lateral_patrol" in cmd
    assert "--max_steps 1" in cmd
    assert "--numpy-origin-pre-json" in cmd
    assert "--numpy-origin-post-json" in cmd
    assert "--typing-extensions-pre-json" in cmd
    assert "--typing-extensions-post-json" in cmd
    argv = [
        "docker",
        "run",
        "--rm",
        "-v",
        "/home/czz/GMrobot/g1_ur10e_disturbance/results:/opt/projects/g1_ur10e_disturbance/results",
        M1V_IMAGE_TAG,
        "bash",
        "-lc",
        cmd,
    ]
    assert_no_host_code_bind_mount(argv)


def test_typing_extensions_paramspec_guard_roundtrip(tmp_path: Path | None = None):
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "te.json"
        payload = verify_typing_extensions_paramspec(stage="unit", json_out=str(out))
        assert payload["ParamSpec_available"] is True
        assert payload["ok"] is True
        assert out.is_file()


def main() -> None:
    test_dockerfile_from_clean_b4_and_no_package_mutation()
    test_bake_sources_include_outer_lateral_and_paramspec_guard()
    test_canonical_smoke_no_code_mount_no_network_no_prebundle_injection()
    test_typing_extensions_paramspec_guard_roundtrip()
    print("PASS test_e01_dyn_b_m1v_clean_runtime_unit")


if __name__ == "__main__":
    main()
