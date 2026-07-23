#!/usr/bin/env python3
"""Offline policy checks for V1-M1Z clean image Dockerfile."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_runtime_guard import M1Z_DOCKERFILE  # noqa: E402


def test_m1z_dockerfile_policy() -> None:
    dockerfile = ROOT / M1Z_DOCKERFILE
    text = dockerfile.read_text(encoding="utf-8")
    low = text.lower()
    assert "FROM gmdisturb:b4-p010-20260721" in text
    assert "COPY . /opt/projects/g1_ur10e_disturbance" in text
    assert "pip install" not in low
    assert "apt-get" not in low
    assert "conda " not in low
    assert "test_e01_dyn_b_m1y_camera_framing_unit.py" in text
    assert "test_e01_dyn_b_m1w1_command_construction_unit.py" in text
    assert "dyn_b_source_closure.py" in text


def main() -> None:
    test_m1z_dockerfile_policy()
    print("PASS test_e01_dyn_b_m1z_image_policy_unit")


if __name__ == "__main__":
    main()
