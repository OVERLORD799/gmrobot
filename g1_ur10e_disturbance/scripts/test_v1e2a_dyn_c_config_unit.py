#!/usr/bin/env python3
"""Static config checks for Dyn-C default-off capture profile."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_dyn_c_config_default_off() -> None:
    cfg = Path(__file__).resolve().parents[1] / "configs" / "e01_dyn_c_capture.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["scenario"] == "mirrored_outer_lateral_patrol"
    assert data["motion_source"] == "scripted_g1_mirrored_outer_lateral_patrol"
    assert data["seed"] == 44
    assert data["enable_capture"] is False
    assert data["execute_capture"] is False
    assert data["task_execution"] is False
    assert data["visual_dataset_only"] is True
    assert data["camera"]["pos"] == [0.45, 0.0, 2.7]
    assert data["camera"]["rot"] == [0.7071, 0.0, 0.7071, 0.0]


if __name__ == "__main__":
    test_dyn_c_config_default_off()
    print("PASS test_v1e2a_dyn_c_config_unit")
