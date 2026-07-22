#!/usr/bin/env python3
"""Unit tests for unique stale_result_count semantics (no network)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402


def _fast_vlm(rgb, **kw):
    return {
        "ok": True,
        "request_id": kw.get("request_id"),
        "frame_id": kw.get("frame_id"),
        "scene_summary": "s",
        "keywords": ["a"],
        "risk_type": "none",
        "risk_confidence": 0.1,
        "affected_entities": [],
        "predicted_consequence": "c",
        "prediction_horizon_s": 1.0,
        "explanation": "e",
        "suggested_action": "continue",
        "spatial_hint": "none",
        "prompt_version": "five_stage_safety_v1",
        "schema_version": "five_stage_vlm_v1",
        "model_id": "fake",
        "latency_ms": 1.0,
    }


def _fast_ground(rgb, **kw):
    return {
        "ok": True,
        "request_id": kw.get("request_id"),
        "frame_id": kw.get("frame_id"),
        "detections": [],
        "keyword_detection_map": {},
        "latency_ms": 0.0,
    }


class TestStaleUniqueCount(unittest.TestCase):
    def _wait_result(self, worker, request_id, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            res = worker.latest_result()
            if res and res.get("request_id") == request_id:
                return res
            time.sleep(0.01)
        self.fail(f"no result for {request_id}")

    def test_same_stale_polled_100_times_counts_one(self):
        worker = FiveStageShadowWorker(
            vlm_analyze=_fast_vlm,
            perception_ground=_fast_ground,
            max_result_age_s=0.05,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="r1", frame_id="f1")
        res = self._wait_result(worker, "r1")
        completed = float(res["completed_at_s"])
        # Force stale by polling with future now
        for _ in range(100):
            snap = worker.latest_result(now_s=completed + 1.0)
            self.assertTrue(snap["stale"])
            self.assertEqual(snap["request_id"], "r1")
            self.assertEqual(snap["frame_id"], "f1")
        self.assertEqual(worker.metrics.stale_result_count, 1)
        self.assertEqual(worker.metrics.stale_poll_count, 100)
        worker.stop()

    def test_second_result_stale_increments_to_two(self):
        worker = FiveStageShadowWorker(
            vlm_analyze=_fast_vlm,
            perception_ground=_fast_ground,
            max_result_age_s=0.05,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="r1", frame_id="f1")
        r1 = self._wait_result(worker, "r1")
        worker.latest_result(now_s=float(r1["completed_at_s"]) + 1.0)
        self.assertEqual(worker.metrics.stale_result_count, 1)

        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=1, request_id="r2", frame_id="f2")
        r2 = self._wait_result(worker, "r2")
        worker.latest_result(now_s=float(r2["completed_at_s"]) + 1.0)
        self.assertEqual(worker.metrics.stale_result_count, 2)
        worker.stop()

    def test_fresh_result_does_not_increment(self):
        worker = FiveStageShadowWorker(
            vlm_analyze=_fast_vlm,
            perception_ground=_fast_ground,
            max_result_age_s=10.0,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="r1", frame_id="f1")
        r1 = self._wait_result(worker, "r1")
        for _ in range(20):
            snap = worker.latest_result(now_s=float(r1["completed_at_s"]) + 0.01)
            self.assertFalse(snap["stale"])
        self.assertEqual(worker.metrics.stale_result_count, 0)
        self.assertEqual(worker.metrics.stale_poll_count, 0)
        worker.stop()

    def test_deepcopy_preserves_request_identity(self):
        worker = FiveStageShadowWorker(
            vlm_analyze=_fast_vlm,
            perception_ground=_fast_ground,
            max_result_age_s=0.01,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="rid", frame_id="fid")
        r = self._wait_result(worker, "rid")
        a = worker.latest_result(now_s=float(r["completed_at_s"]) + 1.0)
        b = worker.latest_result(now_s=float(r["completed_at_s"]) + 1.0)
        self.assertEqual(a["request_id"], b["request_id"])
        self.assertEqual(a["frame_id"], b["frame_id"])
        self.assertEqual(a["completed_at_s"], b["completed_at_s"])
        self.assertIsNot(a, b)  # deepcopy
        self.assertEqual(worker.metrics.stale_result_count, 1)
        worker.stop()

    def test_multithreaded_polls_do_not_double_count(self):
        worker = FiveStageShadowWorker(
            vlm_analyze=_fast_vlm,
            perception_ground=_fast_ground,
            max_result_age_s=0.01,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="r1", frame_id="f1")
        r = self._wait_result(worker, "r1")
        # Reset poll metric so wait-loop freshness races do not inflate expectations.
        with worker._lock:
            worker.metrics.stale_poll_count = 0
            worker.metrics.stale_result_count = 0
            worker._last_stale_counted_key = None
        now = float(r["completed_at_s"]) + 1.0
        barrier = threading.Barrier(8)

        def poll():
            barrier.wait()
            for _ in range(25):
                worker.latest_result(now_s=now)

        threads = [threading.Thread(target=poll) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(worker.metrics.stale_result_count, 1)
        self.assertEqual(worker.metrics.stale_poll_count, 8 * 25)
        worker.stop()


if __name__ == "__main__":
    unittest.main()
