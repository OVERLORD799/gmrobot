#!/usr/bin/env python3
"""G6c: Compare PPO-trained policy vs scripted baseline on safety metrics.

Reads two CSV logs (PPO + scripted) from safety_logs/ and produces
a comparison report covering intervention_rate, slow_down_rate,
task completion time, and success_rate.
"""

import argparse, csv, json, sys
from collections import defaultdict
from pathlib import Path


def load_metrics(csv_path: Path) -> dict:
    """Extract safety metrics from a CSV log."""
    if not csv_path.exists():
        return {"error": f"not found: {csv_path}"}
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if not rows:
        return {"error": "empty CSV"}
    total = len(rows)
    stop = sum(1 for r in rows if int(float(r.get("g_rule", "0") or 0)) == 1)
    slow = sum(1 for r in rows if int(float(r.get("g_rule", "0") or 0)) == 2)
    gt_stop = sum(1 for r in rows if int(float(r.get("g_ground_truth", "0") or 0)) == 1)
    last_ts = max(int(float(r.get("task_time_step", "0") or 0)) for r in rows)
    outcome = rows[-1].get("outcome", "unknown")
    success = "success" in str(outcome).lower()

    # stop run lengths
    runs, cur = [], 0
    for r in rows:
        if int(float(r.get("g_rule", "0") or 0)) == 1:
            cur += 1
        elif cur > 0:
            runs.append(cur); cur = 0
    if cur > 0:
        runs.append(cur)

    return {
        "total_steps": total,
        "intervention_rate": stop / total if total else 0,
        "slow_down_rate": slow / total if total else 0,
        "gt_stop_steps": gt_stop,
        "max_task_time_step": last_ts,
        "success": success,
        "outcome": outcome,
        "mean_stop_duration": sum(runs) / len(runs) if runs else 0,
        "max_stop_duration": max(runs) if runs else 0,
        "stop_run_count": len(runs),
    }


def compare(ppo_csv: Path, scripted_csv: Path) -> dict:
    ppo = load_metrics(ppo_csv)
    scripted = load_metrics(scripted_csv)
    return {"ppo": ppo, "scripted": scripted}


def main():
    parser = argparse.ArgumentParser(description="Compare PPO vs scripted policy safety metrics.")
    parser.add_argument("--ppo", required=True, help="Path to PPO CSV log directory or episode_0000.csv.")
    parser.add_argument("--scripted", required=True, help="Path to scripted CSV log directory or episode_0000.csv.")
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    def _resolve(p: str) -> Path:
        path = Path(p)
        if path.is_dir():
            path = path / "episode_0000.csv"
        return path

    ppo_path = _resolve(args.ppo)
    scripted_path = _resolve(args.scripted)

    print(f"PPO:      {ppo_path}")
    print(f"Scripted: {scripted_path}")
    print()

    result = compare(ppo_path, scripted_path)

    header = f"{'Metric':<30} {'PPO':>12} {'Scripted':>12} {'Delta':>12}"
    print(header)
    print("-" * len(header))

    keys = [
        ("total_steps", "Total steps", "{:.0f}"),
        ("intervention_rate", "Intervention rate", "{:.4f}"),
        ("slow_down_rate", "Slow-down rate", "{:.4f}"),
        ("gt_stop_steps", "GT STOP steps", "{:.0f}"),
        ("max_task_time_step", "Max task step", "{:.0f}"),
        ("mean_stop_duration", "Mean STOP dur", "{:.1f}"),
        ("max_stop_duration", "Max STOP dur", "{:.0f}"),
        ("stop_run_count", "STOP runs", "{:.0f}"),
    ]

    for key, label, fmt in keys:
        p = result["ppo"].get(key)
        s = result["scripted"].get(key)
        if isinstance(p, (int, float)) and isinstance(s, (int, float)) and s != 0:
            delta = (p - s) / s * 100
            delta_str = f"{delta:+.1f}%"
        else:
            delta_str = "N/A"
        p_str = fmt.format(p) if isinstance(p, (int, float)) else str(p)
        s_str = fmt.format(s) if isinstance(s, (int, float)) else str(s)
        print(f"{label:<30} {p_str:>12} {s_str:>12} {delta_str:>12}")

    print()
    ppo_success = "✅" if result["ppo"].get("success") else "❌"
    scr_success = "✅" if result["scripted"].get("success") else "❌"
    print(f"Success:  PPO={ppo_success}  Scripted={scr_success}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
