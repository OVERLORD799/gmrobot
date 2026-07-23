#!/usr/bin/env python3
"""Offline tests for runtime scene assertions hook."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.runtime_scene_assertions import evaluate_runtime_scene_assertions, run_runtime_scene_assertions  # noqa: E402


def test_fake_stage_pass() -> None:
    env = {"GMROBOT_V1E01_TARGET_FULL": "1", "GMROBOT_V1E01_VISUAL_ONLY": "1"}
    container_assets = {
        "box_A": {"usd_path": "/tmp/container.usd"},
        "grid_A": {"usd_path": "/tmp/grid.usd"},
        "box_B": {"usd_path": "/tmp/container.usd"},
        "grid_B": {"usd_path": "/tmp/grid.usd"},
        "filled_content_B": {"usd_path": "/tmp/container_full_content_visual.usd"},
    }
    part_assets = {}
    prims = [
        "/World/envs/env_0/ContainerA",
        "/World/envs/env_0/GridA",
        "/World/envs/env_0/ContainerB",
        "/World/envs/env_0/GridB",
    ] + [f"/World/envs/env_0/ContainerBFilledContent/FilledContents/FilledContent_{i:02d}" for i in range(20)]
    out = evaluate_runtime_scene_assertions(
        env=env,
        container_assets=container_assets,
        part_assets=part_assets,
        stage_prim_paths=prims,
    )
    assert out["ok"] is True, out


def test_fake_stage_fail_with_parts() -> None:
    env = {"GMROBOT_V1E01_TARGET_FULL": "1", "GMROBOT_V1E01_VISUAL_ONLY": "1"}
    container_assets = {
        "box_A": {"usd_path": "/tmp/container.usd"},
        "grid_A": {"usd_path": "/tmp/grid.usd"},
        "box_B": {"usd_path": "/tmp/container.usd"},
        "grid_B": {"usd_path": "/tmp/grid.usd"},
        "filled_content_B": {"usd_path": "/tmp/container_full_content_visual.usd"},
    }
    part_assets = {"part_1": {"dummy": 1}}
    prims = ["/World/envs/env_0/Part_1"] + [
        f"/World/envs/env_0/ContainerBFilledContent/FilledContents/FilledContent_{i:02d}" for i in range(20)
    ]
    out = evaluate_runtime_scene_assertions(
        env=env,
        container_assets=container_assets,
        part_assets=part_assets,
        stage_prim_paths=prims,
    )
    assert out["ok"] is False, out
    assert out["checks"]["part_count_cfg_zero"] is False


def test_file_written_and_machine_readable() -> None:
    env = {"GMROBOT_V1E01_TARGET_FULL": "1", "GMROBOT_V1E01_VISUAL_ONLY": "1"}
    container_assets = {
        "box_A": {"usd_path": "/tmp/container.usd"},
        "grid_A": {"usd_path": "/tmp/grid.usd"},
        "box_B": {"usd_path": "/tmp/container.usd"},
        "grid_B": {"usd_path": "/tmp/grid.usd"},
        "filled_content_B": {"usd_path": "/tmp/container_full_content_visual.usd"},
    }
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "runtime_scene_assertions.json"
        out = run_runtime_scene_assertions(
            output_path=out_path,
            env=env,
            container_assets=container_assets,
            part_assets={},
            stage=["/World/envs/env_0/ContainerA"]
            + [f"/World/envs/env_0/FilledContents/FilledContent_{i:02d}" for i in range(20)],
        )
        assert out_path.is_file()
        disk = json.loads(out_path.read_text(encoding="utf-8"))
        assert disk["ok"] is True
        assert disk == out


def main() -> None:
    test_fake_stage_pass()
    test_fake_stage_fail_with_parts()
    test_file_written_and_machine_readable()
    print("PASS test_runtime_scene_assertions_unit")


if __name__ == "__main__":
    main()
