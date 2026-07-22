#!/usr/bin/env python3
"""Offline tests for shutdown drain + worker.stop semantics (no network)."""

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


def _rgb(_obs=None):
    return np.zeros((4, 4, 3), dtype=np.uint8)


def _ok_vlm_factory(delay_s: float = 0.0, counter: dict | None = None, fail_first: bool = False):
    def _vlm(rgb, **kw):
        if counter is not None:
            counter["vlm"] = counter.get("vlm", 0) + 1
            n = counter["vlm"]
        else:
            n = 1
        if delay_s > 0:
            time.sleep(delay_s)
        if fail_first and n == 1:
            return {
                "ok": False,
                "error_type": "timeout",
                "error": "vlm_fail",
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
            }
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


class TestShutdownDrain(unittest.TestCase):
    def test_drain_logs_second_result_after_loop(self):
        """Two submits; second finishes after loop ends → drain records 2/2."""
        counter: dict = {}
        # First fast, second slow — completes during drain after loop.
        delays = [0.01, 0.35]

        def vlm(rgb, **kw):
            counter["vlm"] = counter.get("vlm", 0) + 1
            time.sleep(delays[min(counter["vlm"] - 1, len(delays) - 1)])
            return _ok_vlm_factory()(rgb, **kw)

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=vlm,
                perception_ground=_ok_ground,
                perception_track=_ok_track,
                queue_size=2,
                max_result_age_s=30.0,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                shutdown_drain_timeout_s=5.0,
                extract_rgb=_rgb,
            )
            # Simulate short control loop: submit 2 then exit loop quickly.
            sched.on_step({}, 0)
            # Wait until first is logged so we don't lose it to latest-wins.
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 1)
                time.sleep(0.01)
            self.assertEqual(sched.logged_result_count, 1)
            sched.on_step({}, 2)  # second submit
            self.assertEqual(sched.submitted_count, 2)
            # Loop ends here — second still in flight
            self.assertLess(worker.metrics.processed_frames, 2)
            status = sched.shutdown(stop_timeout_s=1.0, drain_timeout_s=5.0)
            self.assertTrue(status["shutdown_drain_complete"])
            self.assertEqual(sched.logged_result_count, 2)
            self.assertEqual(sched.processed_at_shutdown, 2)
            self.assertEqual(logger._n, 2)
            self.assertFalse(sched.worker_thread_alive_after_stop)
            self.assertIsNone(getattr(logger, "_steps_file", None))

    def test_drain_does_not_duplicate_first(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(delay_s=0.05),
                perception_ground=_ok_ground,
                perception_track=_ok_track,
                queue_size=2,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=2,
                shutdown_drain_timeout_s=3.0,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline and sched.logged_result_count < 1:
                sched.on_step({}, 1)
                time.sleep(0.01)
            first_n = logger._n
            self.assertEqual(first_n, 1)
            sched.on_step({}, 2)
            deadline = time.time() + 2.0
            while time.time() < deadline and worker.metrics.processed_frames < 2:
                time.sleep(0.01)
            sched.shutdown(drain_timeout_s=3.0)
            self.assertEqual(logger._n, 2)
            self.assertEqual(sched.logged_result_count, 2)

    def test_no_submit_during_drain(self):
        gate = threading.Event()

        def blocking_vlm(rgb, **kw):
            gate.wait(timeout=5.0)
            return _ok_vlm_factory()(rgb, **kw)

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=blocking_vlm,
                perception_ground=_ok_ground,
                queue_size=1,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=2,
                shutdown_drain_timeout_s=2.0,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            self.assertEqual(sched.submitted_count, 1)

            def drain():
                # Release worker after drain has started forbidding submits
                time.sleep(0.1)
                # Attempt submit via can_submit / on_step during drain
                self.assertFalse(sched.can_submit(0))
                out = sched.on_step({}, 1)
                self.assertFalse(out["submitted"])
                gate.set()

            t = threading.Thread(target=drain)
            # Start drain in main after helper is ready — actually run drain on main
            # and check from side thread during drain.
            checked = {"ok": False}

            def checker():
                while not sched.shutdown_drain_started and not sched._closed:
                    time.sleep(0.01)
                checked["ok"] = not sched.can_submit(0) and not sched._accepting_submissions
                gate.set()

            t = threading.Thread(target=checker)
            t.start()
            sched.shutdown(drain_timeout_s=2.0, stop_timeout_s=1.0)
            t.join(timeout=3.0)
            self.assertTrue(checked["ok"])
            self.assertEqual(sched.submitted_count, 1)

    def test_slow_worker_completes_within_drain(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(delay_s=0.4),
                perception_ground=_ok_ground,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=1,
                shutdown_drain_timeout_s=3.0,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            status = sched.shutdown(drain_timeout_s=3.0, stop_timeout_s=1.0)
            self.assertTrue(status["shutdown_drain_complete"])
            self.assertEqual(sched.logged_at_shutdown, 1)
            self.assertFalse(sched.worker_thread_alive_after_stop)

    def test_drain_timeout_reports_incomplete_and_alive_thread(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(delay_s=5.0),
                perception_ground=_ok_ground,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=1,
                shutdown_drain_timeout_s=0.2,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            status = sched.shutdown(drain_timeout_s=0.2, stop_timeout_s=0.05)
            self.assertFalse(status["shutdown_drain_complete"])
            self.assertTrue(status["worker_thread_alive_after_stop"])
            self.assertTrue(worker.thread_alive())
            self.assertIsNotNone(worker._thread)  # must not pretend None
            self.assertFalse(status["stop_status"]["stopped_cleanly"])
            # Best-effort cleanup: allow finish so process can exit
            worker._stop.set()
            if worker._thread is not None:
                worker._thread.join(timeout=6.0)

    def test_stop_does_not_clear_alive_thread(self):
        started = threading.Event()

        def slow_vlm(rgb, **kw):
            started.set()
            time.sleep(3.0)
            return _ok_vlm_factory()(rgb, **kw)

        worker = FiveStageShadowWorker(
            vlm_analyze=slow_vlm,
            perception_ground=_ok_ground,
            queue_size=2,
        )
        worker.start()
        worker.submit(np.zeros((2, 2, 3), dtype=np.uint8), sim_step=0)
        self.assertTrue(started.wait(timeout=2.0))
        status = worker.stop(timeout_s=0.05)
        self.assertTrue(status["thread_alive"])
        self.assertFalse(status["stopped_cleanly"])
        self.assertIsNotNone(worker._thread)
        worker._stop.set()
        worker._thread.join(timeout=5.0)

    def test_pipeline_halt_still_works(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(fail_first=True),
                perception_ground=_ok_ground,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=50,
                max_submissions=2,
                stop_submissions_on_pipeline_error=True,
                shutdown_drain_timeout_s=2.0,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            deadline = time.time() + 2.0
            while time.time() < deadline and not sched.halt_submissions:
                sched.on_step({}, 1)  # non-interval poll only
                time.sleep(0.01)
            self.assertTrue(sched.halt_submissions)
            self.assertFalse(sched.on_step({}, 50)["submitted"])
            self.assertEqual(sched.submitted_count, 1)
            sched.shutdown(drain_timeout_s=1.0)

    def test_max_submissions_strict(self):
        counter: dict = {}
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(counter=counter),
                perception_ground=_ok_ground,
                perception_track=_ok_track,
                queue_size=2,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=50,
                max_submissions=2,
                shutdown_drain_timeout_s=3.0,
                extract_rgb=_rgb,
            )
            for step in range(200):
                sched.on_step({}, step)
                time.sleep(0.001)
            sched.shutdown(drain_timeout_s=3.0)
            self.assertEqual(sched.submitted_count, 2)
            self.assertEqual(counter.get("vlm", 0), 2)

    def test_leakage_zero_after_drain(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(delay_s=0.05),
                perception_ground=_ok_ground,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=2,
                shutdown_drain_timeout_s=3.0,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            time.sleep(0.08)
            sched.on_step({}, 1)
            status = sched.shutdown(drain_timeout_s=3.0)
            worker.assert_no_control_side_effects()
            self.assertEqual(status["leakage"]["shadow_gate_override_count"], 0)

    def test_logger_closes_after_final_record(self):
        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=_ok_vlm_factory(delay_s=0.2),
                perception_ground=_ok_ground,
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            sched = FiveStageShadowScheduler(
                worker,
                logger,
                interval=1,
                max_submissions=1,
                shutdown_drain_timeout_s=3.0,
                extract_rgb=_rgb,
            )
            sched.on_step({}, 0)
            close_order = []

            orig_record = logger.record
            orig_close = logger.close

            def rec(result):
                close_order.append("record")
                return orig_record(result)

            def clo():
                close_order.append("close")
                return orig_close()

            logger.record = rec  # type: ignore[method-assign]
            logger.close = clo  # type: ignore[method-assign]
            sched.shutdown(drain_timeout_s=3.0)
            self.assertIn("record", close_order)
            self.assertEqual(close_order[-1], "close")
            self.assertGreater(close_order.index("close"), close_order.index("record"))


if __name__ == "__main__":
    unittest.main()
