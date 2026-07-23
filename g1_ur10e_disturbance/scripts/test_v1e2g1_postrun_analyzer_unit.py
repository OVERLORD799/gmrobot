#!/usr/bin/env python3
"""Unit tests for V1-E2G.1 postrun analyzer."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v1e2g1_postrun_analyzer import analyze_postrun  # noqa: E402


def test_postrun_analyzer_projects_visibility_and_roi() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "run"
        meta = d / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "frame_inventory.json").write_text(
            json.dumps(
                {
                    "frames": [
                        {"step": 10, "path": "scene/frame_000010_env0.png"},
                        {"step": 20, "path": "scene/frame_000020_env0.png"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (meta / "camera_pose.json").write_text(
            json.dumps({"pos": [0.45, 0.0, 2.7], "rot": [0.7071, 0.0, 0.7071, 0.0]}),
            encoding="utf-8",
        )
        rows = [
            {
                "step": 10,
                "g1_bodies": {
                    "torso_link": [0.0, 0.0, 0.3],
                    "head_link": [0.0, 0.0, 0.5],
                },
            },
            {
                "step": 20,
                "g1_bodies": {
                    "torso_link": [0.1, 0.0, 0.3],
                    "head_link": [0.1, 0.0, 0.5],
                },
            },
        ]
        (meta / "body_poses.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        rep = analyze_postrun(d)
        assert rep["frame_count"] == 2
        assert rep["frames"][0]["visible_link_count"] >= 1
        assert rep["frames"][0]["roi_area_fraction"] > 0.0
        assert rep["frames"][1]["projected_actual_displacement_px"] >= 0.0


if __name__ == "__main__":
    test_postrun_analyzer_projects_visibility_and_roi()
    print("PASS test_v1e2g1_postrun_analyzer_unit")
