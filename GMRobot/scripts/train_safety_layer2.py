#!/usr/bin/env python3
"""Train Layer 2 safety classifier from Layer 1 CSV logs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _layer2_import import load_layer2_module

_dataset = load_layer2_module("dataset")
_evaluate = load_layer2_module("evaluate")
_train = load_layer2_module("train")

load_episodes = _dataset.load_episodes
format_metrics_report = _evaluate.format_metrics_report
load_train_config = _train.load_train_config
train_layer2 = _train.train_layer2

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train GM-SafePick Layer 2 safety classifier")
    parser.add_argument(
        "--config",
        type=Path,
        default=_REPO_ROOT / "configs" / "safety_layer2_train.yaml",
        help="Path to Layer 2 training YAML config",
    )
    args = parser.parse_args()

    config = load_train_config(args.config)
    episodes = load_episodes(
        config.log_dir,
        min_run_id=config.min_run_id,
        glob_pattern=config.glob_pattern,
    )
    if not episodes:
        print(f"No episodes found under {config.log_dir} (min_run_id={config.min_run_id})")
        return 1

    total_rows = sum(ep.num_rows for ep in episodes)
    print(f"Loaded {len(episodes)} episodes, {total_rows} rows from {config.log_dir}")

    result = train_layer2(episodes, config)
    metrics = result["metrics"]
    print(f"Artifacts saved to {result['output_dir']}")
    print("Train metrics:")
    print(format_metrics_report(metrics["train"]))
    if metrics.get("val"):
        print("Val metrics:")
        print(format_metrics_report(metrics["val"]))
    if metrics.get("test"):
        print("Test metrics:")
        print(format_metrics_report(metrics["test"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
