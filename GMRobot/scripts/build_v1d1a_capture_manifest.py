#!/usr/bin/env python3
"""Build V1-D1A capture manifest from RGB PNGs + Layer-1 safety CSV (host/offline)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.control_isolation import control_decision_hash  # noqa: E402
from shadow.v1d1a_capture import (  # noqa: E402
    CAPTURE_PLAN_STEPS,
    MIN_PROXY_PIXEL_AREA,
    MIN_SCREEN_DISPLACEMENT_PX,
    VISUAL_SEMANTIC_RISK,
    _linear_pose_at_step,
    audit_geometry_allow,
    build_capture_manifest,
    build_frame_record,
    trajectory_pose_hash,
)


def _sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_traj(cfg: dict) -> dict:
    t = dict(cfg.get("human_trajectory") or {})
    return {
        "start_pos": list(map(float, t["start_pos"])),
        "end_pos": list(map(float, t["end_pos"])),
        "start_step": int(t.get("start_step", 0)),
        "duration_steps": int(t.get("duration_steps", 200)),
        "hold_steps": int(t.get("hold_steps", 0)),
        "retreat_pos": list(map(float, t["retreat_pos"])) if t.get("retreat_pos") else None,
        "retreat_duration_steps": int(t.get("retreat_duration_steps", 0)),
    }


def _find_episode_csv(safety_log_root: Path) -> Path | None:
    if not safety_log_root.exists():
        return None
    csvs = list(safety_log_root.rglob("episode_*.csv"))
    if not csvs:
        return None
    # Prefer the episode with the most rows (ignore short smoke leftovers).
    def _nrows(p: Path) -> int:
        try:
            return max(0, sum(1 for _ in p.open(encoding="utf-8")) - 1)
        except OSError:
            return 0

    return max(csvs, key=_nrows)


def _read_gate_series(csv_path: Path | None) -> tuple[list[int], list[dict], int]:
    if csv_path is None:
        return [], [], 0
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    g_rules = [int(float(r["g_rule"])) for r in rows if r.get("g_rule") not in ("", None)]
    replan = 0
    for r in rows:
        for key in ("replan_triggered", "replan_event", "replan_applied"):
            val = str(r.get(key, "") or "").strip().lower()
            if val in ("1", "true", "yes"):
                replan += 1
                break
    return g_rules, rows, replan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-dir", type=Path, required=True)
    ap.add_argument("--safety-config", type=Path, required=True)
    ap.add_argument("--safety-log-root", type=Path, required=True)
    ap.add_argument("--out-manifest", type=Path, required=True)
    ap.add_argument("--image-id", type=str, required=True)
    ap.add_argument("--plan-steps", type=int, nargs="+", default=list(CAPTURE_PLAN_STEPS))
    ap.add_argument("--xid-before", type=int, default=0)
    ap.add_argument("--xid-after", type=int, default=0)
    ap.add_argument("--exit-code", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=280)
    args = ap.parse_args()

    cfg_raw = yaml.safe_load(args.safety_config.read_text(encoding="utf-8")) or {}
    # Resolve base merge lightly for thresholds (trajectory is in leaf).
    base_rel = cfg_raw.get("base")
    merged = dict(cfg_raw)
    if base_rel:
        base_path = args.safety_config.parent / base_rel
        if base_path.is_file():
            base = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
            merged = {**base, **cfg_raw}
            # deep-merge trajectory from leaf
            merged["human_trajectory"] = cfg_raw.get("human_trajectory", base.get("human_trajectory"))

    traj = _load_traj(merged)
    warn = float(merged.get("safe_dist_warn", 0.16))
    hard = float(merged.get("safe_dist_hard_stop", 0.13))
    ttc = float(merged.get("ttc_threshold", 0.5))
    ttc_w = float(merged.get("ttc_warn_threshold", 1.5))
    radius = float(merged.get("human_hand_radius", 0.05))

    g_rules, csv_rows, replan_count = _read_gate_series(_find_episode_csv(args.safety_log_root))
    by_step = {int(float(r["step_index"])): r for r in csv_rows if r.get("step_index") not in ("", None)}

    frames = []
    for step in args.plan_steps:
        png = args.scene_dir / f"frame_{int(step):06d}_env0.png"
        if not png.is_file():
            raise SystemExit(f"missing RGB: {png}")
        pos, vel = _linear_pose_at_step(**traj, step_index=int(step), control_dt=0.02)
        row = by_step.get(int(step), {})
        dist = row.get("dist_ee_human") or row.get("dist_min_gt") or ""
        dist_f = float(dist) if str(dist).strip() not in ("", "None") else None
        g_rule = int(float(row["g_rule"])) if row.get("g_rule") not in (None, "") else None
        reason = str(row.get("reason") or "") or None
        phase = str(row.get("task_time_step") or "") or None
        cdh = control_decision_hash(
            gate_decision=0 if g_rule is None else g_rule,
            action=None,
            should_advance=True,
            protocol_phase=phase,
            replan_event=None,
            task_progression=int(step),
        )
        frames.append(
            build_frame_record(
                png_path=png,
                sim_step=int(step),
                wall_time_s=float(step) * 0.02,
                proxy_pos=pos.tolist(),
                proxy_vel=vel.tolist(),
                proxy_radius_m=radius,
                dist_ee_human=dist_f,
                dist_held_proxy=None,
                g_rule=g_rule,
                gate_reason=reason,
                protocol_phase=phase,
                control_decision_hash=cdh,
                safe_dist_warn=warn,
                safe_dist_hard_stop=hard,
                ttc_threshold=ttc,
                ttc_warn_threshold=ttc_w,
            )
        )

    margins = [
        f["geometry"]["geometry_margin_vs_warn_m"]
        for f in frames
        if f["geometry"]["geometry_margin_vs_warn_m"] is not None
    ]
    # Full-episode margins from CSV when present
    for r in csv_rows:
        d = r.get("dist_ee_human") or r.get("dist_min_gt") or ""
        if str(d).strip() in ("", "None"):
            continue
        margins.append(float(d) - warn)
    min_margin = min(margins) if margins else None

    gate_audit = audit_geometry_allow(g_rules, replan_count=replan_count) if g_rules else {
        "ok": False,
        "gate_counts": {},
        "replan_count": replan_count,
    }

    visibility_ok = all(
        f["visibility"]["visible"] and f["visibility"]["pixel_area"] >= MIN_PROXY_PIXEL_AREA
        for f in frames
    )
    disp = None
    if len(frames) >= 2:
        c0 = frames[0]["visibility"]["centroid_uv"]
        c1 = frames[1]["visibility"]["centroid_uv"]
        if c0 and c1:
            disp = float(np.hypot(c0[0] - c1[0], c0[1] - c1[1]))

    verdict = "PASS"
    reason = "ok"
    if args.exit_code != 0:
        verdict, reason = "FAIL", "nonzero_exit"
    elif not visibility_ok or (disp is not None and disp < MIN_SCREEN_DISPLACEMENT_PX):
        verdict, reason = "SCENE_VISIBILITY_FAIL", "proxy_not_visible_or_displacement_low"
    elif g_rules and not gate_audit["ok"]:
        verdict, reason = "FAIL", "geometry_not_allow_throughout"
    elif min_margin is not None and min_margin <= 0:
        # Margin uses warn distance; negative means some steps entered warn/STOP band.
        verdict, reason = "FAIL", "non_positive_geometry_margin"

    man = build_capture_manifest(
        frames,
        trajectory_hash=trajectory_pose_hash(**traj),
        safety_config_sha256=_sha256_text(args.safety_config),
        image_id=args.image_id,
        post_count=0,
        gate_counts=gate_audit.get("gate_counts") or {},
        min_geometry_margin_m=min_margin,
        xid_before=args.xid_before,
        xid_after=args.xid_after,
        extra={
            "verdict": verdict,
            "reason": reason,
            "max_steps": args.max_steps,
            "visual_semantic_risk": VISUAL_SEMANTIC_RISK,
            "gate_audit_ok": gate_audit.get("ok"),
            "replan_count": replan_count,
            "pixel_displacement_px": disp,
            "min_proxy_pixel_area_gate": MIN_PROXY_PIXEL_AREA,
            "min_screen_displacement_px_gate": MIN_SCREEN_DISPLACEMENT_PX,
            "safety_csv": str(_find_episode_csv(args.safety_log_root) or ""),
        },
    )
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps(man, indent=2), encoding="utf-8")
    # Also write jsonl for frames
    jsonl = args.out_manifest.with_suffix(".frames.jsonl")
    with jsonl.open("w", encoding="utf-8") as f:
        for fr in frames:
            f.write(json.dumps(fr, ensure_ascii=True) + "\n")
    print(json.dumps({"verdict": verdict, "reason": reason, "manifest": str(args.out_manifest)}, indent=2))
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
