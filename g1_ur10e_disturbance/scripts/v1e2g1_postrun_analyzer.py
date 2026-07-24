#!/usr/bin/env python3
"""Postrun analyzer for V1-E2G.1 preflight frame visibility/ROI/projection."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scene_camera_override import g1_roi_from_body_points, project_world_to_pixel

# V1-E2K user-approved decision (2026-07-24): arm-only settled threshold relaxed
# from 1e-6 to 5e-4 rad (PhysX PD-hold numerical residual, ~0.65mm worst-case EE
# at UR10e reach, far below pixel scale). EE near-zero gate stays mandatory at 1e-6 m.
# See docs/cross-project/vlm-v1e2k-arm-only-threshold-decision-2026-07-24.md
ARM_SETTLED_THRESHOLD_RAD = 5e-4
EE_DISP_THRESHOLD_M = 1e-6
ARM_THRESHOLD_DECISION_DOC = "vlm-v1e2k-arm-only-threshold-decision-2026-07-24"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_body_pose_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    rows.sort(key=lambda r: int(r.get("step", 0)))
    return rows


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _load_runtime_telemetry_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    rows.sort(key=lambda r: int(r.get("sim_step", "0")))
    return rows


def _analyze_ur10_freeze_from_runtime(
    runtime_rows: list[dict[str, Any]],
    *,
    frame_steps: list[int],
    body_rows_by_step: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    if not runtime_rows:
        return {
            "available": False,
            "reason": "runtime_telemetry_missing",
        }
    arm_settled_max = max(
        (_safe_float(r.get("ur10_arm_joint_delta_max_abs_settled"), 0.0) for r in runtime_rows),
        default=0.0,
    )
    arm_norm_max = max(
        (_safe_float(r.get("ur10_arm_joint_delta_norm"), 0.0) for r in runtime_rows),
        default=0.0,
    )
    arm_max_abs = max(
        (_safe_float(r.get("ur10_arm_joint_delta_max_abs"), 0.0) for r in runtime_rows),
        default=0.0,
    )
    arm_joint_max_name = ""
    arm_joint_max_value = 0.0
    arm_settled_joint_max_name = ""
    arm_settled_joint_max_value = 0.0
    arm_joint_abs_by_name_at_max: dict[str, float] = {}
    arm_settled_trace: list[dict[str, Any]] = []
    for row in runtime_rows:
        _cand_name = str(row.get("ur10_arm_joint_delta_max_abs_joint_name", "")).strip()
        _cand_val = _safe_float(row.get("ur10_arm_joint_delta_max_abs_joint_value"), 0.0)
        if abs(_cand_val) >= abs(arm_joint_max_value):
            arm_joint_max_name = _cand_name
            arm_joint_max_value = _cand_val
            raw_json = str(row.get("ur10_arm_joint_delta_abs_by_name_json", "")).strip()
            if raw_json:
                try:
                    parsed = json.loads(raw_json)
                    if isinstance(parsed, dict):
                        arm_joint_abs_by_name_at_max = {str(k): float(v) for k, v in parsed.items()}
                except Exception:
                    arm_joint_abs_by_name_at_max = {}
        settled_name = str(row.get("ur10_arm_joint_delta_max_abs_settled_joint_name", "")).strip()
        settled_val = _safe_float(row.get("ur10_arm_joint_delta_max_abs_settled_joint_value"), 0.0)
        if abs(settled_val) >= abs(arm_settled_joint_max_value):
            arm_settled_joint_max_name = settled_name
            arm_settled_joint_max_value = settled_val
        arm_settled_trace.append(
            {
                "sim_step": int(float(row.get("sim_step", "0"))),
                "arm_joint_delta_max_abs_settled": _safe_float(row.get("ur10_arm_joint_delta_max_abs_settled"), 0.0),
                "arm_joint_delta_max_abs_settled_joint_name": settled_name,
                "arm_joint_delta_max_abs_settled_joint_value": settled_val,
            }
        )
    grip_settled_abs_max = max(
        (abs(_safe_float(r.get("ur10_gripper_joint_delta_settled"), 0.0)) for r in runtime_rows),
        default=0.0,
    )
    selected = "unknown"
    for row in runtime_rows:
        cand = str(row.get("ur10_gripper_selected_state", "")).strip()
        if cand:
            selected = cand
            break
    legacy_settled_max = max(
        (_safe_float(r.get("ur10_joint_delta_max_abs_settled"), 0.0) for r in runtime_rows),
        default=0.0,
    )
    legacy_semantics = ""
    for row in runtime_rows:
        cand = str(row.get("ur10_joint_delta_semantics", "")).strip()
        if cand:
            legacy_semantics = cand
            break

    ee_disp_pairs: list[dict[str, Any]] = []
    sorted_steps = sorted(int(s) for s in frame_steps)
    for idx in range(1, len(sorted_steps)):
        s0 = sorted_steps[idx - 1]
        s1 = sorted_steps[idx]
        r0 = body_rows_by_step.get(s0)
        r1 = body_rows_by_step.get(s1)
        if r0 is None or r1 is None:
            continue
        p0 = r0.get("ur10e_ee")
        p1 = r1.get("ur10e_ee")
        if not isinstance(p0, list) or not isinstance(p1, list) or len(p0) < 3 or len(p1) < 3:
            continue
        dx = float(p1[0]) - float(p0[0])
        dy = float(p1[1]) - float(p0[1])
        dz = float(p1[2]) - float(p0[2])
        ee_disp_pairs.append({"from": s0, "to": s1, "disp_m": float((dx * dx + dy * dy + dz * dz) ** 0.5)})
    ee_disp_settled_max_m = max((float(r["disp_m"]) for r in ee_disp_pairs), default=0.0)

    arm_freeze_threshold_max_abs = ARM_SETTLED_THRESHOLD_RAD
    ee_disp_threshold_m = EE_DISP_THRESHOLD_M
    arm_freeze_qualified = bool(
        arm_settled_max <= arm_freeze_threshold_max_abs and ee_disp_settled_max_m <= ee_disp_threshold_m
    )
    return {
        "available": True,
        "arm_joint_delta_max_abs_max": arm_max_abs,
        "arm_joint_delta_norm_max": arm_norm_max,
        "arm_joint_delta_max_abs_settled_max": arm_settled_max,
        "arm_joint_delta_max_abs_joint_name_at_max": arm_joint_max_name or "unknown",
        "arm_joint_delta_max_abs_joint_value_at_max": float(arm_joint_max_value),
        "arm_joint_delta_abs_by_name_at_max": arm_joint_abs_by_name_at_max,
        "arm_joint_delta_max_abs_settled_joint_name": arm_settled_joint_max_name or "unknown",
        "arm_joint_delta_max_abs_settled_joint_value": float(arm_settled_joint_max_value),
        "arm_settled_trace": arm_settled_trace,
        "gripper_selected_state": selected,
        "gripper_joint_delta_settled_abs_max": grip_settled_abs_max,
        "legacy_joint_delta_max_abs_settled_max": legacy_settled_max,
        "legacy_joint_delta_semantics": legacy_semantics or "missing",
        "ee_disp_pairs_m": ee_disp_pairs,
        "ee_disp_settled_max_m": ee_disp_settled_max_m,
        "arm_freeze_thresholds": {
            "arm_joint_delta_max_abs_settled_max": arm_freeze_threshold_max_abs,
            "ee_disp_settled_max_m": ee_disp_threshold_m,
            "decision_doc": ARM_THRESHOLD_DECISION_DOC,
        },
        "arm_freeze_qualified": arm_freeze_qualified,
    }


def analyze_postrun(result_dir: Path) -> dict[str, Any]:
    meta = result_dir / "meta"
    frame_inventory = _load_json(meta / "frame_inventory.json")
    camera = _load_json(meta / "camera_pose.json")
    body_rows = _load_body_pose_rows(meta / "body_poses.jsonl")
    runtime_rows = _load_runtime_telemetry_rows(result_dir / "safety_logs" / "phase3_runtime_telemetry.csv")
    if not body_rows:
        raise ValueError("body_poses.jsonl has no rows")
    row_by_step = {int(r["step"]): r for r in body_rows}
    img_w, img_h = 640, 480
    cam_pos = camera["pos"]

    frames: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for fr in frame_inventory.get("frames", []):
        step = int(fr["step"])
        rec = row_by_step.get(step)
        if rec is None:
            continue
        links = rec.get("g1_bodies", {})
        projected_links: dict[str, list[float]] = {}
        clipped_links: list[str] = []
        for name, xyz in links.items():
            uv = project_world_to_pixel(xyz, cam_pos=cam_pos, image_w=img_w, image_h=img_h)
            if uv is None:
                continue
            u = float(uv[0])
            v = float(uv[1])
            projected_links[str(name)] = [u, v]
            if u < 0.0 or u >= float(img_w) or v < 0.0 or v >= float(img_h):
                clipped_links.append(str(name))

        roi = g1_roi_from_body_points(
            list(links.values()),
            cam_pos=cam_pos,
            image_w=img_w,
            image_h=img_h,
            pad_px=12.0,
        )
        roi_area_fraction = float(roi.get("roi_area_px2", 0.0) / float(img_w * img_h))
        projected_disp_px = 0.0
        actual_disp_m = 0.0
        if previous is not None:
            disp_px_vals = []
            disp_m_vals = []
            prev_links = previous.get("g1_bodies", {})
            for lk, uv in projected_links.items():
                if lk not in previous.get("projected_links", {}):
                    continue
                uv_prev = previous["projected_links"][lk]
                du = float(uv[0]) - float(uv_prev[0])
                dv = float(uv[1]) - float(uv_prev[1])
                disp_px_vals.append((du * du + dv * dv) ** 0.5)
                if lk in prev_links:
                    p_now = links[lk]
                    p_prev = prev_links[lk]
                    dx = float(p_now[0]) - float(p_prev[0])
                    dy = float(p_now[1]) - float(p_prev[1])
                    dz = float(p_now[2]) - float(p_prev[2])
                    disp_m_vals.append((dx * dx + dy * dy + dz * dz) ** 0.5)
            if disp_px_vals:
                projected_disp_px = float(max(disp_px_vals))
            if disp_m_vals:
                actual_disp_m = float(max(disp_m_vals))

        out = {
            "step": step,
            "frame_id": str(fr.get("path", "")),
            "visible_links": sorted(projected_links.keys()),
            "visible_link_count": len(projected_links),
            "clipped_links": sorted(clipped_links),
            "roi_bbox_xyxy": [float(x) for x in roi.get("bbox_xyxy", [])],
            "roi_area_fraction": roi_area_fraction,
            "projected_actual_displacement_px": projected_disp_px,
            "actual_link_displacement_m": actual_disp_m,
        }
        frames.append(out)
        previous = dict(rec)
        previous["projected_links"] = projected_links

    frame_steps = [int(f.get("step", 0)) for f in frames]
    ur10 = _analyze_ur10_freeze_from_runtime(runtime_rows, frame_steps=frame_steps, body_rows_by_step=row_by_step)

    return {
        "milestone": "V1-E2G.1",
        "result_dir": str(result_dir),
        "camera_pos": [float(x) for x in cam_pos],
        "frame_count": len(frames),
        "frames": frames,
        "max_projected_actual_displacement_px": max((f["projected_actual_displacement_px"] for f in frames), default=0.0),
        "max_roi_area_fraction": max((f["roi_area_fraction"] for f in frames), default=0.0),
        "ur10": ur10,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-E2G.1 postrun analyzer")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--json-out", required=True)
    args = ap.parse_args()
    report = analyze_postrun(Path(args.result_dir))
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "json_out": str(out), "frame_count": report["frame_count"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
