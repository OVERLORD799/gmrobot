"""V1-E2A Dyn-C mirrored outer patrol offline prebuild evaluator."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from scene_camera_override import project_world_to_pixel

E01_DYN_C_SCENE = "E01-Dyn-C"
E01_DYN_C_SCENARIO = "mirrored_outer_lateral_patrol"
E01_DYN_C_MOTION_SOURCE = "scripted_g1_mirrored_outer_lateral_patrol"
E01_DYN_C_SEED = 44
E01_DYN_C_SCENE_GROUP = "e01_dyn_c_formal_m1e2a_20260723"
E01_DYN_C_CAMERA_POS: tuple[float, float, float] = (0.45, 0.0, 2.7)
E01_DYN_C_CAMERA_ROT: tuple[float, float, float, float] = (0.7071, 0.0, 0.7071, 0.0)

CAPTURE_STEPS: tuple[int, int] = (240, 310)
ADJACENT_GROUP_A: tuple[int, int, int] = (239, 240, 241)
ADJACENT_GROUP_B: tuple[int, int, int] = (309, 310, 311)
GEOMETRY_WINDOW: tuple[int, int] = (220, 330)

IMAGE_W = 640
IMAGE_H = 480
IMAGE_AREA = float(IMAGE_W * IMAGE_H)
MARGIN_PX = 12.0

MIN_VISIBLE_LINKS = 4
MIN_ROI_AREA_FRAC = 0.01
MAX_CLIPPING_RATIO = 0.50
MIN_CENTROID_DISPLACEMENT_PX = 30.0

TARGET_LINKS: tuple[str, ...] = (
    "torso_link",
    "head_link",
    "left_shoulder_pitch_link",
    "right_shoulder_pitch_link",
    "left_elbow_link",
    "right_elbow_link",
    "left_wrist_pitch_link",
    "right_wrist_pitch_link",
)

WORKCELL_ANCHORS: dict[str, tuple[float, float, float]] = {
    "table_near_left": (0.15, -0.50, 0.0),
    "table_near_right": (0.15, 0.50, 0.0),
    "bin_a_center": (0.75, -0.25, 0.0),
    "bin_b_center": (0.75, 0.25, 0.0),
}


@dataclass(frozen=True)
class Phase:
    name: str
    duration_steps: int
    vx: float
    vy: float
    wz: float = 0.0


MIRRORED_OUTER_LATERAL_PATROL_PHASES: tuple[Phase, ...] = (
    Phase("approach_outer_lane_mirror", 150, 0.36, 0.00),
    Phase("settle_heading_mirror", 30, 0.03, 0.00),
    Phase("lateral_negative_sweep_mirror", 70, 0.02, -0.24),
    Phase("lateral_positive_sweep_mirror", 70, -0.02, 0.24),
    Phase("retreat_outer_lane_mirror", 90, -0.30, 0.00),
    Phase("idle", 9999, 0.0, 0.0),
)

OUTER_LATERAL_PATROL_PHASES_DYN_B: tuple[Phase, ...] = (
    Phase("approach_outer_lane", 140, 0.34, 0.00),
    Phase("settle_heading", 20, 0.04, 0.00),
    Phase("lateral_positive_sweep", 90, 0.02, 0.22),
    Phase("lateral_negative_sweep", 90, -0.02, -0.22),
    Phase("retreat_outer_lane", 80, -0.32, 0.00),
    Phase("idle", 9999, 0.0, 0.0),
)


def _traj_hash(seed: int, phases: Sequence[Phase]) -> str:
    payload = {
        "seed": int(seed),
        "phases": [
            {"name": p.name, "duration_steps": p.duration_steps, "vx": p.vx, "vy": p.vy, "wz": p.wz}
            for p in phases
        ],
        "kind": "scripted_g1_locomotion",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def phase_at_step(step: int) -> Phase:
    s = int(step)
    if s <= 0:
        return MIRRORED_OUTER_LATERAL_PATROL_PHASES[-1]
    acc = 0
    for ph in MIRRORED_OUTER_LATERAL_PATROL_PHASES:
        acc += ph.duration_steps
        if s <= acc:
            return ph
    return MIRRORED_OUTER_LATERAL_PATROL_PHASES[-1]


def trajectory_xy(step: int, *, dt: float = 0.02, init_xy: Sequence[float] = (-1.5, 0.0)) -> tuple[float, float]:
    x, y = float(init_xy[0]), float(init_xy[1])
    rem = max(0, int(step))
    for ph in MIRRORED_OUTER_LATERAL_PATROL_PHASES:
        if rem <= 0:
            break
        n = min(rem, ph.duration_steps)
        x += ph.vx * dt * n
        y += ph.vy * dt * n
        rem -= n
    return x, y


def _link_points_from_root(root_xy: Sequence[float]) -> dict[str, tuple[float, float, float]]:
    x, y = float(root_xy[0]), float(root_xy[1])
    return {
        "torso_link": (x, y, 0.95),
        "head_link": (x, y, 1.20),
        "left_shoulder_pitch_link": (x, y + 0.18, 0.95),
        "right_shoulder_pitch_link": (x, y - 0.18, 0.95),
        "left_elbow_link": (x + 0.10, y + 0.24, 0.82),
        "right_elbow_link": (x + 0.10, y - 0.24, 0.82),
        "left_wrist_pitch_link": (x + 0.16, y + 0.28, 0.72),
        "right_wrist_pitch_link": (x + 0.16, y - 0.28, 0.72),
    }


def _eval_frame(step: int) -> dict[str, Any]:
    root = trajectory_xy(step)
    links = _link_points_from_root(root)
    pixels: dict[str, tuple[float, float]] = {}
    for lk in TARGET_LINKS:
        uv = project_world_to_pixel(links[lk], cam_pos=E01_DYN_C_CAMERA_POS, image_w=IMAGE_W, image_h=IMAGE_H)
        if uv is not None:
            pixels[lk] = (float(uv[0]), float(uv[1]))
    if not pixels:
        raise RuntimeError(f"step {step} has no projected links")
    us = [p[0] for p in pixels.values()]
    vs = [p[1] for p in pixels.values()]
    x0, y0, x1, y1 = min(us), min(vs), max(us), max(vs)
    visible_links = sum(1 for u, v in pixels.values() if MARGIN_PX <= u <= IMAGE_W - 1 - MARGIN_PX and MARGIN_PX <= v <= IMAGE_H - 1 - MARGIN_PX)
    clipping_ratio = 1.0 - (float(visible_links) / float(len(TARGET_LINKS)))
    cx0, cy0 = max(0.0, x0), max(0.0, y0)
    cx1, cy1 = min(float(IMAGE_W - 1), x1), min(float(IMAGE_H - 1), y1)
    area = max(0.0, (cx1 - cx0) * (cy1 - cy0))
    return {
        "step": int(step),
        "phase": phase_at_step(step).name,
        "root_xy": [float(root[0]), float(root[1])],
        "visible_links": int(visible_links),
        "clipping_ratio": float(clipping_ratio),
        "roi_area_fraction": float(area / IMAGE_AREA),
        "bbox_xyxy": [float(x0), float(y0), float(x1), float(y1)],
        "centroid_uv": [float(0.5 * (x0 + x1)), float(0.5 * (y0 + y1))],
    }


def _anchors_ok() -> dict[str, Any]:
    details: dict[str, Any] = {}
    ok = True
    for name, xyz in sorted(WORKCELL_ANCHORS.items()):
        uv = project_world_to_pixel(xyz, cam_pos=E01_DYN_C_CAMERA_POS, image_w=IMAGE_W, image_h=IMAGE_H)
        in_frame = bool(
            uv is not None
            and 24.0 <= float(uv[0]) <= IMAGE_W - 25.0
            and 24.0 <= float(uv[1]) <= IMAGE_H - 25.0
        )
        details[name] = {"uv": [float(uv[0]), float(uv[1])] if uv else None, "in_frame": in_frame}
        ok = ok and in_frame
    return {"pass": ok, "anchors": details}


def evaluate_dyn_c_prebuild() -> dict[str, Any]:
    eval_steps = sorted(set((*ADJACENT_GROUP_A, *ADJACENT_GROUP_B, *CAPTURE_STEPS)))
    frames = {s: _eval_frame(s) for s in eval_steps}
    c0 = frames[CAPTURE_STEPS[0]]["centroid_uv"]
    c1 = frames[CAPTURE_STEPS[1]]["centroid_uv"]
    centroid_disp = float(math.hypot(c1[0] - c0[0], c1[1] - c0[1]))

    per_frame_gate = all(
        frames[s]["visible_links"] >= MIN_VISIBLE_LINKS
        and frames[s]["roi_area_fraction"] >= MIN_ROI_AREA_FRAC
        and frames[s]["clipping_ratio"] <= MAX_CLIPPING_RATIO
        for s in eval_steps
    )
    anchors = _anchors_ok()
    gates = {
        "per_frame_gate_ok": bool(per_frame_gate),
        "centroid_displacement_ok": bool(centroid_disp >= MIN_CENTROID_DISPLACEMENT_PX),
        "workcell_double_bins_visible": bool(anchors["pass"]),
    }
    verdict = "PREBUILD_READY" if all(gates.values()) else "BLOCKED"

    dyn_c_hash = _traj_hash(E01_DYN_C_SEED, MIRRORED_OUTER_LATERAL_PATROL_PHASES)
    dyn_b_hash = _traj_hash(43, OUTER_LATERAL_PATROL_PHASES_DYN_B)

    return {
        "run_id": "v1e2a_dyn_c_mirrored_outer_patrol_design_20260723",
        "date": "2026-07-23",
        "scene": E01_DYN_C_SCENE,
        "scenario": E01_DYN_C_SCENARIO,
        "motion_source": E01_DYN_C_MOTION_SOURCE,
        "seed": E01_DYN_C_SEED,
        "scene_group": E01_DYN_C_SCENE_GROUP,
        "camera_pose": {"pos": list(E01_DYN_C_CAMERA_POS), "rot": list(E01_DYN_C_CAMERA_ROT)},
        "capture_window": {"geometry_window": list(GEOMETRY_WINDOW), "capture_steps": list(CAPTURE_STEPS)},
        "adjacent_triplets": {"A": list(ADJACENT_GROUP_A), "B": list(ADJACENT_GROUP_B)},
        "thresholds": {
            "min_visible_links": MIN_VISIBLE_LINKS,
            "min_roi_area_fraction": MIN_ROI_AREA_FRAC,
            "max_clipping_ratio": MAX_CLIPPING_RATIO,
            "min_centroid_displacement_px": MIN_CENTROID_DISPLACEMENT_PX,
        },
        "trajectory_identity": {
            "trajectory_id_dyn_c": dyn_c_hash,
            "trajectory_id_dyn_b_seed43_outer_lateral_patrol": dyn_b_hash,
            "is_distinct_from_dyn_b": dyn_c_hash != dyn_b_hash,
        },
        "frame_predictions": {str(k): frames[k] for k in eval_steps},
        "cross_capture_centroid_displacement_px": centroid_disp,
        "anchors": anchors,
        "gates": gates,
        "label_contract": {
            "risk_type": "dynamic",
            "category": "provisional",
            "reviewer_approved": False,
            "synthetic": False,
            "scripted_locomotion": True,
            "human_motion": False,
            "human_hand": False,
            "glove": False,
            "PPE": False,
            "VLM_output": False,
            "geometry_evidence": False,
            "control_evidence": False,
        },
        "policy_contract": {
            "task_execution": False,
            "visual_dataset_only": True,
            "live_control_evidence": False,
            "safety_evidence": False,
            "control_evidence": False,
        },
        "next_step_budget": {"build_allowed": 1, "visual_capture_allowed": 1},
        "verdict": verdict,
    }


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

