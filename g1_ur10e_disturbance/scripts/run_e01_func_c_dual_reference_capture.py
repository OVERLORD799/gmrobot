#!/usr/bin/env python3
"""Capture-only runner for Func-C Dual reference scene (no GM state machine)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from func_c_dual_reference_contract import (
    OPT_IN_ENV,
    REFERENCE_CAMERA_POS,
    REFERENCE_CAMERA_ROT,
    build_scene_contract,
    resolve_part_locations,
)
from func_c_dual_reference_runtime_assertions import write_runtime_assertions


def main() -> None:
    ap = argparse.ArgumentParser(description="Func-C Dual reference scene capture preflight.")
    ap.add_argument("--runtime-assertions-json", required=True)
    args = ap.parse_args()

    env = dict(os.environ)
    if env.get(OPT_IN_ENV, "0").strip() not in {"1", "true", "yes", "on"}:
        raise RuntimeError(f"{OPT_IN_ENV}=1 required for Func-C Dual reference capture.")

    # Enforce reference camera pose lock for frame330-aligned scene identity.
    env["GMDISTURB_SCENE_CAMERA_OVERRIDE"] = "1"
    env["GMDISTURB_SCENE_CAMERA_POS"] = ",".join(str(x) for x in REFERENCE_CAMERA_POS)
    env["GMDISTURB_SCENE_CAMERA_ROT"] = ",".join(str(x) for x in REFERENCE_CAMERA_ROT)

    contract = build_scene_contract(env)
    part_locations = resolve_part_locations(env)
    write_runtime_assertions(
        output_path=args.runtime_assertions_json,
        env=env,
        container_pose={
            "container_a": [0.75, -0.25, 0.0],
            "container_b": [0.75, 0.25, 0.0],
            "grid_a": [0.47695, -0.41637, 0.10],
            "grid_b": [0.47695, 0.08363, 0.10],
        },
        camera_pose={
            "pos": list(REFERENCE_CAMERA_POS),
            "rot": list(REFERENCE_CAMERA_ROT),
        },
        part_locations=part_locations,
    )
    print(
        f"[func-c-dual-reference] assertions_written={Path(args.runtime_assertions_json)} "
        f"task_execution={contract['task_execution']} visual_dataset_only={contract['visual_dataset_only']}"
    )


if __name__ == "__main__":
    main()
