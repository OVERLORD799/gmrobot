#!/usr/bin/env python3
"""Five-stage shadow logger unit tests."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Import leaf packages without GMRobot/__init__.py (avoids IsaacLab).
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.logger import FiveStageShadowLogger  # noqa: E402


def test_logger_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        log = FiveStageShadowLogger(tmp, episode_id="ep1", enabled=True)
        result = {
            "episode_id": "ep1",
            "sim_step": 10,
            "frame_id": "f1",
            "request_id": "r1",
            "parent_request_id": "r1",
            "track_session_id": "s1",
            "track_id": "t1",
            "track_state": "tracking",
            "scene_summary": "summary",
            "keywords": ["hand"],
            "risk_type": "static",
            "risk_confidence": 0.5,
            "predicted_consequence": "c",
            "prediction_horizon_s": 1.2,
            "suggested_action": "slow_down",
            "spatial_hint": "left",
            "keyword_detection_map": {"hand": ["d0"]},
            "status": "ok",
            "error_type": "",
            "perception_status": "ok",
            "would_stop": False,
            "would_replan": False,
            "vlm_latency_ms": 1.0,
            "ground_latency_ms": 2.0,
            "track_latency_ms": 3.0,
            "end_to_end_latency_ms": 6.0,
            "queue_wait_ms": 0.1,
            "stale": False,
            "schema_version": "five_stage_vlm_v1",
            "prompt_version": "five_stage_safety_v1",
            "vlm_model_id": "m",
            "gdino_model_id": "g",
            "sam2_model_id": "s",
            "metrics": {
                "submitted_frames": 1,
                "processed_frames": 1,
                "dropped_frames": 0,
                "stale_result_count": 0,
            },
            "leakage": {
                "shadow_gate_override_count": 0,
                "shadow_action_override_count": 0,
                "shadow_clock_blocked_steps": 0,
                "shadow_replan_applied_count": 0,
                "shadow_protocol_override_count": 0,
            },
        }
        log.record(result)
        summary = log.flush_summary()
        log.close()
        assert summary is not None and summary.exists()
        rows = list(csv.DictReader(open(log._steps_path, encoding="utf-8")))
        assert len(rows) == 1
        assert rows[0]["request_id"] == "r1"
        assert rows[0]["frame_id"] == "f1"
        assert rows[0]["shadow_gate_override_count"] == "0"
        lines = log._requests_path.read_text(encoding="utf-8").strip().splitlines()
        assert json.loads(lines[0])["keywords"] == ["hand"]


if __name__ == "__main__":
    test_logger_roundtrip()
    print("All five-stage shadow logging unit tests passed.")
