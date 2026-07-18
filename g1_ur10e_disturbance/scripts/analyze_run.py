#!/usr/bin/env python3
"""Print a concise analysis of a _steps.csv run file. Usage: analyze_run.py <steps.csv>"""

import csv
import sys
from collections import defaultdict, Counter

EPISODE_PHASES = [
    "IDLE", "APPROACH", "GRASP", "LIFT", "RETREAT", "CARRY", "PLACE",
    "RETURN", "WAIT", "DONE", "DEADLOCK", "UNSTUCK", "ABORTED",
]


def analyze(path):
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        sys.exit(f"ERROR: file not found: {path}")
    except Exception as e:
        sys.exit(f"ERROR: cannot read {path}: {e}")

    if not rows:
        sys.exit("ERROR: empty CSV")

    total = len(rows)
    policy_steps = sum(1 for r in rows if r.get("gate", "") == "ALLOW")
    parts_placed = int(max(r.get("parts_placed", 0) or 0 for r in rows))
    gate_counts = Counter(r.get("gate", "") for r in rows)
    replan_count = int(max(r.get("replan_count", 0) or 0 for r in rows))

    print("=" * 64)
    print("EPISODE SUMMARY")
    print("=" * 64)
    print(f"  Total steps:        {total}")
    print(f"  Policy steps:       {policy_steps} (ALLOW)")
    print(f"  Parts placed:       {parts_placed}")
    for g in ("STOP", "SLOW", "ALLOW"):
        print(f"  {g}:                {gate_counts.get(g, 0)}")
    print(f"  Replan count:       {replan_count}")

    # --- Per-part breakdown ---
    by_part = defaultdict(list)  # part -> list of (step_idx, row)
    for i, r in enumerate(rows):
        part = r.get("protocol_part", "") or "(none)"
        by_part[part].append((i, r))

    print("\n" + "=" * 64)
    print("PER-PART BREAKDOWN")
    print("=" * 64)
    for part, entries in by_part.items():
        phases_seen = []
        for _, r in entries:
            ph = r.get("protocol_phase", "")
            if ph and (not phases_seen or phases_seen[-1] != ph):
                phases_seen.append(ph)
        start, end = entries[0][0], entries[-1][0]
        stop_count = sum(1 for _, r in entries if r.get("gate", "") == "STOP")
        print(f"\n  part={part}  steps={start}..{end}  phases={phases_seen}  STOP={stop_count}")

    # --- Replan events ---
    replans = []
    seen_trigger = set()
    for i, r in enumerate(rows):
        if r.get("replan_strategy", "") and (r.get("replan_raise_m") or r.get("replan_lateral_m")):
            tup = (r.get("step", ""), r.get("replan_strategy", ""),
                   r.get("replan_raise_m", ""), r.get("replan_lateral_m", ""))
            if tup not in seen_trigger:
                seen_trigger.add(tup)
                replans.append((i, r))
    if replans:
        print("\n" + "=" * 64)
        print("REPLAN EVENTS")
        print("=" * 64)
        print(f"  {'step':>6s}  {'trigger_rule':>20s}  {'strategy':>12s}  {'raise_m':>8s}  {'lateral_m':>10s}")
        print(f"  {'-'*6}  {'-'*20}  {'-'*12}  {'-'*8}  {'-'*10}")
        for _, r in replans:
            print(f"  {r['step']:>6s}  {r.get('gate_trigger',''):>20s}  {r['replan_strategy']:>12s}  {r['replan_raise_m']:>8s}  {r['replan_lateral_m']:>10s}")

    # --- Deadlock events ---
    deadlocks = [(i, r) for i, r in enumerate(rows) if float(r.get("deadlock_tier", 0) or 0) > 0]
    if deadlocks:
        print("\n" + "=" * 64)
        print("DEADLOCK EVENTS")
        print("=" * 64)
        for i, r in deadlocks:
            print(f"  step={r.get('step','?')}  tier={r['deadlock_tier']}  phase={r.get('protocol_phase','')}  part={r.get('protocol_part','')}")

    # --- G1 body proximity ---
    body_vals = []
    close_steps = []
    for i, r in enumerate(rows):
        v = r.get("g1_body_dist", "")
        if v:
            bd = float(v)
            body_vals.append(bd)
            if bd < 0.20:
                close_steps.append((i, r))
    if body_vals:
        print("\n" + "=" * 64)
        print("G1 BODY PROXIMITY")
        print("=" * 64)
        print(f"  min:  {min(body_vals):.4f}")
        print(f"  mean: {sum(body_vals) / len(body_vals):.4f}")
        if close_steps:
            print(f"  steps with dist < 0.20: {len(close_steps)}")
            for _, r in close_steps:
                print(f"    step={r.get('step','?')}  dist={float(r['g1_body_dist']):.4f}  part={r.get('protocol_part','')}")

    # --- Part Z tracking ---
    z_vals = []
    for r in rows:
        v = r.get("min_part_z", "")
        if v:
            z_vals.append(float(v))
    max_below = max(int(r.get("parts_below_table", 0) or 0) for r in rows)
    if z_vals:
        print("\n" + "=" * 64)
        print("PART Z TRACKING")
        print("=" * 64)
        print(f"  min part Z:       {min(z_vals):.4f}")
        print(f"  max parts below:  {max_below}")

    # --- Grasp events ---
    max_rewinds = max(int(r.get("grasp_rewinds", 0) or 0) for r in rows)
    carry_aborted = any(r.get("carry_aborted", "") == "1" for r in rows)
    print("\n" + "=" * 64)
    print("GRASP EVENTS")
    print("=" * 64)
    print(f"  max grasp rewinds:  {max_rewinds}")
    print(f"  carry aborted:      {carry_aborted}")

    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: analyze_run.py <steps.csv>")
    analyze(sys.argv[1])
