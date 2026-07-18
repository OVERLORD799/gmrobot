"""Label extraction for Layer 2 training."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Sequence

from ..types import GateDecision

_LABEL_SOURCES = frozenset(
    {"g_rule", "collision", "gt_ground_truth", "hybrid"}
)

_GT_COLUMN_NAMES = ("g_ground_truth", "gt_collision")
_STOP = int(GateDecision.STOP)
_SLOW = int(GateDecision.SLOW_DOWN)
_ALLOW = int(GateDecision.ALLOW)


def _gt_column(row: Mapping[str, Any]) -> str:
    for name in _GT_COLUMN_NAMES:
        raw = row.get(name, "")
        if raw is not None and raw != "":
            return name
    raise ValueError(
        f"Missing ground-truth label column; expected one of {_GT_COLUMN_NAMES}"
    )


def _parse_float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        raw = row.get(key, "")
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except (ValueError, TypeError):
            continue
    return None


def _parse_positions(row: Mapping[str, Any]) -> tuple[list[float], list[float]] | None:
    ee_raw = row.get("ee_pos", "")
    hand_raw = row.get("human_hand_pos", "")
    if ee_raw in (None, "") or hand_raw in (None, ""):
        return None
    try:
        if isinstance(ee_raw, str):
            ee = json.loads(ee_raw)
        else:
            ee = list(ee_raw)
        if isinstance(hand_raw, str):
            hand = json.loads(hand_raw)
        else:
            hand = list(hand_raw)
        return ee[:3], hand[:3]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def row_distance(
    row: Mapping[str, Any],
    *,
    collision_threshold: float = 0.13,
) -> float | None:
    """Best-effort distance from log row (GT v1.2 envelope-first)."""
    dist = _parse_float(
        row,
        "dist_min_envelope",
        "dist_ee_human_gt",
        "dist_ee_human",
    )
    if dist is not None:
        return dist
    positions = _parse_positions(row)
    if positions is None:
        return None
    ee, hand = positions
    return float(math.dist(ee, hand))


def in_hybrid_warn_zone(
    row: Mapping[str, Any],
    *,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
) -> bool:
    """Caution band for hybrid pseudo-STOP labels."""
    g_rule_raw = row.get("g_rule", "")
    if g_rule_raw not in (None, "") and int(g_rule_raw) == _SLOW:
        return True
    dist = row_distance(row, collision_threshold=safe_dist_hard_stop)
    if dist is None:
        return False
    return safe_dist_hard_stop < dist <= safe_dist_warn


def extract_hybrid_label(
    row: Mapping[str, Any],
    *,
    collision_threshold: float = 0.13,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
) -> int:
    """Hybrid labels for imbalanced GT STOP data.

    Priority:
    1. dist < collision_threshold → STOP (true GT intrusion)
    2. warn zone + g_rule STOP (dist still >= collision_threshold) → STOP (pseudo-positive)
    3. g_rule STOP outside warn / beyond collision → ALLOW (rule false-stop; ML should disagree)
    4. g_rule SLOW_DOWN → SLOW_DOWN
    5. otherwise ALLOW
    """
    dist = row_distance(row, collision_threshold=collision_threshold)
    if dist is not None and dist < collision_threshold:
        return _STOP

    g_rule_raw = row.get("g_rule", "")
    g_rule = int(g_rule_raw) if g_rule_raw not in (None, "") else _ALLOW

    if g_rule == _STOP:
        if in_hybrid_warn_zone(
            row,
            safe_dist_hard_stop=safe_dist_hard_stop,
            safe_dist_warn=safe_dist_warn,
        ):
            return _STOP
        return _ALLOW

    if g_rule == _SLOW:
        return _SLOW

    return _ALLOW


def extract_label(
    row: Mapping[str, Any],
    *,
    label_source: str = "g_rule",
    collision_threshold: float = 0.13,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
) -> int:
    """Map a log row to integer class label {ALLOW=0, STOP=1, SLOW_DOWN=2}."""
    if label_source not in _LABEL_SOURCES:
        raise ValueError(
            f"Unsupported label_source={label_source!r}; expected one of {_LABEL_SOURCES}"
        )

    if label_source == "hybrid":
        return extract_hybrid_label(
            row,
            collision_threshold=collision_threshold,
            safe_dist_hard_stop=safe_dist_hard_stop,
            safe_dist_warn=safe_dist_warn,
        )

    if label_source == "g_rule":
        raw = row.get("g_rule", "")
        if raw is None or raw == "":
            raise ValueError("Missing g_rule label in row")
        label = int(raw)
        if label not in (_ALLOW, _STOP, _SLOW):
            raise ValueError(f"Invalid g_rule label: {label}")
        return label

    if label_source in ("collision", "gt_ground_truth"):
        col = _gt_column(row)
        raw = row.get(col, "")
        if raw is None or raw == "":
            raise ValueError(f"Missing {col} label in row")
        label = int(raw)
        if label not in (_ALLOW, _STOP):
            raise ValueError(
                f"Invalid ground-truth label: {label} (expected ALLOW=0 or STOP=1)"
            )
        return label

    raise AssertionError(f"unhandled label_source={label_source!r}")


def extract_labels(
    rows: Sequence[Mapping[str, Any]],
    *,
    label_source: str = "g_rule",
    collision_threshold: float = 0.13,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
) -> list[int]:
    return [
        extract_label(
            row,
            label_source=label_source,
            collision_threshold=collision_threshold,
            safe_dist_hard_stop=safe_dist_hard_stop,
            safe_dist_warn=safe_dist_warn,
        )
        for row in rows
    ]
