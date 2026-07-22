#!/usr/bin/env python3
"""Shadow isolation / zero control-leakage unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Import leaf packages without GMRobot/__init__.py (avoids IsaacLab).
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.isolation import shadow_control_decision  # noqa: E402
from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402
import numpy as np


def test_shadow_does_not_change_gate_action_clock_replan_protocol():
    gate = object()
    action = object()
    out = shadow_control_decision(
        gate_decision=gate,
        action=action,
        policy_clock_advance=True,
        replan_event=None,
        protocol_phase="transit",
        shadow_result={
            "would_stop": True,
            "would_replan": True,
            "suggested_action": "replan",
        },
        enforcement_mode="shadow",
    )
    assert out["gate_decision"] is gate
    assert out["action"] is action
    assert out["policy_clock_advance"] is True
    assert out["replan_event"] is None
    assert out["protocol_phase"] == "transit"
    assert out["would_stop"] is True
    assert out["would_replan"] is True
    assert all(v == 0 for v in out["leakage"].values())


def test_live_enforcement_rejected():
    try:
        shadow_control_decision(
            gate_decision="ALLOW",
            action=None,
            policy_clock_advance=True,
            replan_event=None,
            protocol_phase=None,
            shadow_result=None,
            enforcement_mode="live",
        )
        assert False
    except ValueError:
        pass


def test_worker_leakage_counters_remain_zero():
    def vlm(rgb, **kw):
        return {
            "ok": True,
            "request_id": kw["request_id"],
            "frame_id": kw["frame_id"],
            "scene_summary": "s",
            "keywords": ["hand"],
            "risk_type": "dynamic",
            "risk_confidence": 0.99,
            "affected_entities": [],
            "predicted_consequence": "x",
            "prediction_horizon_s": 1.0,
            "explanation": "e",
            "suggested_action": "replan",
            "spatial_hint": "none",
            "prompt_version": "five_stage_safety_v1",
            "schema_version": "five_stage_vlm_v1",
            "model_id": "m",
            "latency_ms": 1.0,
        }

    def ground(rgb, **kw):
        return {
            "ok": True,
            "request_id": kw["request_id"],
            "frame_id": kw["frame_id"],
            "detections": [],
            "keyword_detection_map": {},
            "perception_status": "ok",
            "model_versions": {},
        }

    worker = FiveStageShadowWorker(vlm_analyze=vlm, perception_ground=ground)
    worker.start()
    worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0)
    import time

    time.sleep(0.1)
    worker.assert_no_control_side_effects()
    assert worker.leakage.all_zero()
    worker.stop()


if __name__ == "__main__":
    test_shadow_does_not_change_gate_action_clock_replan_protocol()
    test_live_enforcement_rejected()
    test_worker_leakage_counters_remain_zero()
    print("All five-stage shadow isolation unit tests passed.")
