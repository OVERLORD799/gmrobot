#!/usr/bin/env python3
"""Pipeline failure halt latch tests for FiveStageShadowScheduler (offline)."""

from __future__ import annotations

import sys
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


def _rgb(_obs=None):
    return np.zeros((4, 4, 3), dtype=np.uint8)


def _ok_vlm(rgb, **kw):
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


def _ok_ground(rgb, **kw):
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
        "model_versions": {"gdino_model_id": "fake-g", "sam2_model_id": "fake-s"},
    }


def _ok_track(rgb, **kw):
    return {
        "ok": True,
        "parent_request_id": kw.get("parent_request_id") or kw.get("request_id"),
        "tracks": [
            {
                "track_id": 0,
                "label": "electronic device",
                "box_xyxy": [1, 2, 3, 4],
                "mask_area": 10,
                "sam2_score": 0.8,
                "track_state": "initialized",
            }
        ],
        "track_session_id": "sess",
        "session_present": True,
        "session_match": True,
        "track_state": "initialized",
        "track_state_native": False,
        "track_state_source": "legacy_gateway_inferred",
    }


class TestPipelineHalt(unittest.TestCase):
    def _run_until_logged(self, sched, start_step=1, timeout=3.0):
        deadline = time.time() + timeout
        step = start_step
        while time.time() < deadline and sched.logged_result_count < 1:
            sched.on_step({}, step)
            step += 1
            time.sleep(0.01)
        return step

    def test_first_frame_vlm_fail_submit_one(self):
        counter = {"vlm": 0, "ground": 0, "track": 0}

        def bad_vlm(rgb, **kw):
            counter["vlm"] += 1
            return {
                "ok": False,
                "error_type": "timeout",
                "error": "vlm_down",
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
            }

        def ground(rgb, **kw):
            counter["ground"] += 1
            return _ok_ground(rgb, **kw)

        def track(rgb, **kw):
            counter["track"] += 1
            return _ok_track(rgb, **kw)

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=bad_vlm, perception_ground=ground, perception_track=track
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=50,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                extract_rgb=_rgb,
            )
            self.assertTrue(sched.on_step({}, 0)["submitted"])
            self._run_until_logged(sched)
            self.assertTrue(sched.halt_submissions)
            self.assertEqual(sched.on_step({}, 50)["submitted"], False)
            self.assertEqual(sched.on_step({}, 100)["submitted"], False)
            self.assertEqual(sched.submitted_count, 1)
            self.assertEqual(counter["vlm"], 1)
            self.assertEqual(counter["ground"], 0)
            latest = worker.latest_result()
            self.assertFalse(latest["pipeline_ok"])
            self.assertEqual(latest["pipeline_error_stage"], "vlm")
            worker.assert_no_control_side_effects()
            sched.shutdown()
            self.assertEqual(logger._n, 1)

    def test_first_frame_ground_fail_submit_one(self):
        counter = {"vlm": 0, "ground": 0}

        def vlm(rgb, **kw):
            counter["vlm"] += 1
            return _ok_vlm(rgb, **kw)

        def bad_ground(rgb, **kw):
            counter["ground"] += 1
            return {
                "ok": False,
                "error_type": "http_error",
                "error": "ground_down",
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "detections": [],
            }

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(vlm_analyze=vlm, perception_ground=bad_ground)
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=50,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            self._run_until_logged(sched)
            self.assertEqual(sched.submitted_count, 1)
            self.assertFalse(sched.can_submit(50))
            latest = worker.latest_result()
            self.assertEqual(latest["pipeline_error_stage"], "ground")
            # nested error preserved
            self.assertEqual(latest["ground"]["error"], "ground_down")
            sched.shutdown()

    def test_first_frame_track_fail_submit_one(self):
        counter = {"track": 0}

        def bad_track(rgb, **kw):
            counter["track"] += 1
            return {"ok": False, "error_type": "session_error", "error": "track_down", "tracks": []}

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm, perception_ground=_ok_ground, perception_track=bad_track
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=50,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            self._run_until_logged(sched)
            self.assertEqual(sched.submitted_count, 1)
            self.assertEqual(counter["track"], 1)
            self.assertEqual(worker.latest_result()["pipeline_error_stage"], "track")
            self.assertFalse(sched.on_step({}, 50)["submitted"])
            sched.shutdown()

    def test_two_success_then_no_third(self):
        counter = {"vlm": 0}

        def vlm(rgb, **kw):
            counter["vlm"] += 1
            return _ok_vlm(rgb, **kw)

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=vlm, perception_ground=_ok_ground, perception_track=_ok_track
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=50,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                extract_rgb=_rgb,
            )
            for step in range(200):
                sched.on_step({}, step)
                time.sleep(0.001)
            deadline = time.time() + 3.0
            while time.time() < deadline and sched.logged_result_count < 2:
                sched.on_step({}, 199)
                time.sleep(0.01)
            self.assertEqual(sched.submitted_count, 2)
            self.assertEqual(counter["vlm"], 2)
            self.assertFalse(sched.can_submit(100))
            self.assertFalse(sched.halt_submissions)
            worker.assert_no_control_side_effects()
            sched.shutdown()

    def test_empty_detections_not_transport_error(self):
        def empty_ground(rgb, **kw):
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "detections": [],
                "keyword_detection_map": {},
                "latency_ms": 0.0,
                "model_versions": {"gdino_model_id": "fake-g", "sam2_model_id": "fake-s"},
            }

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm, perception_ground=empty_ground, perception_track=_ok_track
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=1,
                stop_submissions_on_pipeline_error=True,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            self._run_until_logged(sched)
            latest = worker.latest_result()
            self.assertTrue(latest["pipeline_ok"])
            self.assertEqual(latest["pipeline_error_stage"], "")
            self.assertIsNone(latest.get("track"))  # not called without detections
            self.assertFalse(sched.halt_submissions)
            sched.shutdown()

    def test_halt_does_not_touch_leakage(self):
        def bad_vlm(rgb, **kw):
            return {"ok": False, "error_type": "x", "error": "y", "request_id": kw.get("request_id")}

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(vlm_analyze=bad_vlm, perception_ground=_ok_ground)
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            self._run_until_logged(sched)
            for step in range(1, 20):
                sched.on_step({}, step)  # control-loop stand-in
            worker.assert_no_control_side_effects()
            self.assertTrue(worker.leakage.all_zero())
            sched.shutdown()


if __name__ == "__main__":
    unittest.main()
