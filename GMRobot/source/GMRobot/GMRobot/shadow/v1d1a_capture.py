"""V1-D1A far-corridor capture helpers (offline; no VLM/perception POST).

Builds RGB manifests, red-proxy visibility metrics, trajectory hashes, and
geometry ALLOW audits from capture-only Isaac artifacts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

__all__ = [
    "CAPTURE_PLAN_STEPS",
    "MIN_PROXY_PIXEL_AREA",
    "MIN_SCREEN_DISPLACEMENT_PX",
    "VISUAL_SEMANTIC_RISK",
    "trajectory_pose_hash",
    "detect_red_proxy_roi",
    "image_stats",
    "sha256_file",
    "build_frame_record",
    "build_capture_manifest",
    "audit_geometry_allow",
    "validate_capture_only_flags",
    "assert_b0_b4_untouched_by_config",
]


# Planned formal D1 submit moments (capture must preserve these RGB hashes).
CAPTURE_PLAN_STEPS: tuple[int, ...] = (0, 100)
# Red sphere r=0.05m under overhead camera; FOV-edge frames can be ~60–100 px.
MIN_PROXY_PIXEL_AREA: int = 64
MIN_SCREEN_DISPLACEMENT_PX: float = 25.0
VISUAL_SEMANTIC_RISK: str = "low"


@dataclass(frozen=True)
class RedProxyRoi:
    visible: bool
    pixel_area: int
    centroid_uv: tuple[float, float] | None
    bbox_xyxy: tuple[int, int, int, int] | None
    nonzero_red_ratio: float


def _linear_pose_at_step(
    *,
    start_pos: Sequence[float],
    end_pos: Sequence[float],
    start_step: int,
    duration_steps: int,
    hold_steps: int,
    retreat_pos: Sequence[float] | None,
    retreat_duration_steps: int,
    step_index: int,
    control_dt: float,
    eps: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Mirror HumanTrajectoryConfig.compute_pose (single source math, no Isaac)."""
    start = np.asarray(start_pos, dtype=np.float64)
    end = np.asarray(end_pos, dtype=np.float64)
    dt = max(float(control_dt), eps)
    approach_end = int(start_step) + int(duration_steps)
    hold_end = approach_end + int(hold_steps)
    if retreat_pos is None:
        retreat_end = hold_end
    else:
        retreat_end = hold_end + int(retreat_duration_steps)

    if step_index < int(start_step):
        return start.copy(), np.zeros(3, dtype=np.float64)
    if step_index < approach_end:
        alpha = (step_index - int(start_step)) / max(int(duration_steps), 1)
        pos = start + alpha * (end - start)
        vel = (end - start) / max(int(duration_steps) * dt, eps)
        return pos, vel
    if step_index < hold_end:
        return end.copy(), np.zeros(3, dtype=np.float64)
    if retreat_pos is not None and step_index < retreat_end:
        retreat = np.asarray(retreat_pos, dtype=np.float64)
        alpha = (step_index - hold_end) / max(int(retreat_duration_steps), 1)
        pos = end + alpha * (retreat - end)
        vel = (retreat - end) / max(int(retreat_duration_steps) * dt, eps)
        return pos, vel
    if retreat_pos is not None:
        return np.asarray(retreat_pos, dtype=np.float64).copy(), np.zeros(3, dtype=np.float64)
    return end.copy(), np.zeros(3, dtype=np.float64)


