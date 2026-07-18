#!/usr/bin/env python3
"""Offline evaluation for a trained Layer 2 safety model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _layer2_import import load_layer2_module

_dataset = load_layer2_module("dataset")
_evaluate = load_layer2_module("evaluate")
_labels = load_layer2_module("labels")
_predictor = load_layer2_module("predictor")
_split = load_layer2_module("split")
_train = load_layer2_module("train")

load_episodes = _dataset.load_episodes
compute_metrics = _evaluate.compute_metrics
format_metrics_report = _evaluate.format_metrics_report
extract_labels = _labels.extract_labels
SafetyPredictor = _predictor.SafetyPredictor
split_episodes = _split.split_episodes
load_train_config = _train.load_train_config

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _rows_from_episodes(episodes):
    rows = []
    for episode in episodes:
        rows.extend(episode.rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GM-SafePick Layer 2 model offline")
    parser.add_argument(
        "--model-dir",
        type=Path,
        required=True,
        help="Directory containing model.joblib and feature_schema.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_REPO_ROOT / "configs" / "safety_layer2_train.yaml",
        help="Data/split config (for hold-out evaluation)",
    )
    parser.add_argument(
        "--split",
        choices=("test", "val", "all"),
        default="test",
        help="Which episode split to evaluate (uses config split ratios)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Override log_dir from config for ad-hoc evaluation",
    )
    parser.add_argument(
        "--min-run-id",
        type=str,
        default=None,
        help="Override min_run_id from config",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write metrics JSON",
    )
    args = parser.parse_args()

    config = load_train_config(args.config)
    log_dir = args.log_dir or Path(config.log_dir)
    min_run_id = args.min_run_id if args.min_run_id is not None else config.min_run_id

    episodes = load_episodes(log_dir, min_run_id=min_run_id, glob_pattern=config.glob_pattern)
    if not episodes:
        print(f"No episodes found under {log_dir}")
        return 1

    predictor = SafetyPredictor.from_artifacts(args.model_dir)

    if args.split == "all":
        eval_episodes = episodes
        split_name = "all"
    else:
        split = split_episodes(
            episodes,
            train_ratio=config.split_train_ratio,
            val_ratio=config.split_val_ratio,
            test_ratio=config.split_test_ratio,
            seed=config.split_seed,
        )
        eval_episodes = split.test if args.split == "test" else split.val
        split_name = args.split

    rows = _rows_from_episodes(eval_episodes)
    y_true = extract_labels(rows, label_source=config.label_source)
    y_pred = predictor.predict_rows(rows).tolist()
    metrics = compute_metrics(y_true, y_pred)

    print(f"Evaluated {len(eval_episodes)} episodes ({split_name}), {len(rows)} rows")
    print(format_metrics_report(metrics))
    print(json.dumps(metrics.get("confusion_matrix", {}), indent=2))

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        print(f"Wrote metrics to {args.output_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
