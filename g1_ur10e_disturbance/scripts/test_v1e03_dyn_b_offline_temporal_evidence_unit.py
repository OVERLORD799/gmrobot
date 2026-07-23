#!/usr/bin/env python3
"""Unit tests for V1-E0.3 offline temporal evidence evaluator."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v1e03_dyn_b_offline_temporal_evidence import (  # noqa: E402
    MIN_CENTROID_DISPLACEMENT_PX,
    MIN_ROI_INNER_CHANGE_RATIO_220_330,
    _change_ratio,
    derive_motion_attribution_from_metrics,
)


def test_roi_attribution_prefers_inner_change() -> None:
    a = np.zeros((10, 10), dtype=np.uint8)
    b = np.zeros((10, 10), dtype=np.uint8)
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:8, 2:8] = True
    b[3:7, 3:7] = 255
    inner = _change_ratio(a, b, mask)
    outer = _change_ratio(a, b, ~mask)
    assert inner > 0.0
    assert outer == 0.0


def test_full_image_change_counterexample_blocked() -> None:
    verdict, gates = derive_motion_attribution_from_metrics(
        frame_gate_ok=True,
        centroid_displacement_px=MIN_CENTROID_DISPLACEMENT_PX + 1.0,
        roi_inner_change_ratio=0.01,
        roi_outer_change_ratio=0.05,
        stability_ok=True,
        full_image_change_ratio=0.2,
    )
    assert verdict == "INSUFFICIENT"
    assert gates["not_hash_only_guard"] is False


def test_threshold_boundary_passes_on_exact_values() -> None:
    verdict, gates = derive_motion_attribution_from_metrics(
        frame_gate_ok=True,
        centroid_displacement_px=MIN_CENTROID_DISPLACEMENT_PX,
        roi_inner_change_ratio=MIN_ROI_INNER_CHANGE_RATIO_220_330,
        roi_outer_change_ratio=MIN_ROI_INNER_CHANGE_RATIO_220_330 / 1.2,
        stability_ok=True,
        full_image_change_ratio=0.05,
    )
    assert verdict == "SCRIPTED_G1_MOTION_SUPPORTED"
    assert all(gates.values())


if __name__ == "__main__":
    test_roi_attribution_prefers_inner_change()
    test_full_image_change_counterexample_blocked()
    test_threshold_boundary_passes_on_exact_values()
    print(json.dumps({"ok": True}))
