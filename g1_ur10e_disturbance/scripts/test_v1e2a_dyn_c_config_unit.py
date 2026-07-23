#!/usr/bin/env python3
"""Static config checks for Dyn-C default-off capture profile."""

from __future__ import annotations

from pathlib import Path

import yaml
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config_loader import load_config  # noqa: E402
from e01_dyn_b_runtime_guard import build_e2a_dyn_c_prebuild_inner_command  # noqa: E402


def test_dyn_c_config_default_off() -> None:
    cfg = ROOT / "configs" / "e01_dyn_c_capture.yaml"
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
    assert data["capture_steps"] == [240, 310]
    assert data["adjacent_groups"]["A"] == [239, 240, 241]
    assert data["adjacent_groups"]["B"] == [309, 310, 311]


def test_dyn_c_config_load_config_full_parse() -> None:
    cfg = ROOT / "configs" / "e01_dyn_c_capture.yaml"
    loaded = load_config(str(cfg))
    # Ensure schema-clean Dyn-C config is fully parsable by config_loader.
    assert loaded.virtual_hand.reach_radius == 0.45
    assert loaded.virtual_hand.transit_proxy_radius == 0.40
    assert loaded.vlm.interval == 200
    assert loaded.vlm.host == "localhost"


def test_dyn_c_disable_vhand_vlm_is_cli_boundary() -> None:
    inner = build_e2a_dyn_c_prebuild_inner_command(
        result_root_in_container="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e2c1_dyn_c_schema_fix_20260723"
    )
    assert "--virtual-hand" not in inner
    assert "--vlm" not in inner
    assert "--per-part-protocol" not in inner


if __name__ == "__main__":
    test_dyn_c_config_default_off()
    test_dyn_c_config_load_config_full_parse()
    test_dyn_c_disable_vhand_vlm_is_cli_boundary()
    print("PASS test_v1e2a_dyn_c_config_unit")
