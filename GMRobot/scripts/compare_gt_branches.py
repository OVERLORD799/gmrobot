#!/usr/bin/env python3
"""Offline GT audit branch comparison on safety CSV logs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

from _safety_import import bootstrap_safety, load_safety_module

bootstrap_safety()
_config = load_safety_module("config")
_gt = load_safety_module("gt_branches")
_types = load_safety_module("types")

load_safety_config = _config.load_safety_config
recompute_gt_from_row = _gt.recompute_gt_from_row
GateDecision = _types.GateDecision


def _parse_vec(raw: str | list) -> list[float]:
    if isinstance(raw, str) and raw.startswith("["):
        return json.loads(raw)
    return list(raw)


def _gt_from_row(row: dict, config) -> int:
    for col in ("g_ground_truth", "gt_collision"):
        val = row.get(col, "")
        if val not in (None, ""):
            return int(val)
    g_gt, _ = recompute_gt_from_row(row, config)
    return g_gt


def analyze_csv(csv_path: Path, config_path: Path | None) -> dict:
    config = load_safety_config(config_path)
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return {"path": str(csv_path), "steps": 0}

    ee_gt_mismatch = 0
    arm_branch_mismatch = 0
    arm_rows = 0
    contact_unknown = 0
    contact_rows = 0
    gt_stop = 0
    gt_allow = 0

    for row in rows:
        g_gt = _gt_from_row(row, config)
        if g_gt == int(GateDecision.STOP):
            gt_stop += 1
        else:
            gt_allow += 1

        ee_pos = _parse_vec(row["ee_pos"])
        hand_pos = _parse_vec(row["human_hand_pos"])
        recomputed, _ = recompute_gt_from_row(row, config)
        if recomputed != g_gt:
            ee_gt_mismatch += 1

        if row.get("g_gt_arm", "") not in ("", None):
            arm_rows += 1
            if int(row["g_gt_arm"]) != g_gt:
                arm_branch_mismatch += 1

        if row.get("gt_contact", "") not in ("", None):
            contact_rows += 1
            if row.get("gt_contact") == "unknown":
                contact_unknown += 1

    n = len(rows)
    return {
        "path": str(csv_path),
        "steps": n,
        "gt_stop_steps": gt_stop,
        "gt_allow_steps": gt_allow,
        "ee_gt_recompute_mismatch_rate": ee_gt_mismatch / n,
        "arm_branch_rows": arm_rows,
        "arm_vs_ee_gt_discrepancy_rate": (
            arm_branch_mismatch / arm_rows if arm_rows else None
        ),
        "contact_rows": contact_rows,
        "contact_unknown_rate": (
            contact_unknown / contact_rows if contact_rows else None
        ),
        "config_ee_radius": config.ee_radius,
        "config_collision_threshold": config.human_hand_radius + config.ee_radius,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare GT audit branches on safety CSVs.")
    parser.add_argument(
        "csv_paths",
        nargs="+",
        type=Path,
        help="One or more episode_*.csv paths or log session directories.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Safety config YAML (default: configs/safety_layer1.yaml).",
    )
    args = parser.parse_args()

    config_path = args.config or (_REPO / "configs" / "safety_layer1.yaml")
    csv_files: list[Path] = []
    for p in args.csv_paths:
        if p.is_dir():
            csv_files.extend(sorted(p.glob("episode_*.csv")))
        else:
            csv_files.append(p)

    if not csv_files:
        print("No CSV files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Config: {config_path}")
    print("-" * 72)
    for csv_path in csv_files:
        report = analyze_csv(csv_path, config_path)
        print(f"File: {report['path']}")
        print(f"  steps: {report['steps']}")
        print(f"  GT STOP/ALLOW steps: {report['gt_stop_steps']}/{report['gt_allow_steps']}")
        print(
            f"  ee GT recompute mismatch rate: {report['ee_gt_recompute_mismatch_rate']:.4f}"
        )
        if report["arm_branch_rows"]:
            print(
                f"  arm branch vs ee GT discrepancy: "
                f"{report['arm_vs_ee_gt_discrepancy_rate']:.4f} "
                f"({report['arm_branch_rows']} rows with g_gt_arm)"
            )
        else:
            print("  arm branch: no g_gt_arm column (pre-Phase-1 logs OK)")
        if report["contact_rows"]:
            print(
                f"  contact unknown rate: {report['contact_unknown_rate']:.4f} "
                f"({report['contact_rows']} rows)"
            )
        else:
            print("  contact branch: no gt_contact column")
        print()


if __name__ == "__main__":
    main()
