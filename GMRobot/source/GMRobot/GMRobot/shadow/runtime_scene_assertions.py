"""Runtime scene assertions for V1E01 visual-only smoke."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shadow.target_full_override import resolve_v1e01_mode_flags


def _stage_prim_paths(stage: Any) -> list[str]:
    paths: list[str] = []
    if stage is None:
        return paths
    if isinstance(stage, Iterable) and not hasattr(stage, "Traverse"):
        for item in stage:
            paths.append(str(item))
        return paths
    if hasattr(stage, "Traverse"):
        for prim in stage.Traverse():
            get_path = getattr(prim, "GetPath", None)
            if callable(get_path):
                paths.append(str(get_path()))
            else:
                paths.append(str(prim))
    return paths


def evaluate_runtime_scene_assertions(
    *,
    env: Mapping[str, str],
    container_assets: Mapping[str, Any],
    part_assets: Mapping[str, Any],
    stage_prim_paths: Iterable[str],
) -> dict[str, Any]:
    flags = resolve_v1e01_mode_flags(env)
    part_count_cfg = len([k for k in part_assets.keys() if str(k).startswith("part_")])
    prim_paths = [str(p) for p in stage_prim_paths]
    part_count_stage = sum(1 for p in prim_paths if "/Part_" in p or p.endswith("Part_"))
    result = {
        "mode_flags": {
            "task_execution": bool(flags.get("task_execution", True)),
            "visual_dataset_only": bool(flags.get("visual_dataset_only", False)),
            "spawn_task_parts": bool(flags.get("spawn_task_parts", True)),
        },
        "container_presence": {
            "box_A": "box_A" in container_assets,
            "grid_A": "grid_A" in container_assets,
            "box_B": "box_B" in container_assets,
        },
        "asset_identity": {
            "box_A_usd": str(container_assets.get("box_A", {}).get("usd_path", "")),
            "box_B_usd": str(container_assets.get("box_B", {}).get("usd_path", "")),
        },
        "part_count_cfg": int(part_count_cfg),
        "part_count_stage": int(part_count_stage),
        "stage_prim_total": len(prim_paths),
    }
    checks = {
        "task_execution_false": result["mode_flags"]["task_execution"] is False,
        "visual_dataset_only_true": result["mode_flags"]["visual_dataset_only"] is True,
        "spawn_task_parts_false": result["mode_flags"]["spawn_task_parts"] is False,
        "part_count_cfg_zero": result["part_count_cfg"] == 0,
        "containers_exist": all(result["container_presence"].values()),
        "box_a_identity_container": result["asset_identity"]["box_A_usd"].endswith("container.usd"),
        "box_b_identity_full_visual": result["asset_identity"]["box_B_usd"].endswith("container_full_visual.usd"),
    }
    result["checks"] = checks
    result["ok"] = all(checks.values())
    return result


def run_runtime_scene_assertions(
    *,
    output_path: str | Path,
    env: Mapping[str, str],
    container_assets: Mapping[str, Any],
    part_assets: Mapping[str, Any],
    stage: Any | None = None,
) -> dict[str, Any]:
    if stage is None:
        import omni.usd  # type: ignore

        stage = omni.usd.get_context().get_stage()
    evaluated = evaluate_runtime_scene_assertions(
        env=env,
        container_assets=container_assets,
        part_assets=part_assets,
        stage_prim_paths=_stage_prim_paths(stage),
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evaluated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not evaluated.get("ok", False):
        raise RuntimeError(f"runtime scene assertions failed: {json.dumps(evaluated, ensure_ascii=False)}")
    return evaluated
