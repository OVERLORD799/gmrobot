#!/usr/bin/env python3
"""Offline tests for pip_prebundle NumPy-only quarantine scope."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pip_prebundle_numpy_dedup import discover_all_targets, quarantine_targets  # noqa: E402


def test_only_numpy_family_is_targeted_and_quarantined():
    with tempfile.TemporaryDirectory() as td:
        exts = Path(td) / "extscache"
        pip_root = exts / "omni.kit.pip_archive-abc.lx64.cp311" / "pip_prebundle"
        pip_root.mkdir(parents=True, exist_ok=True)

        (pip_root / "numpy").mkdir()
        (pip_root / "numpy.libs").mkdir()
        (pip_root / "numpy-1.26.0.dist-info").mkdir()
        # Non-NumPy packages must remain untouched.
        (pip_root / "pydantic").mkdir()
        (pip_root / "pillow.libs").mkdir()
        (pip_root / "typing_extensions-4.0.0.dist-info").mkdir()

        targets = discover_all_targets(exts)
        rels = sorted(t.rel for t in targets)
        assert rels == ["numpy", "numpy-1.26.0.dist-info", "numpy.libs"], rels

        qroot = exts / "quarantine"
        moved = quarantine_targets(targets, qroot)
        assert len(moved) == 3
        assert not (pip_root / "numpy").exists()
        assert not (pip_root / "numpy.libs").exists()
        assert not (pip_root / "numpy-1.26.0.dist-info").exists()

        assert (pip_root / "pydantic").is_dir()
        assert (pip_root / "pillow.libs").is_dir()
        assert (pip_root / "typing_extensions-4.0.0.dist-info").is_dir()


def main() -> None:
    test_only_numpy_family_is_targeted_and_quarantined()
    print("PASS test_pip_prebundle_numpy_dedup_unit")


if __name__ == "__main__":
    main()
