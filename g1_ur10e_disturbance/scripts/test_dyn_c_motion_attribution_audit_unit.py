#!/usr/bin/env python3
"""Unit tests for Dyn-C offline motion attribution audit."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_c_motion_attribution_audit import _best_global_shift, _changed_fraction, _equal_area_square  # noqa: E402


def test_best_global_shift_recovers_translation() -> None:
    base = np.zeros((40, 60), dtype=np.float32)
    base[10:20, 15:25] = 200.0
    moved = np.zeros_like(base)
    # base 向右2、向下1 平移到 moved
    moved[11:21, 17:27] = 200.0
    mask = np.zeros_like(base, dtype=bool)
    dx, dy = _best_global_shift(base, moved, mask, max_shift=4)
    # 函数返回的是 gray_b 相对 gray_a 的最优回对齐位移
    assert (dx, dy) == (-2, -1)


def test_changed_fraction_thresholding() -> None:
    diff = np.zeros((20, 20), dtype=np.float32)
    diff[5:10, 5:10] = 25.0
    frac = _changed_fraction(diff, (0, 0, 20, 20), threshold=20.0)
    assert math.isclose(frac, 25.0 / 400.0, rel_tol=1e-9)


def test_equal_area_square_is_bounded() -> None:
    x0, y0, x1, y1 = _equal_area_square(2.0, 2.0, area=100.0, w=16, h=16)
    assert 0 <= x0 < x1 <= 16
    assert 0 <= y0 < y1 <= 16


if __name__ == "__main__":
    test_best_global_shift_recovers_translation()
    test_changed_fraction_thresholding()
    test_equal_area_square_is_bounded()
    print("ok")
