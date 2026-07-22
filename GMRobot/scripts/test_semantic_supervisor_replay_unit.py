#!/usr/bin/env python3
"""V0-C3 negative replay + synthetic positive tests for V1-B supervisor."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import types

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
_SAFETY = ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))
_pkg = types.ModuleType("safety")
_pkg.__path__ = [str(_SAFETY)]
sys.modules["safety"] = _pkg

from safety.semantic_supervisor import (  # noqa: E402
    GATE_ALLOW,
    GATE_SLOW_DOWN,
    REASON_CONSISTENCY_PENDING,
    REASON_LOW_CONFIDENCE,
    REASON_RISK_TYPE_NOT_ALLOWED,
    SemanticAdvisoryInput,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
    advisory_input_from_shadow_row,
)


def _resolve_v0c3() -> Path:
    base = REPO / "g1_ur10e_disturbance" / "results" / "paper_demo" / "v0c3_isaac_shadow_20260721"
    top = base / "five_stage_shadow_requests.jsonl"
    if top.is_file():
        return top
    matches = sorted(base.glob("five_stage_shadow_*/five_stage_shadow_requests.jsonl"))
    assert matches, f"missing V0-C3 jsonl under {base}"
    return matches[-1]


def test_v0c3_negative_accepted_zero():
    path = _resolve_v0c3()
    # Ensure original untouched: read only
    raw = path.read_text(encoding="utf-8")
    cfg = SemanticSupervisorConfig.from_dict(
        dict(
            enabled=True,
            enforcement_mode="shadow",
            min_risk_confidence=0.85,
            min_consistent_results=2,
            reject_static_risk_in_v1=True,
        )
    )
    s = SemanticSafetySupervisor(cfg)
    reasons = []
    accepted = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        inp = advisory_input_from_shadow_row(row, result_age_s=0.1, current_geometry_gate=GATE_ALLOW)
        d = s.evaluate(inp)
        reasons.append(d.rejection_reason)
        if d.accepted:
            accepted += 1
        assert d.intentional_control_effect is False
        assert d.would_stop is False
        assert d.would_replan is False
    assert accepted == 0
    assert REASON_RISK_TYPE_NOT_ALLOWED in reasons
    # Original file unchanged
    assert path.read_text(encoding="utf-8") == raw


def test_v0c3_static_slow_down_rejected():
    path = _resolve_v0c3()
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    vlm = row.get("vlm") or {}
    assert (vlm.get("risk_type") or row.get("risk_type")) == "static"
    assert (vlm.get("suggested_action") or row.get("suggested_action")) == "slow_down"
    cfg = SemanticSupervisorConfig.from_dict(dict(enabled=True, enforcement_mode="shadow"))
    s = SemanticSafetySupervisor(cfg)
    d = s.evaluate(advisory_input_from_shadow_row(row, result_age_s=0.1))
    assert d.accepted is False
    assert d.rejection_reason == REASON_RISK_TYPE_NOT_ALLOWED


def test_v0c3_dynamic_low_conf_also_blocked():
    path = _resolve_v0c3()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 2
    row = json.loads(lines[1])
    cfg = SemanticSupervisorConfig.from_dict(dict(enabled=True, enforcement_mode="shadow"))
    s = SemanticSafetySupervisor(cfg)
    # First consume frame0 so frame1 is evaluated fresh? Actually different request ids.
    # Frame0 rejected for static still consumes request id.
    s.evaluate(advisory_input_from_shadow_row(json.loads(lines[0]), result_age_s=0.1))
    d = s.evaluate(advisory_input_from_shadow_row(row, result_age_s=0.1))
    # conf 0.7 < 0.85
    assert d.rejection_reason == REASON_LOW_CONFIDENCE


def test_synthetic_dynamic_two_accepted():
    cfg = SemanticSupervisorConfig.from_dict(
        dict(enabled=True, enforcement_mode="shadow", min_consistent_results=2, cooldown_s=0.0)
    )
    s = SemanticSafetySupervisor(cfg)

    def make(rid, t):
        return SemanticAdvisoryInput(
            episode_id="synth",
            sim_step=0,
            current_time_s=t,
            request_id=rid,
            frame_id=rid + "-f",
            result_age_s=0.05,
            schema_version="five_stage_vlm_v1",
            gateway_parse_ok=True,
            risk_type="dynamic",
            risk_confidence=0.92,
            affected_entities=["human", "robot"],
            predicted_consequence="potential collision with human",
            prediction_horizon_s=1.5,
            suggested_action="slow_down",
            spatial_hint="front",
            current_geometry_gate=GATE_ALLOW,
            synthetic=True,
        )

    d1 = s.evaluate(make("s1", 1.0))
    assert d1.rejection_reason == REASON_CONSISTENCY_PENDING
    d2 = s.evaluate(make("s2", 1.4))
    assert d2.accepted is True
    assert d2.requested_gate == GATE_SLOW_DOWN
    assert d2.effective_gate_shadow == GATE_SLOW_DOWN
    assert d2.intentional_control_effect is False
    assert d2.synthetic is True


def test_replay_script_exit_zero():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "replay_out"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "replay_semantic_supervisor_v1b.py"),
                "--repo-root",
                str(REPO),
                "--out-dir",
                str(out),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "V1B_NEGATIVE_REPLAY_OK" in proc.stdout
        summary = json.loads((out / "replay_summary.json").read_text(encoding="utf-8"))
        assert summary["accepted_count"] == 0
        assert summary["intentional_control_effect_count"] == 0
        assert summary["contains_risk_type_not_allowed"] is True
        assert summary["real_post_count"] == 0
        assert summary["isaac_run"] is False


def test_old_vlm_stage5_replan_not_invoked_by_supervisor():
    """Supervisor module must not reference the legacy live replan trigger source."""
    src = (ROOT / "source" / "GMRobot" / "GMRobot" / "safety" / "semantic_supervisor.py").read_text(
        encoding="utf-8"
    )
    assert "vlm_stage5_replan" not in src
    agent = (ROOT / "scripts" / "gm_state_machine_agent.py").read_text(encoding="utf-8")
    assert "vlm_stage5_replan" in agent  # legacy path still present (not deleted)
    # Default config does not enable live replan coupling
    cfg_text = (ROOT / "configs" / "semantic_safety_supervisor.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in cfg_text
    assert "allow_replan: false" in cfg_text


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("PASS")
