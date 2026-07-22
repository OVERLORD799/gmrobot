#!/usr/bin/env python3
"""Logger round-trip / sensitive-field tests for semantic supervisor."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

import types

ROOT = Path(__file__).resolve().parents[1]
_SAFETY = ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))
_pkg = types.ModuleType("safety")
_pkg.__path__ = [str(_SAFETY)]
sys.modules["safety"] = _pkg

from safety.semantic_supervisor import (  # noqa: E402
    GATE_ALLOW,
    SemanticAdvisoryInput,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
)
from safety.semantic_supervisor_logger import (  # noqa: E402
    SEMANTIC_SUPERVISOR_FIELDS,
    SemanticSupervisorLogger,
    sanitize_for_semantic_log,
)


def _accept_decision():
    cfg = SemanticSupervisorConfig.from_dict(
        dict(
            enabled=True,
            enforcement_mode="shadow",
            min_consistent_results=2,
            cooldown_s=0.0,
        )
    )
    s = SemanticSafetySupervisor(cfg)

    def one(rid, t):
        return s.evaluate(
            SemanticAdvisoryInput(
                episode_id="0",
                sim_step=0,
                current_time_s=t,
                request_id=rid,
                frame_id=rid + "-f",
                result_age_s=0.1,
                schema_version="five_stage_vlm_v1",
                gateway_parse_ok=True,
                risk_type="dynamic",
                risk_confidence=0.92,
                affected_entities=["human"],
                predicted_consequence="potential collision",
                prediction_horizon_s=1.5,
                suggested_action="slow_down",
                spatial_hint="left",
                current_geometry_gate=GATE_ALLOW,
                synthetic=True,
            )
        )

    one("r1", 1.0)
    return one("r2", 1.5)


def test_logger_round_trip():
    d = _accept_decision()
    with tempfile.TemporaryDirectory() as td:
        logger = SemanticSupervisorLogger(td, enabled=True)
        logger.log_decision(d)
        summary = logger.close()
        assert summary["rows"] == 1
        assert summary["accepted_count"] == 1
        session = logger.session_dir
        assert session is not None
        rows = [
            json.loads(line)
            for line in (session / "semantic_supervisor_decisions.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(rows) == 1
        assert rows[0]["accepted"] is True
        assert rows[0]["intentional_control_effect"] is False
        with (session / "semantic_supervisor_steps.csv").open(encoding="utf-8") as f:
            cr = list(csv.DictReader(f))
        assert list(cr[0].keys()) == SEMANTIC_SUPERVISOR_FIELDS
        assert cr[0]["accepted"] in ("True", "true", True) or cr[0]["accepted"] == "True"
        # csv writes bool as True/False strings
        assert str(cr[0]["requested_gate"]) == "SLOW_DOWN"
        assert str(cr[0]["effective_gate_shadow"]) == "SLOW_DOWN"


def test_log_has_no_sensitive_fields():
    blob = sanitize_for_semantic_log(
        {
            "session_id": "secret-session-xyz",
            "track_session_id": "abc",
            "explanation": "very long " * 100,
            "token": "tok",
            "image_b64": "aaaa",
            "ok": True,
            "consequence": "potential collision",
        }
    )
    assert blob["session_id"] == "<redacted>"
    assert blob["track_session_id"] == "<redacted>"
    assert "explanation" not in blob
    assert blob["token"] == "<redacted>"
    assert blob["image_b64"] == "<redacted>"
    text = json.dumps(blob)
    assert "secret-session-xyz" not in text
    assert "aaaa" not in text


def test_no_replan_fields_true():
    d = _accept_decision()
    assert d.would_replan is False
    assert d.would_stop is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("PASS")