def trajectory_pose_hash(
    *,
    start_pos: Sequence[float],
    end_pos: Sequence[float],
    start_step: int,
    duration_steps: int,
    hold_steps: int = 0,
    retreat_pos: Sequence[float] | None = None,
    retreat_duration_steps: int = 0,
    sample_steps: Sequence[int] = CAPTURE_PLAN_STEPS,
    control_dt: float = 0.02,
) -> str:
    """Deterministic hash of scripted poses at sample steps (no Isaac)."""
    samples: list[dict[str, Any]] = []
    for step in sample_steps:
        pos, vel = _linear_pose_at_step(
            start_pos=start_pos,
            end_pos=end_pos,
            start_step=start_step,
            duration_steps=duration_steps,
            hold_steps=hold_steps,
            retreat_pos=retreat_pos,
            retreat_duration_steps=retreat_duration_steps,
            step_index=int(step),
            control_dt=float(control_dt),
        )
        samples.append(
            {
                "step": int(step),
                "pos": [round(float(x), 8) for x in pos.tolist()],
                "vel": [round(float(x), 8) for x in vel.tolist()],
            }
        )
    blob = json.dumps(
        {
            "start_pos": list(map(float, start_pos)),
            "end_pos": list(map(float, end_pos)),
            "start_step": int(start_step),
            "duration_steps": int(duration_steps),
            "hold_steps": int(hold_steps),
            "retreat_pos": list(map(float, retreat_pos)) if retreat_pos else None,
            "retreat_duration_steps": int(retreat_duration_steps),
            "samples": samples,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def detect_red_proxy_roi(rgb: np.ndarray) -> RedProxyRoi:
    """Detect the kinematic red sphere in scene_rgb (empirical visibility)."""
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"expected HxWx3 rgb, got {getattr(rgb, 'shape', None)}")
    arr = np.asarray(rgb)
    if arr.dtype != np.uint8:
        # float observations may be 0..1 or 0..255
        amax = float(np.nanmax(arr)) if arr.size else 0.0
        if amax <= 1.5:
            arr = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
        else:
            arr = np.clip(arr, 0.0, 255.0).astype(np.uint8)
    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    mask = (r > 140) & (r > g + 30) & (r > b + 30)
    area = int(mask.sum())
    ratio = float(area) / float(mask.size) if mask.size else 0.0
    if area <= 0:
        return RedProxyRoi(False, 0, None, None, ratio)
    ys, xs = np.where(mask)
    centroid = (float(xs.mean()), float(ys.mean()))
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return RedProxyRoi(True, area, centroid, bbox, ratio)


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


def build_frame_record(
    *,
    png_path: Path,
    sim_step: int,
    wall_time_s: float | None,
    proxy_pos: Sequence[float],
    proxy_vel: Sequence[float],
    proxy_radius_m: float,
    dist_ee_human: float | None,
    dist_held_proxy: float | None,
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
    roi = detect_red_proxy_roi(rgb)
    stats = image_stats(rgb)
    fid = frame_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"v1d1a:{png_path.name}:{sim_step}"))
    rid = request_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"v1d1a-req:{fid}"))
    margin = None
    if dist_ee_human is not None:
        margin = float(dist_ee_human) - float(safe_dist_warn)
    return {
        "frame_id": fid,
        "request_id": rid,
        "sim_step": int(sim_step),
        "wall_time_s": wall_time_s,
        "rgb_path": str(png_path),
        "rgb_sha256": sha256_file(png_path),
        "image": stats,
        "proxy": {
            "name": "human_hand_sphere",
            "visual_semantic_risk": VISUAL_SEMANTIC_RISK,
            "radius_m": float(proxy_radius_m),
            "world_pos": [float(x) for x in proxy_pos],
            "world_vel": [float(x) for x in proxy_vel],
        },
        "visibility": {
            "visible": roi.visible,
            "pixel_area": roi.pixel_area,
            "centroid_uv": list(roi.centroid_uv) if roi.centroid_uv else None,
            "bbox_xyxy": list(roi.bbox_xyxy) if roi.bbox_xyxy else None,
            "nonzero_red_ratio": roi.nonzero_red_ratio,
        },
        "geometry": {
            "dist_ee_proxy_m": dist_ee_human,
            "dist_held_proxy_m": dist_held_proxy,
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


def _screen_displacement_px(a: Mapping[str, Any], b: Mapping[str, Any]) -> float | None:
    ca = (a.get("visibility") or {}).get("centroid_uv")
    cb = (b.get("visibility") or {}).get("centroid_uv")
    if not ca or not cb:
        return None
    return float(np.hypot(float(ca[0]) - float(cb[0]), float(ca[1]) - float(cb[1])))


def build_capture_manifest(
    frames: Sequence[Mapping[str, Any]],
    *,
    trajectory_hash: str,
    safety_config_sha256: str,
    image_id: str,
    post_count: int = 0,
    gate_counts: Mapping[str, int] | None = None,
    min_geometry_margin_m: float | None = None,
    leakage: Mapping[str, int] | None = None,
    xid_before: int = 0,
    xid_after: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    frame_list = [dict(f) for f in frames]
    disp = None
    if len(frame_list) >= 2:
        disp = _screen_displacement_px(frame_list[0], frame_list[1])
    hashes = [f.get("rgb_sha256") for f in frame_list]
    manifest = {
        "phase": "V1-D1A",
        "visual_semantic_risk": VISUAL_SEMANTIC_RISK,
        "image_id": image_id,
        "safety_config_sha256": safety_config_sha256,
        "trajectory_pose_hash": trajectory_hash,
        "plan_steps": list(CAPTURE_PLAN_STEPS),
        "frames": frame_list,
        "pixel_displacement_px": disp,
        "rgb_hashes_unique": len(set(hashes)) == len(hashes) and all(hashes),
        "post_count": int(post_count),
        "gate_counts": dict(gate_counts or {}),
        "min_geometry_margin_m": min_geometry_margin_m,
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
    }
    if extra:
        manifest.update(dict(extra))
    return manifest


def audit_geometry_allow(
    g_rules: Sequence[int],
    *,
    replan_count: int = 0,
) -> dict[str, Any]:
    """Pass iff every gate is ALLOW and no replan attributed.

    GateDecision ints: ALLOW=0, STOP=1, SLOW_DOWN=2.
    """
    counts = {
        "ALLOW": sum(1 for g in g_rules if int(g) == 0),
        "STOP": sum(1 for g in g_rules if int(g) == 1),
        "SLOW_DOWN": sum(1 for g in g_rules if int(g) == 2),
    }
    ok = (
        counts["STOP"] == 0
        and counts["SLOW_DOWN"] == 0
        and int(replan_count) == 0
        and len(g_rules) > 0
        and counts["ALLOW"] == len(g_rules)
    )
    return {"ok": ok, "gate_counts": counts, "replan_count": int(replan_count)}


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
) -> dict[str, Any]:
    """Capture-only: cameras+optional safety; no network / live semantic / replan."""
    network_flags = {
        "enable_vlm": bool(enable_vlm),
        "enable_perception": bool(enable_perception),
        "enable_five_stage_shadow": bool(enable_five_stage_shadow),
        "enable_semantic_supervisor_shadow": bool(enable_semantic_supervisor_shadow),
    }
    ok = (
        enable_cameras
        and save_camera
        and enable_safety
        and not any(network_flags.values())
        and not enable_replan
    )
    return {
        "ok": ok,
        "post_count_expected": 0,
        "clients_initialized_expected": False,
        "network_flags": network_flags,
        "enable_replan": bool(enable_replan),
        "enable_safety": bool(enable_safety),
        "semantic_enforcement_mode": "shadow_or_off",
    }


def assert_b0_b4_untouched_by_config(config_path: Path | str) -> None:
    """Ensure this YAML does not claim to rewrite frozen physical B0–B4 assets."""
    text = Path(config_path).read_text(encoding="utf-8")
    forbidden = (
        "b0-",
        "b1-",
        "b2-",
        "b3-",
        "b4-",
        "defe95e7",
        "static_occupancy_proxy",
        "dynamic_lateral_sweep_proxy",
    )
    lower = text.lower()
    for token in forbidden:
        if token in lower:
            raise AssertionError(f"config must not reference frozen B0–B4 token: {token}")


def red_proxy_roi_as_dict(roi: RedProxyRoi) -> dict[str, Any]:
    return asdict(roi)
