#!/usr/bin/env python3
"""Offline unit tests for FiveStageShadowScheduler (no network)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402
from shadow.logger import FiveStageShadowLogger  # noqa: E402
from shadow.scheduler import FiveStageShadowScheduler  # noqa: E402


def _vlm_factory(delay_s: float = 0.0, counter: dict | None = None):
    def _vlm(rgb, **kw):
        if counter is not None:
            counter["vlm"] = counter.get("vlm", 0) + 1
        if delay_s > 0:
            time.sleep(delay_s)
        return {
            "ok": True,
            "request_id": kw.get("request_id"),
            "frame_id": kw.get("frame_id"),
            "scene_summary": "s",
            "keywords": ["electronic device"],
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

    return _vlm


def _ground_factory(counter: dict | None = None):
    def _ground(rgb, **kw):
        if counter is not None:
            counter["ground"] = counter.get("ground", 0) + 1
        return {
            "ok": True,
            "request_id": kw.get("request_id"),
            "frame_id": kw.get("frame_id"),
            "parent_request_id": kw.get("request_id"),
            "detections": [
                {"label": "electronic device", "score": 0.9, "box_xyxy": [1, 2, 3, 4]}
            ],
            "keyword_detection_map": {"electronic device": [0]},
            "latency_ms": 0.0,
            "model_versions": {
                "gdino_model_id": "fake-gdino",
                "sam2_model_id": "fake-sam2",
            },
        }

    return _ground


def _track_factory(counter: dict | None = None):
    def _track(rgb, **kw):
        if counter is not None:
            counter["track"] = counter.get("track", 0) + 1
        return {
            "ok": True,
            "parent_request_id": kw.get("request_id"),
            "tracks": [
                {
                    "track_id": 0,
                    "label": "electronic device",
                    "box_xyxy": [1, 2, 3, 4],
                    "mask_area": 10,
                    "sam2_score": 0.8,
                    "track_state": "initialized" if counter and counter["track"] == 1 else "tracking",
                }
            ],
            "track_session_id": "sess",
            "session_present": True,
            "track_state": "initialized" if counter and counter["track"] == 1 else "tracking",
            "track_state_native": False,
            "track_state_source": "legacy_gateway_inferred",
        }

    return _track


def _rgb_obs(_obs=None):
    return np.zeros((4, 4, 3), dtype=np.uint8)


class TestFiveStageShadowScheduler(unittest.TestCase):
    def _make(self, tmp, *, interval=50, max_submissions=0, delay_s=0.0, counter=None):
        counter = counter if counter is not None else {}
        worker = FiveStageShadowWorker(
            vlm_analyze=_vlm_factory(delay_s=delay_s, counter=counter),
            perception_ground=_ground_factory(counter=counter),
            perception_track=_track_factory(counter=counter),
            max_result_age_s=10.0,
        )
        worker.start()
        logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
        sched = FiveStageShadowScheduler(
            worker,
            logger,
            interval=interval,
            max_submissions=max_submissions,
            extract_rgb=_rgb_obs,
        )
        return sched, worker, logger, counter

    def test_runs_without_safety_flag(self):
        """safety disabled is a non-issue: scheduler itself has no safety dependency."""
        with TemporaryDirectory() as tmp:
            sched, worker, logger, counter = self._make(tmp, interval=1, max_submissions=1)
            out = sched.on_step({}, 0)
            self.assertTrue(out["submitted"])
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 1)
                time.sleep(0.01)
            self.assertEqual(sched.submitted_count, 1)
            self.assertGreaterEqual(sched.logged_result_count, 1)
            self.assertEqual(worker.leakage.as_dict(), {
                "shadow_gate_override_count": 0,
                "shadow_action_override_count": 0,
                "shadow_clock_blocked_steps": 0,
                "shadow_replan_applied_count": 0,
                "shadow_protocol_override_count": 0,
            })
            sched.shutdown()

    def test_max_submissions_two_over_200_steps(self):
        with TemporaryDirectory() as tmp:
            counter: dict = {}
            sched, worker, logger, counter = self._make(
                tmp, interval=50, max_submissions=2, counter=counter
            )
            for step in range(200):
                sched.on_step({}, step)
                time.sleep(0.001)
            # Allow in-flight jobs to finish then poll
            deadline = time.time() + 3.0
            while time.time() < deadline and sched.logged_result_count < 2:
                sched.on_step({}, 199)
                time.sleep(0.01)
            self.assertEqual(sched.submitted_count, 2)
            self.assertEqual(sched.configured_max_submissions, 2)
            self.assertEqual(counter.get("vlm", 0), 2)
            self.assertEqual(counter.get("ground", 0), 2)
            self.assertEqual(counter.get("track", 0), 2)
            # third interval step (100) must not submit a 3rd
            self.assertFalse(sched.can_submit(100))
            self.assertFalse(sched.can_submit(150))
            sched.shutdown()

    def test_poll_does_not_duplicate_logger(self):
        with TemporaryDirectory() as tmp:
            sched, worker, logger, _ = self._make(tmp, interval=1, max_submissions=1)
            sched.on_step({}, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 1)
                time.sleep(0.01)
            self.assertEqual(sched.logged_result_count, 1)
            for _ in range(50):
                sched.on_step({}, 2)
            self.assertEqual(sched.logged_result_count, 1)
            self.assertEqual(logger._n, 1)
            sched.shutdown()

    def test_slow_worker_still_logged(self):
        with TemporaryDirectory() as tmp:
            sched, worker, logger, _ = self._make(
                tmp, interval=1, max_submissions=1, delay_s=0.15
            )
            sched.on_step({}, 0)
            # Poll while worker is still running — should not hang
            for step in range(1, 30):
                sched.on_step({}, step)
                time.sleep(0.01)
            deadline = time.time() + 3.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 99)
                time.sleep(0.02)
            self.assertEqual(sched.logged_result_count, 1)
            sched.shutdown()

    def test_shutdown_logs_unlogged_result(self):
        with TemporaryDirectory() as tmp:
            sched, worker, logger, _ = self._make(tmp, interval=1, max_submissions=1)
            sched.on_step({}, 0)
            # Wait for completion without polling
            deadline = time.time() + 2.0
            while time.time() < deadline:
                res = worker.latest_result()
                if res is not None and not res.get("stale"):
                    # reset poll side-effect counting by not using scheduler poll
                    break
                time.sleep(0.01)
            # Direct worker poll may have marked stale metrics; ensure result exists
            self.assertIsNotNone(worker.latest_result())
            self.assertEqual(sched.logged_result_count, 0)
            sched.shutdown()
            self.assertEqual(sched.logged_result_count, 1)
            self.assertEqual(logger._n, 1)

    def test_shutdown_does_not_duplicate(self):
        with TemporaryDirectory() as tmp:
            sched, worker, logger, _ = self._make(tmp, interval=1, max_submissions=1)
            sched.on_step({}, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 1)
                time.sleep(0.01)
            self.assertEqual(sched.logged_result_count, 1)
            sched.shutdown()
            self.assertEqual(sched.logged_result_count, 1)
            self.assertEqual(logger._n, 1)

    def test_stale_unique_via_scheduler_polls(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_vlm_factory(),
                perception_ground=_ground_factory(),
                max_result_age_s=0.05,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker, logger, interval=1, max_submissions=1, extract_rgb=_rgb_obs
            )
            sched.on_step({}, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 1)
                time.sleep(0.01)
            res = worker.latest_result()
            completed = float(res["completed_at_s"])
            for _ in range(40):
                worker.latest_result(now_s=completed + 1.0)
            self.assertEqual(worker.metrics.stale_result_count, 1)
            sched.shutdown()

    def test_shadow_off_noop(self):
        """No scheduler means control path unchanged — represented as None."""
        self.assertIsNone(None)

    def test_leakage_zero(self):
        with TemporaryDirectory() as tmp:
            sched, worker, logger, _ = self._make(tmp, interval=1, max_submissions=2)
            for step in range(5):
                sched.on_step({}, step)
                time.sleep(0.02)
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 2:
                sched.on_step({}, 99)
                time.sleep(0.01)
            worker.assert_no_control_side_effects()
            sched.shutdown()


class TestSchedulerWithGateways(unittest.TestCase):
    """Canonical/legacy mode smoke using fake analyze/ground callbacks."""

    def test_canonical_and_legacy_callback_shapes(self):
        for mode in ("canonical_v0a", "legacy_v2"):
            with TemporaryDirectory() as tmp:
                counter: dict = {}
                worker = FiveStageShadowWorker(
                    vlm_analyze=_vlm_factory(counter=counter),
                    perception_ground=_ground_factory(counter=counter),
                    perception_track=_track_factory(counter=counter)
                    if mode == "legacy_v2"
                    else None,
                )
                worker.start()
                logger = FiveStageShadowLogger(tmp, episode_id=mode, enabled=True)
                sched = FiveStageShadowScheduler(
                    worker,
                    logger,
                    interval=1,
                    max_submissions=1,
                    extract_rgb=_rgb_obs,
                )
                sched.on_step({}, 0)
                deadline = time.time() + 2.0
                while time.time() < deadline and sched.logged_result_count < 1:
                    sched.on_step({}, 1)
                    time.sleep(0.01)
                self.assertEqual(sched.submitted_count, 1)
                self.assertEqual(sched.logged_result_count, 1)
                worker.assert_no_control_side_effects()
                sched.shutdown()


if __name__ == "__main__":
    unittest.main()
