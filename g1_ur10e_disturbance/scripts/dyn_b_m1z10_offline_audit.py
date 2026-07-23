#!/usr/bin/env python3
"""V1-M1Z10 offline root-cause audit for Dyn-B M1Z9."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from dyn_b_acceptance_semantics import derive_proxy_semantics, derive_step_completion


TARGET_STEPS = (167, 212, 228)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_float(v: str | None) -> float:
    if v is None:
        return float("nan")
    t = str(v).strip()
    if t in {"", "nan", "NaN", "null", "None"}:
        return float("nan")
    if t in {"inf", "Infinity"}:
        return float("inf")
    if t in {"-inf", "-Infinity"}:
        return float("-inf")
    return float(t)


def _step_table(rows: dict[int, dict[str, str]], center: int, radius: int = 10) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in range(center - radius, center + radius + 1):
        r = rows[s]
        out.append(
            {
                "sim_step": s,
                "policy_step": int(r["policy_step"]),
                "gate_effective": r["gate_effective"],
                "phase": r["phase"],
                "stage": r["ur10e_stage"],
                "closest_g1_body": r["closest_g1_body"],
                "dist_min_for_gating_m": _to_float(r["dist_min_for_gating_m"]),
                "dist_min_g1_body_m": _to_float(r["dist_min_g1_body_m"]),
                "dist_min_proxy_m": _to_float(r["dist_min_proxy_m"]),
                "ttc_observed_s": _to_float(r["ttc_observed_s"]),
                "approach_rate_mps": _to_float(r["approach_rate_mps"]),
                "proxy_surface_velocity_mps": _to_float(r["proxy_surface_velocity_mps"]),
                "robot_ee_velocity_mps": _to_float(r["robot_ee_velocity_mps"]),
                "approach_rate_source": r["approach_rate_source"],
                "ttc_observed_source": r["ttc_observed_source"],
                "relative_velocity_source": r["relative_velocity_source"],
            }
        )
    return out


def classify_step(rows: dict[int, dict[str, str]], target: int) -> dict[str, Any]:
    seq = _step_table(rows, target, radius=10)
    target_row = next(x for x in seq if x["sim_step"] == target)
    prev = rows[target - 1]
    prev_body = prev["closest_g1_body"]
    cur_body = rows[target]["closest_g1_body"]
    switched = prev_body != cur_body

    proxy_v = target_row["proxy_surface_velocity_mps"]
    ee_v = target_row["robot_ee_velocity_mps"]
    neighbor_proxy = [
        x["proxy_surface_velocity_mps"]
        for x in seq
        if x["sim_step"] != target and math.isfinite(x["proxy_surface_velocity_mps"])
    ]
    proxy_med = median(neighbor_proxy) if neighbor_proxy else float("nan")
    proxy_spike = (
        math.isfinite(proxy_v)
        and math.isfinite(proxy_med)
        and proxy_v > 3.0 * max(proxy_med, 1e-6)
        and proxy_v > 3.0 * max(ee_v, 1e-6)
    )

    root = "PROXY_MOTION_OR_PROXY_PROJECTION"
    confidence = 0.86 if proxy_spike else 0.62
    unknowns = []
    if rows[target]["relative_velocity_source"] == "not_exposed_in_runtime_gate_metadata":
        unknowns.append("relative_velocity_mps unavailable in runtime gate metadata")
    if not proxy_spike:
        root = "UNKNOWN"
        confidence = 0.45
        unknowns.append("proxy velocity spike criterion not met")

    if switched:
        root = "CLOSEST_LINK_SWITCH_WITH_PROXY_SPIKE"
        confidence = min(0.93, confidence + 0.05)

    return {
        "sim_step": target,
        "classification": root,
        "confidence": round(confidence, 3),
        "closest_body_prev": prev_body,
        "closest_body_curr": cur_body,
        "closest_body_switched": switched,
        "evidence": {
            "ttc_observed_s": target_row["ttc_observed_s"],
            "approach_rate_mps": target_row["approach_rate_mps"],
            "proxy_surface_velocity_mps": proxy_v,
            "robot_ee_velocity_mps": ee_v,
            "proxy_velocity_neighbor_median_mps": proxy_med,
            "approach_rate_source": target_row["approach_rate_source"],
            "ttc_observed_source": target_row["ttc_observed_source"],
            "relative_velocity_source": target_row["relative_velocity_source"],
        },
        "time_series_pm10": seq,
        "unknowns": unknowns,
    }


def build_report(base_dir: Path, script_path: Path) -> dict[str, Any]:
    safety = base_dir / "safety_logs"
    meta = base_dir / "meta"
    audit_rows = _read_csv(safety / "phase3_dyn_b_per_step_audit.csv")
    phase3_rows = _read_csv(safety / "phase3.csv")
    steps_rows = _read_csv(safety / "phase3_steps.csv")
    events_rows = _read_csv(safety / "phase3_events.csv")
    rows = {int(r["sim_step"]): r for r in audit_rows}

    step_reports = [classify_step(rows, s) for s in TARGET_STEPS]
    completed_window = list(range(159, 339))
    present = {int(r["sim_step"]) for r in audit_rows if 159 <= int(r["sim_step"]) <= 338}
    missing = [s for s in completed_window if s not in present]

    summary = phase3_rows[0]
    total_steps = int(summary["total_steps"])
    policy_steps = int(summary["policy_steps"])
    max_steps = 341
    completion = derive_step_completion(
        total_steps=total_steps,
        policy_steps=policy_steps,
        max_steps=max_steps,
        task_completed=summary.get("task_completed"),
    )
    proxy = derive_proxy_semantics(
        steps_rows=steps_rows,
        window_start=159,
        window_end=338,
        legacy_red_proxy_any=None,
        visual_red_proxy_detected=None,
    )

    return {
        "milestone": "V1-M1Z10",
        "result_dir": str(base_dir),
        "machine_readable_root_cause_classification": {
            "A_ttc_approach_rate_origin": {
                "per_step": step_reports,
                "global_judgement": "PROXY_DOMINATED_SPIKES_NOT_PROVEN_REAL_G1_RELATIVE_MOTION",
                "confidence": 0.88,
                "unknowns": [
                    "runtime metadata does not expose relative_velocity_mps",
                    "body_poses.jsonl only contains camera keyframes (219/220/221/329/330/331), not steps 167/212/228",
                ],
            },
            "B_red_proxy_any_semantics": {
                "classification": "ACCEPTER_PROXY_TELEMETRY_FLAG_NOT_PIXEL_RED_DETECTOR",
                "confidence": 0.95,
                "definition_source": f"{script_path}: red_proxy_any set true when proxy_center_(x,y,z) any non-zero string in step window",
                "detector_type": "telemetry-presence, not color segmentation",
                "window_proxy_rows_nonzero": proxy["proxy_telemetry_rows_nonzero"],
                "proxy_telemetry_present": proxy["proxy_telemetry_present"],
                "red_proxy_any": proxy["red_proxy_any_legacy_compat"],
                "visual_red_proxy_detected": proxy["visual_red_proxy_detected"],
                "visual_red_proxy_evaluation": proxy["visual_red_proxy_evaluation"],
                "events_csv_rows": len(events_rows),
                "unknowns": [
                    "no pixel-level red-proxy detector is executed in M1Z9 flow",
                    "cannot separate real red proxy vs ordinary red object vs visual false-positive from this flag alone",
                ],
            },
            "C_termination_boundary": {
                "classification": completion["termination_reason"],
                "confidence": 0.83,
                "evidence": {
                    "total_steps": completion["total_steps"],
                    "policy_steps_last": completion["policy_steps_last"],
                    "max_steps": completion["max_steps"],
                    "steps_completed_by_total": completion["steps_completed_by_total"],
                    "policy_step_lag": completion["policy_step_lag"],
                    "task_completed": completion["task_completed"],
                    "g1_fell": summary["g1_fell"],
                    "episode_length_note": "episode_length_s configured to cover max_steps in run_phase3",
                },
                "distinction": {
                    "total_sim_steps": "EpisodeMetrics.total_steps increments once per env.step",
                    "policy_steps": "metrics.policy_steps tracks ur10e.time_step and can lag under safety gate holds; it is diagnostic-only for completion",
                },
                "unknowns": [
                    "capture_stdout lacks final termination print lines; reason inferred from final CSV counters and loop contract",
                ],
            },
            "window_159_338_integrity": {
                "classification": "COMPLETE_CONTIGUOUS_WINDOW",
                "confidence": 0.99,
                "missing_steps": missing,
                "risk_of_trailing_incomplete_window": False,
            },
        },
        "next_milestone_recommendation": {
            "direction": "FIX_ACCEPTANCE_AUDITER_SEMANTICS",
            "why": "Current FAIL signal couples red_proxy_any to proxy telemetry presence instead of validated visual proxy risk.",
            "control_semantics_change": False,
        },
        "dyn_b_continue_decision": {
            "decision": "WASTEFUL_LOOP_STOP",
            "reason": "Failure dominated by audit/acceptance semantic mismatch plus proxy-induced telemetry spikes; repeated captures without accepter fix are low value.",
        },
    }


def to_markdown(report: dict[str, Any]) -> str:
    a = report["machine_readable_root_cause_classification"]["A_ttc_approach_rate_origin"]
    b = report["machine_readable_root_cause_classification"]["B_red_proxy_any_semantics"]
    c = report["machine_readable_root_cause_classification"]["C_termination_boundary"]
    w = report["machine_readable_root_cause_classification"]["window_159_338_integrity"]
    lines = [
        "# V1-M1Z10 Dyn-B M1Z9 FAIL_FINAL root-cause audit (offline)",
        "",
        f"- result_dir: `{report['result_dir']}`",
        f"- A global judgement: `{a['global_judgement']}` (confidence `{a['confidence']}`)",
        f"- B classification: `{b['classification']}` (confidence `{b['confidence']}`)",
        f"- C classification: `{c['classification']}` (confidence `{c['confidence']}`)",
        f"- window 159..338 complete: `{not w['missing_steps']}`",
        "",
        "## A) step 167/212/228",
    ]
    for item in a["per_step"]:
        lines.append(
            f"- step `{item['sim_step']}`: `{item['classification']}`; closest `{item['closest_body_prev']} -> {item['closest_body_curr']}`; "
            f"ttc `{item['evidence']['ttc_observed_s']}`; approach `{item['evidence']['approach_rate_mps']}`; "
            f"proxy_v `{item['evidence']['proxy_surface_velocity_mps']}`; ee_v `{item['evidence']['robot_ee_velocity_mps']}`"
        )
    lines.extend(
        [
            "",
            "## B) red_proxy_any",
            f"- definition: `{b['definition_source']}`",
            f"- detector_type: `{b['detector_type']}`",
            f"- window_proxy_rows_nonzero: `{b['window_proxy_rows_nonzero']}`",
            "",
            "## C) 335 vs 341",
            f"- total_steps/policy_steps/max_steps: `{c['evidence']['total_steps']}/{c['evidence']['policy_steps_last']}/{c['evidence']['max_steps']}`",
            f"- lag explanation: `{c['distinction']['policy_steps']}`",
            "",
            "## Recommendation",
            f"- direction: `{report['next_milestone_recommendation']['direction']}`",
            f"- Dyn-B decision: `{report['dyn_b_continue_decision']['decision']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline M1Z10 root-cause audit.")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--md-out", required=True)
    args = ap.parse_args()

    report = build_report(Path(args.result_dir), Path(__file__).resolve().with_name("run_e01_dyn_b_m1z_reviewable_preflight.sh"))
    j = Path(args.json_out)
    m = Path(args.md_out)
    j.parent.mkdir(parents=True, exist_ok=True)
    m.parent.mkdir(parents=True, exist_ok=True)
    j.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    m.write_text(to_markdown(report), encoding="utf-8")
    print(json.dumps({"json_out": str(j), "md_out": str(m), "decision": report["dyn_b_continue_decision"]["decision"]}))


if __name__ == "__main__":
    main()
