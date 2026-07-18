"""Feature schema and version metadata for Layer 2 safety models."""

from __future__ import annotations

FEATURE_SCHEMA_VERSION = "layer2_v2"

# Phase 2.5c: envelope distance columns from CSV logger (dist_ee_human retained).
ENVELOPE_FEATURE_NAMES: list[str] = [
    "dist_min_envelope",
    "dist_min_arm",
    "dist_min_gripper",
    "dist_min_held",
]

BASE_FEATURE_NAMES: list[str] = [
    "ee_pos_x",
    "ee_pos_y",
    "ee_pos_z",
    "ee_vel_x",
    "ee_vel_y",
    "ee_vel_z",
    "human_hand_pos_x",
    "human_hand_pos_y",
    "human_hand_pos_z",
    "human_hand_vel_x",
    "human_hand_vel_y",
    "human_hand_vel_z",
    "dist_ee_human",
    *ENVELOPE_FEATURE_NAMES,
    "ttc",
    *[f"joint_{i}_pos" for i in range(6)],
    *[f"joint_{i}_vel" for i in range(6)],
]

DERIVED_FEATURE_NAMES: list[str] = [
    "ee_velocity_magnitude",
    "human_velocity_magnitude",
    "momentum_risk",
    "inv_distance",
    "relative_approach_angle",
]


def feature_names(*, include_derived: bool = False) -> list[str]:
    names = list(BASE_FEATURE_NAMES)
    if include_derived:
        names.extend(DERIVED_FEATURE_NAMES)
    return names


def base_feature_dim() -> int:
    return len(BASE_FEATURE_NAMES)
