"""Offline evaluation metrics for Layer 2 safety classifiers."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from ..types import GateDecision

CLASS_NAMES = {
    int(GateDecision.ALLOW): "ALLOW",
    int(GateDecision.STOP): "STOP",
    int(GateDecision.SLOW_DOWN): "SLOW_DOWN",
}
STOP_CLASS = int(GateDecision.STOP)
ALLOW_CLASS = int(GateDecision.ALLOW)


def _confusion_counts(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[int, dict[int, int]]:
    counts: dict[int, dict[int, int]] = {
        cls: {pred: 0 for pred in CLASS_NAMES} for cls in CLASS_NAMES
    }
    for true, pred in zip(y_true, y_pred, strict=True):
        counts[true][pred] += 1
    return counts


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den > 0 else 0.0


def compute_metrics(y_true: Sequence[int], y_pred: Sequence[int]) -> dict[str, Any]:
    """Compute accuracy, per-class metrics, STOP safety recall, and STOP false-positive rate."""
    y_true_arr = np.asarray(y_true, dtype=int)
    y_pred_arr = np.asarray(y_pred, dtype=int)
    if y_true_arr.size == 0:
        return {
            "num_samples": 0,
            "accuracy": 0.0,
            "confusion_matrix": {},
            "per_class": {},
            "stop_safety_recall": 0.0,
            "stop_false_positive_rate": 0.0,
            "stop_precision": 0.0,
            "stop_f1": 0.0,
        }

    accuracy = float(np.mean(y_true_arr == y_pred_arr))
    confusion = _confusion_counts(y_true_arr.tolist(), y_pred_arr.tolist())

    per_class: dict[str, dict[str, float]] = {}
    for cls, name in CLASS_NAMES.items():
        tp = confusion[cls][cls]
        fn = sum(confusion[cls][other] for other in CLASS_NAMES if other != cls)
        fp = sum(confusion[other][cls] for other in CLASS_NAMES if other != cls)
        support = tp + fn
        per_class[name] = {
            "precision": _safe_div(tp, tp + fp),
            "recall": _safe_div(tp, support),
            "f1": _safe_div(2 * tp, 2 * tp + fp + fn),
            "support": support,
        }

    stop_tp = confusion[STOP_CLASS][STOP_CLASS]
    stop_fn = sum(confusion[STOP_CLASS][other] for other in CLASS_NAMES if other != STOP_CLASS)
    stop_fp = sum(confusion[other][STOP_CLASS] for other in CLASS_NAMES if other != STOP_CLASS)
    allow_as_stop = confusion[ALLOW_CLASS][STOP_CLASS]
    allow_support = sum(confusion[ALLOW_CLASS].values())

    return {
        "num_samples": int(y_true_arr.size),
        "accuracy": accuracy,
        "confusion_matrix": {
            CLASS_NAMES[true]: {CLASS_NAMES[pred]: count for pred, count in row.items()}
            for true, row in confusion.items()
        },
        "per_class": per_class,
        "stop_safety_recall": _safe_div(stop_tp, stop_tp + stop_fn),
        "stop_false_positive_rate": _safe_div(allow_as_stop, allow_support),
        "stop_precision": per_class["STOP"]["precision"],
        "stop_f1": per_class["STOP"]["f1"],
        "stop_false_positives": int(stop_fp),
        "stop_false_negatives": int(stop_fn),
        "allow_misclassified_as_stop": int(allow_as_stop),
    }


def format_metrics_report(metrics: Mapping[str, Any]) -> str:
    lines = [
        f"samples={metrics.get('num_samples', 0)}",
        f"accuracy={metrics.get('accuracy', 0.0):.4f}",
        f"stop_safety_recall={metrics.get('stop_safety_recall', 0.0):.4f}",
        f"stop_false_positive_rate={metrics.get('stop_false_positive_rate', 0.0):.4f}",
        f"stop_f1={metrics.get('stop_f1', 0.0):.4f}",
    ]
    return "\n".join(lines)
