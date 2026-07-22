"""Scene camera pose override helpers (pure; no Isaac import).

Default Dual scene camera remains (1.0, 0.0, 3.0). Override is opt-in via env:

  GMDISTURB_SCENE_CAMERA_OVERRIDE=1
  GMDISTURB_SCENE_CAMERA_POS=0.2,0.0,3.2
  GMDISTURB_SCENE_CAMERA_ROT=0.7071,0.0,0.7071,0.0

When OVERRIDE is unset/false, callers must use DEFAULT_* and ignore POS/ROT env.
"""

from __future__ import annotations

import os
from typing import Sequence

DEFAULT_SCENE_CAMERA_POS: tuple[float, float, float] = (1.0, 0.0, 3.0)
DEFAULT_SCENE_CAMERA_ROT: tuple[float, float, float, float] = (0.7071, 0.0, 0.7071, 0.0)

# E01-Dyn-A recommended pose (documentation constant; applied only when override on).
E01_DYN_A_SCENE_CAMERA_POS: tuple[float, float, float] = (0.2, 0.0, 3.2)
E01_DYN_A_SCENE_CAMERA_ROT: tuple[float, float, float, float] = (0.7071, 0.0, 0.7071, 0.0)

MOTION_SOURCE_ARM_WAVE = "scripted_g1_locomotion_arm_wave"
E01_DYN_A_CAPTURE_STEPS: tuple[int, ...] = (210, 280)
E01_DYN_A_SEED = 42
E01_DYN_A_SCENARIO = "arm_wave"


def _truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def scene_camera_override_enabled(env: dict[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return _truthy(e.get("GMDISTURB_SCENE_CAMERA_OVERRIDE"))


def _parse_floats(raw: str, *, n: int, label: str) -> tuple[float, ...]:
    parts = [p.strip() for p in str(raw).split(",") if p.strip() != ""]
    if len(parts) != n:
        raise ValueError(f"{label} expects {n} comma-separated floats, got {len(parts)}: {raw!r}")
    return tuple(float(p) for p in parts)


def resolve_scene_camera_pose(
    env: dict[str, str] | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """Return (pos, rot). Default Dual pose unless override enabled."""
    e = os.environ if env is None else env
    if not scene_camera_override_enabled(e):
        return DEFAULT_SCENE_CAMERA_POS, DEFAULT_SCENE_CAMERA_ROT
    pos_raw = e.get("GMDISTURB_SCENE_CAMERA_POS", "").strip()
    rot_raw = e.get("GMDISTURB_SCENE_CAMERA_ROT", "").strip()
    if not pos_raw or not rot_raw:
        raise ValueError(
            "GMDISTURB_SCENE_CAMERA_OVERRIDE=1 requires "
            "GMDISTURB_SCENE_CAMERA_POS and GMDISTURB_SCENE_CAMERA_ROT"
        )
    pos = _parse_floats(pos_raw, n=3, label="GMDISTURB_SCENE_CAMERA_POS")
    rot = _parse_floats(rot_raw, n=4, label="GMDISTURB_SCENE_CAMERA_ROT")
    return (float(pos[0]), float(pos[1]), float(pos[2])), (
        float(rot[0]),
        float(rot[1]),
        float(rot[2]),
        float(rot[3]),
    )


def arm_wave_phase_at_step(step: int) -> str:
    """Map 0-based or 1-based controller step to ARM_WAVE phase name.

    Controllers advance after each update; E01 capture steps 210/280 are
    interpreted on the cumulative duration table (approach 150, settle 60,
    stand 150, retreat 80, idle).
    """
    s = int(step)
    if s <= 0:
        return "idle"
    if s <= 150:
        return "approach"
    if s <= 210:
        return "settle"
    if s <= 360:
        return "stand"
    if s <= 440:
        return "retreat"
    return "idle"


def project_world_to_pixel(
    xyz: Sequence[float],
    *,
    cam_pos: Sequence[float],
    image_w: int = 640,
    image_h: int = 480,
    focal_length: float = 18.0,
    horizontal_aperture: float = 20.955,
) -> tuple[float, float] | None:
    """Project world XYZ to pixel for a world-down-looking Dual scene camera.

    Assumes camera looks along -Z in world (quat ≈ look-down), matching
    Dual rot (0.7071, 0, 0.7071, 0). Returns None if behind camera.
    """
    import math

    x, y, z = float(xyz[0]), float(xyz[1]), float(xyz[2])
    cx, cy, cz = float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])
    # Camera looking down: image x ~ world +y, image y ~ world -x (convention for this quat)
    rel_x = x - cx
    rel_y = y - cy
    rel_z = z - cz
    depth = -rel_z  # points below camera have positive depth
    if depth <= 1e-6:
        return None
    fx = (focal_length / horizontal_aperture) * image_w
    fy = fx  # square pixels assumption for TiledCamera
    # Map: u increases with +y, v increases with -x (top of image toward +x)
    u = image_w * 0.5 + fx * (rel_y / depth)
    v = image_h * 0.5 - fy * (rel_x / depth)
    return float(u), float(v)


def g1_roi_from_body_points(
    points_xyz: Sequence[Sequence[float]],
    *,
    cam_pos: Sequence[float],
    image_w: int = 640,
    image_h: int = 480,
    pad_px: float = 12.0,
) -> dict:
    """Axis-aligned ROI from projected G1 body points (deterministic; no color)."""
    pix = []
    for p in points_xyz:
        uv = project_world_to_pixel(p, cam_pos=cam_pos, image_w=image_w, image_h=image_h)
        if uv is not None:
            pix.append(uv)
    if not pix:
        return {
            "visible": False,
            "roi_area_px2": 0.0,
            "centroid_uv": None,
            "bbox_xyxy": None,
            "roi_source": "projected_g1_body_points",
            "n_projected": 0,
        }
    us = [p[0] for p in pix]
    vs = [p[1] for p in pix]
    x0 = max(0.0, min(us) - pad_px)
    y0 = max(0.0, min(vs) - pad_px)
    x1 = min(float(image_w - 1), max(us) + pad_px)
    y1 = min(float(image_h - 1), max(vs) + pad_px)
    area = max(0.0, (x1 - x0) * (y1 - y0))
    cu = 0.5 * (x0 + x1)
    cv = 0.5 * (y0 + y1)
    return {
        "visible": area >= 1.0 and x1 > x0 and y1 > y0,
        "roi_area_px2": float(area),
        "centroid_uv": [float(cu), float(cv)],
        "bbox_xyxy": [float(x0), float(y0), float(x1), float(y1)],
        "roi_source": "projected_g1_body_points",
        "n_projected": len(pix),
    }
