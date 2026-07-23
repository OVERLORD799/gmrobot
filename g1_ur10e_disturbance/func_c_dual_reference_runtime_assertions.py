"""Runtime assertions for Func-C Dual reference capture scene."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from func_c_dual_reference_contract import (
    CONTAINER_A,
    CONTAINER_B,
    SLOT_COUNT,
    build_scene_contract,
)


def _slot_set(prefix: str) -> set[str]:
    return {f"{prefix}@{i}" for i in range(1, SLOT_COUNT + 1)}


def evaluate_runtime_assertions(
    *,
    env: Mapping[str, str],
    container_pose: Mapping[str, Any],
    camera_pose: Mapping[str, Any],
    part_locations: list[str],
) -> dict[str, Any]:
    contract = build_scene_contract(env)
    expected_target = _slot_set(f"{CONTAINER_B}")
    expected_default = _slot_set(f"{CONTAINER_A}")
    observed = set(part_locations)
    checks = {
        "task_execution_false": contract["task_execution"] is False,
        "visual_dataset_only_true": contract["visual_dataset_only"] is True,
        "container_identity_present": bool(container_pose.get("container_a")) and bool(container_pose.get("container_b")),
        "grid_identity_present": bool(container_pose.get("grid_a")) and bool(container_pose.get("grid_b")),
        "camera_pose_reference_locked": tuple(camera_pose.get("pos", [])) == tuple(contract["reference"]["camera_pos"])
        and tuple(camera_pose.get("rot", [])) == tuple(contract["reference"]["camera_rot"]),
        "part_count_20": len(part_locations) == SLOT_COUNT,
        "part_slots_unique": len(observed) == SLOT_COUNT,
        "part_slots_on_target_box": observed == expected_target,
        "other_box_empty": observed.isdisjoint(expected_default),
    }
    out = {
        "contract": contract,
        "observed": {
            "container_pose": container_pose,
            "camera_pose": camera_pose,
            "part_locations": part_locations,
        },
        "checks": checks,
        "ok": all(checks.values()),
    }
    return out


def write_runtime_assertions(
    *,
    output_path: str | Path,
    env: Mapping[str, str],
    container_pose: Mapping[str, Any],
    camera_pose: Mapping[str, Any],
    part_locations: list[str],
) -> dict[str, Any]:
    out = evaluate_runtime_assertions(
        env=env,
        container_pose=container_pose,
        camera_pose=camera_pose,
        part_locations=part_locations,
    )
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not out["ok"]:
        raise RuntimeError(f"Func-C Dual runtime assertions failed: {json.dumps(out, ensure_ascii=False)}")
    return out
