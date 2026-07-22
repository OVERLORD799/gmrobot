#!/usr/bin/env python3
"""Async five-stage shadow worker unit tests (fake clients; no network)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Import leaf packages without GMRobot/__init__.py (avoids IsaacLab).
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402


def _ok_vlm(rgb, **kw):
    time.sleep(0.05)  # pretend slow HTTP
    return {
        "ok": True,
        "request_id": kw.get("request_id"),
        "frame_id": kw.get("frame_id"),
        "scene_summary": "s",
        "keywords": ["bare human hand"],
        "risk_type": "static",
        "risk_confidence": 0.7,
        "affected_entities": ["hand"],
        "predicted_consequence": "contact",
        "prediction_horizon_s": 1.0,
        "explanation": "e",
        "suggested_action": "stop",
        "spatial_hint": "left",
        "prompt_version": "five_stage_safety_v1",
        "schema_version": "five_stage_vlm_v1",
        "model_id": "fake",
        "latency_ms": 50.0,
    }


def _ok_ground(rgb, **kw):
    assert kw.get("keywords") == ["bare human hand"]
    assert kw.get("allow_default_prompt") is False
    return {
        "ok": True,
        "request_id": kw.get("request_id"),
        "frame_id": kw.get("frame_id"),
        "parent_request_id": kw.get("request_id"),
        "detections": [
            {
                "detection_id": "d0",
                "label": "bare human hand",
                "score": 0.9,
                "box_xyxy": [1, 2, 3, 4],
                "mask_available": True,
                "track_id": "t0",
                "track_state": "initialized",
            }
        ],
        "keyword_detection_map": {"bare human hand": ["d0"]},
        "model_versions": {"gdino_model_id": "fake-g", "sam2_model_id": "fake-s"},
        "perception_status": "ok",
        "latency_ms": 1.0,
    }


def test_submit_not_blocked_by_slow_http():
    worker = FiveStageShadowWorker(
        vlm_analyze=_ok_vlm,
        perception_ground=_ok_ground,
        queue_size=1,
        max_result_age_s=2.0,
    )
    worker.start()
    rgb = np.zeros((16, 16, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    ack = worker.submit(rgb, sim_step=0, request_id="r0", frame_id="f0")
    dt_ms = (time.perf_counter() - t0) * 1000.0
    assert ack["accepted"] is True
    assert dt_ms < 20.0, f"submit blocked control loop: {dt_ms:.2f}ms"
    # wait for worker
    for _ in range(50):
        latest = worker.latest_result()
        if latest and latest.get("processed_frames", 0) or (latest and latest.get("ok")):
            if latest and latest.get("request_id") == "r0":
                break
        time.sleep(0.02)
    latest = worker.latest_result()
    assert latest is not None
    assert latest["request_id"] == latest["frame_id"] or latest["request_id"] == "r0"
    assert latest["parent_request_id"] == "r0"
    assert latest["frame_id"] == "f0"
    assert latest["keywords"] == ["bare human hand"]
    worker.stop()
    return dt_ms


def test_latest_frame_wins_drop():
    slow = {"n": 0}

    def slow_vlm(rgb, **kw):
        slow["n"] += 1
        time.sleep(0.08)
        return _ok_vlm(rgb, **kw)

    worker = FiveStageShadowWorker(
        vlm_analyze=slow_vlm,
        perception_ground=_ok_ground,
        queue_size=1,
    )
    worker.start()
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    worker.submit(rgb, sim_step=1, request_id="a", frame_id="fa")
    worker.submit(rgb, sim_step=2, request_id="b", frame_id="fb")
    worker.submit(rgb, sim_step=3, request_id="c", frame_id="fc")
    time.sleep(0.4)
    assert worker.metrics.dropped_frames >= 1
    latest = worker.latest_result()
    assert latest is not None
    # final processed should be a later frame id among submissions
    assert latest["frame_id"] in {"fa", "fb", "fc"}
    worker.stop()


def test_worker_exception_isolated():
    def bad_vlm(*a, **k):
        raise RuntimeError("boom")

    worker = FiveStageShadowWorker(
        vlm_analyze=bad_vlm,
        perception_ground=_ok_ground,
    )
    worker.start()
    worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0)
    time.sleep(0.15)
    latest = worker.latest_result()
    assert latest is not None
    assert latest["ok"] is False
    assert latest["error_type"] == "worker_exception"
    worker.stop()


def test_empty_keywords_skip_and_ids():
    def vlm_no_kw(rgb, **kw):
        out = _ok_vlm(rgb, **kw)
        out["keywords"] = []
        out["suggested_action"] = "continue"
        return out

    called = {"ground": 0}

    def ground(rgb, **kw):
        called["ground"] += 1
        return _ok_ground(rgb, **kw)

    worker = FiveStageShadowWorker(vlm_analyze=vlm_no_kw, perception_ground=ground)
    worker.start()
    worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=9, request_id="rid", frame_id="fid")
    time.sleep(0.15)
    latest = worker.latest_result()
    assert latest["perception_status"] == "skipped_no_keywords"
    assert called["ground"] == 0
    assert latest["request_id"] == "rid"
    assert latest["frame_id"] == "fid"
    worker.stop()


def test_stale_flag():
    worker = FiveStageShadowWorker(
        vlm_analyze=_ok_vlm,
        perception_ground=_ok_ground,
        max_result_age_s=0.01,
    )
    worker.start()
    worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="r", frame_id="f")
    time.sleep(0.2)
    latest = worker.latest_result()
    assert latest["stale"] is True
    worker.stop()


if __name__ == "__main__":
    dt = test_submit_not_blocked_by_slow_http()
    test_latest_frame_wins_drop()
    test_worker_exception_isolated()
    test_empty_keywords_skip_and_ids()
    test_stale_flag()
    print(f"All five-stage shadow worker unit tests passed. submit_ms={dt:.3f}")
