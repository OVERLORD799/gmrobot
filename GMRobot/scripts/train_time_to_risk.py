#!/usr/bin/env python3
"""Train a time-to-risk regressor from the dataset built by build_time_to_risk_dataset.py.

Outputs a ``time_to_risk_model.joblib`` consumable by SafetyPredictor for
online predictive replan (W13 / Phase 4b).

Usage::

    python scripts/train_time_to_risk.py \
        --dataset output/time_to_risk_dataset.csv \
        --output-dir output/safety_models/time_to_risk_v1
"""

from __future__ import annotations

import os

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
from joblib import dump


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a time-to-risk regressor for predictive replan."
    )
    parser.add_argument(
        "--dataset", required=True,
        help="CSV from build_time_to_risk_dataset.py.",
    )
    parser.add_argument(
        "--output-dir", default=os.path.join(os.environ.get("GMROBOT_OUTPUT_DIR", "/root/GMRobot/output"), "safety_models", "time_to_risk_v1"),
        help="Directory for model.joblib + metrics.json.",
    )
    parser.add_argument(
        "--test-split", type=float, default=0.2,
        help="Fraction of rows to hold out for testing.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for split.",
    )
    return parser.parse_args()


def load_dataset(path: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return (X, y, feature_names) from a time-to-risk CSV."""
    import csv
    rows: list[dict[str, float]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            feats = {}
            for k, v in row.items():
                if k in ("time_to_collision_steps", "run_dir", "step_index"):
                    continue
                try:
                    feats[k] = float(v)
                except (ValueError, TypeError):
                    pass
            feats["label"] = float(row.get("time_to_collision_steps", 500))
            rows.append(feats)
    if not rows:
        raise SystemExit("No training rows found.")
    feature_names = sorted(k for k in rows[0] if k != "label")
    X = np.array([[r.get(k, 0.0) for k in feature_names] for r in rows], dtype=np.float64)
    y = np.array([r["label"] for r in rows], dtype=np.float64)
    # Clean: replace NaN/inf with 0, clip extreme values.
    X = np.nan_to_num(X, nan=0.0, posinf=500.0, neginf=-500.0)
    X = np.clip(X, -1e6, 1e6)
    return X, y, feature_names


def train_and_evaluate(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    *,
    test_split: float,
    seed: int,
) -> tuple[Any, dict[str, float], list[str]]:
    """Train a GradientBoostingRegressor and return (model, metrics, feature_names)."""
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import train_test_split

    rng = np.random.RandomState(seed)
    indices = rng.permutation(len(X))
    split_n = max(1, int(len(X) * (1.0 - test_split)))
    train_idx = indices[:split_n]
    test_idx = indices[split_n:]

    X_train, y_train = X[train_idx], y[train_idx]
    X_test, y_test = X[test_idx], y[test_idx]

    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        random_state=seed,
    )
    model.fit(X_train, y_train)

    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    metrics = {
        "train_rmse": float(math.sqrt(np.mean((y_train - y_pred_train) ** 2))),
        "test_rmse": float(math.sqrt(np.mean((y_test - y_pred_test) ** 2))),
        "test_r2": float(model.score(X_test, y_test)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "n_features": int(len(feature_names)),
        "n_estimators": model.n_estimators,
        "max_depth": model.max_depth,
    }
    # Feature importance
    importances = sorted(
        zip(feature_names, model.feature_importances_),
        key=lambda x: -x[1],
    )
    metrics["top_5_features"] = [f"{name}={imp:.4f}" for name, imp in importances[:5]]

    return model, metrics, feature_names


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading dataset: {args.dataset}", file=sys.stderr)
    X, y, feature_names = load_dataset(args.dataset)
    print(f"  {len(X)} rows, {len(feature_names)} features", file=sys.stderr)

    print(f"Training regressor (test_split={args.test_split}, seed={args.seed})...", file=sys.stderr)
    model, metrics, feature_names = train_and_evaluate(
        X, y, feature_names,
        test_split=args.test_split,
        seed=args.seed,
    )

    # Save model
    model_path = out_dir / "time_to_risk_model.joblib"
    dump(
        {"model": model, "feature_names": feature_names},
        model_path,
    )
    print(f"Model saved to {model_path}", file=sys.stderr)

    # Save metrics + feature names
    metrics_path = out_dir / "metrics.json"
    feature_path = out_dir / "feature_names.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    with open(feature_path, "w", encoding="utf-8") as f:
        json.dump(feature_names, f, indent=2)

    print(file=sys.stderr)
    for k, v in metrics.items():
        if isinstance(v, list):
            print(f"  {k}: {v}", file=sys.stderr)
        elif isinstance(v, float):
            print(f"  {k}: {v:.4f}", file=sys.stderr)
        else:
            print(f"  {k}: {v}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
