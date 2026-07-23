"""Offline-only M1Y camera framing evaluator for E01-Dyn-B.

Deterministic, fail-closed design using M1W1 body poses + known scene geometry.
No Isaac/Docker/network/VLM/SAM2 dependencies.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from scene_camera_override import (
    DEFAULT_SCENE_CAMERA_POS,
    DEFAULT_SCENE_CAMERA_ROT,
    project_world_to_pixel,
)

IMAGE_W = 640
IMAGE_H = 480
IMAGE_AREA = float(IMAGE_W * IMAGE_H)

TARGET_STEPS: tuple[int, int] = (220, 330)
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

# Explicit world anchors to preserve table/workcell/context in frame.
WORKCELL_ANCHORS: dict[str, tuple[float, float, float]] = {
    "table_near_left": (0.15, -0.50, 0.00),
    "table_near_right": (0.15, 0.50, 0.00),
    "table_far_left": (1.05, -0.50, 0.00),
    "table_far_right": (1.05, 0.50, 0.00),
    "container_A_center": (0.75, -0.25, 0.00),
    "container_B_center": (0.75, 0.25, 0.00),
}

# Workspace anchors (scripted motion relevance area around table front).
WORKSPACE_ANCHORS: dict[str, tuple[float, float, float]] = {
    "workspace_front_left": (0.00, -0.50, 0.00),
    "workspace_front_right": (0.00, 0.50, 0.00),
    "workspace_mid_left": (0.60, -0.50, 0.00),
    "workspace_mid_right": (0.60, 0.50, 0.00),
}

ALL_ANCHORS = {**WORKCELL_ANCHORS, **WORKSPACE_ANCHORS}

# Conservative projection margin: points too close to edges are treated as out.
UNCERTAINTY_MARGIN_PX = 12.0
ANCHOR_MARGIN_PX = 24.0

# Hard visual gates.
MIN_LINKS_IN_FRAME = 4
MAX_CLIPPING_RATIO = 0.50
MIN_ROI_AREA_FRAC = 0.01
MIN_CENTROID_SEPARATION_PX = 20.0

SEARCH_X = (0.20, 1.20, 0.05)
SEARCH_Y = (-0.40, 0.40, 0.05)
SEARCH_Z = (2.70, 3.60, 0.05)


@dataclass(frozen=True)
class StepEval:
    links_visible_margin: int
    links_visible_raw: int
    clipping_ratio: float
    roi_area_fraction: float
    centroid_uv: tuple[float, float] | None
    bbox_xyxy_unclipped: tuple[float, float, float, float] | None
    gate_links: bool
    gate_clipping: bool
    gate_roi_area: bool


def _frange(start: float, stop: float, step: float) -> list[float]:
    vals: list[float] = []
    n = int(round((stop - start) / step))
    for i in range(n + 1):
        vals.append(round(start + i * step, 6))
    return vals


def load_body_pose_steps(body_pose_jsonl: Path | str) -> dict[int, dict[str, Any]]:
    src = Path(body_pose_jsonl)
    out: dict[int, dict[str, Any]] = {}
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        rec = json.loads(line)
        out[int(rec["step"])] = rec
    return out


def _in_frame(uv: tuple[float, float], *, margin_px: float) -> bool:
    u, v = float(uv[0]), float(uv[1])
    return (margin_px <= u <= (IMAGE_W - 1 - margin_px)) and (
        margin_px <= v <= (IMAGE_H - 1 - margin_px)
    )


def _bbox(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    us = [p[0] for p in points]
    vs = [p[1] for p in points]
    return (float(min(us)), float(min(vs)), float(max(us)), float(max(vs)))


def _bbox_area_clipped(b: tuple[float, float, float, float] | None) -> float:
    if b is None:
        return 0.0
    x0, y0, x1, y1 = b
    cx0 = max(0.0, x0)
    cy0 = max(0.0, y0)
    cx1 = min(float(IMAGE_W - 1), x1)
    cy1 = min(float(IMAGE_H - 1), y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return 0.0
    return float((cx1 - cx0) * (cy1 - cy0))


def evaluate_step(links_xyz: Sequence[Sequence[float]], cam_pos: Sequence[float]) -> StepEval:
    proj_all: list[tuple[float, float]] = []
    visible_raw = 0
    visible_margin = 0
    for p in links_xyz:
        uv = project_world_to_pixel(p, cam_pos=cam_pos, image_w=IMAGE_W, image_h=IMAGE_H)
        if uv is None:
            continue
        proj_all.append((float(uv[0]), float(uv[1])))
        if _in_frame(uv, margin_px=0.0):
            visible_raw += 1
        if _in_frame(uv, margin_px=UNCERTAINTY_MARGIN_PX):
            visible_margin += 1

    denom = float(len(TARGET_LINKS))
    clipping_ratio = 1.0 - (visible_margin / denom)
    b = _bbox(proj_all)
    area_frac = _bbox_area_clipped(b) / IMAGE_AREA
    centroid = None
    if b is not None:
        centroid = (0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3]))

    gate_links = visible_margin >= MIN_LINKS_IN_FRAME
    gate_clipping = clipping_ratio <= MAX_CLIPPING_RATIO
    gate_roi_area = area_frac >= MIN_ROI_AREA_FRAC
    return StepEval(
        links_visible_margin=visible_margin,
        links_visible_raw=visible_raw,
        clipping_ratio=float(clipping_ratio),
        roi_area_fraction=float(area_frac),
        centroid_uv=centroid,
        bbox_xyxy_unclipped=b,
        gate_links=gate_links,
        gate_clipping=gate_clipping,
        gate_roi_area=gate_roi_area,
    )


def evaluate_anchors(cam_pos: Sequence[float]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    all_ok = True
    for name, xyz in sorted(ALL_ANCHORS.items()):
        uv = project_world_to_pixel(xyz, cam_pos=cam_pos, image_w=IMAGE_W, image_h=IMAGE_H)
        ok = bool(uv is not None and _in_frame(uv, margin_px=ANCHOR_MARGIN_PX))
        details[name] = {
            "world_xyz": [float(xyz[0]), float(xyz[1]), float(xyz[2])],
            "uv": [float(uv[0]), float(uv[1])] if uv is not None else None,
            "in_frame_with_margin": ok,
        }
        all_ok = all_ok and ok
    return {"pass": all_ok, "margin_px": ANCHOR_MARGIN_PX, "anchors": details}


def _centroid_distance(c0: tuple[float, float] | None, c1: tuple[float, float] | None) -> float | None:
    if c0 is None or c1 is None:
        return None
    return float(math.hypot(c1[0] - c0[0], c1[1] - c0[1]))


def _camera_delta(cam_pos: Sequence[float], prior_cam_pos: Sequence[float]) -> float:
    dx = float(cam_pos[0]) - float(prior_cam_pos[0])
    dy = float(cam_pos[1]) - float(prior_cam_pos[1])
    dz = float(cam_pos[2]) - float(prior_cam_pos[2])
    return float(math.sqrt(dx * dx + dy * dy + dz * dz))


def runtime_override_capability() -> dict[str, Any]:
    return {
        "supports_position_override": True,
        "supports_rotation_override": True,
        "supports_fov_override": False,
        "requires_env_flag": "GMDISTURB_SCENE_CAMERA_OVERRIDE=1",
        "override_fields": [
            "GMDISTURB_SCENE_CAMERA_POS",
            "GMDISTURB_SCENE_CAMERA_ROT",
        ],
    }


def evaluate_candidate(
    *,
    cam_pos: Sequence[float],
    cam_rot: Sequence[float],
    body_rows: dict[int, dict[str, Any]],
    prior_cam_pos: Sequence[float],
) -> dict[str, Any]:
    rec220 = body_rows[TARGET_STEPS[0]]
    rec330 = body_rows[TARGET_STEPS[1]]
    links220 = [rec220["g1_bodies"][k] for k in TARGET_LINKS]
    links330 = [rec330["g1_bodies"][k] for k in TARGET_LINKS]
    s220 = evaluate_step(links220, cam_pos)
    s330 = evaluate_step(links330, cam_pos)

    anchor_eval = evaluate_anchors(cam_pos)
    sep = _centroid_distance(s220.centroid_uv, s330.centroid_uv)
    gate_sep = bool(sep is not None and sep >= MIN_CENTROID_SEPARATION_PX)
    gate_all = (
        s220.gate_links
        and s220.gate_clipping
        and s220.gate_roi_area
        and s330.gate_links
        and s330.gate_clipping
        and s330.gate_roi_area
        and gate_sep
        and anchor_eval["pass"]
    )
    delta = _camera_delta(cam_pos, prior_cam_pos)

    # Deterministic fail-first ranking key.
    failed = int(not gate_all)
    slack_links = min(s220.links_visible_margin, s330.links_visible_margin) - MIN_LINKS_IN_FRAME
    slack_clip = MAX_CLIPPING_RATIO - max(s220.clipping_ratio, s330.clipping_ratio)
    slack_area = min(s220.roi_area_fraction, s330.roi_area_fraction) - MIN_ROI_AREA_FRAC
    slack_sep = (sep - MIN_CENTROID_SEPARATION_PX) if sep is not None else -1.0e9
    score = (
        float(slack_links) * 100.0
        + float(slack_clip) * 200.0
        + float(slack_area) * 300.0
        + float(slack_sep) * 1.0
        - float(delta) * 10.0
    )
    rank_key = (
        failed,
        -round(score, 6),
        round(delta, 6),
        round(float(cam_pos[0]), 6),
        round(float(cam_pos[1]), 6),
        round(float(cam_pos[2]), 6),
    )

    return {
        "cam_pos": [float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])],
        "cam_rot": [float(cam_rot[0]), float(cam_rot[1]), float(cam_rot[2]), float(cam_rot[3])],
        "step_220": {
            "links_visible_margin": s220.links_visible_margin,
            "links_visible_raw": s220.links_visible_raw,
            "clipping_ratio": s220.clipping_ratio,
            "roi_area_fraction": s220.roi_area_fraction,
            "centroid_uv": list(s220.centroid_uv) if s220.centroid_uv else None,
            "gate_links": s220.gate_links,
            "gate_clipping": s220.gate_clipping,
            "gate_roi_area": s220.gate_roi_area,
        },
        "step_330": {
            "links_visible_margin": s330.links_visible_margin,
            "links_visible_raw": s330.links_visible_raw,
            "clipping_ratio": s330.clipping_ratio,
            "roi_area_fraction": s330.roi_area_fraction,
            "centroid_uv": list(s330.centroid_uv) if s330.centroid_uv else None,
            "gate_links": s330.gate_links,
            "gate_clipping": s330.gate_clipping,
            "gate_roi_area": s330.gate_roi_area,
        },
        "anchors": anchor_eval,
        "centroid_separation_px_220_330": sep,
        "gate_centroid_separation": gate_sep,
        "gate_all": gate_all,
        "camera_delta_from_prior_m": delta,
        "ranking_score": float(score),
        "_rank_key": rank_key,
    }


def run_search(
    *,
    body_pose_jsonl: Path | str,
    prior_camera_pos: Sequence[float] = DEFAULT_SCENE_CAMERA_POS,
    prior_camera_rot: Sequence[float] = DEFAULT_SCENE_CAMERA_ROT,
    max_ranked_candidates: int = 300,
) -> dict[str, Any]:
    rows = load_body_pose_steps(body_pose_jsonl)
    for st in TARGET_STEPS:
        if st not in rows:
            raise ValueError(f"required step missing in body_pose_jsonl: {st}")
        if "g1_bodies" not in rows[st]:
            raise ValueError(f"missing g1_bodies at step {st}")

    xs = _frange(*SEARCH_X)
    ys = _frange(*SEARCH_Y)
    zs = _frange(*SEARCH_Z)
    candidates: list[dict[str, Any]] = []
    for x in xs:
        for y in ys:
            for z in zs:
                candidates.append(
                    evaluate_candidate(
                        cam_pos=(x, y, z),
                        cam_rot=prior_camera_rot,
                        body_rows=rows,
                        prior_cam_pos=prior_camera_pos,
                    )
                )
    candidates.sort(key=lambda c: c["_rank_key"])
    for c in candidates:
        c.pop("_rank_key", None)
    ranked_export = candidates[: max(1, int(max_ranked_candidates))]

    best = candidates[0] if candidates else None
    runtime_cap = runtime_override_capability()
    can_express = bool(
        runtime_cap["supports_position_override"]
        and runtime_cap["supports_rotation_override"]
        and (best is not None)
    )
    recommend = bool(best is not None and best["gate_all"] and can_express)
    verdict = "GO" if recommend else "NO_GO"
    selected = best if recommend else None
    return {
        "version": "V1-M1Y",
        "mode": "offline_only_design",
        "input": {
            "body_pose_jsonl": str(body_pose_jsonl),
            "target_steps": list(TARGET_STEPS),
            "prior_camera_pos": [float(prior_camera_pos[0]), float(prior_camera_pos[1]), float(prior_camera_pos[2])],
            "prior_camera_rot": [float(prior_camera_rot[0]), float(prior_camera_rot[1]), float(prior_camera_rot[2]), float(prior_camera_rot[3])],
            "search_bounds": {
                "x": list(SEARCH_X),
                "y": list(SEARCH_Y),
                "z": list(SEARCH_Z),
            },
            "uncertainty_margin_px": UNCERTAINTY_MARGIN_PX,
        },
        "runtime_override_capability": runtime_cap,
        "runtime_override_can_express_selected_pose": can_express,
        "gates": {
            "min_links_in_frame": MIN_LINKS_IN_FRAME,
            "max_clipping_ratio": MAX_CLIPPING_RATIO,
            "min_roi_area_fraction": MIN_ROI_AREA_FRAC,
            "min_centroid_separation_px": MIN_CENTROID_SEPARATION_PX,
            "anchor_margin_px": ANCHOR_MARGIN_PX,
        },
        "candidate_count": len(candidates),
        "ranked_candidates": ranked_export,
        "ranked_candidates_truncated": len(ranked_export) < len(candidates),
        "recommended_pose": selected,
        "verdict": verdict,
    }


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
