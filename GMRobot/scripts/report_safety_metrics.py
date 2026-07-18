#!/usr/bin/env python3
"""Report Layer 1 safety metrics from CSV logs (offline)."""

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

import yaml


def _gt_label(row: dict, config) -> int:
    """GT label for metrics; envelope v1.2 when gating enabled and dist_min logged."""
    use_envelope = bool(
        getattr(getattr(config, "envelope", None), "gating_enabled", False)
    )
    dist_min = row.get("dist_min_envelope")
    if use_envelope and dist_min not in (None, ""):
        _ground_truth = load_safety_module("ground_truth")
        g_gt, _ = _ground_truth.compute_ground_truth_v12(
            float(dist_min), config=config
        )
        return int(g_gt)
    for col in ("g_ground_truth", "gt_collision"):
        val = row.get(col, "")
        if val not in (None, ""):
            return int(val)
    g_gt, _ = recompute_gt_from_row(row, config)
    return g_gt


def _load_registry() -> dict:
    reg_path = _REPO / "configs" / "ivj" / "registry.yaml"
    if not reg_path.is_file():
        return {}
    with open(reg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _match_preset(run_dir: Path, registry: dict) -> str:
    """Best-effort preset name from run metadata or directory naming."""
    meta = run_dir / "preset.txt"
    if meta.is_file():
        return meta.read_text(encoding="utf-8").strip()
    return run_dir.name


def compute_metrics(rows: list[dict], config) -> dict:
    n = len(rows)
    if n == 0:
        return {}

    stop_steps = 0
    slow_steps = 0
    false_stops = 0
    misses = 0
    gt_stops = 0
    caught = 0

    for row in rows:
        g_rule = int(row.get("g_rule", 0))
        g_gt = _gt_label(row, config)

        if g_rule == int(GateDecision.STOP):
            stop_steps += 1
            if g_gt == int(GateDecision.ALLOW):
                false_stops += 1
        if g_rule == int(GateDecision.SLOW_DOWN):
            slow_steps += 1
        if g_gt == int(GateDecision.STOP):
            gt_stops += 1
            if g_rule == int(GateDecision.STOP):
                caught += 1
            elif g_rule == int(GateDecision.ALLOW):
                misses += 1

    intervention_steps = stop_steps + slow_steps
    return {
        "steps": n,
        "intervention_rate": intervention_steps / n,
        "stop_rate": stop_steps / n,
        "slow_down_rate": slow_steps / n,
        "false_stop_rate": false_stops / n,
        "miss_rate": misses / n,
        "safety_recall": caught / gt_stops if gt_stops else None,
        "gt_stop_steps": gt_stops,
        "false_stops": false_stops,
        "misses": misses,
        "outcome": rows[-1].get("outcome", "") if rows else "",
    }


def analyze_path(path: Path, config_path: Path | None) -> dict:
    config = load_safety_config(config_path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    metrics = compute_metrics(rows, config)
    metrics["csv"] = str(path)
    return metrics


def collect_csv_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("episode_*.csv")))
        else:
            files.append(p)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Report safety metrics from CSV logs.")
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="CSV files or log session directories.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Safety config for offline GT recompute.",
    )
    parser.add_argument(
        "--registry",
        action="store_true",
        help="Print IV-J registry expected bands alongside metrics.",
    )
    args = parser.parse_args()

    config_path = args.config or (_REPO / "configs" / "safety_layer1.yaml")
    registry = _load_registry() if args.registry else {}
    csv_files = collect_csv_files(args.paths)

    if not csv_files:
        print("No CSV files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Config: {config_path}")
    print("=" * 72)
    for csv_path in csv_files:
        m = analyze_path(csv_path, config_path)
        run_dir = csv_path.parent
        preset = _match_preset(run_dir, registry)
        print(f"Run: {run_dir.name}  preset={preset}")
        print(f"  CSV: {m['csv']}")
        print(f"  steps: {m['steps']}")
        print(f"  intervention_rate: {m['intervention_rate']:.4f}")
        print(f"  stop_rate: {m['stop_rate']:.4f}  slow_down_rate: {m['slow_down_rate']:.4f}")
        print(f"  false_stop_rate: {m['false_stop_rate']:.4f}  ({m['false_stops']} steps)")
        print(f"  miss_rate: {m['miss_rate']:.4f}  ({m['misses']} steps)")
        recall = m["safety_recall"]
        if recall is not None:
            print(f"  safety_recall: {recall:.4f} (GT STOP steps={m['gt_stop_steps']})")
        else:
            print("  safety_recall: N/A (no GT STOP steps)")
        print(f"  outcome: {m.get('outcome', '')}")
        print()


if __name__ == "__main__":
    main()
