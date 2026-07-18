"""Load trained Layer 2 models and run inference."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np

# Suppress sklearn version-mismatch noise when deserializing models
# trained in a different environment.  The warnings are cosmetic: the
# underlying RandomForest/XGBoost logic is unaffected.
warnings.filterwarnings(
    "ignore",
    message=r".*delayed.*should be used with.*Parallel.*",
    category=UserWarning,
    module=r"sklearn",
)
warnings.filterwarnings(
    "ignore",
    message=r".*X does not have valid feature names.*",
    category=UserWarning,
    module=r"sklearn",
)

from ..types import GateDecision
from .features import FeatureConfig, extract_feature_matrix, extract_features
from .schema import FEATURE_SCHEMA_VERSION


class SafetyPredictor:
    """Offline predictor for Layer 2 safety classifiers."""

    def __init__(
        self,
        model: Any,
        feature_names: Sequence[str],
        *,
        schema_version: str = FEATURE_SCHEMA_VERSION,
        feature_config: FeatureConfig | None = None,
    ):
        self.model = model
        self.feature_names = list(feature_names)
        self.schema_version = schema_version
        self.feature_config = feature_config or FeatureConfig()

    @classmethod
    def from_artifacts(cls, artifact_dir: str | Path) -> SafetyPredictor:
        root = Path(artifact_dir)
        model_path = root / "model.joblib"
        schema_path = root / "feature_schema.json"
        if not model_path.is_file():
            raise FileNotFoundError(f"Missing model artifact: {model_path}")
        if not schema_path.is_file():
            raise FileNotFoundError(f"Missing feature schema: {schema_path}")

        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)

        feature_config = FeatureConfig(
            include_derived=bool(schema.get("include_derived", False)),
        )
        return cls(
            model=joblib.load(model_path),
            feature_names=schema.get("feature_names", []),
            schema_version=str(schema.get("version", FEATURE_SCHEMA_VERSION)),
            feature_config=feature_config,
        )

    def predict_row(self, row: Mapping[str, Any]) -> int:
        features = extract_features(row, self.feature_config).reshape(1, -1)
        return int(self.model.predict(features)[0])

    def predict_rows(self, rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
        if not rows:
            return np.empty(0, dtype=int)
        features = extract_feature_matrix(rows, self.feature_config)
        return np.asarray(self.model.predict(features), dtype=int)

    def predict_proba_row(self, row: Mapping[str, Any]) -> np.ndarray | None:
        if not hasattr(self.model, "predict_proba"):
            return None
        features = extract_features(row, self.feature_config).reshape(1, -1)
        proba = np.asarray(self.model.predict_proba(features)[0], dtype=float)
        return proba

    def predict_proba_for_label(self, row: Mapping[str, Any], label: int) -> float | None:
        """Return P(label) using sklearn ``classes_`` alignment."""
        proba = self.predict_proba_row(row)
        if proba is None or not hasattr(self.model, "classes_"):
            return None
        classes = list(int(c) for c in self.model.classes_)
        try:
            idx = classes.index(int(label))
        except ValueError:
            return None
        return float(proba[idx])

    @staticmethod
    def decision_name(label: int) -> str:
        return GateDecision(label).name


class TimeToRiskPredictor:
    """Online predictor for W13 time-to-risk regression model.

    Loads a ``time_to_risk_model.joblib`` trained by
    ``scripts/train_time_to_risk.py`` and returns predicted steps
    until the next collision event.
    """

    def __init__(self, model: Any, feature_names: Sequence[str]):
        self.model = model
        self.feature_names = list(feature_names)

    @classmethod
    def from_artifacts(cls, artifact_dir: str | Path) -> TimeToRiskPredictor:
        root = Path(artifact_dir)
        model_path = root / "time_to_risk_model.joblib"
        if not model_path.is_file():
            raise FileNotFoundError(f"Missing model artifact: {model_path}")
        bundle = joblib.load(model_path)
        if isinstance(bundle, dict):
            model = bundle["model"]
            feature_names = bundle.get("feature_names", [])
        else:
            model = bundle
            feature_path = root / "feature_names.json"
            if feature_path.is_file():
                with open(feature_path, encoding="utf-8") as f:
                    feature_names = json.load(f)
            else:
                feature_names = []
        return cls(model=model, feature_names=feature_names)

    def predict(self, row: dict[str, float]) -> float:
        """Return predicted time-to-collision in steps (clamped >= 0)."""
        if not self.feature_names:
            return 500.0
        feats = np.array(
            [[row.get(k, 0.0) for k in self.feature_names]],
            dtype=np.float64,
        )
        feats = np.nan_to_num(feats, nan=0.0).clip(-1e6, 1e6)
        raw = float(self.model.predict(feats)[0])
        return max(0.0, raw)

    @property
    def n_features(self) -> int:
        return len(self.feature_names)
