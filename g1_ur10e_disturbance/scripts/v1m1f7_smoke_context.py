"""Offline/host-side context checks for V1-M1F7 smoke outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_runtime_scene_assertions_or_raise(result_dir: str | Path) -> dict[str, Any]:
    path = Path(result_dir) / "meta" / "runtime_scene_assertions.json"
    if not path.is_file():
        raise SystemExit("STOP_NO_RETRY: runtime_scene_assertions.json missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not bool(data.get("ok", False)):
        raise SystemExit("STOP_NO_RETRY: runtime scene assertions failed")
    required_checks = (
        "task_execution_false",
        "visual_dataset_only_true",
        "spawn_task_parts_false",
        "part_count_cfg_zero",
        "containers_exist",
        "box_a_identity_container",
        "box_b_identity_full_visual",
    )
    checks = data.get("checks", {})
    for key in required_checks:
        if not bool(checks.get(key, False)):
            raise SystemExit(f"STOP_NO_RETRY: runtime check failed: {key}")
    return data
