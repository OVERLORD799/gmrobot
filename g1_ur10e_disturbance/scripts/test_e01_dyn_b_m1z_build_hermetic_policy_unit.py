#!/usr/bin/env python3
"""Reject build-time dependency on runtime paper_demo artifacts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE_M1Z = ROOT / "docker" / "Dockerfile.e01-dyn-b-clean-m1z"
BUILD_SCRIPTS: tuple[Path, ...] = (
    ROOT / "docker" / "build.sh",
)
FORBIDDEN = ("results/paper_demo", "body_poses.jsonl")


def _assert_no_forbidden(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    for needle in FORBIDDEN:
        assert needle.lower() not in low, f"forbidden build-time artifact dependency in {path}: {needle}"


def test_m1z_dockerfile_has_no_runtime_artifact_dependency() -> None:
    _assert_no_forbidden(DOCKERFILE_M1Z)


def test_build_scripts_have_no_runtime_artifact_dependency() -> None:
    for script in BUILD_SCRIPTS:
        _assert_no_forbidden(script)


def main() -> None:
    test_m1z_dockerfile_has_no_runtime_artifact_dependency()
    test_build_scripts_have_no_runtime_artifact_dependency()
    print("PASS test_e01_dyn_b_m1z_build_hermetic_policy_unit")


if __name__ == "__main__":
    main()
