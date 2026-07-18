"""Unit tests for SafetyLogger VLM column wiring (no Isaac)."""

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
vlm_log_fields_from_result = safety.logger.vlm_log_fields_from_result
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


def test_vlm_log_fields_from_result_maps_api_keys():
    fields = vlm_log_fields_from_result(
        {
            "vlm_risk_type": "static",
            "vlm_confidence": 0.82,
            "vlm_suggested_action": "slow_down",
            "model_id": "Qwen2.5-VL-7B-Instruct-awq",
        },
        rgb_frame_path="vlm:step=100",
    )
    assert fields == {
        "vlm_risk_class": "static",
        "vlm_confidence": "0.82",
        "vlm_suggested_action": "slow_down",
        "vlm_model_id": "Qwen2.5-VL-7B-Instruct-awq",
        "rgb_frame_path": "vlm:step=100",
    }


def test_vlm_log_fields_from_result_returns_none_on_error():
    assert vlm_log_fields_from_result({"ok": False, "error": "timeout"}) is None


def test_safety_logger_forward_fills_vlm_columns():
    with tempfile.TemporaryDirectory() as tmp:
        logger = SafetyLogger(tmp, episode_id=0, enabled=True, flush_interval=1)
        vlm_fields = {
            "vlm_risk_class": "none",
            "vlm_confidence": "0.5",
            "vlm_suggested_action": "continue",
            "vlm_model_id": "Qwen2.5-VL-7B-Instruct-awq",
            "rgb_frame_path": "vlm:step=0",
        }
        action = _action()
        gate = _gate()

        logger.record(_state(0), action, gate, action, vlm_fields=vlm_fields)
        logger.record(_state(1), action, gate, action)
        path = logger.flush()
        assert path is not None

        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        for row in rows:
            assert row["vlm_suggested_action"] == "continue"
            assert row["vlm_model_id"] == "Qwen2.5-VL-7B-Instruct-awq"
            assert row["rgb_frame_path"] == "vlm:step=0"


if __name__ == "__main__":
    test_vlm_log_fields_from_result_maps_api_keys()
    test_vlm_log_fields_from_result_returns_none_on_error()
    test_safety_logger_forward_fills_vlm_columns()
    print("All VLM logger unit tests passed.")
