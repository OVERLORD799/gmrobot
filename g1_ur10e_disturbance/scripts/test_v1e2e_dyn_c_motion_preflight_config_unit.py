#!/usr/bin/env python3
"""Static config checks for V1-E2E Dyn-C short motion-preflight profile."""

from __future__ import annotations

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_motion_preflight_config_contract() -> None:
    cfg = ROOT / "configs" / "e01_dyn_c_motion_preflight.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["scenario"] == "mirrored_outer_lateral_patrol"
    assert data["seed"] == 44
    assert data["task_execution"] is False
    assert data["freeze_ur10e"] is True
    assert data["max_steps"] == 260
    assert data["gates"]["min_projected_displacement_px"] >= 40
    assert data["gates"]["min_roi_area_fraction"] >= 0.012


if __name__ == "__main__":
    test_motion_preflight_config_contract()
    print("PASS test_v1e2e_dyn_c_motion_preflight_config_unit")
