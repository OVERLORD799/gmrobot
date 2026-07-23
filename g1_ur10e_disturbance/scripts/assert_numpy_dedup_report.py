#!/usr/bin/env python3
"""Validate NumPy pip_prebundle quarantine report using structural rules."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DIST_INFO_RE = re.compile(r"^numpy-(?P<version>[^/]+)\.dist-info$")


def _assert_names(names: list[str]) -> str:
    assert "numpy" in names, names
    assert "numpy.libs" in names, names
    dist_infos = [n for n in names if DIST_INFO_RE.match(n)]
    assert len(dist_infos) == 1, names
    return dist_infos[0]


def _assert_kit_roots(report: dict, kit_site_root: Path) -> None:
    kit = report["kit_numpy"]
    root = str(kit_site_root.resolve()) + "/"
    assert str(kit["numpy_file"]).startswith(root), kit
    assert str(kit["numpy_random_file"]).startswith(root), kit
    assert str(kit["numpy_random_generator_file"]).startswith(root), kit
    assert str(kit["numpy_random_mt19937_file"]).startswith(root), kit


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-json", type=Path, required=True)
    ap.add_argument("--kit-site-root", type=Path, required=True)
    ap.add_argument("--require-sentinel", type=Path, default=None)
    args = ap.parse_args()

    report = json.loads(args.report_json.read_text(encoding="utf-8"))
    moved = list(report.get("moved", []))
    names = sorted(Path(str(x["source"])).name for x in moved)
    dist_info_name = _assert_names(names)
    assert not report.get("remaining_importable_numpy_prebundle"), report
    assert int(report.get("moved_count", -1)) == len(moved), report
    assert all(len(str(x.get("digest", ""))) == 64 for x in moved), moved
    _assert_kit_roots(report, args.kit_site_root)
    if args.require_sentinel is not None:
        assert args.require_sentinel.is_file(), str(args.require_sentinel)

    # Surface the dynamic dist-info target used by this assertion.
    print(dist_info_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
