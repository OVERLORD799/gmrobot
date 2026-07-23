#!/usr/bin/env python3
"""Offline unit tests for V1-M1F11 Dual reference Func-C scene pivot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from func_c_dual_reference_contract import (
    OPT_IN_ENV,
    REFERENCE_CAMERA_POS,
    REFERENCE_CAMERA_ROT,
    build_scene_contract,
    default_part_locations,
    resolve_part_locations,
)
from func_c_dual_reference_runtime_assertions import evaluate_runtime_assertions

WS = ROOT.parent

def test_default_part_locations_unchanged() -> None:
    default = default_part_locations()
    assert len(default) == 20
    assert len(set(default)) == 20
    assert default[0] == "A@1"
    assert default[-1] == "A@20"
    assert resolve_part_locations({}) == default


def test_opt_in_maps_to_target_slots_and_other_box_empty() -> None:
    env = {OPT_IN_ENV: "1"}
    locs = resolve_part_locations(env)
    assert len(locs) == 20
    assert len(set(locs)) == 20
    assert locs[0] == "B@1"
    assert locs[-1] == "B@20"
    assert all(not x.startswith("A@") for x in locs)


def test_scene_identity_and_runtime_assertions_contract() -> None:
    env = {OPT_IN_ENV: "1"}
    c = build_scene_contract(env)
    assert c["task_execution"] is False
    assert c["visual_dataset_only"] is True
    assert tuple(c["reference"]["camera_pos"]) == REFERENCE_CAMERA_POS
    assert tuple(c["reference"]["camera_rot"]) == REFERENCE_CAMERA_ROT

    out = evaluate_runtime_assertions(
        env=env,
        container_pose={
            "container_a": [0.75, -0.25, 0.0],
            "container_b": [0.75, 0.25, 0.0],
            "grid_a": [0.47695, -0.41637, 0.10],
            "grid_b": [0.47695, 0.08363, 0.10],
        },
        camera_pose={"pos": list(REFERENCE_CAMERA_POS), "rot": list(REFERENCE_CAMERA_ROT)},
        part_locations=resolve_part_locations(env),
    )
    assert out["ok"] is True, json.dumps(out, ensure_ascii=False)


def test_no_legacy_content_or_full_assets_in_dual_reference_runner() -> None:
    runner = (ROOT / "scripts" / "run_e01_func_c_dual_reference_capture.py").read_text(encoding="utf-8")
    assert "container_full_visual.usd" not in runner
    assert "container_full_content_visual.usd" not in runner
    assert "gm_state_machine_agent.py" not in runner


def test_b0_b4_yaml_unchanged_by_git_diff() -> None:
    # Guardrail: V1-M1F11 must not alter frozen B0-B4 paper scenario YAMLs.
    import subprocess

    rels = [
        "paper_scenarios/baseline_safe.yaml",
        "paper_scenarios/static_occupancy_proxy.yaml",
        "paper_scenarios/static_occupancy_proxy_1part.yaml",
        "paper_scenarios/static_occupancy_proxy_8part.yaml",
        "paper_scenarios/static_occupancy_proxy_mini.yaml",
    ]
    cmd = ["git", "diff", "--name-only", "--", *rels]
    out = subprocess.check_output(cmd, cwd=WS, text=True).strip()
    assert out == "", f"B0-B4 YAML changed:\n{out}"


def main() -> None:
    test_default_part_locations_unchanged()
    test_opt_in_maps_to_target_slots_and_other_box_empty()
    test_scene_identity_and_runtime_assertions_contract()
    test_no_legacy_content_or_full_assets_in_dual_reference_runner()
    test_b0_b4_yaml_unchanged_by_git_diff()
    print("PASS test_v1m1f11_func_c_dual_reference_scene_unit")


if __name__ == "__main__":
    main()
