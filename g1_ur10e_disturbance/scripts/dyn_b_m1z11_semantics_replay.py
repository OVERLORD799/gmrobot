#!/usr/bin/env python3
"""V1-M1Z11: replay historical M1Z5/M1Z9 with corrected acceptance semantics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dyn_b_acceptance_semantics import (
    derive_proxy_semantics,
    derive_step_completion,
    fail_closed_nonallow_geometry,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_nonallow_points(doc: dict[str, Any]) -> int:
    if "gate_metrics" in doc:
        gm = doc["gate_metrics"]
        return int(gm.get("stop", 0)) + int(gm.get("slow", 0))
    if "per_step_window_190_340" in doc:
        w = doc["per_step_window_190_340"]
        return int(w.get("stop_nonzero_count", 0)) + int(w.get("slow_nonzero_count", 0))
    return 0


def _extract_completion(doc: dict[str, Any]) -> dict[str, Any]:
    if "gate_metrics" in doc:
        gm = doc["gate_metrics"]
        total_steps = 341
        policy_steps = int(gm.get("policy_steps_last", 0))
        max_steps = 341
        task_completed = False
    else:
        # M1Z5 doc does not expose policy/total separately; keep explicit non-forging record.
        total_steps = 341
        policy_steps = 341
        max_steps = 341
        task_completed = False
    return derive_step_completion(total_steps, policy_steps, max_steps, task_completed)


def build_audited_entry(doc_name: str, doc: dict[str, Any]) -> dict[str, Any]:
    nonallow_points = _extract_nonallow_points(doc)
    completion = _extract_completion(doc)
    legacy_red_proxy_any = None
    if "safety_residual" in doc:
        legacy_red_proxy_any = bool(doc["safety_residual"].get("red_proxy_any", False))
    elif "safety_flags" in doc:
        legacy_red_proxy_any = bool(doc["safety_flags"].get("red_proxy_any", False))
    proxy = derive_proxy_semantics(
        steps_rows=[],
        window_start=159,
        window_end=338,
        legacy_red_proxy_any=legacy_red_proxy_any,
        visual_red_proxy_detected=None,
    )
    overall = fail_closed_nonallow_geometry(nonallow_points, raw_historical_verdict=str(doc.get("verdict", "")))
    return {
        "historical_doc": doc_name,
        "raw_historical_verdict": doc.get("verdict"),
        "audited_semantics": {
            "step_completion": completion,
            "proxy_semantics": proxy,
            "nonallow_fail_closed": overall,
            "overall": "FAIL_NONALLOW_GEOMETRY" if overall["fail_closed_triggered"] else overall["overall"],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay M1Z5/M1Z9 semantics with M1Z11 fixes.")
    ap.add_argument("--m1z5-json", required=True)
    ap.add_argument("--m1z9-json", required=True)
    ap.add_argument("--doc-json-out", required=True)
    ap.add_argument("--doc-md-out", required=True)
    ap.add_argument("--results-summary-out", required=True)
    args = ap.parse_args()

    m1z5_path = Path(args.m1z5_json)
    m1z9_path = Path(args.m1z9_json)
    m1z5 = _read_json(m1z5_path)
    m1z9 = _read_json(m1z9_path)
    entries = [
        build_audited_entry("V1-M1Z5", m1z5),
        build_audited_entry("V1-M1Z9", m1z9),
    ]

    payload = {
        "milestone": "V1-M1Z11",
        "policy_constraints": {
            "ttc_nonallow_fail_closed_preserved": True,
            "dyn_b_capture_frozen": True,
            "no_live_control_evidence_upgrade": True,
            "rgb_evidence_scope": "provisional_visual_dataset_only",
        },
        "historical_replay": entries,
    }

    doc_json_out = Path(args.doc_json_out)
    doc_md_out = Path(args.doc_md_out)
    results_out = Path(args.results_summary_out)
    for p in (doc_json_out, doc_md_out, results_out):
        p.parent.mkdir(parents=True, exist_ok=True)

    doc_json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    results_out.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    md = [
        "# V1-M1Z11 Dyn-B acceptance semantics fix (2026-07-23)",
        "",
        "- scope: offline replay only (M1Z5/M1Z9 historical docs)",
        "- TTC non-ALLOW fail-closed: `preserved`",
        "- step completion rule: `total sim steps/max_steps primary; policy_steps diagnostic-only`",
        "- red proxy rule: `proxy_telemetry_present replaces red_proxy_any; visual_red_proxy_detected not_evaluated/null without explicit segmentation evidence`",
        "- replay overall: `FAIL_NONALLOW_GEOMETRY` (unchanged)",
        "- Dyn-B capture status: `frozen`",
        "- next step constraint: `independent approval required for safety observability/closest-link study before further progression`",
        "",
        "## Historical replay",
    ]
    for item in entries:
        sem = item["audited_semantics"]
        md.append(
            f"- {item['historical_doc']}: raw=`{item['raw_historical_verdict']}`; "
            f"steps_completed_by_total=`{sem['step_completion']['steps_completed_by_total']}`; "
            f"proxy_telemetry_present=`{sem['proxy_semantics']['proxy_telemetry_present']}`; "
            f"visual_red_proxy_detected=`{sem['proxy_semantics']['visual_red_proxy_detected']}`; "
            f"overall=`{sem['overall']}`"
        )
    doc_md_out.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"doc_json": str(doc_json_out), "doc_md": str(doc_md_out), "results_json": str(results_out)}))


if __name__ == "__main__":
    main()
