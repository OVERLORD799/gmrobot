"""Held-aware detour strategy selection (Phase 4a v2, ADR §12 addendum).

Visual inspection (fast_sweep v2 @ step 640): upward dodge can knock held parts off
when the held-box envelope protrudes toward the hand. v2 replan considers held
primitive geometry, workspace Z headroom, and picks among multiple splice patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

# Re-exported from envelope.py — single source of truth for held-box geometry.
from ..envelope import DEFAULT_HELD_BOX_DIMS_M  # noqa: F401 (re-export)

# Workspace ceiling used by scripted policy transit (m).
# R7: raised from 0.75 → 0.90 to allow high vertical detours over virtual hand.
WORKSPACE_Z_MAX_M = 0.90

# Held envelope tighter than EE → boost lateral / pick retreat arc.
HELD_TIGHT_DIST_M = 0.12
HELD_CRITICAL_DEFER_M = 0.10

# Prefer lateral-first when little room to raise without hitting z_max.
Z_HEADROOM_LATERAL_FIRST_M = 0.08
# R7: when headroom is ample, RAISE_HIGH wins — go OVER the obstacle entirely.
Z_HEADROOM_RAISE_HIGH_M = 0.25

# Extra lateral when held is the closest primitive (m).
HELD_CLOSEST_LATERAL_BOOST_M = 0.05

# retreat_then_arc: short XY retreat opposite hand before smaller raise.
RETREAT_DIST_M = 0.06
RETREAT_RAISE_SCALE = 0.55

# Fast hand radial approach (m/s): boost lateral / retreat before Tier0 held_critical STOP.
HAND_SPEED_FAST_MPS = 0.15
HAND_SPEED_LATERAL_BONUS = 0.75
HAND_SPEED_RETREAT_BONUS = 0.50

# S13 P1: SAM2 /track speed/direction bonus thresholds (image-space px/s, degrees).
PERCEPTION_TRACK_SPEED_FAST_PX_S = 20.0
PERCEPTION_TRACK_LATERAL_SWEEP_DEG_MIN = 45.0
PERCEPTION_TRACK_LATERAL_SWEEP_DEG_MAX = 135.0
PERCEPTION_TRACK_SPEED_BONUS = 0.75
PERCEPTION_TRACK_LATERAL_SWEEP_BONUS = 0.50
PERCEPTION_TRACK_INWARD_BONUS = 0.50


class DetourStrategy(str, Enum):
    """Splice waypoint ordering for geometry replan v2."""

    RAISE_THEN_LATERAL = "raise_then_lateral"
    LATERAL_FIRST = "lateral_first"
    RETREAT_THEN_ARC = "retreat_then_arc"
    RAISE_HIGH = "raise_high"  # R7: vertical clearance over obstacle (headroom >= 0.25m)


@dataclass(frozen=True)
class DetourPlan:
    """Resolved detour parameters passed to policy splice."""

    strategy: DetourStrategy
    raise_m: float
    lateral_m: float
    retreat_m: float = 0.0
    lateral_first_raise_m: float = 0.02
    score: float = 0.0
    reason: str = ""


def _away_xy(ee_xy: np.ndarray, hand_xy: np.ndarray) -> np.ndarray:
    delta = ee_xy - hand_xy
    norm = float(np.linalg.norm(delta))
    if norm < 1e-6:
        return np.array([0.0, 1.0], dtype=np.float32)
    return (delta / norm).astype(np.float32)


def held_protrusion_toward_hand_m(
    ee_pos: np.ndarray | tuple[float, float, float],
    human_hand_pos: np.ndarray | tuple[float, float, float],
    *,
    held_dims_m: tuple[float, float, float] = DEFAULT_HELD_BOX_DIMS_M,
) -> float:
    """Conservative held-box extent toward the hand along XY (tool-axis box MVP).

    Uses circumscribed horizontal radius plus vertical half-extent projected when
    the hand is below the EE (typical carry pose).
    """
    ee = np.asarray(ee_pos, dtype=np.float64).reshape(-1)[:3]
    hand = np.asarray(human_hand_pos, dtype=np.float64).reshape(-1)[:3]
    half_xy = max(float(held_dims_m[0]), float(held_dims_m[1])) * 0.5
    half_z = float(held_dims_m[2]) * 0.5
    horiz = float(np.linalg.norm(ee[:2] - hand[:2]))
    # When hand is under the carried box, raising sweeps the lower face toward hand.
    vert_overlap = max(0.0, (ee[2] - half_z) - hand[2])
    if horiz < 1e-6:
        return half_xy + half_z
    return half_xy + min(half_z, vert_overlap * 0.5)


def scale_raise_for_headroom(ee_z: float, raise_m: float, z_max: float = WORKSPACE_Z_MAX_M) -> float:
    headroom = z_max - float(ee_z)
    if headroom <= 0.0:
        return 0.0
    return min(float(raise_m), max(0.0, headroom - 0.01))


def adjust_lateral_for_held(
    lateral_m: float,
    *,
    dist_min_held: float | None,
    closest_primitive_id: str | None,
    protrusion_m: float,
) -> float:
    out = float(lateral_m)
    if closest_primitive_id and closest_primitive_id.startswith("held:"):
        out += HELD_CLOSEST_LATERAL_BOOST_M
    if dist_min_held is not None and float(dist_min_held) < HELD_TIGHT_DIST_M:
        tightness = (HELD_TIGHT_DIST_M - float(dist_min_held)) / HELD_TIGHT_DIST_M
        out += HELD_CLOSEST_LATERAL_BOOST_M * min(1.0, max(0.0, tightness))
    out += min(protrusion_m * 0.25, 0.04)
    return out


def perception_track_strategy_bonus(
    *,
    enabled: bool,
    speed_px_s: float | None,
    direction_deg: float | None,
) -> tuple[float, float, str]:
    """Bonus scores for lateral_first vs retreat_then_arc from /track kinematics."""
    if not enabled or speed_px_s is None:
        return 0.0, 0.0, ""

    lateral_bonus = 0.0
    retreat_bonus = 0.0
    parts: list[str] = []

    if float(speed_px_s) >= PERCEPTION_TRACK_SPEED_FAST_PX_S:
        lateral_bonus += PERCEPTION_TRACK_SPEED_BONUS
        parts.append(f"track_speed={float(speed_px_s):.1f}px/s")

    if direction_deg is not None:
        d = ((float(direction_deg) + 180.0) % 360.0) - 180.0
        if (
            PERCEPTION_TRACK_LATERAL_SWEEP_DEG_MIN
            <= abs(d)
            <= PERCEPTION_TRACK_LATERAL_SWEEP_DEG_MAX
        ):
            lateral_bonus += PERCEPTION_TRACK_LATERAL_SWEEP_BONUS
            parts.append(f"track_lateral_sweep dir={d:.0f}°")
        else:
            retreat_bonus += PERCEPTION_TRACK_INWARD_BONUS
            parts.append(f"track_inward dir={d:.0f}°")

    return lateral_bonus, retreat_bonus, ";".join(parts)


def select_detour_strategy(
    *,
    transport_phase: str,
    ee_z: float,
    raise_m: float,
    lateral_m: float,
    dist_min_held: float | None = None,
    closest_primitive_id: str | None = None,
    hand_speed: float = 0.0,
    trigger_rule: str = "static_warn",
    z_max: float = WORKSPACE_Z_MAX_M,
    ee_pos: tuple[float, float, float] | None = None,
    human_hand_pos: tuple[float, float, float] | None = None,
    use_perception_track_strategy: bool = False,
    perception_track_speed_px_s: float | None = None,
    perception_track_direction_deg: float | None = None,
) -> DetourPlan:
    """Score candidate strategies; return best held-aware detour plan.

    Scoring (higher wins):
    - lateral_first when z headroom < 0.08 m (avoid knock-off from raise-first)
    - retreat_then_arc when held is closest / dist_min_held tight
    - raise_then_lateral default for transit with ample headroom
    """
    headroom = z_max - float(ee_z)
    scaled_raise = scale_raise_for_headroom(ee_z, raise_m, z_max)

    protrusion = 0.0
    if ee_pos is not None and human_hand_pos is not None:
        protrusion = held_protrusion_toward_hand_m(ee_pos, human_hand_pos)

    adj_lateral = adjust_lateral_for_held(
        lateral_m,
        dist_min_held=dist_min_held,
        closest_primitive_id=closest_primitive_id,
        protrusion_m=protrusion,
    )

    held_is_closest = bool(
        closest_primitive_id and closest_primitive_id.startswith("held:")
    )
    held_tight = (
        dist_min_held is not None and float(dist_min_held) < HELD_TIGHT_DIST_M
    )

    scores: dict[DetourStrategy, float] = {
        DetourStrategy.RAISE_THEN_LATERAL: 1.0,
        DetourStrategy.LATERAL_FIRST: 0.5,
        DetourStrategy.RETREAT_THEN_ARC: 0.5,
    }
    reasons: dict[DetourStrategy, str] = {
        DetourStrategy.RAISE_THEN_LATERAL: "default",
        DetourStrategy.LATERAL_FIRST: "default",
        DetourStrategy.RETREAT_THEN_ARC: "default",
    }

    # R7: when headroom is ample (hand is below EE operating ceiling),
    # prefer RAISE_HIGH — go OVER the obstacle entirely rather than around it.
    # Exceptions:
    #   - Held object at risk (closest or tight) → raising risks knock-off.
    #   - TTC / ttc_forecast → time-critical; immediate lateral movement needed.
    if (
        headroom >= Z_HEADROOM_RAISE_HIGH_M
        and not (held_is_closest or held_tight)
        and trigger_rule not in ("ttc", "ttc_forecast")
    ):
        scores[DetourStrategy.RAISE_THEN_LATERAL] += 4.0
        reasons[DetourStrategy.RAISE_THEN_LATERAL] = f"raise_high:headroom={headroom:.3f}m"
        scores[DetourStrategy.LATERAL_FIRST] -= 1.0
        scores[DetourStrategy.RETREAT_THEN_ARC] -= 1.0
    elif headroom < Z_HEADROOM_LATERAL_FIRST_M:
        scores[DetourStrategy.LATERAL_FIRST] += 2.5
        reasons[DetourStrategy.LATERAL_FIRST] = f"z_headroom={headroom:.3f}m"
        scores[DetourStrategy.RAISE_THEN_LATERAL] -= 1.5

    if scaled_raise < raise_m * 0.5:
        scores[DetourStrategy.LATERAL_FIRST] += 1.0
        scores[DetourStrategy.RAISE_THEN_LATERAL] -= 0.5

    if held_is_closest or held_tight:
        scores[DetourStrategy.RETREAT_THEN_ARC] += 2.0
        reasons[DetourStrategy.RETREAT_THEN_ARC] = (
            f"held_closest={held_is_closest} dist_min_held={dist_min_held}"
        )
        scores[DetourStrategy.RAISE_THEN_LATERAL] -= 1.0

    if transport_phase == "place":
        scores[DetourStrategy.LATERAL_FIRST] += 0.5
        scores[DetourStrategy.RAISE_THEN_LATERAL] -= 0.5
        scaled_raise = min(scaled_raise, raise_m * 0.5)
        adj_lateral = min(adj_lateral, lateral_m)

    if trigger_rule in (
        "ttc",
        "ttc_forecast",
        "held_critical_early",
        "route_conflict",
    ) and hand_speed >= 0.05:
        scores[DetourStrategy.LATERAL_FIRST] += 0.75
        reasons[DetourStrategy.LATERAL_FIRST] = f"{trigger_rule} hand_speed={hand_speed:.2f}"

    if hand_speed >= HAND_SPEED_FAST_MPS:
        if (held_is_closest or held_tight) and transport_phase == "transit":
            scores[DetourStrategy.RETREAT_THEN_ARC] += (
                HAND_SPEED_LATERAL_BONUS + HAND_SPEED_RETREAT_BONUS + 0.5
            )
            scores[DetourStrategy.LATERAL_FIRST] -= 0.75
            reasons[DetourStrategy.RETREAT_THEN_ARC] = (
                f"fast_hand={hand_speed:.2f} held_closest={held_is_closest} transit_carry"
            )
        else:
            scores[DetourStrategy.LATERAL_FIRST] += HAND_SPEED_LATERAL_BONUS
            scores[DetourStrategy.RETREAT_THEN_ARC] += HAND_SPEED_RETREAT_BONUS
            if held_is_closest or held_tight:
                scores[DetourStrategy.RETREAT_THEN_ARC] += 0.5
                reasons[DetourStrategy.RETREAT_THEN_ARC] = (
                    f"fast_hand={hand_speed:.2f} held_closest={held_is_closest}"
                )
            elif reasons[DetourStrategy.LATERAL_FIRST] == "default":
                reasons[DetourStrategy.LATERAL_FIRST] = f"fast_hand={hand_speed:.2f}"

    track_lat, track_ret, track_reason = perception_track_strategy_bonus(
        enabled=use_perception_track_strategy,
        speed_px_s=perception_track_speed_px_s,
        direction_deg=perception_track_direction_deg,
    )
    if track_lat or track_ret:
        if not (held_is_closest or held_tight):
            scores[DetourStrategy.LATERAL_FIRST] += track_lat
            scores[DetourStrategy.RETREAT_THEN_ARC] += track_ret
            if track_lat >= track_ret:
                reasons[DetourStrategy.LATERAL_FIRST] = (
                    f"{reasons[DetourStrategy.LATERAL_FIRST]};{track_reason}".strip(";")
                )
            else:
                reasons[DetourStrategy.RETREAT_THEN_ARC] = (
                    f"{reasons[DetourStrategy.RETREAT_THEN_ARC]};{track_reason}".strip(";")
                )

    # max() on dict returns the first key with the highest value in insertion
    # order (Python 3.7+).  Insertion order is RAISE_THEN_LATERAL, LATERAL_FIRST,
    # RETREAT_THEN_ARC — so RAISE_THEN_LATERAL wins ties by design (it is the
    # safest default: raise first avoids knocking the held box into the hand).
    best = max(scores, key=scores.get)
    return DetourPlan(
        strategy=best,
        raise_m=scaled_raise,
        lateral_m=adj_lateral,
        retreat_m=RETREAT_DIST_M if best == DetourStrategy.RETREAT_THEN_ARC else 0.0,
        lateral_first_raise_m=min(0.03, scaled_raise) if best == DetourStrategy.LATERAL_FIRST else 0.02,
        score=scores[best],
        reason=reasons[best],
    )


# Waypoint geometry lives in scripts/pick_and_place_policy._build_detour_waypoints
# (Isaac script layer; avoids circular deps with the sim policy).


def should_defer_for_held_critical(
    transport_phase: str,
    dist_min_held: float | None,
    *,
    threshold_m: float = HELD_CRITICAL_DEFER_M,
) -> bool:
    """Defer geometric splice when held envelope is critically tight in place phase."""
    if transport_phase != "place":
        return False
    if dist_min_held is None:
        return False
    return float(dist_min_held) < threshold_m
