"""Train Layer 2 safety classifiers from Layer 1 logs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import resolve_output_path

import joblib
import numpy as np
import yaml

from .dataset import SafetyEpisode
from .evaluate import compute_metrics
from .features import FeatureConfig, extract_feature_matrix, get_feature_names
from ..types import GateDecision
from .labels import extract_labels
from .schema import FEATURE_SCHEMA_VERSION
from .split import EpisodeSplit, split_episodes


@dataclass
class ModelConfig:
    type: str = "random_forest"
    random_forest: dict[str, Any] = field(
        default_factory=lambda: {
            "n_estimators": 200,
            "max_depth": None,
            "min_samples_leaf": 1,
            "random_state": 42,
            "n_jobs": -1,
        }
    )
    xgboost: dict[str, Any] = field(
        default_factory=lambda: {
            "n_estimators": 200,
            "max_depth": 6,
            "learning_rate": 0.1,
            "random_state": 42,
            "n_jobs": -1,
        }
    )


@dataclass
class HybridLabelConfig:
    collision_threshold: float = 0.13
    safe_dist_hard_stop: float = 0.13
    safe_dist_warn: float = 0.16


@dataclass
class Layer2TrainConfig:
    log_dir: str = field(default_factory=lambda: resolve_output_path("safety_logs"))
    min_run_id: str = "20260617_141625"
    glob_pattern: str = "**/episode_*.csv"
    label_source: str = "g_rule"
    hybrid: HybridLabelConfig = field(default_factory=HybridLabelConfig)
    oversample_stop: bool = True
    oversample_stop_ratio: float = 3.0
    features: FeatureConfig = field(default_factory=FeatureConfig)
    split_train_ratio: float = 0.70
    split_val_ratio: float = 0.15
    split_test_ratio: float = 0.15
    split_seed: int = 42
    model: ModelConfig = field(default_factory=ModelConfig)
    output_dir: str = field(default_factory=lambda: resolve_output_path("safety_models"))
    run_name: str = "auto"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Layer2TrainConfig:
        data_cfg = data.get("data", {})
        label_cfg = data.get("labels", {})
        hybrid_cfg = label_cfg.get("hybrid", {})
        split_cfg = data.get("split", {})
        model_cfg = data.get("model", {})
        output_cfg = data.get("output", {})
        return cls(
            log_dir=str(data_cfg.get("log_dir", resolve_output_path("safety_logs"))),
            min_run_id=str(data_cfg.get("min_run_id", "20260617_141625")),
            glob_pattern=str(data_cfg.get("glob_pattern", "**/episode_*.csv")),
            label_source=str(label_cfg.get("label_source", "g_rule")),
            hybrid=HybridLabelConfig(
                collision_threshold=float(hybrid_cfg.get("collision_threshold", 0.13)),
                safe_dist_hard_stop=float(hybrid_cfg.get("safe_dist_hard_stop", 0.13)),
                safe_dist_warn=float(hybrid_cfg.get("safe_dist_warn", 0.16)),
            ),
            oversample_stop=bool(label_cfg.get("oversample_stop", True)),
            oversample_stop_ratio=float(label_cfg.get("oversample_stop_ratio", 3.0)),
            features=FeatureConfig.from_dict(data.get("features", {})),
            split_train_ratio=float(split_cfg.get("train_ratio", 0.70)),
            split_val_ratio=float(split_cfg.get("val_ratio", 0.15)),
            split_test_ratio=float(split_cfg.get("test_ratio", 0.15)),
            split_seed=int(split_cfg.get("seed", 42)),
            model=ModelConfig(
                type=str(model_cfg.get("type", "random_forest")),
                random_forest=dict(model_cfg.get("random_forest", {})),
                xgboost=dict(model_cfg.get("xgboost", {})),
            ),
            output_dir=str(output_cfg.get("dir", resolve_output_path("safety_models"))),
            run_name=str(output_cfg.get("run_name", "auto")),
        )


def load_train_config(path: str | Path) -> Layer2TrainConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Layer2TrainConfig.from_dict(data)


def _rows_from_episodes(episodes: Sequence[SafetyEpisode]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        rows.extend(episode.rows)
    return rows


def _label_kwargs(config: Layer2TrainConfig) -> dict[str, Any]:
    return {
        "label_source": config.label_source,
        "collision_threshold": config.hybrid.collision_threshold,
        "safe_dist_hard_stop": config.hybrid.safe_dist_hard_stop,
        "safe_dist_warn": config.hybrid.safe_dist_warn,
    }


def _oversample_stop_rows(
    x: np.ndarray,
    y: np.ndarray,
    *,
    ratio: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Duplicate STOP rows so minority class is better represented."""
    stop_idx = np.where(y == int(GateDecision.STOP))[0]
    if stop_idx.size == 0 or ratio <= 1.0:
        return x, y
    extra_count = int(round(stop_idx.size * (ratio - 1.0)))
    if extra_count <= 0:
        return x, y
    rng = np.random.default_rng(42)
    pick = rng.choice(stop_idx, size=extra_count, replace=True)
    return np.vstack([x, x[pick]]), np.concatenate([y, y[pick]])


