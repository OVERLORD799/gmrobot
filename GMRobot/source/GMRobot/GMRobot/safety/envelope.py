"""Full-geometry envelope distance (Phase 2.5a audit; Phase 2.5b gating when enabled).

Computes dist_min across arm links, fingertip spheres, and held-object box.
When ``envelope.gating_enabled`` is true, RuleEngine uses dist_min for static/TTC bands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from .config import EnvelopeConfig, SafetyConfig
from .gt_branches import (
    DEFAULT_ARM_LINK_NAMES,
    _align_fk_to_world,
    ur10e_fk_link_positions,
)
from .types import SafetyState

DEFAULT_FINGERTIP_LINK_NAMES: tuple[str, ...] = (
    "left_outer_finger",
    "right_outer_finger",
)

# MVP held-object fixed box (m): 5 cm × 5 cm × 17 cm along tool axis.
DEFAULT_HELD_BOX_DIMS_M: tuple[float, float, float] = (0.05, 0.05, 0.17)


@dataclass(frozen=True)
class EnvelopePrimitive:
    """Single collision primitive for envelope distance audit."""

    primitive_id: str
    group: str
    pos: np.ndarray
    radius: float


@dataclass
class EnvelopeResult:
    """Envelope distances and closest-primitive metadata.

    ``closest_primitive_pos`` is the 3D world position of the envelope
    primitive closest to the human hand.  When available it allows TTC to
    use envelope-relative (not EE-relative) approach rate, closing the
    tangential-motion blind spot (S7 Option C).
    """

    dist_min_envelope: float
    dist_min_arm: float | None = None
    dist_min_gripper: float | None = None
    dist_min_held: float | None = None
    closest_primitive_id: str = ""
    closest_primitive_pos: np.ndarray | None = None
    primitives_used: list[str] = field(default_factory=list)

    def to_log_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "dist_min_envelope": float(self.dist_min_envelope),
            "closest_primitive_id": self.closest_primitive_id,
        }
        if self.dist_min_arm is not None:
            out["dist_min_arm"] = float(self.dist_min_arm)
        if self.dist_min_gripper is not None:
            out["dist_min_gripper"] = float(self.dist_min_gripper)
        if self.dist_min_held is not None:
            out["dist_min_held"] = float(self.dist_min_held)
        return out


def held_box_bounding_sphere_radius(
    dims_m: Sequence[float] = DEFAULT_HELD_BOX_DIMS_M,
) -> float:
    """Conservative circumscribed-sphere radius for a fixed held-object box."""
    half = [float(d) * 0.5 for d in dims_m]
    return float(math.sqrt(sum(h * h for h in half)))


def surface_gap_sphere(
    hand_pos: np.ndarray | Sequence[float],
    hand_radius: float,
    prim_pos: np.ndarray | Sequence[float],
    prim_radius: float,
) -> float:
    """Center-to-center distance minus combined radii (surface gap proxy)."""
    hand = np.asarray(hand_pos, dtype=np.float64).reshape(-1)[:3]
    pos = np.asarray(prim_pos, dtype=np.float64).reshape(-1)[:3]
    center_dist = float(np.linalg.norm(hand - pos))
    return max(0.0, center_dist - float(hand_radius) - float(prim_radius))


def compute_min_dist(
    hand_pos: np.ndarray | Sequence[float],
    hand_radius: float,
    primitives: Sequence[EnvelopePrimitive],
) -> tuple[float, str, dict[str, float], np.ndarray | None]:
    """Return (global min gap, closest primitive id, per-group mins, closest pos)."""
    if not primitives:
        return float("inf"), "", {}, None

    group_mins: dict[str, float] = {}
    closest_id = ""
    closest_pos = None
    dist_min = float("inf")

    for prim in primitives:
        gap = surface_gap_sphere(hand_pos, hand_radius, prim.pos, prim.radius)
        group_mins[prim.group] = min(group_mins.get(prim.group, float("inf")), gap)
        if gap < dist_min:
            dist_min = gap
            closest_id = prim.primitive_id
            closest_pos = prim.pos.copy()

    return dist_min, closest_id, group_mins, closest_pos


class EnvelopeEvaluator:
    """Build envelope primitives and compute audit distances each control step."""

    def __init__(self, config: SafetyConfig | EnvelopeConfig | None = None):
        if isinstance(config, EnvelopeConfig):
            self._cfg = config
            self._hand_radius = SafetyConfig().human_hand_radius
        else:
            safety_cfg = config or SafetyConfig()
            self._cfg = safety_cfg.envelope
            self._hand_radius = safety_cfg.human_hand_radius

    def build_primitives(
        self,
        state: SafetyState,
        *,
        arm_link_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
        fingertip_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
        held_object_active: bool = False,
        held_part_pose: np.ndarray | None = None,
    ) -> list[EnvelopePrimitive]:
        """Assemble arm / gripper / held primitives for the current step.

        When ``held_part_pose`` is provided (7D ``[x,y,z,qw,qx,qy,qz]``), the
        held-box sphere is centred on the **part's** rigid-body position rather
        than the EE position.  This removes the EE→part offset error from
        ``dist_min_held``, improving knock-detection accuracy.
        """
        cfg = self._cfg
        primitives: list[EnvelopePrimitive] = []

        arm_positions = self._resolve_arm_positions(state, arm_link_positions_w)
        for name in cfg.arm_link_names:
            if name not in arm_positions:
                continue
            primitives.append(
                EnvelopePrimitive(
                    primitive_id=f"arm:{name}",
                    group="arm",
                    pos=np.asarray(arm_positions[name], dtype=np.float64).reshape(-1)[:3],
                    radius=cfg.arm_link_radius,
                )
            )

        # D3: 3 interpolation spheres between consecutive arm links.
        # Closes centroid-only gaps (e.g. forearm→wrist_1, ~0.2m uncovered).
        _link_names = cfg.arm_link_names
        for i in range(len(_link_names) - 1):
            a_name, b_name = _link_names[i], _link_names[i + 1]
            if a_name not in arm_positions or b_name not in arm_positions:
                continue
            a = np.asarray(arm_positions[a_name], dtype=np.float64).reshape(-1)[:3]
            b = np.asarray(arm_positions[b_name], dtype=np.float64).reshape(-1)[:3]
            for frac in (0.25, 0.50, 0.75):
                mid = a + frac * (b - a)
                primitives.append(
                    EnvelopePrimitive(
                        primitive_id=f"arm:{a_name}_to_{b_name}@{frac:.2f}",
                        group="arm",
                        pos=mid,
                        radius=cfg.arm_link_radius,
                    )
                )

        if fingertip_positions_w:
            for name in cfg.fingertip_link_names:
                if name not in fingertip_positions_w:
                    continue
                primitives.append(
                    EnvelopePrimitive(
                        primitive_id=f"gripper:{name}",
                        group="gripper",
                        pos=np.asarray(
                            fingertip_positions_w[name], dtype=np.float64
                        ).reshape(-1)[:3],
                        radius=cfg.fingertip_radius,
                    )
                )

        # Optional human torso primitive (W17).
        if hasattr(state, "has_torso") and state.has_torso:
            torso_pos = np.asarray(state.human_torso_pos, dtype=np.float64).reshape(-1)[:3]
            torso_radius = float(getattr(self._cfg, "human_torso_radius", 0.0) or 0.0)
            if torso_radius > 0.0:
                primitives.append(
                    EnvelopePrimitive(
                        primitive_id="human:torso",
                        group="arm",  # same group as arm links for gating purposes
                        pos=torso_pos.copy(),
                        radius=torso_radius,
                    )
                )

        if held_object_active:
            held_center = np.asarray(state.ee_pos, dtype=np.float64).reshape(-1)[:3].copy()
            held_radius = cfg.effective_held_box_radius()

            if held_part_pose is not None and len(held_part_pose) >= 7:
                # Use the part's actual rigid-body position (not EE) for the
                # sphere centre — removes the EE→part offset error.
                part_arr = np.asarray(held_part_pose, dtype=np.float64).reshape(-1)
                part_center = part_arr[:3].copy()
                part_quat = part_arr[3:7].copy()  # scalar-first [qw,qx,qy,qz]

                # Build 3 smaller spheres along the part's local Z axis
                # (the 17 cm dimension) so the collision boundary is tighter
                # and direction-aware.  Each sphere covers a ~5.7 cm segment
                # with overlap to avoid gaps.
                # Deferred import: this code path is only reached when a held part
                # pose is passed at runtime (gripper_closed window).  Other callers
                # of envelope.py (config loading, audit-only paths) do not need scipy.
                try:
                    from scipy.spatial.transform import Rotation as _R
                except ImportError:
                    raise ImportError(
                        "scipy is required for held-part pose envelope computation. "
                        "Install with: pip install scipy"
                    )
                half_z = float(cfg.held_box_dims_m[2]) * 0.5  # 0.085 m
                spacing = half_z * 2.0 / 3.0  # 3 spheres → ~5.67 cm spacing
                # Radius must cover half the XY face plus the spacing segment.
                half_xy = max(float(cfg.held_box_dims_m[0]), float(cfg.held_box_dims_m[1])) * 0.5  # 0.025 m
                seg_radius = float(math.sqrt(half_xy**2 + half_xy**2 + (spacing * 0.5)**2))

                rot = _R.from_quat(part_quat, scalar_first=True)
                offsets_local = np.array([
                    [0.0, 0.0, 0.0],
                    [0.0, 0.0, spacing],
                    [0.0, 0.0, -spacing],
                ], dtype=np.float64)
                offsets_world = rot.apply(offsets_local)
                for i, offset in enumerate(offsets_world):
                    primitives.append(
                        EnvelopePrimitive(
                            primitive_id=f"held:box_seg{i}" if i > 0 else "held:box_center",
                            group="held",
                            pos=part_center + offset,
                            radius=float(seg_radius),
                        )
                    )
            else:
                # Fallback: single sphere at EE position (legacy behaviour).
                primitives.append(
                    EnvelopePrimitive(
                        primitive_id="held:fixed_box",
                        group="held",
                        pos=held_center,
                        radius=held_radius,
                    )
                )

        return primitives

    def evaluate(
        self,
        state: SafetyState,
        *,
        arm_link_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
        fingertip_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
        held_object_active: bool = False,
        held_part_pose: np.ndarray | None = None,
    ) -> EnvelopeResult:
        """Compute envelope distances for logging and optional gating (2.5b)."""
        primitives = self.build_primitives(
            state,
            arm_link_positions_w=arm_link_positions_w,
            fingertip_positions_w=fingertip_positions_w,
            held_object_active=held_object_active,
            held_part_pose=held_part_pose,
        )
        dist_min, closest_id, group_mins, closest_pos = compute_min_dist(
            state.human_hand_pos,
            self._hand_radius,
            primitives,
        )
        return EnvelopeResult(
            dist_min_envelope=dist_min,
            dist_min_arm=group_mins.get("arm"),
            dist_min_gripper=group_mins.get("gripper"),
            dist_min_held=group_mins.get("held"),
            closest_primitive_id=closest_id,
            closest_primitive_pos=closest_pos,
            primitives_used=[p.primitive_id for p in primitives],
        )

    def _resolve_arm_positions(
        self,
        state: SafetyState,
        arm_link_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None,
    ) -> dict[str, np.ndarray]:
        resolved: dict[str, np.ndarray] = {}
        if arm_link_positions_w:
            for name, pos in arm_link_positions_w.items():
                resolved[name] = np.asarray(pos, dtype=np.float64).reshape(-1)[:3]

        missing = [name for name in self._cfg.arm_link_names if name not in resolved]
        if not missing:
            return resolved

        fk = ur10e_fk_link_positions(
            state.joint_pos,
            link_names=self._cfg.arm_link_names,
        )
        aligned = _align_fk_to_world(fk, state.ee_pos)
        for name in missing:
            if name in aligned:
                resolved[name] = aligned[name].copy()
        return resolved


def compute_envelope_audit(
    state: SafetyState,
    config: SafetyConfig | None = None,
    *,
    arm_link_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
    fingertip_positions_w: Mapping[str, np.ndarray | Sequence[float]] | None = None,
    held_object_active: bool = False,
    held_part_pose: np.ndarray | None = None,
) -> EnvelopeResult:
    """Functional wrapper used by runtime and offline scripts."""
    return EnvelopeEvaluator(config).evaluate(
        state,
        arm_link_positions_w=arm_link_positions_w,
        fingertip_positions_w=fingertip_positions_w,
        held_object_active=held_object_active,
        held_part_pose=held_part_pose,
    )
