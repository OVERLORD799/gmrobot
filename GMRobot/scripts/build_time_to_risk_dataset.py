#!/usr/bin/env python3
"""Build a time-to-risk regression dataset from IV-J safety CSV logs (W13).

Reads one or more ``episode_0000.csv`` files produced by
``gm_state_machine_agent.py --enable_safety``, computes per-row features
and a ``time_to_collision_steps`` label, and writes a single training
CSV consumable by ``layer2/train.py`` (or an equivalent regressor).

Usage::

    python scripts/build_time_to_risk_dataset.py \
        --runs output/safety_logs/20260618_134706 \
               output/safety_logs/20260618_135142 \
        --output output/time_to_risk_dataset.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

# Feature window: number of past steps to include as lag features.
_HISTORY_WINDOW = 10

# Label horizon: max steps to look ahead for the first GT collision.
_MAX_LABEL_HORIZON = 500

# Feature column groups (must match CSV columns written by SafetyLogger).
_DIST_FEATURES = [
    "dist_ee_human",
    "dist_min_envelope",
    "dist_min_held",
    "dist_min_arm",
    "dist_min_gripper",
]
_VELOCITY_FEATURES = [
    "ee_vel_x", "ee_vel_y", "ee_vel_z",
    "human_hand_vel_x", "human_hand_vel_y", "human_hand_vel_z",
]
_TTC_FEATURES = ["ttc", "approach_rate", "ttc_forecast_s"]
_GATE_FEATURES = ["g_rule", "trigger_rule", "slow_down_alpha"]
_REPLAN_FEATURES = ["replan_active", "replan_event"]
_PHASE_FEATURES = ["task_time_step", "transport_phase", "stage_name"]  # derived


def _parse_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_int(val: str, default: int = 0) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _parse_trigger_rule(val: str) -> int:
    """Encode trigger_rule as a categorical int."""
    mapping = {"static": 1, "ttc": 2, "held_critical": 3, "workspace": 4}
    return mapping.get(str(val).strip(), 0)


def _parse_replan_event(val: str) -> int:
    mapping = {"trigger": 1, "applied": 2, "failed": 3}
    return mapping.get(str(val).strip(), 0)


def build_dataset(
    run_dirs: list[str],
    output_path: str,
    *,
    history_window: int = _HISTORY_WINDOW,
    max_label_horizon: int = _MAX_LABEL_HORIZON,
) -> int:
    """Read CSV logs and write time-to-risk training rows.

    Returns the number of training rows written.
    """
    header_written = False
    total_rows = 0
    csv.register_dialect("safety", doublequote=True, quoting=csv.QUOTE_MINIMAL)

    for run_dir in run_dirs:
        run_path = Path(run_dir)
        csv_path = run_path / "episode_0000.csv"
        if not csv_path.exists():
            print(f"[SKIP] {csv_path} not found", file=sys.stderr)
            continue

        rows = _load_csv(csv_path)
        if len(rows) < history_window + 1:
            print(f"[SKIP] {csv_path}: {len(rows)} rows (need >{history_window})", file=sys.stderr)
            continue

        # Build label array: time_to_collision_steps for each row.
        labels = _build_labels(rows, max_label_horizon)

        # Sliding window of history features.
        history_buf: deque[dict[str, float]] = deque(maxlen=history_window)

        mode = "w" if not header_written else "a"
        with open(output_path, mode, newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for i, row in enumerate(rows):
                feats = _extract_features(row)
                history_buf.append(feats)
                if len(history_buf) < history_window:
                    continue

                # Flatten history into lag features.
                flat: dict[str, float] = {}
                for t, hist in enumerate(reversed(history_buf)):
                    for k, v in hist.items():
                        flat[f"{k}_lag{t}"] = v
                flat["time_to_collision_steps"] = labels[i]
                flat["run_dir"] = run_dir
                flat["step_index"] = _parse_int(row.get("step_index", "0"))

                if not header_written:
                    writer.writerow(list(flat.keys()))
                    header_written = True
                writer.writerow([str(flat[k]) for k in flat])
                total_rows += 1

        print(f"[OK] {csv_path}: {total_rows} training rows written", file=sys.stderr)

    return total_rows


def _load_csv(csv_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _build_labels(
    rows: list[dict[str, str]],
    max_horizon: int,
) -> list[int]:
    """For each row i, label = min steps until g_ground_truth==1 or max_horizon."""
    n = len(rows)
    labels = [max_horizon] * n

    # Forward-scan to find first GT collision.
    next_collision = max_horizon
    for i in range(n - 1, -1, -1):
        g_gt = _parse_int(rows[i].get("g_ground_truth", "0"))
        gt_collision = _parse_int(rows[i].get("gt_collision", "0"))
        g_rule = _parse_int(rows[i].get("g_rule", "0"))

        # Use GT collision if available; fall back to g_rule STOP.
        is_collision = (g_gt == 1 or gt_collision == 1 or g_rule == 1)

        if is_collision:
            next_collision = 0
        elif next_collision < max_horizon:
            next_collision += 1

        labels[i] = min(next_collision, max_horizon)

    return labels


def _extract_features(row: dict[str, str]) -> dict[str, float]:
    """Extract a flat feature vector from one CSV row."""
    feats: dict[str, float] = {}

    # Distance features
    for key in _DIST_FEATURES:
        val = row.get(key, "")
        if val not in ("", None):
            feats[key] = _parse_float(val, -1.0)

    # Velocity features — extracted from array columns.
    _extract_vel_features(row, feats)

    # TTC features
    for key in _TTC_FEATURES:
        val = row.get(key, "")
        if val not in ("", None):
            feats[key] = _parse_float(val)

    # Gate features
    feats["g_rule"] = float(_parse_int(row.get("g_rule", "0")))
    feats["trigger_rule_cat"] = float(_parse_trigger_rule(row.get("trigger_rule", "")))

    # Replan features
    feats["replan_active"] = float(_parse_int(row.get("replan_active", "0")))
    feats["replan_event_cat"] = float(_parse_replan_event(row.get("replan_event", "")))

    # Task progress
    feats["task_time_step"] = float(_parse_int(row.get("task_time_step", "0")))

    return feats


def _extract_vel_features(row: dict[str, str], feats: dict[str, float]) -> None:
    """Parse human_hand_vel from CSV array columns when available.

    Falls back to human_hand_vel array column, or velocity_xy_px_s from /track.
    """
    # L1 3D velocity
    hand_vel_str = row.get("human_hand_vel", "")
    if hand_vel_str and hand_vel_str not in ("", "[]"):
        try:
            parts = _parse_array_column(hand_vel_str)
            if len(parts) >= 3:
                feats["human_hand_vel_x"] = float(parts[0])
                feats["human_hand_vel_y"] = float(parts[1])
                feats["human_hand_vel_z"] = float(parts[2])
        except (ValueError, IndexError):
            pass

    # SAM2 2D velocity (pixel-space)
    track_vel = row.get("perception_track_speed_px_s", "")
    if track_vel not in ("", None):
        feats["track_speed_px_s"] = _parse_float(track_vel)
    track_dir = row.get("perception_track_direction_deg", "")
    if track_dir not in ("", None):
        feats["track_direction_deg"] = _parse_float(track_dir)


def _parse_array_column(raw: str) -> list[str]:
    """Best-effort parse of a Python list literal like '[0.1, 0.2, 0.3]'."""
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip() for x in s.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build time-to-risk regression dataset from IV-J CSV logs."
    )
    parser.add_argument(
        "--runs", nargs="+", required=True,
        help="One or more safety_log run directories.",
    )
    parser.add_argument(
        "--output", default=os.path.join(os.environ.get("GMROBOT_OUTPUT_DIR", "/root/GMRobot/output"), "time_to_risk_dataset.csv"),
        help="Output CSV path.",
    )
    parser.add_argument(
        "--history-window", type=int, default=_HISTORY_WINDOW,
        help=f"Number of history steps for lag features (default: {_HISTORY_WINDOW}).",
    )
    parser.add_argument(
        "--max-label-horizon", type=int, default=_MAX_LABEL_HORIZON,
        help=f"Max steps to look ahead for collision label (default: {_MAX_LABEL_HORIZON}).",
    )
    args = parser.parse_args()

    total = build_dataset(
        args.runs,
        args.output,
        history_window=args.history_window,
        max_label_horizon=args.max_label_horizon,
    )
    print(f"[DONE] {total} training rows written to {args.output}")


if __name__ == "__main__":
    main()
