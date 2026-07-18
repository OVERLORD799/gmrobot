"""Unit tests for SafetyLogger perception column wiring (no Isaac)."""

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
perception_log_fields_from_result = safety.logger.perception_log_fields_from_result
track_log_fields_from_result = safety.logger.track_log_fields_from_result
merge_perception_log_fields = safety.logger.merge_perception_log_fields
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


def test_perception_log_fields_from_result_maps_api_keys():
    fields = perception_log_fields_from_result(
        {
            "gdino_model_id": "IDEA-Research/grounding-dino-tiny",
            "latency_ms": 130.5,
            "detections": [
                {"label": "gripper", "score": 0.31},
                {"label": "hand", "score": 0.42},
            ],
        }
    )
    assert fields == {
        "perception_detection_count": "2",
        "perception_top_label": "hand",
        "perception_top_score": "0.42",
        "perception_latency_ms": "130.5",
        "perception_gdino_model_id": "IDEA-Research/grounding-dino-tiny",
    }


def test_perception_log_fields_from_result_returns_none_on_error():
    assert perception_log_fields_from_result({"ok": False, "error": "timeout"}) is None


def test_track_log_fields_from_result_maps_kinematics():
    fields = track_log_fields_from_result(
        {"latency_ms": 40.0},
        {
            "label": "hand",
            "center_xy": [320.5, 240.0],
            "speed_px_s": 18.2,
            "direction_deg": -12.5,
        },
    )
    assert fields == {
        "perception_track_label": "hand",
        "perception_track_center_x": "320.5",
        "perception_track_center_y": "240.0",
        "perception_track_speed_px_s": "18.2",
        "perception_track_direction_deg": "-12.5",
    }


def test_merge_perception_log_fields_combines_ground_and_track():
    merged = merge_perception_log_fields(
        {
            "perception_detection_count": "2",
            "perception_top_label": "hand",
            "perception_top_score": "0.42",
            "perception_latency_ms": "130.5",
            "perception_gdino_model_id": "IDEA-Research/grounding-dino-tiny",
        },
        {
            "perception_track_label": "hand",
            "perception_track_center_x": "100.0",
            "perception_track_center_y": "200.0",
            "perception_track_speed_px_s": "15.0",
            "perception_track_direction_deg": "45.0",
        },
    )
    assert merged is not None
    assert merged["perception_detection_count"] == "2"
    assert merged["perception_track_speed_px_s"] == "15.0"


def test_safety_logger_partial_track_update_preserves_ground_columns():
    with tempfile.TemporaryDirectory() as tmp:
        logger = SafetyLogger(tmp, episode_id=0, enabled=True, flush_interval=1)
        action = _action()
        gate = _gate()
        logger.record(
            _state(0),
            action,
            gate,
            action,
            perception_fields={
                "perception_detection_count": "3",
                "perception_top_label": "hand",
                "perception_top_score": "0.35",
                "perception_latency_ms": "128.0",
                "perception_gdino_model_id": "IDEA-Research/grounding-dino-tiny",
            },
        )
        logger.record(
            _state(1),
            action,
            gate,
            action,
            perception_fields={
                "perception_track_label": "hand",
                "perception_track_center_x": "310.0",
                "perception_track_center_y": "220.0",
                "perception_track_speed_px_s": "12.5",
                "perception_track_direction_deg": "90.0",
            },
        )
        path = logger.flush()
        assert path is not None
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[1]["perception_detection_count"] == "3"
        assert rows[1]["perception_track_speed_px_s"] == "12.5"


def test_safety_logger_forward_fills_perception_columns():
    with tempfile.TemporaryDirectory() as tmp:
        logger = SafetyLogger(tmp, episode_id=0, enabled=True, flush_interval=1)
        perception_fields = {
            "perception_detection_count": "3",
            "perception_top_label": "hand",
            "perception_top_score": "0.35",
            "perception_latency_ms": "128.0",
            "perception_gdino_model_id": "IDEA-Research/grounding-dino-tiny",
            "perception_track_label": "hand",
            "perception_track_center_x": "310.0",
            "perception_track_center_y": "220.0",
            "perception_track_speed_px_s": "12.5",
            "perception_track_direction_deg": "90.0",
        }
        action = _action()
        gate = _gate()

        logger.record(
            _state(0), action, gate, action, perception_fields=perception_fields
        )
        logger.record(_state(1), action, gate, action)
        path = logger.flush()
        assert path is not None

        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        for row in rows:
            assert row["perception_detection_count"] == "3"
            assert row["perception_top_label"] == "hand"
            assert row["perception_gdino_model_id"] == "IDEA-Research/grounding-dino-tiny"
            assert row["perception_track_speed_px_s"] == "12.5"


if __name__ == "__main__":
    test_perception_log_fields_from_result_maps_api_keys()
    test_perception_log_fields_from_result_returns_none_on_error()
    test_track_log_fields_from_result_maps_kinematics()
    test_merge_perception_log_fields_combines_ground_and_track()
    test_safety_logger_partial_track_update_preserves_ground_columns()
    test_safety_logger_forward_fills_perception_columns()
    print("All perception logger unit tests passed.")
