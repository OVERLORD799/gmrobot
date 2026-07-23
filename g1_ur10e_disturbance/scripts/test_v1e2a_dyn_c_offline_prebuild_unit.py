#!/usr/bin/env python3
"""Unit tests for V1-E2A Dyn-C offline prebuild evaluator."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_c_offline_prebuild import (  # noqa: E402
    CAPTURE_STEPS,
    E01_DYN_C_MOTION_SOURCE,
    E01_DYN_C_SCENARIO,
    E01_DYN_C_SEED,
    GEOMETRY_WINDOW,
    MIN_CENTROID_DISPLACEMENT_PX,
    evaluate_dyn_c_prebuild,
)


def test_contract_constants() -> None:
    assert E01_DYN_C_SCENARIO == "mirrored_outer_lateral_patrol"
    assert E01_DYN_C_MOTION_SOURCE == "scripted_g1_mirrored_outer_lateral_patrol"
    assert E01_DYN_C_SEED == 44
    assert CAPTURE_STEPS == (240, 310)
    assert GEOMETRY_WINDOW == (220, 330)


def test_prebuild_projection_gates_and_trajectory_distinct() -> None:
    report = evaluate_dyn_c_prebuild()
    assert report["trajectory_identity"]["is_distinct_from_dyn_b"] is True
    assert report["gates"]["workcell_double_bins_visible"] is True
    assert report["cross_capture_centroid_displacement_px"] >= MIN_CENTROID_DISPLACEMENT_PX
    assert report["gates"]["per_frame_gate_ok"] is True
    assert report["verdict"] == "PREBUILD_READY"


if __name__ == "__main__":
    test_contract_constants()
    test_prebuild_projection_gates_and_trajectory_distinct()
    print(json.dumps({"ok": True}))
