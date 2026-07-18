#!/usr/bin/env python3
"""Gripper open/close trace for place window (offline, no Isaac).

Reconstructs policy + agent-style gripper overrides per ``task_time_step`` and
flags descend false-open / post-release re-close anomalies.

Usage:
  # Offline simulation (default part 1)
  python scripts/diagnose_gripper_trace.py

  # Real safety log CSV
  python scripts/diagnose_gripper_trace.py --run-dir output/safety_logs/20260626_124417

  # Limit to part index
  python scripts/diagnose_gripper_trace.py --run-dir PATH --part 1

  # JSON summary
  python scripts/diagnose_gripper_trace.py --run-dir PATH --json
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pick_and_place_policy import (  # noqa: E402
    GRIPPER_CLOSED,
    GRIPPER_OPEN,
    PLACE_ZONE_RADIUS_M,
    SingleEnvPickAndPlacePolicy,
)

CARRY_THRESHOLD = (GRIPPER_OPEN + GRIPPER_CLOSED) / 2.0

AnomalyKind = Literal[
    "ANOMALY_FAKE_OPEN",
    "ANOMALY_RE_CLOSE",
    "ANOMALY_HOLD_RECLOSE",
    "ANOMALY_OPEN_BLOCKED",
]


@dataclass
class TraceRow:
    task_ts: int
    stage_name: str
    script_gripper: float
    prop_gripper: float
    exec_gripper: float | None
    hold_open: bool
    hold_release: bool
    force_open: bool
    keep_open: bool
    release_committed: bool
    g_rule: int | None
    ee_xy_err: float
    gripper_hold_reason: str = "script"
    anomalies: list[AnomalyKind] = field(default_factory=list)


def _default_obs(part: int = 1) -> dict[str, np.ndarray]:
    obs: dict[str, np.ndarray] = {}
    for slot in ("A", "B"):
        key = f"slot_{slot}_{part}_T"
        obs[key] = np.eye(4)
    obs[f"slot_A_{part}_T"][:3, 3] = [0.6, 0.0, 0.0]
    obs[f"slot_B_{part}_T"][:3, 3] = [0.8, 0.0, 0.0]
    return obs


def _policy_for_part(part: int) -> SingleEnvPickAndPlacePolicy:
    policy = SingleEnvPickAndPlacePolicy()
    policy.user_commands = [{"pick": f"A@{part}", "place": f"B@{part}"}]
    policy.reset(_default_obs(part))
    return policy


def _parse_vec(raw: str) -> np.ndarray | None:
    if not raw:
        return None
    try:
        return np.asarray(ast.literal_eval(raw), dtype=np.float64).reshape(-1)
    except (SyntaxError, ValueError):
        return None


def _simulate_agent_gripper(
    policy: SingleEnvPickAndPlacePolicy,
    *,
    task_time_step: int,
    ee_pos: np.ndarray,
    part_pose: np.ndarray | None = None,
) -> tuple[float, str]:
    """Mirror ``gm_state_machine_agent._apply_policy_gripper_overrides``."""
    policy.time_step = task_time_step
    proposed_g = float(policy.get_action({}, advance=False)[7])
    safe_g = proposed_g
    eval_steps = policy.gripper_hold_eval_steps(task_time_step)
    reasons: list[str] = []

    release_part_pose = part_pose
    keep_open = policy.should_keep_release_gripper_open(task_time_step + 1)
    if policy.should_force_open_gripper():
        return float(policy.gripper_open), "force_open"
    if keep_open:
        safe_g = float(policy.gripper_open)
        reasons.append("keep_release")
    elif (
        not policy._release_gripper_committed
        and policy.stage_name_at_step(task_time_step + 1).startswith(
            "open_gripper_to_release_"
        )
        and safe_g > CARRY_THRESHOLD
        and not any(
            policy.should_hold_release(ee_pos, release_part_pose, step)
            or policy.should_hold_open_gripper(ee_pos, step)
            for step in eval_steps
        )
    ):
        policy.mark_release_gripper_open()
        reasons.append("mark_release")

    if not keep_open and not policy._release_gripper_committed:
        for step in eval_steps:
            if policy.should_hold_open_gripper(ee_pos, step):
                safe_g = float(policy.gripper_closed)
                reasons.append("hold_open")
                break
            if policy.should_hold_release(ee_pos, release_part_pose, step):
                safe_g = float(policy.gripper_closed)
                reasons.append("hold_release")
                break

    return safe_g, "+".join(reasons) if reasons else "script"


def _place_window(policy: SingleEnvPickAndPlacePolicy, part: int) -> tuple[int, int]:
    windows = policy.part_stage_windows().get(part)
    if not windows:
        raise ValueError(f"part {part} has no stage windows")
    start = int(windows["descend_start"])
    end = int(windows.get("open_end", windows.get("cycle_end", start)))
    return start, end


def _xy_err(policy: SingleEnvPickAndPlacePolicy, task_ts: int, ee: np.ndarray) -> float:
    target = policy.place_target_xy_at_step(task_ts)
    if target is None:
        return 0.0
    return float(np.linalg.norm(ee[:2] - target[:2]))


def _detect_anomalies(rows: list[TraceRow]) -> None:
    open_start_idx: int | None = None
    for i, row in enumerate(rows):
        if row.stage_name.startswith("descend_to_box_with_"):
            if row.script_gripper > CARRY_THRESHOLD:
                row.anomalies.append("ANOMALY_FAKE_OPEN")
            if row.prop_gripper > CARRY_THRESHOLD:
                row.anomalies.append("ANOMALY_FAKE_OPEN")
            if row.exec_gripper is not None and row.exec_gripper > CARRY_THRESHOLD:
                row.anomalies.append("ANOMALY_FAKE_OPEN")

        if row.stage_name.startswith("open_gripper_to_release_"):
            if open_start_idx is None:
                open_start_idx = i
            if (
                row.script_gripper > CARRY_THRESHOLD
                and row.exec_gripper is not None
                and row.exec_gripper <= CARRY_THRESHOLD
                and not row.release_committed
                and not row.hold_open
                and not row.hold_release
            ):
                row.anomalies.append("ANOMALY_OPEN_BLOCKED")
            if (
                row.release_committed
                and row.prop_gripper > CARRY_THRESHOLD
                and row.exec_gripper is not None
                and row.exec_gripper <= CARRY_THRESHOLD
            ):
                row.anomalies.append("ANOMALY_HOLD_RECLOSE")

        if i > 0 and rows[i - 1].stage_name.startswith("open_gripper_to_release_"):
            prev = rows[i - 1]
            if prev.stage_name.startswith("open_gripper_to_release_"):
                if (
                    prev.exec_gripper is not None
                    and prev.exec_gripper > CARRY_THRESHOLD
                    and row.exec_gripper is not None
                    and row.exec_gripper <= CARRY_THRESHOLD
                ):
                    row.anomalies.append("ANOMALY_RE_CLOSE")


def build_offline_trace(
    policy: SingleEnvPickAndPlacePolicy,
    part: int,
    *,
    ee_pos: np.ndarray | None = None,
    part_pose: np.ndarray | None = None,
) -> list[TraceRow]:
    start, end = _place_window(policy, part)
    if ee_pos is None:
        ee_pos = np.array([0.8, 0.0, 0.13], dtype=np.float32)
    if part_pose is None:
        part_pose = np.array([0.8, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float64)

    policy._release_gripper_committed = False
    rows: list[TraceRow] = []
    for task_ts in range(start, end + 1):
        policy.time_step = task_ts
        release_step = task_ts + 1
        eval_steps = policy.gripper_hold_eval_steps(task_ts)
        script_g = float(policy._gripper_at_step(task_ts))
        prop_g = float(policy.get_action({}, advance=False)[7])
        sim_g, reason = _simulate_agent_gripper(
            policy,
            task_time_step=task_ts,
            ee_pos=ee_pos,
            part_pose=part_pose,
        )
        rows.append(
            TraceRow(
                task_ts=task_ts,
                stage_name=policy.stage_name_at_step(task_ts),
                script_gripper=script_g,
                prop_gripper=prop_g,
                exec_gripper=sim_g,
                hold_open=any(
                    policy.should_hold_open_gripper(ee_pos, step) for step in eval_steps
                ),
                hold_release=any(
                    policy.should_hold_release(ee_pos, part_pose, step)
                    for step in eval_steps
                ),
                force_open=policy.should_force_open_gripper(),
                keep_open=policy.should_keep_release_gripper_open(release_step),
                release_committed=policy._release_gripper_committed,
                g_rule=None,
                ee_xy_err=_xy_err(policy, task_ts, ee_pos),
                gripper_hold_reason=reason,
            )
        )
    _detect_anomalies(rows)
    return rows


def build_csv_trace(
    csv_path: Path,
    policy: SingleEnvPickAndPlacePolicy,
    part: int,
) -> list[TraceRow]:
    start, end = _place_window(policy, part)
    rows_out: list[TraceRow] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            task_ts = int(float(row["task_time_step"]))
            if task_ts < start or task_ts > end:
                continue
            ee = _parse_vec(row.get("ee_pos", ""))
            if ee is None or ee.size < 3:
                ee = np.zeros(3, dtype=np.float64)
            prop = _parse_vec(row.get("action_proposed", ""))
            exe = _parse_vec(row.get("action_executed", ""))
            prop_g = float(prop[7]) if prop is not None and prop.size > 7 else 0.0
            exe_g = float(exe[7]) if exe is not None and exe.size > 7 else None
            release_step = task_ts + 1
            eval_steps = policy.gripper_hold_eval_steps(task_ts)
            script_g = float(policy._gripper_at_step(task_ts))
            policy.time_step = task_ts
            hold_reason = row.get("gripper_hold_reason", "")
            if not hold_reason:
                _, hold_reason = _simulate_agent_gripper(
                    policy,
                    task_time_step=task_ts,
                    ee_pos=ee[:3].astype(np.float32),
                    part_pose=None,
                )
            rows_out.append(
                TraceRow(
                    task_ts=task_ts,
                    stage_name=policy.stage_name_at_step(task_ts),
                    script_gripper=script_g,
                    prop_gripper=prop_g,
                    exec_gripper=exe_g,
                    hold_open=any(
                        policy.should_hold_open_gripper(
                            ee[:3].astype(np.float32), step
                        )
                        for step in eval_steps
                    ),
                    hold_release=any(
                        policy.should_hold_release(
                            ee[:3].astype(np.float32), None, step
                        )
                        for step in eval_steps
                    ),
                    force_open=policy.should_force_open_gripper(),
                    keep_open=policy.should_keep_release_gripper_open(release_step),
                    release_committed=bool(
                        str(row.get("release_gripper_committed", "")).strip() in ("1", "True")
                    )
                    or policy._release_gripper_committed,
                    g_rule=int(row["g_rule"]) if row.get("g_rule") not in (None, "") else None,
                    ee_xy_err=_xy_err(policy, task_ts, ee[:3]),
                    gripper_hold_reason=hold_reason,
                )
            )
    _detect_anomalies(rows_out)
    return rows_out


def _format_table(rows: list[TraceRow]) -> str:
    header = (
        "task_ts stage script prop exec hold_o hold_r force keep commit reason "
        "g_rule xy_err anomalies"
    )
    lines = [header]
    for r in rows:
        anom = ",".join(r.anomalies) if r.anomalies else ""
        exec_s = "" if r.exec_gripper is None else f"{r.exec_gripper:.2f}"
        lines.append(
            f"{r.task_ts} {r.stage_name[:28]} "
            f"{r.script_gripper:.2f} {r.prop_gripper:.2f} {exec_s} "
            f"{int(r.hold_open)} {int(r.hold_release)} {int(r.force_open)} "
            f"{int(r.keep_open)} {int(r.release_committed)} {r.gripper_hold_reason} "
            f"{r.g_rule if r.g_rule is not None else ''} {r.ee_xy_err:.3f} {anom}"
        )
    return "\n".join(lines)


def _summary(rows: list[TraceRow]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for r in rows:
        for a in r.anomalies:
            counts[a] = counts.get(a, 0) + 1
    return {
        "steps": len(rows),
        "anomaly_counts": counts,
        "descend_prop_open": sum(
            1
            for r in rows
            if r.stage_name.startswith("descend_to_box_with_")
            and r.prop_gripper > CARRY_THRESHOLD
        ),
        "descend_exec_open": sum(
            1
            for r in rows
            if r.stage_name.startswith("descend_to_box_with_")
            and r.exec_gripper is not None
            and r.exec_gripper > CARRY_THRESHOLD
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gripper trace for place window")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Safety log session dir containing episode_0000.csv",
    )
    parser.add_argument("--part", type=int, default=1, help="1-based part index")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary only")
    args = parser.parse_args()

    policy = _policy_for_part(args.part)
    if args.run_dir is not None:
        csv_path = args.run_dir / "episode_0000.csv"
        if not csv_path.is_file():
            print(f"Missing {csv_path}", file=sys.stderr)
            return 1
        rows = build_csv_trace(csv_path, policy, args.part)
        source = str(csv_path)
    else:
        rows = build_offline_trace(policy, args.part)
        source = "offline_simulation"

    summary = _summary(rows)
    summary["source"] = source
    summary["part"] = args.part
    summary["carry_threshold"] = CARRY_THRESHOLD

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0 if not summary["anomaly_counts"] else 2

    print(f"# gripper trace source={source} part={args.part}")
    print(_format_table(rows))
    print()
    print(json.dumps(summary, indent=2))
    return 0 if not summary["anomaly_counts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
