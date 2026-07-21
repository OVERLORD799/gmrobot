#!/usr/bin/env python3
"""GMDisturb batch runner — multi-episode sweep across parameters.

Usage:
    python scripts/run_batch.py --radii 0.5,0.8,1.0 --repeats 3 --max-steps 3000
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from paths import PHASE3_SCRIPT as _PHASE3, resolve_python, \
    ISAACLAB_ROOT as _ISAAC_LAB, CONDA_PREFIX as _CONDA_PREFIX

_PYTHON = resolve_python()

parser = argparse.ArgumentParser(description="GMDisturb Batch Runner")
parser.add_argument("--radii", type=str, default="0.5,0.8,1.0",
                    help="Comma-separated virtual hand radii (default: 0.5,0.8,1.0)")
parser.add_argument("--repeats", type=int, default=3,
                    help="Episodes per radius (default: 3)")
parser.add_argument("--max-steps", type=int, default=3000,
                    help="Steps per episode (default: 3000)")
parser.add_argument("--speed", type=float, default=0.08,
                    help="Virtual hand speed (default: 0.08)")
parser.add_argument("--replan", action="store_true", default=False,
                    help="Enable motion replan (default: off)")
parser.add_argument("--output-dir", type=str, default="/tmp/gmdisturb_batch",
                    help="Output directory (default: /tmp/gmdisturb_batch)")
parser.add_argument("--progress-interval", type=int, default=500,
                    help="Progress print interval (default: 500)")
args_cli = parser.parse_args()

radii = [float(r.strip()) for r in args_cli.radii.split(",")]
repeats = args_cli.repeats
total = len(radii) * repeats

os.makedirs(args_cli.output_dir, exist_ok=True)
jsonl_path = os.path.join(args_cli.output_dir, "episodes.jsonl")
summary_path = os.path.join(args_cli.output_dir, "summary.csv")

print(f"[batch] {len(radii)} radii × {repeats} repeats = {total} episodes")
print(f"[batch] Output: {args_cli.output_dir}")

results: list[dict] = []
episode_num = 0

for radius in radii:
    for rep in range(repeats):
        episode_num += 1
        csv_path = os.path.join(args_cli.output_dir, f"r{radius:.1f}_run{rep+1}.csv")
        tag = f"r={radius:.1f} #{rep+1}/{repeats}"

        print(f"\n{'='*60}")
        print(f"[batch] Episode {episode_num}/{total}: {tag}")
        print(f"[batch] Start: {time.strftime('%H:%M:%S')}")

        cmd = [
            _PYTHON, "-u", _PHASE3,
            "--virtual-hand", str(radius),
            "--virtual-hand-speed", str(args_cli.speed),
            "--max-steps", str(args_cli.max_steps),
            "--progress-interval", str(args_cli.progress_interval),
            "--output_csv", csv_path,
        ]
        if args_cli.replan:
            cmd.append("--replan")

        t0 = time.monotonic()
        env = os.environ.copy()
        env["CONDA_PREFIX"] = _CONDA_PREFIX
        env["OMNI_KIT_ACCEPT_EULA"] = "YES"
        env["DISPLAY"] = os.environ.get("DISPLAY", ":20")

        # R7 C1 fix: use shell=False with list-based cmd (same as batch_runner.py).
        # shell=True with unsanitized user input (--output-dir) is a command
        # injection vulnerability.  cwd= replaces the `cd` prefix.
        try:
            result = subprocess.run(
                cmd,
                cwd=_ISAAC_LAB,
                shell=False,
                env=env,
                capture_output=True, text=True, timeout=3600,
            )
        except subprocess.TimeoutExpired:
            print(f"[batch] TIMEOUT after 3600s")
            results.append({"episode": episode_num, "radius": radius, "repeat": rep+1,
                           "success": False, "error": "timeout"})
            continue

        elapsed = time.monotonic() - t0

        if result.returncode != 0:
            print(f"[batch] ERROR: exit code {result.returncode}")
            print(f"[batch] STDERR: {result.stderr[:500]}")
            results.append({"episode": episode_num, "radius": radius, "repeat": rep+1,
                           "success": False, "error": result.stderr[:200]})
            continue

        # Parse output for key metrics
        output = result.stdout + result.stderr
        success = "ALL PARTS PLACED" in output
        fell = "G1 collapsed" in output
        maxed = "Max steps" in output

        # Parse Safety line
        safety_line = ""
        stop = slow = replan_count = stuck = 0
        parts = 0
        for line in output.split("\n"):
            if "Safety: STOP=" in line:
                safety_line = line
                import re
                m_stop = re.search(r'STOP=(\d+)', line)
                m_slow = re.search(r'SLOW=(\d+)', line)
                m_replan = re.search(r'REPLAN=(\d+)', line)
                m_stuck = re.search(r'STUCK=(\d+)', line)
                if m_stop: stop = int(m_stop.group(1))
                if m_slow: slow = int(m_slow.group(1))
                if m_replan: replan_count = int(m_replan.group(1))
                if m_stuck: stuck = int(m_stuck.group(1))
            if "time_step=" in line and "success=" in line:
                import re
                m_parts = re.search(r'parts=(\d+)/(\d+)', line)
                if m_parts: parts = int(m_parts.group(1))

        # Read CSV for proximity
        min_dist = mean_dist = 0.0
        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    min_dist = float(row.get("min_g1_ur10e_distance_m", 0))
                    mean_dist = float(row.get("mean_g1_ur10e_distance_m", 0))
        except Exception:
            pass

        episode = {
            "episode": episode_num,
            "radius": radius,
            "repeat": rep + 1,
            "success": success,
            "fell": fell,
            "maxed": maxed,
            "stop": stop,
            "slow_down": slow,
            "replan": replan_count,
            "stuck": stuck,
            "parts": parts,
            "min_distance": round(min_dist, 4),
            "mean_distance": round(mean_dist, 4),
            "elapsed_s": round(elapsed, 1),
            "csv": csv_path,
        }
        results.append(episode)

        status = "✅" if success else ("💀" if fell else ("⏱️" if maxed else "❓"))
        print(f"[batch] {status} STOP={stop} SLOW={slow} REPLAN={replan_count} "
              f"parts={parts} time={elapsed:.0f}s")

        # Write incremental JSONL
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(episode) + "\n")

# ── Summary ──────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"[batch] All {total} episodes complete")
print(f"[batch] JSONL: {jsonl_path}")

# Per-radius summary
print(f"\n{'Radius':<8} {'Success':>8} {'STOP':>8} {'SLOW':>8} {'REPLAN':>8} {'Parts':>6}")
print("-" * 50)
for radius in radii:
    group = [r for r in results if r.get("radius") == radius]
    n = len(group)
    if n == 0: continue
    succ = sum(1 for r in group if r.get("success"))
    avg_stop = sum(r.get("stop", 0) for r in group) / n
    avg_slow = sum(r.get("slow_down", 0) for r in group) / n
    avg_replan = sum(r.get("replan", 0) for r in group) / n
    avg_parts = sum(r.get("parts", 0) for r in group) / n
    print(f"{radius:<8.1f} {succ}/{n:<5}  {avg_stop:>7.1f} {avg_slow:>7.1f} {avg_replan:>7.1f} {avg_parts:>5.1f}")

# Write summary CSV
with open(summary_path, "w", newline="") as f:
    fields = ["episode", "radius", "repeat", "success", "fell", "maxed",
              "stop", "slow_down", "replan", "stuck", "parts",
              "min_distance", "mean_distance", "elapsed_s"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in results:
        writer.writerow({k: r[k] for k in fields})

print(f"\n[batch] Summary CSV: {summary_path}")
print(f"[batch] Done at {time.strftime('%H:%M:%S')}")