def _xy_from_episodes(
    episodes: Sequence[SafetyEpisode],
    config: Layer2TrainConfig,
    *,
    oversample: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    rows = _rows_from_episodes(episodes)
    x = extract_feature_matrix(rows, config.features)
    y = np.asarray(extract_labels(rows, **_label_kwargs(config)), dtype=int)
    if oversample and config.oversample_stop:
        x, y = _oversample_stop_rows(
            x, y, ratio=config.oversample_stop_ratio
        )
    return x, y


def _build_classifier(model_cfg: ModelConfig):
    if model_cfg.type == "random_forest":
        from sklearn.ensemble import RandomForestClassifier

        params = {
            "n_estimators": 200,
            "max_depth": None,
            "min_samples_leaf": 1,
            "random_state": 42,
            "n_jobs": -1,
            "class_weight": "balanced",
        }
        params.update(model_cfg.random_forest)
        params.setdefault("class_weight", "balanced")
        return RandomForestClassifier(**params)

    if model_cfg.type == "xgboost":
        try:
            from xgboost import XGBClassifier
        except ImportError as exc:
            raise ImportError("xgboost is required when model.type=xgboost") from exc

        params = {
            "n_estimators": 200,
            "max_depth": 6,
            "learning_rate": 0.1,
            "random_state": 42,
            "n_jobs": -1,
            "objective": "multi:softmax",
            "num_class": 3,
        }
        params.update(model_cfg.xgboost)
        return XGBClassifier(**params)

    raise ValueError(f"Unsupported model.type={model_cfg.type!r}")


def _resolve_output_dir(config: Layer2TrainConfig) -> Path:
    base = Path(config.output_dir)
    run_name = config.run_name
    if run_name == "auto":
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base / run_name
    out.mkdir(parents=True, exist_ok=True)
    return out


def train_layer2(
    episodes: Sequence[SafetyEpisode],
    config: Layer2TrainConfig,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Train classifier, evaluate splits, and persist artifacts."""
    split = split_episodes(
        episodes,
        train_ratio=config.split_train_ratio,
        val_ratio=config.split_val_ratio,
        test_ratio=config.split_test_ratio,
        seed=config.split_seed,
    )

    x_train, y_train = _xy_from_episodes(split.train, config, oversample=True)
    x_val, y_val = _xy_from_episodes(split.val, config)
    x_test, y_test = _xy_from_episodes(split.test, config)

    classifier = _build_classifier(config.model)
    classifier.fit(x_train, y_train)

    val_metrics = compute_metrics(y_val, classifier.predict(x_val)) if y_val.size else {}
    test_metrics = compute_metrics(y_test, classifier.predict(x_test)) if y_test.size else {}
    train_metrics = compute_metrics(y_train, classifier.predict(x_train))

    out_dir = output_dir or _resolve_output_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_schema = {
        "version": FEATURE_SCHEMA_VERSION,
        "feature_names": get_feature_names(config.features),
        "include_derived": config.features.include_derived,
        "label_source": config.label_source,
        "num_features": len(get_feature_names(config.features)),
    }

    metrics = {
        "train": train_metrics,
        "val": val_metrics,
        "test": test_metrics,
        "split": {
            "train_episodes": len(split.train),
            "val_episodes": len(split.val),
            "test_episodes": len(split.test),
            "train_rows": int(y_train.size),
            "val_rows": int(y_val.size),
            "test_rows": int(y_test.size),
        },
        "episodes_total": len(episodes),
    }

    joblib.dump(classifier, out_dir / "model.joblib")
    with open(out_dir / "feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(feature_schema, f, indent=2)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    with open(out_dir / "train_config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {
                "data": {
                    "log_dir": config.log_dir,
                    "min_run_id": config.min_run_id,
                    "glob_pattern": config.glob_pattern,
                },
                "labels": {
                    "label_source": config.label_source,
                    "hybrid": {
                        "collision_threshold": config.hybrid.collision_threshold,
                        "safe_dist_hard_stop": config.hybrid.safe_dist_hard_stop,
                        "safe_dist_warn": config.hybrid.safe_dist_warn,
                    },
                    "oversample_stop": config.oversample_stop,
                    "oversample_stop_ratio": config.oversample_stop_ratio,
                },
                "features": asdict(config.features),
                "split": {
                    "train_ratio": config.split_train_ratio,
                    "val_ratio": config.split_val_ratio,
                    "test_ratio": config.split_test_ratio,
                    "seed": config.split_seed,
                },
                "model": {
                    "type": config.model.type,
                    "random_forest": config.model.random_forest,
                    "xgboost": config.model.xgboost,
                },
                "output": {"dir": config.output_dir, "run_name": out_dir.name},
            },
            f,
            sort_keys=False,
        )

    return {
        "output_dir": str(out_dir),
        "metrics": metrics,
        "split": split,
        "model": classifier,
    }
