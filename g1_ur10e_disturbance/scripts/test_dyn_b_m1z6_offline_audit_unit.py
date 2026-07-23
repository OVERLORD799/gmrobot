#!/usr/bin/env python3
"""Unit tests for V1-M1Z6 offline audit helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_m1z6_offline_audit import _non_allow_ranges  # noqa: E402


def _row(step: int, gate: str) -> dict[str, str]:
    return {"sim_step": str(step), "gate_effective": gate}


def test_non_allow_range_grouping() -> None:
    rows = [_row(i, "ALLOW") for i in range(0, 10)]
    rows += [_row(10, "SLOW_DOWN"), _row(11, "STOP"), _row(13, "SLOW_DOWN")]
    rows += [_row(i, "ALLOW") for i in range(14, 20)]
    got = _non_allow_ranges(rows, 0, 19)
    assert got == [
        {"start": 10, "end": 11, "length": 2, "continuity": "contiguous"},
        {"start": 13, "end": 13, "length": 1, "continuity": "contiguous"},
    ]


def test_non_allow_empty() -> None:
    rows = [_row(i, "ALLOW") for i in range(0, 8)]
    got = _non_allow_ranges(rows, 0, 7)
    assert got == []


def main() -> None:
    test_non_allow_range_grouping()
    test_non_allow_empty()
    print("PASS test_dyn_b_m1z6_offline_audit_unit")


if __name__ == "__main__":
    main()
