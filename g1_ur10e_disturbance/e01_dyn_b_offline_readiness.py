"""E01-Dyn-B offline readiness helpers (no Isaac / no POST)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from scene_camera_override import E01_DYN_A_SCENE_CAMERA_POS, E01_DYN_A_SCENE_CAMERA_ROT, project_world_to_pixel

E01_DYN_B_SCENE = "E01-Dyn-B"
E01_DYN_B_SCENARIO = "outer_lateral_patrol"
E01_DYN_B_SEED = 43
E01_DYN_B_CAPTURE_STEPS: tuple[int, int] = (220, 330)
E01_DYN_B_GEOMETRY_WINDOW: tuple[int, int] = (190, 340)
E01_DYN_B_MOTION_SOURCE = "scripted_g1_outer_lateral_patrol"
E01_DYN_B_EVIDENCE_KIND = "synthetic_scripted_motion_evidence"
E01_DYN_B_PROVENANCE = {
    "motion_source": E01_DYN_B_MOTION_SOURCE,
    "evidence": E01_DYN_B_EVIDENCE_KIND,
    "not_human_hand_or_ppe": True,
    "not_vlm_output": True,
    "red_ball_proxy": False,
}

DEFAULT_CONTROL_DT = 0.02
G1_INIT_XY = (-1.5, 0.0)
UR10E_ENVELOPE_CENTER_XY = (0.75, 0.0)
UR10E_ENVELOPE_RADIUS_M = 0.55
G1_BODY_RADIUS_M = 0.35
TRAJECTORY_UNCERTAINTY_M = 0.10
MIN_EXTRA_SEPARATION_M = 0.10
MIN_CAPTURE_DISPLACEMENT_PX = 20.0


@dataclass(frozen=True)
class Phase:
    name: str
    duration_steps: int
    vx: float
    vy: float
    wz: float = 0.0


OUTER_LATERAL_PATROL_PHASES: tuple[Phase, ...] = (
    Phase("approach_outer_lane", 140, 0.34, 0.00, 0.0),
    Phase("settle_heading", 20, 0.04, 0.00, 0.0),
    Phase("lateral_positive_sweep", 90, 0.02, 0.22, 0.0),
    Phase("lateral_negative_sweep", 90, -0.02, -0.22, 0.0),
    Phase("retreat_outer_lane", 80, -0.32, 0.00, 0.0),
    Phase("idle", 9999, 0.0, 0.0, 0.0),
)


def phase_at_step(step: int) -> Phase:
    s = int(step)
    if s <= 0:
        return OUTER_LATERAL_PATROL_PHASES[-1]
    acc = 0
    for ph in OUTER_LATERAL_PATROL_PHASES:
        acc += ph.duration_steps
        if s <= acc:
            return ph
    return OUTER_LATERAL_PATROL_PHASES[-1]


def trajectory_xy(step: int, *, dt: float = DEFAULT_CONTROL_DT, init_xy: Sequence[float] = G1_INIT_XY) -> tuple[float, float]:
    """Integrate scripted planar trajectory up to inclusive `step`."""
    x, y = float(init_xy[0]), float(init_xy[1])
    s = max(0, int(step))
    rem = s
    for ph in OUTER_LATERAL_PATROL_PHASES:
        if rem <= 0:
            break
        n = min(rem, ph.duration_steps)
        x += ph.vx * dt * n
        y += ph.vy * dt * n
        rem -= n
    return x, y


def conservative_center_distance_to_envelope(xy: Sequence[float]) -> float:
    dx = float(xy[0]) - UR10E_ENVELOPE_CENTER_XY[0]
    dy = float(xy[1]) - UR10E_ENVELOPE_CENTER_XY[1]
    return math.hypot(dx, dy)


def conservative_separation_margin_m(xy: Sequence[float]) -> float:
    center_dist = conservative_center_distance_to_envelope(xy)
    inflated = UR10E_ENVELOPE_RADIUS_M + G1_BODY_RADIUS_M + TRAJECTORY_UNCERTAINTY_M
    return center_dist - inflated


def build_body_points_from_root(root_xy: Sequence[float]) -> list[tuple[float, float, float]]:
    x, y = float(root_xy[0]), float(root_xy[1])
    return [
        (x, y, 0.95),
        (x, y + 0.18, 0.85),
        (x, y - 0.18, 0.85),
        (x + 0.10, y + 0.25, 0.75),
        (x + 0.10, y - 0.25, 0.75),
    ]


def estimate_centroid_uv(root_xy: Sequence[float], cam_pos: Sequence[float] = E01_DYN_A_SCENE_CAMERA_POS) -> tuple[float, float] | None:
    pts = build_body_points_from_root(root_xy)
    pix = []
    for p in pts:
        uv = project_world_to_pixel(p, cam_pos=cam_pos)
        if uv is not None:
            pix.append(uv)
    if not pix:
        return None
    u = sum(p[0] for p in pix) / len(pix)
    v = sum(p[1] for p in pix) / len(pix)
    return float(u), float(v)


def visibility_assumption_ok(root_xy: Sequence[float], cam_pos: Sequence[float] = E01_DYN_A_SCENE_CAMERA_POS) -> bool:
    c = estimate_centroid_uv(root_xy, cam_pos=cam_pos)
    if c is None:
        return False
    u, v = c
    return 40.0 <= u <= 600.0 and 40.0 <= v <= 440.0


def predicted_capture_displacement_px(
    *,
    steps: Sequence[int] = E01_DYN_B_CAPTURE_STEPS,
    cam_pos: Sequence[float] = E01_DYN_A_SCENE_CAMERA_POS,
) -> float | None:
    if len(steps) < 2:
        return None
    r0 = trajectory_xy(int(steps[0]))
    r1 = trajectory_xy(int(steps[1]))
    c0 = estimate_centroid_uv(r0, cam_pos=cam_pos)
    c1 = estimate_centroid_uv(r1, cam_pos=cam_pos)
    if c0 is None or c1 is None:
        return None
    return math.hypot(c1[0] - c0[0], c1[1] - c0[1])


def capture_steps_inside_moving_phase(steps: Sequence[int] = E01_DYN_B_CAPTURE_STEPS) -> bool:
    for st in steps:
        ph = phase_at_step(int(st))
        if abs(ph.vx) + abs(ph.vy) <= 1e-6:
            return False
    return True


def geometry_precheck() -> dict[str, Any]:
    lo, hi = E01_DYN_B_GEOMETRY_WINDOW
    min_margin = None
    min_step = None
    for st in range(lo, hi + 1):
        xy = trajectory_xy(st)
        margin = conservative_separation_margin_m(xy)
        if min_margin is None or margin < min_margin:
            min_margin = margin
            min_step = st
    assert min_margin is not None and min_step is not None
    return {
        "ok": bool(min_margin >= MIN_EXTRA_SEPARATION_M),
        "window": [lo, hi],
        "min_step": int(min_step),
        "min_separation_margin_m": float(min_margin),
        "required_margin_m": float(MIN_EXTRA_SEPARATION_M),
        "envelope": {
            "center_xy": list(UR10E_ENVELOPE_CENTER_XY),
            "ur10e_radius_m": UR10E_ENVELOPE_RADIUS_M,
            "g1_body_radius_m": G1_BODY_RADIUS_M,
            "trajectory_uncertainty_m": TRAJECTORY_UNCERTAINTY_M,
        },
    }


def default_off_flags_ok(enable_capture: bool, execute_capture: bool) -> bool:
    return (not bool(enable_capture)) and (not bool(execute_capture))


def no_red_proxy_ok(*, virtual_hand: bool, mention_red_ball: bool) -> bool:
    return (not virtual_hand) and (not mention_red_ball)


def select_capture_steps() -> dict[str, Any]:
    s0, s1 = E01_DYN_B_CAPTURE_STEPS
    ph0, ph1 = phase_at_step(s0), phase_at_step(s1)
    disp = predicted_capture_displacement_px(steps=(s0, s1))
    return {
        "steps": [s0, s1],
        "phase_names": [ph0.name, ph1.name],
        "phase_vxy": [[ph0.vx, ph0.vy], [ph1.vx, ph1.vy]],
        "predicted_displacement_px": disp,
        "inside_moving_phase": capture_steps_inside_moving_phase((s0, s1)),
        "meets_displacement_gate": bool(disp is not None and disp >= MIN_CAPTURE_DISPLACEMENT_PX),
    }


def full_readiness_report(*, enable_capture: bool = False, execute_capture: bool = False) -> dict[str, Any]:
    geo = geometry_precheck()
    sel = select_capture_steps()
    roots = [trajectory_xy(s) for s in E01_DYN_B_CAPTURE_STEPS]
    vis_ok = all(visibility_assumption_ok(r) for r in roots)
    ok = (
        default_off_flags_ok(enable_capture=enable_capture, execute_capture=execute_capture)
        and no_red_proxy_ok(virtual_hand=False, mention_red_ball=False)
        and geo["ok"]
        and sel["inside_moving_phase"]
        and sel["meets_displacement_gate"]
        and vis_ok
    )
    verdict = "GO_PRECHECK_ONLY" if ok else "NO_GO"
    return {
        "scene": E01_DYN_B_SCENE,
        "scenario": E01_DYN_B_SCENARIO,
        "seed": E01_DYN_B_SEED,
        "camera_pose": {"pos": list(E01_DYN_A_SCENE_CAMERA_POS), "rot": list(E01_DYN_A_SCENE_CAMERA_ROT)},
        "provenance": dict(E01_DYN_B_PROVENANCE),
        "default_off": {
            "enable_capture": bool(enable_capture),
            "execute_capture": bool(execute_capture),
            "ok": default_off_flags_ok(enable_capture, execute_capture),
        },
        "geometry_precheck": geo,
        "capture_selection": sel,
        "predicted_roots_xy": [list(r) for r in roots],
        "visibility_assumption_ok": vis_ok,
        "verdict": verdict,
    }


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
