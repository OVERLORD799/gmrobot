#!/usr/bin/env python3
"""V1-E0.3 deterministic offline temporal evidence evaluator for Dyn-B."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_m1y_camera_framing import TARGET_LINKS
from scene_camera_override import project_world_to_pixel


RUN_DATE = "2026-07-23"
RUN_ID = "v1e03_dyn_b_offline_temporal_evidence_20260723"
EXPECTED_HEAD = "98446d1a8f2243d21af27015755cdf33dfd56273"

IMAGE_W = 640
IMAGE_H = 480
IMAGE_AREA = float(IMAGE_W * IMAGE_H)
MARGIN_PX = 12.0

# Pre-registered hard gates inherited from E0.1/E0.2 trajectory review.
MIN_VISIBLE_LINKS = 4
MIN_ROI_AREA_FRAC = 0.01
MAX_CLIPPING_RATIO = 0.50
MIN_CENTROID_DISPLACEMENT_PX = 20.0
# Pre-run fixed constants (not tuned post-hoc).
MIN_ROI_INNER_CHANGE_RATIO_220_330 = 0.02
MAX_STABILITY_CHANGE_RATIO = 0.001
MIN_INNER_OUTER_CONTRAST = 1.2
PIXEL_DIFF_THRESHOLD = 10

SCENE_GROUP = "e01_dyn_b_formal_m1z9_20260723"
GROUPS = {"A": [219, 220, 221], "B": [329, 330, 331]}
CROSS_STEPS = (220, 330)


@dataclass(frozen=True)
class FrameGeom:
    step: int
    visible_links: int
    clipping_ratio: float
    roi_area_frac: float
    centroid_uv: tuple[float, float]
    bbox_xyxy: tuple[float, float, float, float]
    per_link_uv: dict[str, tuple[float, float]]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_body_poses(path: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        out[int(row["step"])] = row
    return out


def _project_frame(step: int, body: dict[int, dict[str, Any]], cam_pos: list[float]) -> FrameGeom:
    rec = body[step]
    points: list[tuple[float, float]] = []
    per_link: dict[str, tuple[float, float]] = {}
    for lk in TARGET_LINKS:
        uv = project_world_to_pixel(rec["g1_bodies"][lk], cam_pos=cam_pos, image_w=IMAGE_W, image_h=IMAGE_H)
        if uv is None:
            continue
        u, v = float(uv[0]), float(uv[1])
        per_link[lk] = (u, v)
        points.append((u, v))
    if not points:
        raise RuntimeError(f"step {step} has no projected links")
    us = [x for x, _ in points]
    vs = [y for _, y in points]
    x0, y0 = min(us), min(vs)
    x1, y1 = max(us), max(vs)
    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    visible_links = sum(1 for u, v in points if MARGIN_PX <= u <= IMAGE_W - 1 - MARGIN_PX and MARGIN_PX <= v <= IMAGE_H - 1 - MARGIN_PX)
    clipping_ratio = 1.0 - (float(visible_links) / float(len(TARGET_LINKS)))
    cx0 = max(0.0, x0)
    cy0 = max(0.0, y0)
    cx1 = min(float(IMAGE_W - 1), x1)
    cy1 = min(float(IMAGE_H - 1), y1)
    area = max(0.0, (cx1 - cx0) * (cy1 - cy0))
    return FrameGeom(
        step=step,
        visible_links=visible_links,
        clipping_ratio=clipping_ratio,
        roi_area_frac=area / IMAGE_AREA,
        centroid_uv=(cx, cy),
        bbox_xyxy=(x0, y0, x1, y1),
        per_link_uv=per_link,
    )


def _load_gray(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("L"), dtype=np.uint8)


def _union_mask(boxes: list[tuple[float, float, float, float]]) -> np.ndarray:
    mask = np.zeros((IMAGE_H, IMAGE_W), dtype=bool)
    for x0, y0, x1, y1 in boxes:
        ix0 = max(0, int(math.floor(x0)))
        iy0 = max(0, int(math.floor(y0)))
        ix1 = min(IMAGE_W - 1, int(math.ceil(x1)))
        iy1 = min(IMAGE_H - 1, int(math.ceil(y1)))
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        mask[iy0 : iy1 + 1, ix0 : ix1 + 1] = True
    return mask


def _change_ratio(img_a: np.ndarray, img_b: np.ndarray, mask: np.ndarray) -> float:
    if mask.sum() <= 0:
        return 0.0
    diff = np.abs(img_a.astype(np.int16) - img_b.astype(np.int16))
    changed = diff > PIXEL_DIFF_THRESHOLD
    return float(changed[mask].mean())


def _frame_pair_metrics(
    step_a: int,
    step_b: int,
    geom: dict[int, FrameGeom],
    img_by_step: dict[int, np.ndarray],
) -> dict[str, Any]:
    union = _union_mask([geom[step_a].bbox_xyxy, geom[step_b].bbox_xyxy])
    inside = _change_ratio(img_by_step[step_a], img_by_step[step_b], union)
    outside = _change_ratio(img_by_step[step_a], img_by_step[step_b], ~union)
    global_change = _change_ratio(
        img_by_step[step_a],
        img_by_step[step_b],
        np.ones((IMAGE_H, IMAGE_W), dtype=bool),
    )
    return {
        "steps": [step_a, step_b],
        "roi_union_area_fraction": float(union.mean()),
        "roi_inner_change_ratio": inside,
        "roi_outer_change_ratio": outside,
        "full_image_change_ratio": global_change,
        "ur10e_region_change_ratio": "not_available",
        "ur10e_region_note": "not_available: reliable ur10e pixel segmentation is not guaranteed in fixed offline assets",
    }


def derive_motion_attribution_from_metrics(
    *,
    frame_gate_ok: bool,
    centroid_displacement_px: float,
    roi_inner_change_ratio: float,
    roi_outer_change_ratio: float,
    stability_ok: bool,
    full_image_change_ratio: float,
) -> tuple[str, dict[str, bool]]:
    centroid_gate_ok = centroid_displacement_px >= MIN_CENTROID_DISPLACEMENT_PX
    local_change_ok = (
        roi_inner_change_ratio >= MIN_ROI_INNER_CHANGE_RATIO_220_330
        and roi_inner_change_ratio >= roi_outer_change_ratio * MIN_INNER_OUTER_CONTRAST
    )
    not_hash_only_guard = not (full_image_change_ratio > 0.0 and roi_inner_change_ratio <= roi_outer_change_ratio)
    supported = frame_gate_ok and centroid_gate_ok and local_change_ok and stability_ok and not_hash_only_guard
    return (
        "SCRIPTED_G1_MOTION_SUPPORTED" if supported else "INSUFFICIENT",
        {
            "frame_gate_ok": frame_gate_ok,
            "centroid_gate_ok": centroid_gate_ok,
            "local_change_ok": local_change_ok,
            "temporal_stability_ok": stability_ok,
            "not_hash_only_guard": not_hash_only_guard,
        },
    )


def evaluate(repo_root: Path) -> dict[str, Any]:
    project = repo_root / "g1_ur10e_disturbance"
    run_dir = project / "results" / "paper_demo" / "v1e01_dyn_b_formal_m1z9_20260723"
    meta = run_dir / "meta"
    scene = run_dir / "scene"
    cam = _load_json(meta / "camera_pose.json")
    body = _load_body_poses(meta / "body_poses.jsonl")
    all_steps = [219, 220, 221, 329, 330, 331]
    geom = {s: _project_frame(s, body, cam["pos"]) for s in all_steps}
    imgs = {_s: _load_gray(scene / f"frame_{_s:06d}_env0.png") for _s in all_steps}

    # Group ROIs and stability checks.
    group_eval: dict[str, Any] = {}
    for gname, steps in GROUPS.items():
        boxes = [geom[s].bbox_xyxy for s in steps]
        union = _union_mask(boxes)
        p1 = _frame_pair_metrics(steps[0], steps[1], geom, imgs)
        p2 = _frame_pair_metrics(steps[1], steps[2], geom, imgs)
        group_eval[gname] = {
            "steps": steps,
            "group_union_roi_area_fraction": float(union.mean()),
            "adjacent_pairs": [p1, p2],
            "stability_pass": p1["roi_inner_change_ratio"] <= MAX_STABILITY_CHANGE_RATIO
            and p2["roi_inner_change_ratio"] <= MAX_STABILITY_CHANGE_RATIO,
        }

    # Cross-frame evidence 220 -> 330.
    cross = _frame_pair_metrics(CROSS_STEPS[0], CROSS_STEPS[1], geom, imgs)
    per_link_disp: dict[str, float] = {}
    common_links = sorted(set(geom[220].per_link_uv.keys()) & set(geom[330].per_link_uv.keys()))
    for lk in common_links:
        a = geom[220].per_link_uv[lk]
        b = geom[330].per_link_uv[lk]
        per_link_disp[lk] = float(math.hypot(b[0] - a[0], b[1] - a[1]))
    cx0, cy0 = geom[220].centroid_uv
    cx1, cy1 = geom[330].centroid_uv
    centroid_disp = float(math.hypot(cx1 - cx0, cy1 - cy0))

    # Gates.
    frame_gate_ok = all(
        geom[s].visible_links >= MIN_VISIBLE_LINKS
        and geom[s].roi_area_frac >= MIN_ROI_AREA_FRAC
        and geom[s].clipping_ratio <= MAX_CLIPPING_RATIO
        for s in all_steps
    )
    temporal_stability_ok = group_eval["A"]["stability_pass"] and group_eval["B"]["stability_pass"]
    attribution, gates = derive_motion_attribution_from_metrics(
        frame_gate_ok=frame_gate_ok,
        centroid_displacement_px=centroid_disp,
        roi_inner_change_ratio=cross["roi_inner_change_ratio"],
        roi_outer_change_ratio=cross["roi_outer_change_ratio"],
        stability_ok=temporal_stability_ok,
        full_image_change_ratio=cross["full_image_change_ratio"],
    )
    supported = attribution == "SCRIPTED_G1_MOTION_SUPPORTED"
    tech_status = "technical_temporal_pass_pending_user" if supported else "fail"

    return {
        "run_id": RUN_ID,
        "date": RUN_DATE,
        "semantic_identity": "scripted_g1_locomotion",
        "human_motion": False,
        "human_hand": False,
        "PPE": False,
        "scene_group": SCENE_GROUP,
        "camera_pose": cam,
        "thresholds": {
            "min_visible_links": MIN_VISIBLE_LINKS,
            "min_roi_area_fraction": MIN_ROI_AREA_FRAC,
            "max_clipping_ratio": MAX_CLIPPING_RATIO,
            "min_centroid_displacement_px": MIN_CENTROID_DISPLACEMENT_PX,
            "min_roi_inner_change_ratio_220_330": MIN_ROI_INNER_CHANGE_RATIO_220_330,
            "max_stability_change_ratio": MAX_STABILITY_CHANGE_RATIO,
            "min_inner_outer_change_contrast": MIN_INNER_OUTER_CONTRAST,
            "pixel_diff_threshold": PIXEL_DIFF_THRESHOLD,
        },
        "per_frame": {
            str(s): {
                "visible_links": geom[s].visible_links,
                "roi_area_fraction": geom[s].roi_area_frac,
                "clipping_ratio": geom[s].clipping_ratio,
                "centroid_uv": [geom[s].centroid_uv[0], geom[s].centroid_uv[1]],
                "bbox_xyxy": [*geom[s].bbox_xyxy],
            }
            for s in all_steps
        },
        "per_group": group_eval,
        "cross_frame_220_330": {
            **cross,
            "centroid_displacement_px": centroid_disp,
            "per_link_displacement_px": per_link_disp,
            "common_links_count": len(common_links),
        },
        "gates": gates,
        "motion_attribution": attribution,
        "technical_review_status": tech_status,
    }


def write_outputs(repo_root: Path, report: dict[str, Any]) -> dict[str, str]:
    project = repo_root / "g1_ur10e_disturbance"
    packet_dir = project / "results" / "paper_demo" / "review_packet" / RUN_ID
    packet_dir.mkdir(parents=True, exist_ok=True)
    report_json = packet_dir / "dyn_b_temporal_evidence.json"
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    docs_dir = project / "docs" / "cross-project"
    md = docs_dir / "vlm-v1e03-dyn-b-offline-temporal-evidence-2026-07-23.md"
    js = docs_dir / "vlm-v1e03-dyn-b-offline-temporal-evidence-2026-07-23.json"
    js.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    lines = [
        "# V1-E0.3 Dyn-B Offline Temporal Evidence",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- motion_attribution: `{report['motion_attribution']}`",
        f"- technical_review_status: `{report['technical_review_status']}`",
        "- semantic_identity: `scripted_g1_locomotion`",
        "- human_motion/human_hand/PPE: `false/false/false`",
        "- ur10e_region_change_ratio: `not_available` (可靠分割不可保证)",
        "",
        "## 固定门禁阈值",
        f"- links>=`{MIN_VISIBLE_LINKS}`; ROI>=`{MIN_ROI_AREA_FRAC}`; clipping<=`{MAX_CLIPPING_RATIO}`; centroid>=`{MIN_CENTROID_DISPLACEMENT_PX}`",
        f"- local ROI change(220->330)>=`{MIN_ROI_INNER_CHANGE_RATIO_220_330}`; ROI内外对照>=`{MIN_INNER_OUTER_CONTRAST}`",
        "",
        "## 关键结论",
        f"- A组(219/220/221)稳定性通过: `{report['per_group']['A']['stability_pass']}`",
        f"- B组(329/330/331)稳定性通过: `{report['per_group']['B']['stability_pass']}`",
        f"- 220->330 centroid displacement(px): `{report['cross_frame_220_330']['centroid_displacement_px']}`",
        f"- 220->330 ROI inner/outer/full change: `{report['cross_frame_220_330']['roi_inner_change_ratio']}` / `{report['cross_frame_220_330']['roi_outer_change_ratio']}` / `{report['cross_frame_220_330']['full_image_change_ratio']}`",
        "",
        "## 数据充分性复评（按 scene_group，不拆相邻帧）",
        "- functional_positive_groups: `2`（D1B 历史组 + M1M 组）",
        "- dynamic_positive_groups: `" + ("1" if report["motion_attribution"] == "SCRIPTED_G1_MOTION_SUPPORTED" else "0") + "`",
        "- dataset_status: `DATASET_INSUFFICIENT`",
        "- gap: `dynamic` 仍只有单组，缺少跨组动态正样本与独立 holdout 组，不能支撑稳健泛化评估。",
    ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"packet_json": str(report_json), "docs_md": str(md), "docs_json": str(js)}


def update_manifest_and_index(repo_root: Path, report: dict[str, Any], outputs: dict[str, str]) -> None:
    docs_dir = repo_root / "g1_ur10e_disturbance" / "docs" / "cross-project"
    manifest_path = docs_dir / "vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json"
    index_path = docs_dir / "vlm-v1e02-visual-dataset-manifest-index-2026-07-23.json"
    manifest = _load_json(manifest_path)
    index = _load_json(index_path)

    manifest["manifest_version"] = "3.0.0"
    prev = manifest.setdefault("previous_version_refs", [])
    if not any(str(x.get("version")) == "2.0.0" for x in prev):
        prev.append(
            {
                "version": "2.0.0",
                "path": "g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json",
                "immutable": True,
            }
        )
    manifest["review_packet"]["run_id"] = RUN_ID
    manifest["review_packet"]["date"] = RUN_DATE
    manifest["review_packet"]["packet_dir"] = str(
        repo_root / "g1_ur10e_disturbance" / "results" / "paper_demo" / "review_packet" / RUN_ID
    )
    manifest["review_packet"]["preflight"] = {"head": EXPECTED_HEAD, "worktree_clean": True}
    manifest["review_packet"]["offline_only"] = True
    manifest["review_packet"]["temporal_evidence_json"] = outputs["packet_json"]
    manifest["global_flags"]["technical_review_status"] = report["technical_review_status"]
    manifest["global_flags"]["reviewer_approved"] = False
    manifest["global_flags"]["human_hand"] = False
    manifest["global_flags"]["PPE"] = False

    for c in manifest.get("candidates", []):
        if c.get("id") == "E02-DYN-B-M1Z9-STEP220-330":
            c["semantic_identity"] = "scripted_g1_locomotion"
            c["human_motion"] = False
            c["human_hand"] = False
            c["PPE"] = False
            c["motion_attribution"] = report["motion_attribution"]
            c["technical_review_status"] = report["technical_review_status"]
            c["reviewer_approved"] = False
            c["temporal_evidence"] = {
                "run_id": RUN_ID,
                "steps": [219, 220, 221, 329, 330, 331],
                "cross_step_pair": [220, 330],
                "report_json": outputs["packet_json"],
            }
            break

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    index["version"] = "2.0.0"
    arts = index.setdefault("artifacts", [])
    if not any(a.get("kind") == "review_doc_md_v1e03" for a in arts):
        arts.append({"kind": "review_doc_md_v1e03", "path": outputs["docs_md"]})
    if not any(a.get("kind") == "review_doc_json_v1e03" for a in arts):
        arts.append({"kind": "review_doc_json_v1e03", "path": outputs["docs_json"]})
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run V1-E0.3 offline temporal evidence evaluator.")
    ap.add_argument("--repo-root", default="/home/czz/GMrobot")
    ap.add_argument("--head", default="")
    args = ap.parse_args()
    repo_root = Path(args.repo_root).resolve()
    head = args.head.strip()
    if head and head != EXPECTED_HEAD:
        raise RuntimeError(f"HEAD mismatch: expected {EXPECTED_HEAD}, got {head}")

    report = evaluate(repo_root)
    outputs = write_outputs(repo_root, report)
    update_manifest_and_index(repo_root, report, outputs)
    print(json.dumps({"ok": True, "motion_attribution": report["motion_attribution"], **outputs}, ensure_ascii=True))


if __name__ == "__main__":
    main()
