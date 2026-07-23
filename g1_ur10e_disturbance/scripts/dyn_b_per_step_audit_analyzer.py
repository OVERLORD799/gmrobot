#!/usr/bin/env python3
"""Dyn-B per-step attribution analyzer with old-schema compatibility."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def _to_int(text: str) -> int:
    return int(str(text).strip())


def _is_nullish(text: str | None) -> bool:
    token = ("" if text is None else str(text).strip())
    return token in {"", "null", "None", "nan", "NaN"}


def _non_allow_ranges(steps: list[int]) -> list[dict[str, int | str]]:
    if not steps:
        return []
    out: list[dict[str, int | str]] = []
    s = steps[0]
    p = steps[0]
    for cur in steps[1:]:
        if cur == p + 1:
            p = cur
            continue
        out.append({"start": s, "end": p, "length": p - s + 1, "continuity": "contiguous"})
        s = cur
        p = cur
    out.append({"start": s, "end": p, "length": p - s + 1, "continuity": "contiguous"})
    return out


def _attribution_for_non_allow(row: dict[str, str]) -> dict[str, str]:
    trigger_rule = str(row.get("trigger_rule", "")).strip()
    trigger_reason = str(row.get("trigger_reason", "")).strip()
    gate_effective = str(row.get("gate_effective", "")).strip().upper()
    has_new_schema = "ttc_observed_s" in row and "ttc_forecast_s" in row
    if not has_new_schema:
        return {
            "attribution_status": "INSUFFICIENT",
            "reason": "old_schema_missing_ttc_attribution_fields",
            "trigger_rule": trigger_rule,
            "trigger_reason": trigger_reason,
            "gate_effective": gate_effective,
        }

    if trigger_rule == "":
        return {
            "attribution_status": "INSUFFICIENT",
            "reason": "missing_trigger_rule",
            "trigger_rule": trigger_rule,
            "trigger_reason": trigger_reason,
            "gate_effective": gate_effective,
        }

    if trigger_rule == "ttc":
        has_ttc_observed = not _is_nullish(row.get("ttc_observed_s"))
        has_ttc_forecast = not _is_nullish(row.get("ttc_forecast_s"))
        has_approach_rate = not _is_nullish(row.get("approach_rate_mps"))
        if (has_ttc_observed or has_ttc_forecast) and has_approach_rate:
            return {
                "attribution_status": "EXPLAINED",
                "reason": "ttc_rule_with_runtime_ttc_and_approach_rate",
                "trigger_rule": trigger_rule,
                "trigger_reason": trigger_reason,
                "gate_effective": gate_effective,
            }
        return {
            "attribution_status": "INSUFFICIENT",
            "reason": "ttc_rule_missing_runtime_ttc_or_approach_rate",
            "trigger_rule": trigger_rule,
            "trigger_reason": trigger_reason,
            "gate_effective": gate_effective,
        }

    return {
        "attribution_status": "EXPLAINED",
        "reason": "non_ttc_rule_with_trigger_rule_present",
        "trigger_rule": trigger_rule,
        "trigger_reason": trigger_reason,
        "gate_effective": gate_effective,
    }


def analyze_dyn_b_per_step_window(
    csv_path: Path | str,
    *,
    step_start: int = 190,
    step_end: int = 340,
    min_margin_m: float = 0.10,
) -> dict:
    del min_margin_m  # M1Z7: margin is not a safety/explanation criterion.
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    valid_rows = [r for r in rows if str(r.get("sim_step", "")).strip() != ""]
    window = [r for r in valid_rows if step_start <= _to_int(r["sim_step"]) <= step_end]
    window_steps = [int(r["sim_step"]) for r in window]
    ctr = Counter(window_steps)
    expected = list(range(step_start, step_end + 1))
    missing = [s for s in expected if ctr.get(s, 0) == 0]
    duplicates = sorted(s for s, c in ctr.items() if c > 1)

    non_allow_rows = [r for r in window if str(r.get("gate_effective", "")).upper() != "ALLOW"]
    non_allow_steps = sorted(_to_int(r["sim_step"]) for r in non_allow_rows)
    points = []
    explained_steps: list[int] = []
    insufficient_steps: list[int] = []
    for row in non_allow_rows:
        step = _to_int(row["sim_step"])
        attr = _attribution_for_non_allow(row)
        if attr["attribution_status"] == "EXPLAINED":
            explained_steps.append(step)
        else:
            insufficient_steps.append(step)
        points.append({"sim_step": step, **attr})

    errors: list[str] = []
    if missing:
        errors.append(f"missing sim_step(s): {missing}")
    if duplicates:
        errors.append(f"duplicate sim_step(s): {duplicates}")
    if insufficient_steps:
        errors.append(f"non-ALLOW attribution insufficient at steps: {sorted(insufficient_steps)}")

    has_new_schema = all(
        name in (rows[0].keys() if rows else [])
        for name in ("protocol_phase", "ur10e_stage", "ttc_observed_s", "ttc_forecast_s")
    )
    return {
        "csv_path": str(path),
        "step_start": step_start,
        "step_end": step_end,
        "expected_count": len(expected),
        "observed_count": len(window_steps),
        "missing_steps": missing,
        "duplicate_steps": duplicates,
        "schema_version": "m1z7" if has_new_schema else "legacy_pre_m1z7",
        "non_allow_steps": non_allow_steps,
        "non_allow_ranges": _non_allow_ranges(non_allow_steps),
        "non_allow_points": sorted(points, key=lambda x: int(x["sim_step"])),
        "explained_steps": sorted(explained_steps),
        "insufficient_steps": sorted(insufficient_steps),
        "pass": len(errors) == 0,
        "errors": errors,
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
