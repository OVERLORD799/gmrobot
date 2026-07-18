"""Unit tests for SafetyLogger replan column wiring (no Isaac)."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _safety_import import bootstrap_safety, load_safety_module

safety = bootstrap_safety()
load_safety_module("logger")
SafetyLogger = safety.logger.SafetyLogger
replan_log_fields_for_step = safety.logger.replan_log_fields_for_step
GateDecision = safety.types.GateDecision
GateResult = safety.types.GateResult
SafetyState = safety.types.SafetyState


def _state(step_index: int) -> SafetyState:
    return SafetyState(
        ee_pos=np.zeros(3, dtype=np.float32),
        ee_vel=np.zeros(3, dtype=np.float32),
        human_hand_pos=np.zeros(3, dtype=np.float32),
        human_hand_vel=np.zeros(3, dtype=np.float32),
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        sim_time=float(step_index) * 0.02,
        step_index=step_index,
    )


def _gate() -> GateResult:
    return GateResult(g_t=GateDecision.ALLOW, reason="ok", metadata={})


def _action() -> np.ndarray:
    return np.zeros(8, dtype=np.float32)


def test_replan_log_fields_for_step_maps_active_and_event():
    idle = replan_log_fields_for_step(
        replan_enabled=True,
        transport_phase="transit",
        stage_name="move_above_slot_A_1",
        post_replan_advance_active=False,
    )
    assert idle == {
        "replan_active": "0",
        "replan_stage": "",
        "replan_event": "",
        "replan_trigger": "",
    }

    triggered = replan_log_fields_for_step(
        replan_enabled=True,
        transport_phase="transit",
        stage_name="move_above_slot_A_1",
        post_replan_advance_active=False,
        event="trigger",
        trigger_rule="ttc",
    )
    assert triggered["replan_event"] == "trigger"
    assert triggered["replan_trigger"] == "ttc"

    applied = replan_log_fields_for_step(
        replan_enabled=True,
        transport_phase="transit",
        stage_name="move_above_slot_A_1",
        post_replan_advance_active=True,
        event="applied",
        trigger_rule="ttc",
    )
    assert applied["replan_event"] == "applied"
    assert applied["replan_trigger"] == "ttc"

    detour = replan_log_fields_for_step(
        replan_enabled=True,
        transport_phase="transit",
        stage_name="replan_detour_raise",
        post_replan_advance_active=False,
    )
    assert detour["replan_active"] == "1"
    assert detour["replan_stage"] == "replan_detour_raise"


def test_replan_log_fields_disabled_returns_empty_columns():
    fields = replan_log_fields_for_step(replan_enabled=False)
    assert fields == {
        "replan_active": "",
        "replan_stage": "",
        "replan_event": "",
        "replan_trigger": "",
    }


def test_safety_logger_record_writes_replan_columns():
    with tempfile.TemporaryDirectory() as tmp:
        logger = SafetyLogger(tmp, episode_id=0, enabled=True, flush_interval=1)
        action = _action()
        gate = _gate()
        replan_fields = replan_log_fields_for_step(
            replan_enabled=True,
            transport_phase="transit",
            stage_name="replan_detour_lateral",
            post_replan_advance_active=True,
            event="applied",
            trigger_rule="ttc",
        )

        logger.record(_state(0), action, gate, action, replan_fields=replan_fields)
        logger.record(_state(1), action, gate, action)
        path = logger.flush()
        assert path is not None

        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        assert rows[0]["replan_active"] == "1"
        assert rows[0]["replan_stage"] == "replan_detour_lateral"
        assert rows[0]["replan_event"] == "applied"
        assert rows[0]["replan_trigger"] == "ttc"
        for key in ("replan_active", "replan_stage", "replan_event", "replan_trigger"):
            assert key in rows[1]
            assert rows[1][key] == ""


if __name__ == "__main__":
    test_replan_log_fields_for_step_maps_active_and_event()
    test_replan_log_fields_disabled_returns_empty_columns()
    test_safety_logger_record_writes_replan_columns()
    print("All replan logger unit tests passed.")
