#!/usr/bin/env python3
"""V1-D5A: offline evaluation of the evidence-gated dynamic rule (0 POSTs).

Replays real recorded evidence/VLM pairs from D3B/D3C/D4C result dirs through
`decide_dynamic_from_evidence`. No network, no new inference.
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

if "torch" not in sys.modules:  # host stub for GMRobot.safety.__init__
    t = types.ModuleType("torch")
    t.device = lambda *_a, **_k: "cpu"
    t.tensor = lambda *a, **k: a
    t.float32 = "float32"
    t.no_grad = lambda: type("NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None})()
    sys.modules["torch"] = t
    sys.modules["torch.nn"] = types.ModuleType("torch.nn")

from GMRobot.safety.evidence_gated_rule import decide_dynamic_from_evidence  # noqa: E402
from GMRobot.vlm.temporal_evidence import TemporalTrackEvidence  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"


def _load_ev(path: Path, **overrides: Any) -> TemporalTrackEvidence:
    d = json.loads(path.read_text())
    d.setdefault("drift_suspect", False)
    d.update(overrides)
    return TemporalTrackEvidence(**d)


def _load_vlm(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> None:
    out = PD / "v1d5a_rule_offline_eval_20260724"
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    out.mkdir(parents=True)

    d3c_ev = PD / "v1d3c_dense_replay_eval_20260724/raw/evidence_249.json"
    d3c_vlm = _load_vlm(PD / "v1d3c_dense_replay_eval_20260724/raw/analyze_249.json")
    d3b_ev = PD / "v1d3b_grounding_eval_20260724/raw/B_gtseed_evidence.json"
    p3_ev = PD / "v1d4c_paired_replay_20260724/raw/P3_perfect_tracker_probe_evidence.json"
    p3_vlm = _load_vlm(PD / "v1d4c_paired_replay_20260724/raw/P3_perfect_tracker_probe.json")

    cases = [
        {
            "case": "C1_d3c_drift_with_d4a",
            "desc": "real drifted SAM2 evidence + D4A flag + real VLM static@0.7",
            "decision": decide_dynamic_from_evidence(
                _load_ev(d3c_ev, drift_suspect=True, valid=False,
                         rejection_reason="pending_validation"),
                vlm_annotation=d3c_vlm,
            ),
            "expect_triggered": False,
        },
        {
            "case": "C2_d3c_drift_without_d4a",
            "desc": "same evidence, pre-D4A world: rule inherits the false positive",
            "decision": decide_dynamic_from_evidence(
                _load_ev(d3c_ev, drift_suspect=False, valid=False,
                         rejection_reason="pending_validation"),
                vlm_annotation=d3c_vlm,
            ),
            "expect_triggered": True,
        },
        {
            "case": "C3_perfect_tracker_probe",
            "desc": "GT-derived probe (35.5 px/s humanoid, diagnostic_only) + real VLM static@0.7 (D4C P3)",
            "decision": decide_dynamic_from_evidence(
                _load_ev(p3_ev, valid=False, rejection_reason="pending_validation"),
                vlm_annotation=p3_vlm,
            ),
            "expect_triggered": True,
        },
        {
            "case": "C4_d3b_sparse_low_score",
            "desc": "real sparse-gap evidence, score 0.26",
            "decision": decide_dynamic_from_evidence(
                _load_ev(d3b_ev, valid=False, rejection_reason="pending_validation"),
            ),
            "expect_triggered": False,
        },
        {
            "case": "C5_vlm_alone_cannot_mint",
            "desc": "no evidence + hypothetical VLM dynamic@0.99/stop",
            "decision": decide_dynamic_from_evidence(
                None,
                vlm_annotation={"risk_type": "dynamic", "risk_confidence": 0.99,
                                "suggested_action": "stop"},
            ),
            "expect_triggered": False,
        },
    ]

    rows = []
    all_ok = True
    for c in cases:
        d = c["decision"]
        ok = d.dynamic_triggered == c["expect_triggered"]
        all_ok = all_ok and ok
        rows.append({
            "case": c["case"], "desc": c["desc"],
            "triggered": d.dynamic_triggered,
            "expected": c["expect_triggered"], "as_expected": ok,
            "rejection_reason": d.rejection_reason,
            "gate_confidence": d.gate_confidence,
            "speed_px_s": d.speed_px_s,
            "recommended_action": d.recommended_action,
            "action_source": d.action_source,
            "vlm_annotation_risk": [d.vlm_annotation.get("risk_type"),
                                    d.vlm_annotation.get("risk_confidence")],
        })

    report = {
        "milestone": "V1-D5A",
        "date": time.strftime("%Y-%m-%d"),
        "rule_version": "evidence_gated_dynamic_rule_v1",
        "post_count": 0,
        "retry_count": 0,
        "cases": rows,
        "all_as_expected": all_ok,
        "verdict": "D5A_RULE_OFFLINE_EVAL_PASS" if all_ok else "D5A_RULE_OFFLINE_EVAL_FAIL",
        "notes": {
            "C2_meaning": "deliberate demonstration that the rule is exactly as good as the evidence layer; D4A drift rejection is mandatory in deployment",
            "C3_meaning": "the dynamic true positive the VLM never produced (static@0.7 attached as annotation); GT-derived probe, diagnostic_only",
            "fusion_v1_untouched": True,
            "semantic_gate_0_85_untouched": True,
        },
    }
    (out / "v1d5a_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"cases": [
        {k: r[k] for k in ("case", "triggered", "expected", "as_expected", "rejection_reason", "recommended_action")}
        for r in rows
    ], "verdict": report["verdict"]}, indent=1))


if __name__ == "__main__":
    main()
