"""Func-C reference-scene contract for DualEnvCfg capture-only mode.

Pure Python module: no Isaac imports.
"""

from __future__ import annotations

from typing import Mapping

OPT_IN_ENV = "GMDISTURB_V1E01_FUNC_C_VISUAL"
REFERENCE_SCENE_GROUP = "e01_dyn_b_formal_m1z9_20260723"
REFERENCE_FRAME = "frame_000330_env0.png"

REFERENCE_CAMERA_POS = (0.45, 0.0, 2.7)
REFERENCE_CAMERA_ROT = (0.7071, 0.0, 0.7071, 0.0)

CONTAINER_A = "A"
CONTAINER_B = "B"
SLOT_COUNT = 20

# The visual reference content is treated as 20 deterministic part slots.
# If this provenance is changed to non-parts in future audit, route must block.
REFERENCE_CONTENT_SOURCE = "part_assets_20_slots"


def _truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def visual_opt_in_enabled(env: Mapping[str, str] | None = None) -> bool:
    if env is None:
        import os

        env = os.environ
    return _truthy(env.get(OPT_IN_ENV))


def default_part_locations() -> list[str]:
    return [f"{CONTAINER_A}@{i}" for i in range(1, SLOT_COUNT + 1)]


def opt_in_part_locations() -> list[str]:
    return [f"{CONTAINER_B}@{i}" for i in range(1, SLOT_COUNT + 1)]


def resolve_part_locations(env: Mapping[str, str] | None = None) -> list[str]:
    return opt_in_part_locations() if visual_opt_in_enabled(env) else default_part_locations()


def build_scene_contract(env: Mapping[str, str] | None = None) -> dict[str, object]:
    enabled = visual_opt_in_enabled(env)
    part_locations = resolve_part_locations(env)
    return {
        "opt_in_env": OPT_IN_ENV,
        "opt_in_enabled": bool(enabled),
        "task_execution": False if enabled else True,
        "visual_dataset_only": True if enabled else False,
        "reference": {
            "scene_group": REFERENCE_SCENE_GROUP,
            "frame": REFERENCE_FRAME,
            "camera_pos": list(REFERENCE_CAMERA_POS),
            "camera_rot": list(REFERENCE_CAMERA_ROT),
            "content_source": REFERENCE_CONTENT_SOURCE,
        },
        "part_locations": part_locations,
        "part_locations_unique": len(set(part_locations)) == SLOT_COUNT,
        "part_count": SLOT_COUNT,
        "target_slots_container": CONTAINER_B if enabled else CONTAINER_A,
        "other_box_empty": True,
    }
