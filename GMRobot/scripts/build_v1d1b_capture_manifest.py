#!/usr/bin/env python3
"""Build V1-D1B capture manifest from RGB + Layer-1 CSV (host/offline)."""

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
from shadow.v1d1b_capture import (  # noqa: E402
    CAPTURE_PLAN_STEPS,
    MIN_ROI_PIXEL_AREA,
    TARGET_CONTAINER_POSE,
    audit_geometry_allow,
    blocker_world_pose_b10,
    build_capture_manifest,
    build_frame_record,
    scene_layout_hash,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_episode_csv(root: Path) -> Path | None:
    csvs = list(root.rglob("episode_*.csv"))
    if not csvs:
        return None

    def nrows(p: Path) -> int:
        try:
            return max(0, sum(1 for _ in p.open(encoding="utf-8")) - 1)
        except OSError:
            return 0

    return max(csvs, key=nrows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-dir", type=Path, required=True)
    ap.add_argument("--safety-config", type=Path, required=True)
    ap.add_argument("--safety-log-root", type=Path, required=True)
    ap.add_argument("--out-manifest", type=Path, required=True)
    ap.add_argument("--image-id", required=True)
    ap.add_argument("--plan-steps", type=int, nargs="+", default=list(CAPTURE_PLAN_STEPS))
    ap.add_argument("--max-steps", type=int, default=280)
    ap.add_argument("--xid-before", type=int, default=0)
    ap.add_argument("--xid-after", type=int, default=0)
    ap.add_argument("--exit-code", type=int, default=0)
    args = ap.parse_args()

    cfg = yaml.safe_load(args.safety_config.read_text(encoding="utf-8")) or {}
    base_rel = cfg.get("base")
    merged = dict(cfg)
    if base_rel:
        bp = args.safety_config.parent / base_rel
        if bp.is_file():
            base = yaml.safe_load(bp.read_text(encoding="utf-8")) or {}
            merged = {**base, **cfg}
            merged["human_trajectory"] = cfg.get("human_trajectory", base.get("human_trajectory"))
    warn = float(merged.get("safe_dist_warn", 0.16))
    hard = float(merged.get("safe_dist_hard_stop", 0.13))
    ttc = float(merged.get("ttc_threshold", 0.5))
    ttc_w = float(merged.get("ttc_warn_threshold", 1.5))
    traj = merged.get("human_trajectory") or {}
    hand = list(map(float, traj.get("start_pos", [0.25, -0.75, 0.60])))

    csv_path = _find_episode_csv(args.safety_log_root)
    rows: list[dict] = []
    if csv_path:
        with csv_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    by_step = {int(float(r["step_index"])): r for r in rows if r.get("step_index") not in ("", None)}
    g_rules = [int(float(r["g_rule"])) for r in rows if r.get("g_rule") not in ("", None)]

    blocker = blocker_world_pose_b10()
    target = TARGET_CONTAINER_POSE
    frames = []
    for step in args.plan_steps:
        png = args.scene_dir / f"frame_{int(step):06d}_env0.png"
        if not png.is_file():
            raise SystemExit(f"missing RGB {png}")
        row = by_step.get(int(step), {})
        dist_hand = row.get("dist_ee_human") or ""
        dist_hand_f = float(dist_hand) if str(dist_hand).strip() not in ("", "None") else None
        # EE–blocker approximate from known early EE if absent
        dist_blocker = None
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
                robot_ee_pos=None,
                blocker_pos=blocker,
                target_pos=target,
                hand_pos=hand,
                dist_ee_blocker=dist_blocker,
                dist_ee_hand=dist_hand_f,
                dist_held_blocker=None,
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

    margins = []
    for r in rows:
        d = r.get("dist_ee_human") or ""
        if str(d).strip() in ("", "None"):
            continue
        margins.append(float(d) - warn)
    min_margin = min(margins) if margins else None
    margin_dist = {}
    if margins:
        arr = np.asarray(margins, dtype=np.float64)
        margin_dist = {
            "min": float(arr.min()),
            "p10": float(np.percentile(arr, 10)),
            "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
            "max": float(arr.max()),
        }

    last_capture = max(args.plan_steps)
    post_live = int(args.max_steps) - int(last_capture)
    # Live window: first capture through last_capture+50
    win_hi = min(len(g_rules) - 1, int(last_capture) + 50) if g_rules else -1
    win_lo = min(args.plan_steps) if g_rules else 0
    gate_full = audit_geometry_allow(g_rules, replan_count=0) if g_rules else {"ok": False, "gate_counts": {}}
    gate_win = (
        audit_geometry_allow(g_rules, replan_count=0, window=(win_lo, win_hi))
        if g_rules and win_hi >= win_lo
        else {"ok": False, "gate_counts": {}}
    )

    semantic_ok = all(
        f["blockage_metric"]["inside"]
        and f["assets"]["blocker"]["primitive_sphere"] is False
        and (f["visibility"]["blocker_roi"]["visible"] or f["visibility"]["target_roi"]["visible"])
        for f in frames
    )
    # Prefer projected blocker visibility; if projection fails UV, world containment still required
    blocker_vis = all(f["visibility"]["blocker_roi"]["visible"] for f in frames)
    target_vis = all(f["visibility"]["target_roi"]["visible"] for f in frames)

    # Prefer geometry-window failure over visibility when both fail.
    if args.exit_code != 0:
        verdict, reason = "FAIL", "nonzero_exit"
    elif not gate_win.get("ok") or (min_margin is not None and min_margin <= 0 and not gate_win.get("ok")):
        verdict, reason = "GEOMETRY_OVERLAP", "capture_live_window_not_allow"
    elif not gate_full.get("ok"):
        verdict, reason = "GEOMETRY_OVERLAP", "episode_not_allow_throughout"
    elif not semantic_ok or not (blocker_vis and target_vis):
        verdict, reason = "SCENE_SEMANTIC_VISIBILITY_FAIL", "target_or_blocker_not_clear"
    elif post_live < 50:
        verdict, reason = "FAIL", "post_capture_live_steps_lt_50"
    else:
        verdict, reason = "PASS", "ok"

    man = build_capture_manifest(
        frames,
        layout_hash=scene_layout_hash(hand_park=hand),
        safety_config_sha256=_sha256_file(args.safety_config),
        image_id=args.image_id,
        post_count=0,
        gate_counts=gate_full.get("gate_counts") or {},
        min_geometry_margin_m=min_margin,
        margin_distribution=margin_dist,
        xid_before=args.xid_before,
        xid_after=args.xid_after,
        post_capture_live_steps=post_live,
        extra={
            "verdict": verdict,
            "reason": reason,
            "max_steps": args.max_steps,
            "gate_window_ok": gate_win.get("ok"),
            "gate_window_counts": gate_win.get("gate_counts"),
            "safety_csv": str(csv_path or ""),
            "min_roi_pixel_area_gate": MIN_ROI_PIXEL_AREA,
        },
    )
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps(man, indent=2), encoding="utf-8")
    with args.out_manifest.with_suffix(".frames.jsonl").open("w", encoding="utf-8") as f:
        for fr in frames:
            f.write(json.dumps(fr) + "\n")
    print(json.dumps({"verdict": verdict, "reason": reason, "manifest": str(args.out_manifest)}, indent=2))
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
