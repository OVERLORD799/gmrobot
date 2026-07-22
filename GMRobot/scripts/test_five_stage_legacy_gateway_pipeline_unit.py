#!/usr/bin/env python3
"""Offline pipeline tests: legacy gateways + FiveStageShadowWorker."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "v0b3_legacy"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from perception.legacy_gateway import LegacyPerceptionGateway  # noqa: E402
from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402
from vlm.legacy_gateway import convert_legacy_analyze_response  # noqa: E402
from vlm.client import VLMClient, VLMClientConfig  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


class TestLegacyGatewayPipeline(unittest.TestCase):
    def test_fixture_round_trip_pipeline(self):
        vlm_remote = _load("legacy_vlm_analyze_response.json")
        ground_remote = _load("legacy_ground_response.json")
        init_remote = _load("legacy_track_init_response.json")
        step_remote = _load("legacy_track_step_response.json")
        posts = []

        def vlm_analyze(rgb, **kw):
            return convert_legacy_analyze_response(
                vlm_remote,
                request_id=str(kw.get("request_id")),
                frame_id=str(kw.get("frame_id")),
            )

        def perc_post(endpoint, body):
            posts.append((endpoint, {k: v for k, v in body.items() if k != "image_b64"}))
            if endpoint == "/ground":
                return ground_remote
            if body.get("action") == "init":
                return init_remote
            return step_remote

        gw = LegacyPerceptionGateway(http_post=perc_post)

        def ground(rgb, **kw):
            return gw.ground(image_b64="ZmFrZQ==", **kw)

        def track(rgb, **kw):
            return gw.track(image_b64="ZmFrZQ==", **kw)

        worker = FiveStageShadowWorker(
            vlm_analyze=vlm_analyze,
            perception_ground=ground,
            perception_track=track,
        )
        worker.start()
        rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        # frame 0 → VLM + ground + track init
        sub = worker.submit(rgb, sim_step=0, request_id="reqA", frame_id="frm0")
        self.assertTrue(sub["accepted"])
        # wait for process
        deadline = time.time() + 2.0
        res0 = None
        while time.time() < deadline:
            res0 = worker.latest_result()
            if res0 and res0.get("request_id") == "reqA" and res0.get("track"):
                break
            time.sleep(0.01)
        self.assertIsNotNone(res0)
        assert res0 is not None
        self.assertTrue(res0["ok"])
        self.assertEqual(res0["vlm_remote_contract"], "legacy_v2")
        self.assertEqual(res0["perception_remote_contract"], "legacy_v0_1")
        self.assertEqual(res0["id_source"], "local_gateway")
        self.assertEqual(res0["track_state"], "initialized")
        self.assertFalse(res0["track_state_native"])
        self.assertEqual(int(res0["track_id"]), 0)
        self.assertTrue(res0["leakage"])
        self.assertTrue(all(v == 0 for v in res0["leakage"].values()))

        # frame 1 → step tracking
        worker.submit(rgb, sim_step=10, request_id="reqB", frame_id="frm1")
        deadline = time.time() + 2.0
        res1 = None
        while time.time() < deadline:
            res1 = worker.latest_result()
            if res1 and res1.get("request_id") == "reqB" and res1.get("track_state") == "tracking":
                break
            time.sleep(0.01)
        self.assertIsNotNone(res1)
        assert res1 is not None
        self.assertEqual(res1["track_state"], "tracking")
        self.assertEqual(int(res1["track_id"]), 0)
        worker.assert_no_control_side_effects()
        worker.stop()

        # no base64 / real session secrets in posts audit (image stripped) or results
        blob = json.dumps(res0) + json.dumps(res1) + json.dumps(posts)
        self.assertNotIn("ZmFrZQ==", blob)
        self.assertNotIn("image_b64", json.dumps(res0.get("vlm", {})))

    def test_submit_non_blocking(self):
        def slow_vlm(rgb, **kw):
            time.sleep(0.2)
            return convert_legacy_analyze_response(
                _load("legacy_vlm_analyze_response.json"),
                request_id=str(kw["request_id"]),
                frame_id=str(kw["frame_id"]),
            )

        def ground(rgb, **kw):
            return {
                "ok": True,
                "detections": [],
                "keyword_detection_map": {},
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
            }

        worker = FiveStageShadowWorker(vlm_analyze=slow_vlm, perception_ground=ground)
        worker.start()
        t0 = time.perf_counter()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(elapsed_ms, 50.0)
        worker.stop()

    def test_canonical_path_unaffected(self):
        client = VLMClient(VLMClientConfig(contract_mode="canonical_v0a"))
        self.assertEqual(client.config.contract_mode, "canonical_v0a")

    def test_legacy_config_explicit_only(self):
        # Default yaml-equivalent remains canonical; legacy requires explicit mode
        self.assertEqual(VLMClientConfig().contract_mode, "canonical_v0a")
        legacy = VLMClientConfig(contract_mode="legacy_v2")
        self.assertEqual(legacy.contract_mode, "legacy_v2")

    def test_worker_forwards_normalized_keywords_to_track(self):
        captured = {}

        def vlm_analyze(rgb, **kw):
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "scene_summary": "s",
                "keywords": ["  electronic device  ", "electronic device", ""],
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
                "remote_contract": "legacy_v2",
                "id_source": "local_gateway",
            }

        def ground(rgb, **kw):
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "detections": [
                    {
                        "label": "noise",
                        "score": 0.99,
                        "box_xyxy": [0, 0, 1, 1],
                        "detection_id": "d0",
                    },
                    {
                        "label": "electronic device",
                        "score": 0.2,
                        "box_xyxy": [2, 2, 3, 3],
                        "detection_id": "d1",
                    },
                ],
                "keyword_detection_map": {},
                "remote_contract": "legacy_v0_1",
                "gateway_parse_ok": True,
            }

        def track(rgb, **kw):
            captured["keywords"] = list(kw.get("keywords") or [])
            captured["detections"] = list(kw.get("detections") or [])
            return {
                "ok": True,
                "tracks": [
                    {
                        "track_id": 0,
                        "label": "electronic device",
                        "box_xyxy": [2, 2, 3, 3],
                        "track_state": "initialized",
                    }
                ],
                "track_id": 0,
                "track_state": "initialized",
                "track_state_native": False,
                "track_state_source": "legacy_gateway_inferred",
                "remote_contract": "legacy_v0_1",
                "id_source": "local_gateway",
            }

        worker = FiveStageShadowWorker(
            vlm_analyze=vlm_analyze,
            perception_ground=ground,
            perception_track=track,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="rk", frame_id="fk")
        deadline = time.time() + 2.0
        res = None
        while time.time() < deadline:
            res = worker.latest_result()
            if res and res.get("request_id") == "rk" and res.get("track"):
                break
            time.sleep(0.01)
        worker.stop()
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(captured["keywords"], ["electronic device"])
        self.assertEqual(int(res["track_id"]), 0)
        self.assertTrue(all(v == 0 for v in res["leakage"].values()))
        worker2_leak = FiveStageShadowWorker(
            vlm_analyze=vlm_analyze, perception_ground=ground, perception_track=track
        )
        worker2_leak.assert_no_control_side_effects()

    def test_empty_keywords_skips_ground_and_track(self):
        track_calls = []

        def vlm_analyze(rgb, **kw):
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "scene_summary": "s",
                "keywords": [],
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

        def ground(rgb, **kw):
            raise AssertionError("ground must not run when keywords empty")

        def track(rgb, **kw):
            track_calls.append(1)
            return {"ok": True, "tracks": []}

        worker = FiveStageShadowWorker(
            vlm_analyze=vlm_analyze,
            perception_ground=ground,
            perception_track=track,
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0, request_id="e1", frame_id="e1")
        deadline = time.time() + 2.0
        res = None
        while time.time() < deadline:
            res = worker.latest_result()
            if res and res.get("request_id") == "e1":
                break
            time.sleep(0.01)
        worker.stop()
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.get("perception_status"), "skipped_no_keywords")
        self.assertEqual(track_calls, [])
        self.assertTrue(all(v == 0 for v in res["leakage"].values()))


if __name__ == "__main__":
    unittest.main()
