"""E01-Func-C target-container-full override (pure; no Isaac import).

Default Dual/GMRobot box_B remains ``container.usd``. Opt-in:

  GMROBOT_V1E01_TARGET_FULL=1

When enabled, only ``box_B`` switches to ``container_full.usd`` with a
Func-C-specific spawn scale (the full USD already embeds cm→m hierarchy
and ``metersPerUnit=1``; applying the empty-box ``0.01`` scale would shrink
it ~100×).

Does not enable D1B ``GMROBOT_V1D1B_FUNCTIONAL_BLOCK`` / part_5000@B@10.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

CONTAINER_USD_NAME = "container.usd"
CONTAINER_FULL_USD_NAME = "container_full.usd"
# Spawn payload: relative defaultPrim, no /World absolute paths, no physics.
# Semantic distinction source-of-truth remains container_full.usd.
CONTAINER_FULL_SPAWN_USD_NAME = "container_full_visual.usd"

# Empty box uses (0.01,)*3 in gmrobot_env_cfg. Full visual USD is already meters.
CONTAINER_FULL_SCALE: tuple[float, float, float] = (1.0, 1.0, 1.0)

SCENE_GROUP = "e01_func_c"
EXPECTED_RISK_TYPE = "functional"
LABEL_STATUS = "provisional"
REVIEWER_APPROVED = False
MOTION_SOURCE = "none_static_functional_scene"
E01_FUNC_C_SEED = 51
E01_FUNC_C_CAPTURE_STEPS: tuple[int, ...] = (100, 200)
E01_FUNC_C_GEOMETRY_WINDOW: tuple[int, int] = (100, 200)
CAMERA_POS: tuple[float, float, float] = (0.35, 0.0, 2.5)
CAMERA_ROT: tuple[float, float, float, float] = (0.7071, 0.0, 0.7071, 0.0)
MIN_TARGET_ROI_PX2: float = 2500.0


def _truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def target_full_enabled(env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return _truthy(e.get("GMROBOT_V1E01_TARGET_FULL"))


def d1b_blocker_enabled(env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return _truthy(e.get("GMROBOT_V1D1B_FUNCTIONAL_BLOCK"))


def resolve_box_usd_name(
    container_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return USD basename for box_A / box_B (spawn path)."""
    name = str(container_name)
    if name == "B" and target_full_enabled(env):
        return CONTAINER_FULL_SPAWN_USD_NAME
    return CONTAINER_USD_NAME


def resolve_box_source_usd_name(
    container_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Semantic source asset name (for manifests / precheck)."""
    name = str(container_name)
    if name == "B" and target_full_enabled(env):
        return CONTAINER_FULL_USD_NAME
    return CONTAINER_USD_NAME


def resolve_box_scale(
    container_name: str,
    *,
    default_scale: tuple[float, float, float],
    env: Mapping[str, str] | None = None,
) -> tuple[float, float, float]:
    if str(container_name) == "B" and target_full_enabled(env):
        return CONTAINER_FULL_SCALE
    return tuple(float(x) for x in default_scale)


def assets_dir_from_env_cfg_file(env_cfg_path: Path | str) -> Path:
    p = Path(env_cfg_path).resolve()
    # .../GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py
    # assets at .../GMRobot/assets
    return (p.parents[3] / "assets").resolve()
