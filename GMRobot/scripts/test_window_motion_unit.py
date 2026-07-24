#!/usr/bin/env python3
"""Unit tests for V1-D7B window-aggregate motion assessment."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

from GMRobot.vlm.window_motion import (  # noqa: E402
    WindowMotionConfig,
    assess_window_motion,
)


def _shift(box: list[float], dx: float, dy: float = 0.0) -> list[float]:
    return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]


def test_rigid_translation_above_threshold_is_dynamic() -> None:
    b0 = [100.0, 100.0, 200.0, 300.0]
    # 60 px over 60 steps @60fps = 60 px/s
    seq = [(s, _shift(b0, s)) for s in range(0, 61, 5)]
    r = assess_window_motion(seq)
    assert r["valid"] is True
    assert abs(r["translation_rate_px_s"] - 60.0) < 1e-6
    assert r["scale_rate_px_s"] == 0.0
    assert r["dynamic_by_translation"] is True


def test_idle_sway_below_threshold_is_static() -> None:
    b0 = [100.0, 100.0, 200.0, 300.0]
    # net 10 px over 45 steps = 13.3 px/s (D7A b3 regime)
    seq = [(420 + i * 5, _shift(b0, -(10.0 * i / 9.0))) for i in range(10)]
    r = assess_window_motion(seq)
    assert r["valid"] is True
    assert r["translation_rate_px_s"] < 25.0
    assert r["dynamic_by_translation"] is False


def test_symmetric_growth_is_scale_not_translation() -> None:
    # box grows 30 px per side over 60 steps: pure scale, zero translation
    seq = [(s, [100.0 - s / 2.0, 100.0, 200.0 + s / 2.0, 300.0]) for s in range(0, 61, 5)]
    r = assess_window_motion(seq)
    assert r["translation_rate_px_s"] < 1e-6
    assert r["scale_rate_px_s"] > 25.0
    assert r["dynamic_by_translation"] is False  # depth/leak ambiguity: fail closed


def test_one_sided_trailing_growth_splits_translation_and_scale() -> None:
    # left edge moves -80, right edge fixed (trailing leak while target moves left)
    seq = [(s, [300.0 - 80.0 * s / 60.0, 100.0, 440.0, 300.0]) for s in range(0, 61, 5)]
    r = assess_window_motion(seq)
    assert abs(r["translation_rate_px_s"] - 40.0) < 1e-6
    assert abs(r["scale_rate_px_s"] - 40.0) < 1e-6
    assert r["x_edge_asymmetry"] > 0.9
    assert r["dynamic_by_translation"] is True


def test_insufficient_boxes_fail_closed() -> None:
    r = assess_window_motion([(0, [0, 0, 10, 10]), (5, None), (10, None)])
    assert r["valid"] is False
    assert r["dynamic_by_translation"] is False
    assert r["reason"].startswith("insufficient_boxes")


def test_depth_suspect_requires_translation_floor() -> None:
    # Mask breathing on a static close-range subject: width shrinks 28 px over
    # 45 steps (scale+aspect above depth thresholds) but translation ~ 0.
    seq = [(430 + i * 5, [158.0 + i * 1.4, 0.0, 361.0 - i * 1.7, 479.0]) for i in range(10)]
    r = assess_window_motion(seq)
    assert r["scale_rate_px_s"] >= 18.0
    assert r["aspect_change"] >= 0.05
    assert r["translation_rate_px_s"] < 8.0
    assert r["depth_motion_suspect"] is False  # v2.2 floor rejects it
    assert r["both_y_edges_clipped"] is True


def test_depth_suspect_true_depth_motion_passes_floor() -> None:
    # b2-like retreat: symmetric growth + top edge rising + modest translation
    seq = [(325 + i * 5, [214.0 - i * 2.0, 128.0 - i * 2.5, 344.0 + i * 1.0, 479.0])
           for i in range(16)]
    r = assess_window_motion(seq)
    assert r["depth_motion_suspect"] is True


def test_custom_threshold() -> None:
    b0 = [100.0, 100.0, 200.0, 300.0]
    seq = [(s, _shift(b0, s * 0.3)) for s in range(0, 61, 5)]  # 18 px/s
    assert assess_window_motion(seq)["dynamic_by_translation"] is False
    cfg = WindowMotionConfig(translation_dynamic_threshold_px_s=15.0)
    assert assess_window_motion(seq, config=cfg)["dynamic_by_translation"] is True


def main() -> None:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    main()
