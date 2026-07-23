#!/usr/bin/env python3
"""Offline motion-attribution audit for V1-E2D Dyn-C capture."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scene_camera_override import g1_roi_from_body_points, project_world_to_pixel


CAPTURE_PRIMARY = (240, 310)
CAPTURE_STABILITY = (239, 241, 309, 311)
ROI_DIFF_THRESHOLD = 18.0  # 0..255 luma diff threshold


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_body_pose_jsonl(path: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[int(row["step"])] = row
    return out


def _read_steps_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_gray(path: Path) -> np.ndarray:
    rgb = np.array(Image.open(path).convert("RGB"), dtype=np.float32)
    return (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.float32)


def _bbox_from_roi(roi: dict[str, Any], w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi["bbox_xyxy"]
    xi0 = max(0, min(w - 1, int(math.floor(x0))))
    yi0 = max(0, min(h - 1, int(math.floor(y0))))
    xi1 = max(0, min(w, int(math.ceil(x1))))
    yi1 = max(0, min(h, int(math.ceil(y1))))
    return xi0, yi0, xi1, yi1


def _equal_area_square(center_u: float, center_v: float, area: float, w: int, h: int) -> tuple[int, int, int, int]:
    side = max(8.0, math.sqrt(max(1.0, float(area))))
    hs = side / 2.0
    x0 = int(max(0, math.floor(center_u - hs)))
    y0 = int(max(0, math.floor(center_v - hs)))
    x1 = int(min(w, math.ceil(center_u + hs)))
    y1 = int(min(h, math.ceil(center_v + hs)))
    if x1 <= x0:
        x1 = min(w, x0 + 1)
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    return x0, y0, x1, y1


def _best_global_shift(gray_a: np.ndarray, gray_b: np.ndarray, mask_exclude: np.ndarray, max_shift: int = 5) -> tuple[int, int]:
    h, w = gray_a.shape
    valid = ~mask_exclude
    best = (0, 0)
    best_score = float("inf")
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            x0a = max(0, dx)
            x1a = min(w, w + dx)
            y0a = max(0, dy)
            y1a = min(h, h + dy)
            x0b = max(0, -dx)
            x1b = min(w, w - dx)
            y0b = max(0, -dy)
            y1b = min(h, h - dy)
            if x1a <= x0a or y1a <= y0a:
                continue
            va = valid[y0a:y1a, x0a:x1a]
            if not np.any(va):
                continue
            a = gray_a[y0a:y1a, x0a:x1a]
            b = gray_b[y0b:y1b, x0b:x1b]
            diff = np.abs(a - b)[va]
            score = float(np.mean(diff))
            if score < best_score:
                best_score = score
                best = (dx, dy)
    return best


def _changed_fraction(diff: np.ndarray, bbox: tuple[int, int, int, int], threshold: float = ROI_DIFF_THRESHOLD) -> float:
    x0, y0, x1, y1 = bbox
    patch = diff[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    return float(np.mean(patch >= threshold))


def _roi_from_body_record(record: dict[str, Any], camera_pos: list[float], image_w: int, image_h: int) -> dict[str, Any]:
    points = list(record.get("g1_bodies", {}).values())
    return g1_roi_from_body_points(points, cam_pos=camera_pos, image_w=image_w, image_h=image_h, pad_px=12.0)


def audit(result_dir: Path) -> dict[str, Any]:
    meta = result_dir / "meta"
    scene = result_dir / "scene"
    safety = result_dir / "safety_logs"
    frame_inventory = _load_json(meta / "frame_inventory.json")
    camera = _load_json(meta / "camera_pose.json")
    body = _load_body_pose_jsonl(meta / "body_poses.jsonl")
    raw_metrics = _load_json(meta / "computed_metrics.json")
    phase3_rows = _read_steps_csv(safety / "phase3_steps.csv")

    frame_map = {int(r["step"]): Path(r["path"]) for r in frame_inventory["frames"]}
    image_w, image_h = 640, 480
    camera_pos = camera["pos"]

    roi_by_step: dict[int, dict[str, Any]] = {}
    for s in (*CAPTURE_STABILITY, *CAPTURE_PRIMARY):
        if s not in body:
            continue
        roi_by_step[s] = _roi_from_body_record(body[s], camera_pos, image_w, image_h)

    # 读取主对比帧 (240 -> 310)
    a = _to_gray(frame_map[CAPTURE_PRIMARY[0]])
    b = _to_gray(frame_map[CAPTURE_PRIMARY[1]])
    g1_roi = roi_by_step[CAPTURE_PRIMARY[0]]
    g1_bbox = _bbox_from_roi(g1_roi, image_w, image_h)

    g1_mask = np.zeros_like(a, dtype=bool)
    x0, y0, x1, y1 = g1_bbox
    g1_mask[y0:y1, x0:x1] = True
    shift = _best_global_shift(a, b, g1_mask, max_shift=5)

    # 在最佳全局平移下重新计算差分
    dx, dy = shift
    aa = a[max(0, dy):min(image_h, image_h + dy), max(0, dx):min(image_w, image_w + dx)]
    bb = b[max(0, -dy):min(image_h, image_h - dy), max(0, -dx):min(image_w, image_w - dx)]
    diff = np.abs(aa - bb)
    diff_full = np.zeros_like(a)
    diff_full[max(0, dy):min(image_h, image_h + dy), max(0, dx):min(image_w, image_w + dx)] = diff

    g1_change = _changed_fraction(diff_full, g1_bbox)

    ee = body[CAPTURE_PRIMARY[0]].get("ur10e_ee", [0.0, 0.0, 0.0])
    ee_uv = project_world_to_pixel(ee, cam_pos=camera_pos, image_w=image_w, image_h=image_h)
    if ee_uv is None:
        ur10_bbox = (0, 0, 8, 8)
    else:
        ur10_bbox = _equal_area_square(float(ee_uv[0]), float(ee_uv[1]), g1_roi["roi_area_px2"], image_w, image_h)
    ur10_change = _changed_fraction(diff_full, ur10_bbox)

    # 控制 ROI：固定左上角等面积窗口，避开 G1
    side = int(max(8, round(math.sqrt(max(1.0, g1_roi["roi_area_px2"])))))
    ctrl_bbox = (8, 8, min(image_w, 8 + side), min(image_h, 8 + side))
    ctrl_change = _changed_fraction(diff_full, ctrl_bbox)

    # 相邻帧静稳性（同批次 sha 相同通常意味着静止）
    inv = {int(r["step"]): r for r in frame_inventory["frames"]}
    adjacent_equal = {
        "239_240_sha_equal": inv[239]["sha256"] == inv[240]["sha256"],
        "240_241_sha_equal": inv[240]["sha256"] == inv[241]["sha256"],
        "309_310_sha_equal": inv[309]["sha256"] == inv[310]["sha256"],
        "310_311_sha_equal": inv[310]["sha256"] == inv[311]["sha256"],
    }

    # capture step / sim step / policy step 对齐：本 run 的 steps.csv 为 progress_interval 采样，无法直接看到 240/310
    logged_steps = [int(r["step"]) for r in phase3_rows if str(r.get("step", "")).strip() != ""]
    nearest = {
        240: min(logged_steps, key=lambda s: abs(s - 240)),
        310: min(logged_steps, key=lambda s: abs(s - 310)),
    }
    row_by_step = {int(r["step"]): r for r in phase3_rows if str(r.get("step", "")).strip() != ""}

    ur10_delta = np.array(body[310]["ur10e_ee"], dtype=float) - np.array(body[240]["ur10e_ee"], dtype=float)
    g1_root_delta = np.array(body[310]["g1_root"], dtype=float) - np.array(body[240]["g1_root"], dtype=float)
    g1_root_xy_delta_m = float(np.linalg.norm(g1_root_delta[:2]))

    g1_links = sorted(set(body[240].get("g1_bodies", {}).keys()) & set(body[310].get("g1_bodies", {}).keys()))
    g1_link_delta = {
        lk: float(np.linalg.norm(np.array(body[310]["g1_bodies"][lk], dtype=float) - np.array(body[240]["g1_bodies"][lk], dtype=float)))
        for lk in g1_links
    }
    max_link_delta = max(g1_link_delta.values()) if g1_link_delta else float("nan")

    reliability = "OK"
    unknowns: list[str] = []
    if g1_roi.get("n_projected", 0) < 6 or g1_roi.get("roi_area_px2", 0.0) < 0.008 * image_w * image_h:
        reliability = "LOW"
        unknowns.append("G1 ROI reliability is low from sparse projected links; semantic/instance mask required next run.")
    if 240 not in row_by_step or 310 not in row_by_step:
        unknowns.append("phase3_steps.csv does not log exact capture steps (240/310); UR10 stage/action at capture is UNKNOWN.")

    visible_g1_motion = bool(g1_change >= max(ur10_change * 1.5, ctrl_change * 1.5, 0.018))
    verdict = "REDESIGN_READY" if not visible_g1_motion else "BLOCKED"

    return {
        "milestone": "V1-E2D.1",
        "result_dir": str(result_dir),
        "user_decision": {
            "user_rejected": True,
            "reviewer_approved": False,
            "reason": "no_visible_discriminable_g1_motion_in_rgb_main_frames",
        },
        "raw_e2d_metrics_preserved": raw_metrics.get("metrics", {}),
        "frame_alignment": {
            "capture_steps_primary": list(CAPTURE_PRIMARY),
            "stability_steps": list(CAPTURE_STABILITY),
            "adjacent_sha_equal": adjacent_equal,
            "nearest_logged_step_for_capture": nearest,
            "capture_step_ur10_stage": {
                "240": "UNKNOWN" if 240 not in row_by_step else row_by_step[240].get("stage", ""),
                "310": "UNKNOWN" if 310 not in row_by_step else row_by_step[310].get("stage", ""),
                "nearest_240_stage": row_by_step[nearest[240]].get("stage", "UNKNOWN"),
                "nearest_310_stage": row_by_step[nearest[310]].get("stage", "UNKNOWN"),
            },
        },
        "actual_motion_evidence": {
            "g1_root_delta_xyz_m_240_to_310": [float(x) for x in g1_root_delta.tolist()],
            "g1_root_delta_xy_norm_m_240_to_310": g1_root_xy_delta_m,
            "g1_link_max_displacement_m_240_to_310": max_link_delta,
            "ur10e_ee_delta_xyz_m_240_to_310": [float(x) for x in ur10_delta.tolist()],
        },
        "pixel_attribution_audit": {
            "method": "g1_link_roi + global_alignment + roi_delta_vs_equal_area_ur10_and_control",
            "global_shift_dxdy_px": [int(dx), int(dy)],
            "roi_reliability": reliability,
            "g1_roi_bbox_240_xyxy": [float(x) for x in g1_roi["bbox_xyxy"]] if g1_roi.get("bbox_xyxy") else None,
            "g1_roi_area_fraction": float(g1_roi.get("roi_area_px2", 0.0) / float(image_w * image_h)),
            "change_fraction_threshold": ROI_DIFF_THRESHOLD,
            "g1_roi_change_fraction": g1_change,
            "ur10_equal_area_change_fraction": ur10_change,
            "control_equal_area_change_fraction": ctrl_change,
            "visible_g1_local_motion": visible_g1_motion,
            "policy": "projected_centroid_alone_is_not_motion_evidence",
        },
        "root_cause_attribution": {
            "projected_centroid_nonzero_but_no_visible_g1_motion": [
                "projected body links can move in world while rendered pixels stay visually unchanged",
                "UR10e motion dominates scene change and can be misattributed as G1 motion",
                "adjacent frame identity indicates each capture neighborhood is visually static",
                "possible ROI occlusion/background confound exists without semantic instance mask",
            ],
            "unknowns": unknowns,
            "requires_next_run_segmentation": bool(unknowns),
        },
        "task_execution_false_but_ur10_moves": {
            "audit": "task_execution=false disables task reward/completion contract but does not freeze UR10 policy stepping",
            "next_contract_required": {
                "freeze_ur10e": True,
                "runtime_gate": {
                    "ur10_action_hash_constant": True,
                    "ur10_joint_delta_abs_max": 0.0,
                    "ur10_ee_delta_abs_max": 0.0,
                },
            },
        },
        "next_dyn_positive_gate_design": {
            "must_pass_all": {
                "g1_actual_root_or_link_displacement": "required",
                "g1_local_pixel_displacement": "required",
                "recommended_actual_center_displacement_px": [40, 60],
                "min_g1_roi_area_fraction": 0.012,
                "adjacent_stability_required": True,
                "primary_pair_visible_change_required": True,
            }
        },
        "manifest_update": {
            "dyn_c_status": "user_rejected_no_visible_g1_motion",
            "count_as_dynamic_positive_group": False,
        },
        "verdict": verdict,
        "unique_next_step_prebuild": {
            "id": "V1-E2E-prebuild-freeze-ur10e-and-instance-mask-contract",
            "summary": "预构建仅验证 freeze_ur10e=true、UR10 action/hash/joint-delta=0 门禁、并强制输出可验证 G1 semantic/instance mask 后再进行下一次单次采集。",
        },
    }


def _to_markdown(report: dict[str, Any]) -> str:
    pix = report["pixel_attribution_audit"]
    lines = [
        "# V1-E2D.1 Dyn-C 纯离线运动归因审计与修复设计",
        "",
        f"- verdict: `{report['verdict']}`",
        "- user_rejected: `true`",
        "- reviewer_approved: `false`",
        "- Dyn-C group status: `user_rejected_no_visible_g1_motion`（不计 dynamic positive）",
        "",
        "## 关键事实",
        f"- raw centroid(240->310): `{report['raw_e2d_metrics_preserved'].get('centroid_240_to_310_px')}`（保留但不单独作为运动证据）",
        f"- g1_root_xy_delta_m(240->310): `{report['actual_motion_evidence']['g1_root_delta_xy_norm_m_240_to_310']:.6f}`",
        f"- ur10e_ee_delta_xyz_m(240->310): `{report['actual_motion_evidence']['ur10e_ee_delta_xyz_m_240_to_310']}`",
        "",
        "## 离线像素归因（ROI对照）",
        f"- global_shift(dx,dy): `{pix['global_shift_dxdy_px']}`",
        f"- G1 ROI change fraction: `{pix['g1_roi_change_fraction']:.6f}`",
        f"- UR10 equal-area ROI change fraction: `{pix['ur10_equal_area_change_fraction']:.6f}`",
        f"- control equal-area ROI change fraction: `{pix['control_equal_area_change_fraction']:.6f}`",
        f"- visible_g1_local_motion: `{pix['visible_g1_local_motion']}`",
        "",
        "## 结论与改造方向",
        "- `task_execution=false` 不等于 UR10 冻结；下一场必须 `freeze_ur10e=true` 并加 action/hash/joint-delta=0 运行时门禁。",
        "- Dyn positive 必须同时满足：G1 实际 root/link 位移 + G1-local pixel 位移（建议 center 40-60px、ROI>=1.2%、相邻稳定、主帧明显变化）。",
        f"- 唯一下一步 prebuild：`{report['unique_next_step_prebuild']['id']}`",
        "",
    ]
    if report["root_cause_attribution"]["unknowns"]:
        lines.append("## UNKNOWN / 证据不足")
        for u in report["root_cause_attribution"]["unknowns"]:
            lines.append(f"- {u}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline Dyn-C motion attribution audit.")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--md-out", required=True)
    args = ap.parse_args()

    report = audit(Path(args.result_dir))
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_out.write_text(_to_markdown(report), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "json_out": str(json_out), "md_out": str(md_out)}))


if __name__ == "__main__":
    main()
