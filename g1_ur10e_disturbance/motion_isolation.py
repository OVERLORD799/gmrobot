"""Motion-isolation helpers for Dyn-C UR10 freeze telemetry."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np


def build_ur10_hold_action(initial_joint_pose: np.ndarray, initial_gripper: float) -> np.ndarray:
    """Build explicit hold action from initial joints + gripper."""
    joints = np.asarray(initial_joint_pose, dtype=np.float32).reshape(-1)
    if joints.shape[0] != 7:
        raise ValueError(f"expected 7 UR10 joints, got {joints.shape[0]}")
    return np.concatenate([joints, np.array([float(initial_gripper)], dtype=np.float32)])


def hold_action_hash(hold_action: np.ndarray) -> str:
    """Stable SHA256 over hold action payload."""
    a = np.asarray(hold_action, dtype=np.float32).reshape(-1)
    payload = {"hold_action": [float(x) for x in a.tolist()]}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_ur10_freeze_metrics(
    *,
    effective_action: np.ndarray,
    current_joint_pose: np.ndarray,
    initial_joint_pose: np.ndarray,
) -> dict[str, Any]:
    """Compute per-step freeze metrics for audit CSV/JSONL."""
    eff = np.asarray(effective_action, dtype=np.float32).reshape(-1)
    cur = np.asarray(current_joint_pose, dtype=np.float32).reshape(-1)
    init = np.asarray(initial_joint_pose, dtype=np.float32).reshape(-1)
    if eff.shape[0] < 7 or cur.shape[0] != 7 or init.shape[0] != 7:
        raise ValueError("invalid UR10 action/joint shape")
    delta = cur - init
    return {
        "ur10_action_norm": float(np.linalg.norm(eff[:7])),
        "ur10_joint_delta_norm": float(np.linalg.norm(delta)),
        "ur10_joint_delta_max_abs": float(np.max(np.abs(delta))),
    }
