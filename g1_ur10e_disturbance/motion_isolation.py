"""Motion-isolation helpers for Dyn-C UR10 freeze telemetry."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

import numpy as np

try:
    from dual_env_cfg import ARM_JOINT_NAMES as _CFG_ARM_JOINT_NAMES
    from dual_env_cfg import GRIPPER_JOINT_NAMES as _CFG_GRIPPER_JOINT_NAMES
except Exception:
    _CFG_ARM_JOINT_NAMES = (
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    )
    _CFG_GRIPPER_JOINT_NAMES = (
        "finger_joint",
        "right_outer_knuckle_joint",
        "right_inner_finger_joint",
        "right_inner_finger_knuckle_joint",
        "left_inner_finger_knuckle_joint",
        "left_inner_finger_joint",
    )

ARM_JOINT_NAMES = tuple(str(x) for x in _CFG_ARM_JOINT_NAMES)
GRIPPER_JOINT_NAMES = tuple(str(x) for x in _CFG_GRIPPER_JOINT_NAMES)


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


def _to_float32_1d(value: Any, *, context: str) -> np.ndarray:
    """Convert observation/action payload to a flat float32 numpy vector."""
    v = value
    if hasattr(v, "detach"):
        v = v.detach()
    if hasattr(v, "cpu"):
        v = v.cpu()
    if hasattr(v, "numpy"):
        v = v.numpy()
    arr = np.asarray(v, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{context}: empty payload")
    return arr


def resolve_ur10_freeze_action_seed(
    *,
    ur10_state_action: Any | None,
    ur10_policy_obs: Any,
    policy_ee_pos_indices: Sequence[int] = (0, 1, 2, 3, 4, 5, 6),
) -> tuple[np.ndarray, float, str]:
    """Resolve 7D hold pose + gripper for freeze init, with provenance.

    Source priority (fail-closed):
    1) Existing UR10e runtime state/action interface (8D action payload).
    2) Explicit `ur10e_policy.ee_pos` indices for the 7D pose.
    Gripper is required from runtime state/action and is never guessed.
    """
    if ur10_state_action is not None:
        action = _to_float32_1d(ur10_state_action, context="ur10_state_action")
        if action.shape[0] < 8:
            raise ValueError(
                f"ur10_state_action must provide at least 8 dims [pose7+gripper], got {action.shape[0]}"
            )
        return action[:7].copy(), float(action[7]), "ur10_state_action.pose7+gripper"

    if not isinstance(ur10_policy_obs, dict):
        raise TypeError("ur10_policy_obs must be a dict when ur10_state_action is unavailable")
    if "ee_pos" not in ur10_policy_obs:
        raise KeyError("ur10_policy_obs missing required key 'ee_pos'")
    ee_pos = _to_float32_1d(ur10_policy_obs["ee_pos"], context="ur10_policy_obs.ee_pos")
    max_idx = max(int(i) for i in policy_ee_pos_indices)
    if ee_pos.shape[0] <= max_idx:
        raise ValueError(
            f"ur10_policy_obs.ee_pos too short for indices {tuple(policy_ee_pos_indices)}: got {ee_pos.shape[0]}"
        )
    raise ValueError(
        "gripper seed unavailable from ur10_policy_obs-only path; require ur10_state_action to avoid guessing"
    )


def extract_ur10_pose7_from_policy_obs(
    ur10_policy_obs: Any,
    *,
    policy_ee_pos_indices: Sequence[int] = (0, 1, 2, 3, 4, 5, 6),
) -> tuple[np.ndarray, str]:
    """Extract 7D pose from policy observation using explicit indices."""
    if not isinstance(ur10_policy_obs, dict):
        raise TypeError("ur10_policy_obs must be a dict")
    if "ee_pos" not in ur10_policy_obs:
        raise KeyError("ur10_policy_obs missing required key 'ee_pos'")
    ee_pos = _to_float32_1d(ur10_policy_obs["ee_pos"], context="ur10_policy_obs.ee_pos")
    max_idx = max(int(i) for i in policy_ee_pos_indices)
    if ee_pos.shape[0] <= max_idx:
        raise ValueError(
            f"ur10_policy_obs.ee_pos too short for indices {tuple(policy_ee_pos_indices)}: got {ee_pos.shape[0]}"
        )
    pose7 = np.asarray([ee_pos[int(i)] for i in policy_ee_pos_indices], dtype=np.float32)
    return pose7, f"ur10_policy_obs.ee_pos[{tuple(int(i) for i in policy_ee_pos_indices)}]"


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


def _first_name_to_index(joint_names: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, name in enumerate(joint_names):
        if name not in out:
            out[str(name)] = int(i)
    return out


def resolve_ur10_hold_target_from_articulation(articulation: Any) -> tuple[np.ndarray, list[dict[str, Any]], float]:
    """Resolve 7D hold target from articulation actual state.

    The returned 7D vector layout is `[ARM_JOINT_NAMES(6), gripper_actual]`.
    """
    if articulation is None:
        raise ValueError("articulation is required")
    if not hasattr(articulation, "joint_names"):
        raise ValueError("articulation missing joint_names")
    if not hasattr(articulation, "data") or not hasattr(articulation.data, "joint_pos"):
        raise ValueError("articulation missing data.joint_pos")
    joint_names = [str(n) for n in articulation.joint_names]
    name_to_idx = _first_name_to_index(joint_names)
    joint_pos_full = _to_float32_1d(articulation.data.joint_pos[0], context="articulation.data.joint_pos[0]")
    if joint_pos_full.shape[0] < len(joint_names):
        raise ValueError(
            f"articulation joint_pos shorter than joint_names: {joint_pos_full.shape[0]} < {len(joint_names)}"
        )

    provenance: list[dict[str, Any]] = []
    arm_values: list[float] = []
    for jn in ARM_JOINT_NAMES:
        if jn not in name_to_idx:
            raise KeyError(f"missing UR10 arm joint in articulation: {jn}")
        jidx = int(name_to_idx[jn])
        jval = float(joint_pos_full[jidx])
        arm_values.append(jval)
        provenance.append({"kind": "arm", "joint_name": jn, "joint_id": jidx, "value": jval})

    grip_name = None
    grip_idx = None
    grip_val = None
    for cand in GRIPPER_JOINT_NAMES:
        if cand in name_to_idx:
            grip_name = cand
            grip_idx = int(name_to_idx[cand])
            grip_val = float(joint_pos_full[grip_idx])
            break
    if grip_name is None or grip_idx is None or grip_val is None:
        raise KeyError(
            "missing UR10 gripper joint in articulation: "
            f"expected one of {tuple(str(n) for n in GRIPPER_JOINT_NAMES)}"
        )
    provenance.append({"kind": "gripper", "joint_name": grip_name, "joint_id": grip_idx, "value": grip_val})

    hold_target7 = np.asarray(arm_values + [grip_val], dtype=np.float32)
    return hold_target7, provenance, grip_val
