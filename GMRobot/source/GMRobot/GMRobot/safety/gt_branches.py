"""Audit-only ground-truth branches (log-only, no gating).

Branch A: min distance from human hand to UR10e arm link centroids.
Branch B: PhysX contact (best-effort; kinematic human_hand often yields unknown).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from .config import GtBranchesConfig, SafetyConfig, _DEFAULT_ARM_LINK_NAMES
from .ground_truth import collision_threshold_m
from .types import GateDecision, SafetyState

# Re-export canonical names for backward compatibility.
DEFAULT_ARM_LINK_NAMES: tuple[str, ...] = tuple(_DEFAULT_ARM_LINK_NAMES)

# UR10e DH parameters (m, rad) — standard UR convention.
_UR10E_A = (0.0, -0.6127, -0.57155, 0.0, 0.0, 0.0)
_UR10E_D = (0.1807, 0.0, 0.0, 0.17415, 0.11985, 0.11655)
_UR10E_ALPHA = (math.pi / 2, 0.0, 0.0, math.pi / 2, -math.pi / 2, 0.0)
_UR10E_DEFAULT_Q = (
    0.0,
    -1.5707963267948966,
    1.5707963267948966,
    -1.5707963267948966,
    -1.5707963267948966,
    0.0,
)


@dataclass
class GtBranchResult:
    """Optional audit fields; never used for g_t gating."""

    min_dist_arm_links: float | None = None
    g_gt_arm: int | None = None
    gt_contact: str = ""
    gt_contact_pairs: str = ""
    arm_link_positions_used: list[str] = field(default_factory=list)

    def to_log_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.min_dist_arm_links is not None:
            out["min_dist_arm_links"] = float(self.min_dist_arm_links)
        if self.g_gt_arm is not None:
            out["g_gt_arm"] = int(self.g_gt_arm)
        if self.gt_contact:
            out["gt_contact"] = self.gt_contact
        if self.gt_contact_pairs:
            out["gt_contact_pairs"] = self.gt_contact_pairs
        return out


def _dh_transform(a: float, alpha: float, d: float, theta: float) -> np.ndarray:
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha), math.sin(alpha)
    return np.array(
        [
            [ct, -st * ca, st * sa, a * ct],
            [st, ct * ca, -ct * sa, a * st],
            [0.0, sa, ca, d],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def ur10e_fk_link_positions(
    joint_pos: np.ndarray | Sequence[float],
    *,
    default_joint_pos: Sequence[float] = _UR10E_DEFAULT_Q,
    link_names: Sequence[str] = DEFAULT_ARM_LINK_NAMES,
) -> dict[str, np.ndarray]:
    """Forward kinematics for UR10e arm links in robot-base frame (pure NumPy)."""
    q_rel = np.asarray(joint_pos, dtype=np.float64).reshape(-1)[:6]
    q_abs = np.asarray(default_joint_pos, dtype=np.float64)[:6] + q_rel

    t = np.eye(4, dtype=np.float64)
    positions: dict[str, np.ndarray] = {}
    link_idx = 0
    for i in range(6):
        t = t @ _dh_transform(_UR10E_A[i], _UR10E_ALPHA[i], _UR10E_D[i], q_abs[i])
        if link_idx < len(link_names):
            positions[link_names[link_idx]] = t[:3, 3].copy()
            link_idx += 1
    return positions


def _align_fk_to_world(
    fk_base: dict[str, np.ndarray],
    ee_pos_world: np.ndarray,
    wrist_link_name: str = "wrist_3_link",
) -> dict[str, np.ndarray]:
    """Translate FK base-frame links so wrist_3 matches observed ee_pos (yaw-agnostic v1)."""
    if wrist_link_name not in fk_base:
        return fk_base
    offset = np.asarray(ee_pos_world, dtype=np.float64).reshape(-1)[:3] - fk_base[wrist_link_name]
    return {name: pos + offset for name, pos in fk_base.items()}


# ---------------------------------------------------------------------------
# F2: FK finite-difference velocity for envelope primitives
# ---------------------------------------------------------------------------

# Regex patterns for parsing envelope primitive IDs.
import re as _re
_PRIM_ARM_LINK_RE = _re.compile(r"^arm:([a-z_0-9]+)$")
_PRIM_ARM_INTERP_RE = _re.compile(r"^arm:([a-z_0-9]+)_to_([a-z_0-9]+)@([0-9.]+)$")
# Gripper / held primitives are rigidly attached to the wrist — EE velocity is exact.
_PRIM_WRIST_RIGID_RE = _re.compile(r"^(gripper:|held:)")


def ur10e_primitive_velocity_fd(
    joint_pos: np.ndarray | Sequence[float],
    joint_vel: np.ndarray | Sequence[float],
    primitive_id: str,
    *,
    fd_eps: float = 0.001,
    link_names: Sequence[str] = DEFAULT_ARM_LINK_NAMES,
) -> np.ndarray | None:
    """First-order finite-difference linear velocity of an envelope primitive.

    Uses FK at ``q`` and ``q + ε·q̇`` to compute the velocity of the link
    centroid (or interpolated point) in the robot base frame.  This is
    physically correct to O(ε) for revolute-joint kinematic chains.

    Returns ``None`` when the primitive ID cannot be parsed (gripper / held
    primitives, which are rigidly attached to the wrist and should use EE
    velocity directly).
    """
    q = np.asarray(joint_pos, dtype=np.float64).reshape(-1)[:6]
    qd = np.asarray(joint_vel, dtype=np.float64).reshape(-1)[:6]

    # Gripper / held primitives → use EE velocity (caller handles).
    if _PRIM_WRIST_RIGID_RE.match(primitive_id):
        return None

    # Interpolation primitive: arm:A_to_B@frac.
    m_interp = _PRIM_ARM_INTERP_RE.match(primitive_id)
    if m_interp:
        name_a, name_b, frac_str = m_interp.groups()
        frac = float(frac_str)
        fk0 = ur10e_fk_link_positions(q, link_names=[name_a, name_b])
        fk1 = ur10e_fk_link_positions(q + fd_eps * qd, link_names=[name_a, name_b])
        if name_a not in fk0 or name_b not in fk0:
            return None
        va = (fk1[name_a] - fk0[name_a]) / fd_eps
        vb = (fk1[name_b] - fk0[name_b]) / fd_eps
        return (1.0 - frac) * va + frac * vb

    # Single-link primitive: arm:link_name.
    m_link = _PRIM_ARM_LINK_RE.match(primitive_id)
    if m_link:
        name = m_link.group(1)
        fk0 = ur10e_fk_link_positions(q, link_names=[name])
        fk1 = ur10e_fk_link_positions(q + fd_eps * qd, link_names=[name])
        if name not in fk0:
            return None
        return (fk1[name] - fk0[name]) / fd_eps

    return None


def min_dist_hand_to_links(
    hand_pos: np.ndarray | Sequence[float],
    link_positions: Mapping[str, np.ndarray | Sequence[float]],
    *,
    link_radius: float = 0.05,
    hand_radius: float = 0.05,
) -> float:
    """Minimum center-to-center distance minus combined radii (surface gap proxy)."""
    hand = np.asarray(hand_pos, dtype=np.float64).reshape(-1)[:3]
    min_dist = float("inf")
    for pos in link_positions.values():
        p = np.asarray(pos, dtype=np.float64).reshape(-1)[:3]
        d = float(math.dist(hand.tolist(), p.tolist()))
        min_dist = min(min_dist, d)
    if not math.isfinite(min_dist):
        return float("inf")
    return max(0.0, min_dist - link_radius - hand_radius)


def compute_arm_links_branch(
    state: SafetyState,
    config: SafetyConfig | GtBranchesConfig | None = None,
    *,
    arm_link_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
) -> tuple[float | None, int | None]:
    """Audit branch B: arm link distance GT (log-only)."""
    cfg = config if isinstance(config, GtBranchesConfig) else (config or SafetyConfig()).gt_branches
    if not cfg.arm_links_enabled:
        return None, None

    if isinstance(config, SafetyConfig):
        safety_cfg = config
    else:
        # Fall back to defaults when only GtBranchesConfig is provided.
        safety_cfg = SafetyConfig()
    threshold = collision_threshold_m(
        human_hand_radius=safety_cfg.human_hand_radius,
        ee_radius=safety_cfg.ee_radius,
        collision_threshold=safety_cfg.collision_threshold,
    )

    if arm_link_positions_w:
        link_positions = {
            name: np.asarray(pos, dtype=np.float64).reshape(-1)[:3]
            for name, pos in arm_link_positions_w.items()
        }
    else:
        fk = ur10e_fk_link_positions(state.joint_pos, link_names=cfg.arm_link_names)
        link_positions = _align_fk_to_world(fk, state.ee_pos)

    min_dist = min_dist_hand_to_links(
        state.human_hand_pos,
        link_positions,
        link_radius=cfg.arm_link_radius,
        hand_radius=safety_cfg.human_hand_radius,
    )
    g_gt_arm = int(GateDecision.STOP) if min_dist < threshold else int(GateDecision.ALLOW)
    return min_dist, g_gt_arm


def compute_contact_branch(
    *,
    config: SafetyConfig | GtBranchesConfig | None = None,
    env: Any | None = None,
    env_index: int = 0,
    dist_min_envelope: float | None = None,
) -> tuple[str, str]:
    """Audit branch A: contact detection.

    PhysX contacts are unavailable for kinematic bodies.  When
    ``dist_min_envelope`` is provided, use it as a distance-based proxy:
    ``<= 0`` → contact (surfaces overlap), ``> 0`` → no_contact.
    Otherwise falls back to ``"unknown"``.
    """
    cfg = config if isinstance(config, GtBranchesConfig) else (config or SafetyConfig()).gt_branches
    if not cfg.contact_enabled:
        return "", ""

    # Distance-based proxy (W17): envelope surface gap → contact inference.
    if dist_min_envelope is not None:
        if float(dist_min_envelope) <= 0.0:
            return "contact", "envelope_surface_gap<=0"
        return "no_contact", "envelope_surface_gap>0"

    # PhysX API is unavailable for kinematic bodies — fall back to unknown.
    if env is None:
        return "unknown", ""

    try:
        scene = env.unwrapped.scene
        robot = scene["robot"]
        hand = scene["human_hand"]
        if hasattr(robot, "data") and hasattr(hand, "data"):
            robot_pos = robot.data.root_pos_w[env_index]
            hand_pos = hand.data.root_pos_w[env_index]
            dist = float(np.linalg.norm(robot_pos - hand_pos))
            if dist < 0.5:
                return "unknown", "kinematic_hand_no_physx_contact"
        return "unknown", ""
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return "unknown", ""


def compute_gt_branches(
    state: SafetyState,
    config: SafetyConfig | None = None,
    *,
    arm_link_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
    env: Any | None = None,
    env_index: int = 0,
    dist_min_envelope: float | None = None,
) -> GtBranchResult:
    """Compute all enabled audit branches (never affects g_rule)."""
    cfg = config or SafetyConfig()
    result = GtBranchResult()

    if cfg.gt_branches.arm_links_enabled:
        min_dist, g_gt_arm = compute_arm_links_branch(
            state,
            cfg,
            arm_link_positions_w=arm_link_positions_w,
        )
        result.min_dist_arm_links = min_dist
        result.g_gt_arm = g_gt_arm
        if arm_link_positions_w:
            result.arm_link_positions_used = list(arm_link_positions_w.keys())
        else:
            result.arm_link_positions_used = list(cfg.gt_branches.arm_link_names)

    if cfg.gt_branches.contact_enabled:
        gt_contact, pairs = compute_contact_branch(
            config=cfg,
            env=env,
            env_index=env_index,
            dist_min_envelope=dist_min_envelope,
        )
        result.gt_contact = gt_contact
        result.gt_contact_pairs = pairs

    return result


def recompute_gt_from_row(
    row: Mapping[str, Any],
    config: SafetyConfig | None = None,
) -> tuple[int, float]:
    """Offline GT recompute from CSV row ee_pos / human_hand_pos."""
    import json

    cfg = config or SafetyConfig()

    def _parse_vec(key: str) -> np.ndarray:
        raw = row.get(key, "")
        if isinstance(raw, str) and raw.startswith("["):
            return np.asarray(json.loads(raw), dtype=np.float64)
        return np.asarray(raw, dtype=np.float64).reshape(-1)[:3]

    from .ground_truth import compute_ground_truth

    return compute_ground_truth(
        _parse_vec("ee_pos"),
        _parse_vec("human_hand_pos"),
        human_hand_radius=cfg.human_hand_radius,
        ee_radius=cfg.ee_radius,
        collision_threshold=cfg.collision_threshold,
    )
