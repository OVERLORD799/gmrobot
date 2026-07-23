#!/usr/bin/env python3
"""Postrun analyzer for V1-E2G.1 preflight frame visibility/ROI/projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scene_camera_override import g1_roi_from_body_points, project_world_to_pixel


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


def analyze_postrun(result_dir: Path) -> dict[str, Any]:
    meta = result_dir / "meta"
    frame_inventory = _load_json(meta / "frame_inventory.json")
    camera = _load_json(meta / "camera_pose.json")
    body_rows = _load_body_pose_rows(meta / "body_poses.jsonl")
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

    return {
        "milestone": "V1-E2G.1",
        "result_dir": str(result_dir),
        "camera_pos": [float(x) for x in cam_pos],
        "frame_count": len(frames),
        "frames": frames,
        "max_projected_actual_displacement_px": max((f["projected_actual_displacement_px"] for f in frames), default=0.0),
        "max_roi_area_fraction": max((f["roi_area_fraction"] for f in frames), default=0.0),
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
