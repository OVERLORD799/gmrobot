#!/usr/bin/env python3
"""Fail-closed analyzer for Dyn-B per-step geometry audit CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def _f(row: dict[str, str], key: str) -> float:
    return float(str(row.get(key, "")).strip())


def analyze_dyn_b_per_step_window(
    csv_path: Path | str,
    *,
    step_start: int = 190,
    step_end: int = 340,
    min_margin_m: float = 0.10,
) -> dict:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    wanted = [r for r in rows if r.get("sim_step", "").strip() != ""]
    steps = [int(r["sim_step"]) for r in wanted]
    window = [r for r in wanted if step_start <= int(r["sim_step"]) <= step_end]
    window_steps = [int(r["sim_step"]) for r in window]
    ctr = Counter(window_steps)
    expected = list(range(step_start, step_end + 1))
    missing = [s for s in expected if ctr.get(s, 0) == 0]
    duplicates = sorted(s for s, c in ctr.items() if c > 1)
    out_of_window = sorted(s for s in window_steps if s < step_start or s > step_end)

    errors: list[str] = []
    if missing:
        errors.append(f"missing sim_step(s): {missing}")
    if duplicates:
        errors.append(f"duplicate sim_step(s): {duplicates}")
    if out_of_window:
        errors.append(f"out-of-window steps present: {out_of_window}")

    non_allow = [int(r["sim_step"]) for r in window if str(r.get("gate_effective", "")).upper() != "ALLOW"]
    if non_allow:
        errors.append(f"non-ALLOW effective gate in window: {non_allow}")

    stop_nonzero = [int(r["sim_step"]) for r in window if int(float(str(r.get("stop_flag", "0") or "0"))) != 0]
    slow_nonzero = [int(r["sim_step"]) for r in window if int(float(str(r.get("slow_flag", "0") or "0"))) != 0]
    replan_nonzero = [int(r["sim_step"]) for r in window if int(float(str(r.get("replan_flag", "0") or "0"))) != 0]
    if stop_nonzero:
        errors.append(f"stop_flag != 0 at steps: {stop_nonzero}")
    if slow_nonzero:
        errors.append(f"slow_flag != 0 at steps: {slow_nonzero}")
    if replan_nonzero:
        errors.append(f"replan_flag != 0 at steps: {replan_nonzero}")

    low_margin = [int(r["sim_step"]) for r in window if _f(r, "margin_to_gate_m") < min_margin_m]
    if low_margin:
        errors.append(f"margin_to_gate_m < {min_margin_m:.2f} at steps: {low_margin}")

    by_step = {int(r["sim_step"]): r for r in window}
    phase_220 = str(by_step.get(220, {}).get("phase", ""))
    phase_330 = str(by_step.get(330, {}).get("phase", ""))
    if phase_220 != "lateral_positive_sweep":
        errors.append(f"step 220 phase mismatch: {phase_220!r}")
    if phase_330 != "lateral_negative_sweep":
        errors.append(f"step 330 phase mismatch: {phase_330!r}")

    return {
        "csv_path": str(path),
        "step_start": step_start,
        "step_end": step_end,
        "expected_count": len(expected),
        "observed_count": len(window_steps),
        "missing_steps": missing,
        "duplicate_steps": duplicates,
        "non_allow_steps": non_allow,
        "stop_nonzero_steps": stop_nonzero,
        "slow_nonzero_steps": slow_nonzero,
        "replan_nonzero_steps": replan_nonzero,
        "low_margin_steps": low_margin,
        "phase_220": phase_220,
        "phase_330": phase_330,
        "pass": len(errors) == 0,
        "errors": errors,
        "policy": {
            "gate_effective_required": "ALLOW",
            "stop_flag_required": 0,
            "slow_flag_required": 0,
            "replan_flag_required": 0,
            "margin_to_gate_min_m": min_margin_m,
            "phase_220_required": "lateral_positive_sweep",
            "phase_330_required": "lateral_negative_sweep",
            "step_uniqueness_required": "exactly_once_each_integer",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Fail-closed window audit for Dyn-B per-step telemetry.")
    ap.add_argument("--csv", required=True, help="Path to --dyn-b-per-step-audit-csv output.")
    ap.add_argument("--step-start", type=int, default=190)
    ap.add_argument("--step-end", type=int, default=340)
    ap.add_argument("--min-margin-m", type=float, default=0.10)
    ap.add_argument("--json-out", type=str, default="")
    args = ap.parse_args()
    report = analyze_dyn_b_per_step_window(
        args.csv,
        step_start=args.step_start,
        step_end=args.step_end,
        min_margin_m=args.min_margin_m,
    )
    text = json.dumps(report, indent=2, ensure_ascii=True)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
