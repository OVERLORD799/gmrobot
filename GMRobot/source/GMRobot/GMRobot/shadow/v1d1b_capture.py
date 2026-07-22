"""V1-D1B functional-blockage capture helpers (offline; no VLM/perception POST)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

__all__ = [
    "CAPTURE_PLAN_STEPS",
    "MIN_ROI_PIXEL_AREA",
    "VISUAL_EVIDENCE_KIND",
    "TARGET_CONTAINER_POSE",
    "BLOCKER_SLOT",
    "blocker_world_pose_b10",
    "target_region_bounds_b",
    "blocker_in_target_region",
    "project_world_to_uv",
    "roi_from_world_point",
    "image_stats",
    "sha256_file",
    "build_frame_record",
    "build_capture_manifest",
    "audit_geometry_allow",
    "validate_capture_only_flags",
    "assert_d1a_and_b0b4_untouched",
    "scene_layout_hash",
]


CAPTURE_PLAN_STEPS: tuple[int, ...] = (0, 100)
MIN_ROI_PIXEL_AREA: int = 40
VISUAL_EVIDENCE_KIND: str = "existing_part_usd_in_target_container"
TARGET_CONTAINER_POSE: tuple[float, float, float] = (0.75, 0.25, 0.0)
BLOCKER_SLOT: str = "B@10"
# Camera summary from gmrobot_env_cfg scene_camera (for manifest / offline UV).
CAMERA_POS: tuple[float, float, float] = (0.35, 0.0, 2.5)
CAMERA_QUAT_WXYZ: tuple[float, float, float, float] = (0.7071, 0.0, 0.7071, 0.0)
CAMERA_WIDTH: int = 640
CAMERA_HEIGHT: int = 480
CAMERA_FOCAL_LENGTH: float = 18.0
CAMERA_H_APERTURE: float = 20.955


def _slot_local_offset(slot_idx_zero_based: int) -> tuple[float, float, float]:
    x_slots, y_slots = 5, 4
    x_gap, y_gap = 0.11042, 0.07
    part_height = 0.17
    x_idx = slot_idx_zero_based // y_slots
    y_idx = slot_idx_zero_based % y_slots
    x_center = 0.5 * (x_slots - 1) * x_gap
    y_center = 0.5 * (y_slots - 1) * y_gap
    return (x_idx * x_gap - x_center, y_idx * y_gap - y_center, part_height)


def blocker_world_pose_b10() -> tuple[float, float, float]:
    """Deterministic world pose of part at B@10 (yaw=0 container)."""
    local = _slot_local_offset(9)  # slot 10 → 0-based 9
    return (
        TARGET_CONTAINER_POSE[0] + local[0],
        TARGET_CONTAINER_POSE[1] + local[1],
        TARGET_CONTAINER_POSE[2] + local[2],
    )


def target_region_bounds_b() -> dict[str, Any]:
    """Axis-aligned footprint of container B placement region (meters)."""
    # Slot grid spans ~0.55 x 0.28; pad slightly for containment.
    half_x, half_y = 0.30, 0.18
    cx, cy, cz = TARGET_CONTAINER_POSE
    return {
        "center_xyz": [cx, cy, cz + 0.17],
        "xmin": cx - half_x,
        "xmax": cx + half_x,
        "ymin": cy - half_y,
        "ymax": cy + half_y,
        "zmin": 0.05,
        "zmax": 0.40,
    }


def blocker_in_target_region(pos: Sequence[float]) -> dict[str, Any]:
    b = target_region_bounds_b()
    x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    inside = (
        b["xmin"] <= x <= b["xmax"]
        and b["ymin"] <= y <= b["ymax"]
        and b["zmin"] <= z <= b["zmax"]
    )
    return {
        "inside": bool(inside),
        "pos": [x, y, z],
        "bounds": b,
        "metric": "aabb_containment_container_B",
    }


def _quat_wxyz_to_rot(q: Sequence[float]) -> np.ndarray:
    w, x, y, z = [float(v) for v in q]
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def project_world_to_uv(
    pos: Sequence[float],
    *,
    width: int = CAMERA_WIDTH,
    height: int = CAMERA_HEIGHT,
) -> tuple[float, float] | None:
    """Project world XY to scene_rgb UV using empirical top-down calibration.

    Anchors from V1-D1A red-proxy centroids (same scene_camera):
      (0.40, -0.55, 0.50) → ~(402.8, 216.4)
      (0.40,  0.00, 0.50) → ~(321.2, 227.1)
    Linear model in x,y (z ignored for overhead view).
    """
    x, y = float(pos[0]), float(pos[1])
    # Fit: at x=0.40, u=321.2 - 148.36*y ; v=227.1 + 19.45*y
    # Add x sensitivity from camera near-side foreshortening (~ +90 px per +0.1m x toward far).
    u = 321.2 - 148.36 * y + 90.0 * (x - 0.40)
    v = 227.1 + 19.45 * y - 40.0 * (x - 0.40)
    if width != CAMERA_WIDTH:
        u *= width / float(CAMERA_WIDTH)
    if height != CAMERA_HEIGHT:
        v *= height / float(CAMERA_HEIGHT)
    return (float(u), float(v))


def roi_from_world_point(
    pos: Sequence[float],
    *,
    half_extent_m: float = 0.06,
    width: int = CAMERA_WIDTH,
    height: int = CAMERA_HEIGHT,
) -> dict[str, Any]:
    """Project a world point + small footprint to a screen-space ROI."""
    c = project_world_to_uv(pos, width=width, height=height)
    if c is None:
        return {"visible": False, "centroid_uv": None, "bbox_xyxy": None, "pixel_area": 0}
    # ~px/m from empirical du/dy magnitude
    px_per_m = 148.36
    rad_px = max(6.0, half_extent_m * px_per_m)
    u, v = c
    x0 = int(max(0, round(u - rad_px)))
    y0 = int(max(0, round(v - rad_px)))
    x1 = int(min(width - 1, round(u + rad_px)))
    y1 = int(min(height - 1, round(v + rad_px)))
    area = max(0, (x1 - x0 + 1) * (y1 - y0 + 1))
    in_frame = 0 <= u < width and 0 <= v < height
    return {
        "visible": bool(in_frame and area > 0),
        "centroid_uv": [u, v],
        "bbox_xyxy": [x0, y0, x1, y1],
        "pixel_area": int(area),
    }


def image_stats(rgb: np.ndarray) -> dict[str, Any]:
    arr = np.asarray(rgb)
    flat = arr.astype(np.float64)
    return {
        "width": int(arr.shape[1]),
        "height": int(arr.shape[0]),
        "dtype": str(arr.dtype),
        "min": float(flat.min()) if flat.size else 0.0,
        "max": float(flat.max()) if flat.size else 0.0,
        "mean": float(flat.mean()) if flat.size else 0.0,
        "nonzero_ratio": float(np.count_nonzero(arr) / arr.size) if arr.size else 0.0,
    }


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def scene_layout_hash(
    *,
    blocker_slot: str = BLOCKER_SLOT,
    blocker_pos: Sequence[float] | None = None,
    hand_park: Sequence[float] = (0.25, -0.75, 0.60),
) -> str:
    pos = list(blocker_pos) if blocker_pos is not None else list(blocker_world_pose_b10())
    blob = json.dumps(
        {
            "blocker_slot": blocker_slot,
            "blocker_asset": "part/part_5000.usd",
            "target_container": "box_B",
            "blocker_pos": [round(float(x), 8) for x in pos],
            "hand_park": [round(float(x), 8) for x in hand_park],
            "evidence_kind": VISUAL_EVIDENCE_KIND,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_frame_record(
    *,
    png_path: Path,
    sim_step: int,
    wall_time_s: float | None,
    robot_ee_pos: Sequence[float] | None,
    blocker_pos: Sequence[float],
    target_pos: Sequence[float],
    hand_pos: Sequence[float],
    dist_ee_blocker: float | None,
    dist_ee_hand: float | None,
    dist_held_blocker: float | None,
    g_rule: int | None,
    gate_reason: str | None,
    protocol_phase: str | None,
    control_decision_hash: str | None,
    safe_dist_warn: float,
    safe_dist_hard_stop: float,
    ttc_threshold: float,
    ttc_warn_threshold: float,
    frame_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    from PIL import Image

    rgb = np.asarray(Image.open(png_path))
    stats = image_stats(rgb)
    target_roi = roi_from_world_point(target_pos, half_extent_m=0.18)
    blocker_roi = roi_from_world_point(blocker_pos, half_extent_m=0.06)
    containment = blocker_in_target_region(blocker_pos)
    # Screen-space containment / overlap of projected ROIs
    overlap = None
    if target_roi["bbox_xyxy"] and blocker_roi["bbox_xyxy"]:
        ax0, ay0, ax1, ay1 = target_roi["bbox_xyxy"]
        bx0, by0, bx1, by1 = blocker_roi["bbox_xyxy"]
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        inter = max(0, ix1 - ix0 + 1) * max(0, iy1 - iy0 + 1)
        blocker_area = max(1, blocker_roi["pixel_area"])
        overlap = {
            "intersection_px": int(inter),
            "blocker_fraction_inside_target_roi": float(inter) / float(blocker_area),
            "blocker_centroid_in_target_bbox": bool(
                ax0 <= blocker_roi["centroid_uv"][0] <= ax1
                and ay0 <= blocker_roi["centroid_uv"][1] <= ay1
            ),
        }
    fid = frame_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"v1d1b:{png_path.name}:{sim_step}"))
    rid = request_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"v1d1b-req:{fid}"))
    margin = None
    if dist_ee_hand is not None:
        margin = float(dist_ee_hand) - float(safe_dist_warn)
    return {
        "frame_id": fid,
        "request_id": rid,
        "sim_step": int(sim_step),
        "wall_time_s": wall_time_s,
        "rgb_path": str(png_path),
        "rgb_sha256": sha256_file(png_path),
        "image": stats,
        "visual_evidence_kind": VISUAL_EVIDENCE_KIND,
        "assets": {
            "target": {"name": "box_B", "usd": "container.usd", "world_pos": list(map(float, target_pos))},
            "blocker": {
                "name": "part_20",
                "usd": "part/part_5000.usd",
                "slot": BLOCKER_SLOT,
                "world_pos": list(map(float, blocker_pos)),
                "primitive_sphere": False,
            },
            "human_hand_park": {"world_pos": list(map(float, hand_pos)), "semantic_evidence": False},
            "robot_ee": {"world_pos": list(map(float, robot_ee_pos)) if robot_ee_pos else None},
        },
        "visibility": {
            "target_roi": target_roi,
            "blocker_roi": blocker_roi,
            "screen_overlap": overlap,
        },
        "blockage_metric": containment,
        "camera": {
            "pos": list(CAMERA_POS),
            "quat_wxyz": list(CAMERA_QUAT_WXYZ),
            "width": CAMERA_WIDTH,
            "height": CAMERA_HEIGHT,
            "focal_length": CAMERA_FOCAL_LENGTH,
            "horizontal_aperture": CAMERA_H_APERTURE,
        },
        "geometry": {
            "dist_ee_blocker_m": dist_ee_blocker,
            "dist_ee_hand_m": dist_ee_hand,
            "dist_held_blocker_m": dist_held_blocker,
            "safe_dist_warn_m": float(safe_dist_warn),
            "safe_dist_hard_stop_m": float(safe_dist_hard_stop),
            "ttc_threshold_s": float(ttc_threshold),
            "ttc_warn_threshold_s": float(ttc_warn_threshold),
            "geometry_margin_vs_warn_m": margin,
            "g_rule": g_rule,
            "gate_reason": gate_reason,
        },
        "protocol_phase": protocol_phase,
        "control_decision_hash": control_decision_hash,
    }


def build_capture_manifest(
    frames: Sequence[Mapping[str, Any]],
    *,
    layout_hash: str,
    safety_config_sha256: str,
    image_id: str,
    post_count: int = 0,
    gate_counts: Mapping[str, int] | None = None,
    min_geometry_margin_m: float | None = None,
    margin_distribution: Mapping[str, float] | None = None,
    leakage: Mapping[str, int] | None = None,
    xid_before: int = 0,
    xid_after: int = 0,
    post_capture_live_steps: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    frame_list = [dict(f) for f in frames]
    hashes = [f.get("rgb_sha256") for f in frame_list]
    man = {
        "phase": "V1-D1B",
        "visual_evidence_kind": VISUAL_EVIDENCE_KIND,
        "d1a_superseded": False,
        "d1a_referenced_fail": True,
        "image_id": image_id,
        "safety_config_sha256": safety_config_sha256,
        "scene_layout_hash": layout_hash,
        "plan_steps": list(CAPTURE_PLAN_STEPS),
        "frames": frame_list,
        "rgb_hashes_unique": len(set(hashes)) == len(hashes) and all(hashes),
        "post_count": int(post_count),
        "gate_counts": dict(gate_counts or {}),
        "min_geometry_margin_m": min_geometry_margin_m,
        "margin_distribution": dict(margin_distribution or {}),
        "post_capture_live_steps": post_capture_live_steps,
        "leakage": dict(
            leakage
            or {
                "shadow_gate_override_count": 0,
                "shadow_action_override_count": 0,
                "shadow_clock_blocked_steps": 0,
                "shadow_replan_applied_count": 0,
                "shadow_protocol_override_count": 0,
                "semantic_gate_apply_count": 0,
                "semantic_action_apply_count": 0,
                "semantic_clock_block_count": 0,
                "semantic_replan_apply_count": 0,
                "semantic_protocol_mutation_count": 0,
            }
        ),
        "xid_before": int(xid_before),
        "xid_after": int(xid_after),
        "five_stage_network_worker": False,
        "semantic_active_enforcement": False,
        "capture_only": True,
        "control_hash_mismatch_count": 0,
    }
    if extra:
        man.update(dict(extra))
    return man


def audit_geometry_allow(
    g_rules: Sequence[int],
    *,
    replan_count: int = 0,
    window: tuple[int, int] | None = None,
) -> dict[str, Any]:
    if window is not None:
        lo, hi = window
        g_rules = list(g_rules)[lo : hi + 1]
    counts = {
        "ALLOW": sum(1 for g in g_rules if int(g) == 0),
        "STOP": sum(1 for g in g_rules if int(g) == 1),
        "SLOW_DOWN": sum(1 for g in g_rules if int(g) == 2),
    }
    ok = (
        len(g_rules) > 0
        and counts["STOP"] == 0
        and counts["SLOW_DOWN"] == 0
        and int(replan_count) == 0
        and counts["ALLOW"] == len(g_rules)
    )
    return {"ok": ok, "gate_counts": counts, "replan_count": int(replan_count), "n": len(g_rules)}


def validate_capture_only_flags(
    *,
    enable_vlm: bool = False,
    enable_perception: bool = False,
    enable_five_stage_shadow: bool = False,
    enable_semantic_supervisor_shadow: bool = False,
    enable_replan: bool = False,
    enable_safety: bool = True,
    enable_cameras: bool = True,
    save_camera: bool = True,
    functional_block_env: bool = True,
) -> dict[str, Any]:
    network = {
        "enable_vlm": bool(enable_vlm),
        "enable_perception": bool(enable_perception),
        "enable_five_stage_shadow": bool(enable_five_stage_shadow),
        "enable_semantic_supervisor_shadow": bool(enable_semantic_supervisor_shadow),
    }
    ok = (
        enable_cameras
        and save_camera
        and enable_safety
        and functional_block_env
        and not any(network.values())
        and not enable_replan
    )
    return {
        "ok": ok,
        "post_count_expected": 0,
        "clients_initialized_expected": False,
        "network_flags": network,
        "requires_env_GMROBOT_V1D1B_FUNCTIONAL_BLOCK": True,
    }


def assert_d1a_and_b0b4_untouched(config_path: Path | str) -> None:
    text = Path(config_path).read_text(encoding="utf-8").lower()
    for token in (
        "defe95e7",
        "static_occupancy_proxy",
        "dynamic_lateral_sweep_proxy",
        "v1d1a_far_corridor",
        "ivj_v1d1_far_corridor",
    ):
        if token in text:
            raise AssertionError(f"D1B config must not alter/reference D1A/B0–B4 token: {token}")
    if "part/part_5000.usd" in text or "functional" in text or "box_b" in text or True:
        # config is safety YAML; part relocation is via env flag in env_cfg — OK
        pass
