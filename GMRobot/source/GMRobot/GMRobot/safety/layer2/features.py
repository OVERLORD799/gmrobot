"""Feature extraction from Layer 1 safety log rows."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .schema import DERIVED_FEATURE_NAMES, feature_names


@dataclass
class FeatureConfig:
    include_derived: bool = False
    eps: float = 1e-6
    inf_ttc_replacement: float = 999.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> FeatureConfig:
        data = data or {}
        return cls(
            include_derived=bool(data.get("include_derived", False)),
            eps=float(data.get("eps", 1e-6)),
            inf_ttc_replacement=float(data.get("inf_ttc_replacement", 999.0)),
        )


def _parse_json_array(value: Any, dim: int) -> np.ndarray:
    if value is None or value == "":
        return np.zeros(dim, dtype=np.float64)
    if isinstance(value, (list, tuple)):
        arr = np.asarray(value, dtype=np.float64).reshape(-1)
    else:
        arr = np.asarray(json.loads(str(value)), dtype=np.float64).reshape(-1)
    if arr.size < dim:
        padded = np.zeros(dim, dtype=np.float64)
        padded[: arr.size] = arr
        return padded
    return arr[:dim]


def _parse_scalar(
    value: Any,
    *,
    default: float = 0.0,
    inf_replacement: float = 999.0,
) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, str) and value.strip().lower() in {"inf", "+inf", "infinity"}:
        return inf_replacement
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return inf_replacement
    return parsed


def extract_base_features(row: Mapping[str, Any], config: FeatureConfig) -> np.ndarray:
    """Extract 30-dim base feature vector from one log row."""
    ee_pos = _parse_json_array(row.get("ee_pos"), 3)
    ee_vel = _parse_json_array(row.get("ee_vel"), 3)
    hand_pos = _parse_json_array(row.get("human_hand_pos"), 3)
    hand_vel = _parse_json_array(row.get("human_hand_vel"), 3)
    joint_pos = _parse_json_array(row.get("joint_positions"), 6)
    joint_vel = _parse_json_array(row.get("joint_velocities"), 6)
    dist = _parse_scalar(row.get("dist_ee_human"), default=0.0, inf_replacement=config.inf_ttc_replacement)
    dist_min_envelope = _parse_scalar(
        row.get("dist_min_envelope"), default=0.0, inf_replacement=config.inf_ttc_replacement
    )
    dist_min_arm = _parse_scalar(
        row.get("dist_min_arm"), default=0.0, inf_replacement=config.inf_ttc_replacement
    )
    dist_min_gripper = _parse_scalar(
        row.get("dist_min_gripper"), default=0.0, inf_replacement=config.inf_ttc_replacement
    )
    dist_min_held = _parse_scalar(
        row.get("dist_min_held"), default=0.0, inf_replacement=config.inf_ttc_replacement
    )
    ttc = _parse_scalar(
        row.get("ttc"),
        default=config.inf_ttc_replacement,
        inf_replacement=config.inf_ttc_replacement,
    )
    return np.concatenate(
        [
            ee_pos,
            ee_vel,
            hand_pos,
            hand_vel,
            np.array(
                [dist, dist_min_envelope, dist_min_arm, dist_min_gripper, dist_min_held, ttc]
            ),
            joint_pos,
            joint_vel,
        ]
    )


def _derived_features(
    ee_pos: np.ndarray,
    ee_vel: np.ndarray,
    hand_pos: np.ndarray,
    hand_vel: np.ndarray,
    dist: float,
    config: FeatureConfig,
) -> np.ndarray:
    ee_speed = float(np.linalg.norm(ee_vel))
    hand_speed = float(np.linalg.norm(hand_vel))
    momentum_risk = dist * (ee_speed + hand_speed)
    inv_distance = 1.0 / (dist + config.eps)

    rel_vec = hand_pos - ee_pos
    rel_norm = float(np.linalg.norm(rel_vec))
    if rel_norm < config.eps or hand_speed < config.eps:
        approach_angle = 0.0
    else:
        cos_angle = float(np.dot(rel_vec, hand_vel) / (rel_norm * hand_speed))
        cos_angle = max(-1.0, min(1.0, cos_angle))
        approach_angle = math.acos(cos_angle)

    return np.array(
        [ee_speed, hand_speed, momentum_risk, inv_distance, approach_angle],
        dtype=np.float64,
    )


def extract_features(row: Mapping[str, Any], config: FeatureConfig | None = None) -> np.ndarray:
    """Extract feature vector; optionally append derived features."""
    config = config or FeatureConfig()
    base = extract_base_features(row, config)
    if not config.include_derived:
        return base

    ee_pos = base[0:3]
    ee_vel = base[3:6]
    hand_pos = base[6:9]
    hand_vel = base[9:12]
    dist = float(base[12])
    derived = _derived_features(ee_pos, ee_vel, hand_pos, hand_vel, dist, config)
    return np.concatenate([base, derived])


def extract_feature_matrix(
    rows: Sequence[Mapping[str, Any]],
    config: FeatureConfig | None = None,
) -> np.ndarray:
    if not rows:
        config = config or FeatureConfig()
        dim = len(feature_names(include_derived=config.include_derived))
        return np.empty((0, dim), dtype=np.float64)
    vectors = [extract_features(row, config) for row in rows]
    return np.vstack(vectors)


def get_feature_names(config: FeatureConfig | None = None) -> list[str]:
    config = config or FeatureConfig()
    return feature_names(include_derived=config.include_derived)
