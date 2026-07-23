#!/usr/bin/env python3
"""Offline unit test for content-only visual USD generator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts" / "generate_container_full_content_visual_usd.py"


def main() -> None:
    assert GEN.is_file(), GEN
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "container_full_content_visual.usd"
        report = Path(td) / "report.json"
        cmd = [
            sys.executable,
            str(GEN),
            "--freeze-hash",
            "--output",
            str(out),
            "--json",
            str(report),
        ]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"generator failed rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["ok"] is True, data
        assert data["mesh_count"] == 20, data
        assert data["filled_count"] == 20, data
        assert data["part_numeric_count"] == 0, data
        assert data["container_name_hits"] == 0, data
        assert data["rigid_count"] == 0 and data["collision_count"] == 0 and data["mass_count"] == 0, data
        assert data["slot_positions_match"] is True, data
    print("PASS test_generate_container_full_content_visual_usd_unit")


if __name__ == "__main__":
    main()
