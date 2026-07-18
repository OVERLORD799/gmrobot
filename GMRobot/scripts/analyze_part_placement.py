#!/usr/bin/env python3
"""Per-part placement / drop metrics from episode CSV + policy stage windows."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np

from pick_and_place_policy import (
    GRIPPER_CLOSED,
    GRIPPER_OPEN,
    PLACE_ZONE_RADIUS_M,
    SingleEnvPickAndPlacePolicy,
)

GRASP_Z = 0.15
CARRY_THRESHOLD = (GRIPPER_OPEN + GRIPPER_CLOSED) / 2.0
VIOLENT_DZ = 0.08
VIOLENT_STEPS = 3


@dataclass
class PartMetrics:
    part: int
    approach_start: int | None = None
    open_start: int | None = None
    cycle_end: int | None = None
    open_attempt_rows: int = 0
    open_in_zone_rows: int = 0
    open_out_of_zone_rows: int = 0
    mid_transit_drop_rows: int = 0
    violent_lift_events: int = 0
    wait_hold_steps: int = 0
    max_task_ts: int = 0
    min_ee_z_in_place: float | None = None
    replan_detour_rows: int = 0
    task_ts_regressions: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def placement_ok(self) -> bool:
        if self.open_in_zone_rows > 0:
            return True
        if self.wait_hold_steps > 0 and self.mid_transit_drop_rows == 0:
            return True
        return False

    @property
    def no_violent_lift(self) -> bool:
        return self.violent_lift_events == 0

    @property
    def no_mid_transit_drop(self) -> bool:
        return self.mid_transit_drop_rows == 0


def _parse_vec(raw: str | None) -> list[float] | None:
    if raw is None or raw == "":
        return None
    try:
        v = ast.literal_eval(raw)
        return [float(x) for x in v[:3]]
    except Exception:
        return None


def _parse_float(raw: str | None, default: float = 0.0) -> float:
    try:
        return float(raw)
    except Exception:
        return default


def _default_policy() -> SingleEnvPickAndPlacePolicy:
    policy = SingleEnvPickAndPlacePolicy()
    obs = {"slot_A_1_T": np.eye(4), "slot_B_1_T": np.eye(4)}
    obs["slot_A_1_T"][:3, 3] = [0.6, 0.0, 0.0]
    obs["slot_B_1_T"][:3, 3] = [0.8, 0.0, 0.0]
    for i in range(2, 21):
        obs[f"slot_A_{i}_T"] = obs["slot_A_1_T"].copy()
        obs[f"slot_B_{i}_T"] = obs["slot_B_1_T"].copy()
    policy.reset(obs)
    return policy


def _part_for_task_step(windows: dict[int, dict[str, int]], task_ts: int) -> int | None:
    best_part = None
    best_start = -1
    for part, w in windows.items():
        start = w.get("approach_start")
        end = w.get("cycle_end", w.get("open_end"))
        if start is None:
            continue
        if start <= task_ts and (end is None or task_ts <= end) and start >= best_start:
            best_part = part
            best_start = start
    return best_part


def analyze_csv(
    csv_path: Path,
    *,
    place_radius_m: float = PLACE_ZONE_RADIUS_M,
    focus_part: int | None = None,
) -> tuple[dict[int, PartMetrics], dict]:
    policy = _default_policy()
    windows = policy.part_stage_windows()
    metrics: dict[int, PartMetrics] = {}
    for p, w in windows.items():
        pm = PartMetrics(part=p)
        for key in ("approach_start", "approach_end", "descend_start", "descend_end", "open_start", "open_end", "cycle_end"):
            if key in w:
                setattr(pm, key, w[key])
        metrics[p] = pm

    rows = list(csv.DictReader(open(csv_path)))
    prev_task: int | None = None
    prev_z: float | None = None
    dz_window: list[float] = []

    for row in rows:
        task_ts = int(_parse_float(row.get("task_time_step")))
        part = _part_for_task_step(windows, task_ts)
        if part is None:
            prev_task = task_ts
            continue

        pm = metrics[part]
        pm.max_task_ts = max(pm.max_task_ts, task_ts)
        if prev_task is not None and task_ts < prev_task:
            pm.task_ts_regressions += 1

        ee = _parse_vec(row.get("ee_pos"))
        grip = _parse_float(row.get("gripper") or row.get("action_gripper"), GRIPPER_CLOSED)
        g_rule = int(_parse_float(row.get("g_rule")))

        target_xy = policy.place_target_xy_at_step(task_ts)
        in_place = policy.is_in_place_window(task_ts)
        in_approach_place = policy.is_in_approach_or_place_window(task_ts)

        if in_approach_place and g_rule != 0 and prev_task == task_ts:
            pm.wait_hold_steps += 1

        stage_name = policy.stage_name_at_step(task_ts)
        if stage_name.startswith("replan_detour"):
            pm.replan_detour_rows += 1

        target_grip = float(
            np.interp(task_ts, policy.time_stamps, policy.gripper_traj)
        )
        wants_open = target_grip > CARRY_THRESHOLD

        if wants_open and ee is not None:
            pm.open_attempt_rows += 1
            if target_xy is not None:
                dist_xy = math.hypot(ee[0] - target_xy[0], ee[1] - target_xy[1])
                if dist_xy <= place_radius_m:
                    pm.open_in_zone_rows += 1
                else:
                    pm.open_out_of_zone_rows += 1

        if grip > CARRY_THRESHOLD and ee is not None and ee[2] > GRASP_Z and not in_place:
            pm.mid_transit_drop_rows += 1

        if in_place and ee is not None:
            z = ee[2]
            pm.min_ee_z_in_place = z if pm.min_ee_z_in_place is None else min(pm.min_ee_z_in_place, z)

        if (
            part == focus_part
            and stage_name.startswith("move_above_box_with_")
            and ee is not None
            and g_rule == 2
        ):
            if prev_z is not None:
                dz = ee[2] - prev_z
                if dz > 0:
                    dz_window.append(dz)
                else:
                    dz_window.clear()
                if len(dz_window) >= VIOLENT_STEPS and sum(dz_window[-VIOLENT_STEPS:]) > VIOLENT_DZ:
                    pm.violent_lift_events += 1
                    dz_window.clear()
            prev_z = ee[2]
        elif part == focus_part:
            prev_z = None
            dz_window.clear()

        prev_task = task_ts

    summary = {
        "csv_path": str(csv_path),
        "row_count": len(rows),
        "focus_part": focus_part,
        "place_radius_m": place_radius_m,
    }
    if rows:
        summary["final_task_time_step"] = int(
            _parse_float(rows[-1].get("task_time_step"))
        )
    manifest = csv_path.parent / "run_manifest.json"
    if manifest.is_file():
        summary["manifest"] = json.load(open(manifest))

    return metrics, summary


def print_report(metrics: dict[int, PartMetrics], summary: dict, *, focus_part: int = 5, block_place_smoke: bool = False) -> int:
    print(f"=== Part placement analysis: {summary.get('csv_path')} ===")
    if "manifest" in summary:
        m = summary["manifest"]
        print(
            f"run_id={m.get('run_id')} outcome={m.get('outcome')} "
            f"final_time_step={m.get('final_time_step', m.get('task_time_step'))}"
        )
    print(f"rows={summary.get('row_count')} final_task_ts={summary.get('final_task_time_step')}")
    print("")
    print(
        f"{'part':>4} | {'max_ts':>6} | {'open@zone':>9} | {'mid_drop':>8} | "
        f"{'viol_lift':>9} | {'wait_hold':>9} | {'regress':>7} | ok"
    )
    print("-" * 78)

    fail = 0
    for part in sorted(metrics):
        pm = metrics[part]
        if pm.max_task_ts <= 0:
            continue
        ok = pm.placement_ok and pm.no_mid_transit_drop and pm.no_violent_lift
        mark = "PASS" if ok else "FAIL"
        if part == focus_part and not ok and not block_place_smoke:
            fail = 1
        print(
            f"{part:4d} | {pm.max_task_ts:6d} | {pm.open_in_zone_rows:9d} | "
            f"{pm.mid_transit_drop_rows:8d} | {pm.violent_lift_events:9d} | "
            f"{pm.wait_hold_steps:9d} | {pm.task_ts_regressions:7d} | {mark}"
        )

    if focus_part in metrics:
        pm = metrics[focus_part]
        part6 = metrics.get(focus_part + 1)
        part6_started = part6 is not None and part6.max_task_ts > (part6.approach_start or 10**9)
        print("")
        print(f"--- Part {focus_part} detail ---")
        print(f"  approach_start={pm.approach_start} open_start={pm.open_start} cycle_end={pm.cycle_end}")
        print(f"  min_ee_z_in_place={pm.min_ee_z_in_place}")
        print(f"  replan_detour_rows={pm.replan_detour_rows}")
        print(f"  open_out_of_zone_rows={pm.open_out_of_zone_rows}")
        part5_ok = (
            pm.max_task_ts > 1771
            and pm.no_mid_transit_drop
            and pm.no_violent_lift
            and pm.task_ts_regressions == 0
            and (
                pm.placement_ok
                or (
                    block_place_smoke
                    and pm.cycle_end is not None
                    and pm.max_task_ts >= pm.cycle_end
                )
            )
            and (block_place_smoke or not part6_started)
        )
        print(f"  part6_pick_started={part6_started}")
        print(f"  part5_accept={'PASS' if part5_ok else 'FAIL'}")
        if not part5_ok:
            fail = 1

    return fail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Safety log run directory or episode CSV")
    parser.add_argument("--focus-part", type=int, default=5)
    parser.add_argument("--place-radius-m", type=float, default=PLACE_ZONE_RADIUS_M)
    parser.add_argument(
        "--block-place-smoke",
        action="store_true",
        help="S1/2.5b smoke: pass part5 if unlocked past 1771 with wait-hold even if part6 started",
    )
    args = parser.parse_args()

    path = args.run_dir
    if path.is_dir():
        csv_path = path / "episode_0000.csv"
    else:
        csv_path = path

    if not csv_path.is_file():
        print(f"ERROR: missing {csv_path}", file=sys.stderr)
        return 2

    metrics, summary = analyze_csv(
        csv_path,
        place_radius_m=args.place_radius_m,
        focus_part=args.focus_part,
    )
    return print_report(
        metrics, summary, focus_part=args.focus_part, block_place_smoke=args.block_place_smoke
    )


if __name__ == "__main__":
    raise SystemExit(main())
