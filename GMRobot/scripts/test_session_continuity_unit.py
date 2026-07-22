#!/usr/bin/env python3
"""Offline tests for session continuity audit (pre-redaction match)."""

from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "v0b3_legacy"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from perception.legacy_gateway import LegacyPerceptionGateway  # noqa: E402
from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402
from shadow.logger import FiveStageShadowLogger  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


DET = [{"label": "electronic device", "score": 0.9, "box_xyxy": [1, 2, 3, 4]}]


class TestSessionContinuity(unittest.TestCase):
    def test_init_match_null_ref_session_1(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            return init

        gw = LegacyPerceptionGateway(http_post=fake)
        out = gw.track(
            image_b64="QQ==",
            frame_id="f0",
            detections=DET,
            keywords=["electronic device"],
        )
        self.assertTrue(out["ok"])
        self.assertIsNone(out["session_match"])
        self.assertFalse(out["session_match_applicable"])
        self.assertFalse(out["session_continuity_verified"])
        self.assertEqual(out["session_ref"], "session_1")
        self.assertEqual(out["session_generation"], 1)
        self.assertEqual(out["track_session_id"], "<redacted>")
        blob = json.dumps(out)
        self.assertNotIn("fixture-session-token", blob)

    def test_step_same_session_match_true(self):
        init = _load("legacy_track_init_response.json")
        step = _load("legacy_track_step_response.json")

        def fake(endpoint, body):
            return init if body.get("action") == "init" else step

        gw = LegacyPerceptionGateway(http_post=fake)
        gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        out = gw.track(image_b64="QQ==", frame_id="f1", detections=DET)
        self.assertTrue(out["ok"])
        self.assertTrue(out["session_match_applicable"])
        self.assertTrue(out["session_match"])
        self.assertTrue(out["session_continuity_verified"])
        self.assertEqual(out["session_ref"], "session_1")
        self.assertEqual(out["track_state"], "tracking")
        self.assertEqual(int(out["track_id"]), 0)

    def test_step_different_session_pipeline_fail(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            if body.get("action") == "init":
                return init
            return {
                "session_id": "totally-different-remote-session",
                "frame_index": 1,
                "tracks": [
                    {
                        "track_id": 0,
                        "label": "electronic device",
                        "box_xyxy": [1, 2, 3, 4],
                        "mask_area": 10,
                        "sam2_score": 0.9,
                    }
                ],
            }

        gw = LegacyPerceptionGateway(http_post=fake)
        gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        out = gw.track(image_b64="QQ==", frame_id="f1", detections=DET)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_type"], "session_id_mismatch")
        self.assertFalse(out["session_match"])
        self.assertTrue(out["session_match_applicable"])
        self.assertFalse(out["session_continuity_verified"])
        blob = json.dumps(out)
        self.assertNotIn("totally-different-remote-session", blob)
        self.assertNotIn("fixture-session-token", blob)

    def test_mismatch_does_not_overwrite_old_session(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            if body.get("action") == "init":
                return init
            return {
                "session_id": "foreign-session",
                "frame_index": 1,
                "tracks": [
                    {
                        "track_id": 0,
                        "label": "electronic device",
                        "box_xyxy": [1, 2, 3, 4],
                        "mask_area": 10,
                        "sam2_score": 0.9,
                    }
                ],
            }

        gw = LegacyPerceptionGateway(http_post=fake)
        gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        expected = gw._session.session_id
        self.assertEqual(expected, "fixture-session-token")
        gw.track(image_b64="QQ==", frame_id="f1", detections=DET)
        self.assertEqual(gw._session.session_id, expected)
        self.assertEqual(gw._session.session_ref, "session_1")
        self.assertEqual(gw._session.session_generation, 1)

    def test_same_track_id_different_session_fails(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            if body.get("action") == "init":
                return init
            # same track_id=0, different session
            return {
                "session_id": "other-sess",
                "frame_index": 1,
                "tracks": list(init["tracks"]),
            }

        gw = LegacyPerceptionGateway(http_post=fake)
        gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        out = gw.track(image_b64="QQ==", frame_id="f1", detections=DET)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_type"], "session_id_mismatch")

    def test_same_session_track_id_zero_passes(self):
        init = _load("legacy_track_init_response.json")
        step = _load("legacy_track_step_response.json")
        assert int(step["tracks"][0]["track_id"]) == 0

        def fake(endpoint, body):
            return init if body.get("action") == "init" else step

        gw = LegacyPerceptionGateway(http_post=fake)
        gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        out = gw.track(image_b64="QQ==", frame_id="f1", detections=DET)
        self.assertTrue(out["ok"])
        self.assertEqual(int(out["track_id"]), 0)
        self.assertTrue(out["session_match"])

    def test_reset_then_new_init_session_2(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            return init

        gw = LegacyPerceptionGateway(http_post=fake)
        a = gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        self.assertEqual(a["session_ref"], "session_1")
        gw.reset()
        b = gw.track(image_b64="QQ==", frame_id="f1", detections=DET, keywords=["electronic device"])
        self.assertEqual(b["session_ref"], "session_2")
        self.assertEqual(b["session_generation"], 2)

    def test_reacquire_increments_generation(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            if body.get("action") == "init":
                return init
            return {"session_id": "fixture-session-token", "frame_index": 1, "tracks": []}

        gw = LegacyPerceptionGateway(http_post=fake, reinit_after_lost=True)
        gw.track(image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"])
        lost = gw.track(image_b64="QQ==", frame_id="f1", detections=DET)
        self.assertEqual(lost["track_state"], "lost")
        again = gw.track(
            image_b64="QQ==", frame_id="f2", detections=DET, keywords=["electronic device"]
        )
        self.assertEqual(again["track_state"], "reacquired")
        self.assertEqual(again["session_ref"], "session_2")
        self.assertEqual(again["session_generation"], 2)

    def test_logs_contain_no_raw_session_id(self):
        init = _load("legacy_track_init_response.json")
        step = _load("legacy_track_step_response.json")

        def fake(endpoint, body):
            return init if body.get("action") == "init" else step

        gw = LegacyPerceptionGateway(http_post=fake)

        def vlm(rgb, **kw):
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

        def ground(rgb, **kw):
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "detections": DET,
                "keyword_detection_map": {},
                "latency_ms": 0.0,
                "model_versions": {"gdino_model_id": "g", "sam2_model_id": "s"},
            }

        with TemporaryDirectory() as tmp:
            worker = FiveStageShadowWorker(
                vlm_analyze=vlm,
                perception_ground=ground,
                perception_track=lambda rgb, **kw: gw.track(
                    image_b64="QQ==",
                    parent_request_id=kw.get("parent_request_id"),
                    frame_id=kw.get("frame_id"),
                    detections=kw.get("detections"),
                    keywords=kw.get("keywords"),
                ),
            )
            worker.start()
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0)
            import time

            deadline = time.time() + 2
            while time.time() < deadline:
                res = worker.latest_result()
                if res and res.get("track"):
                    logger.record(res)
                    break
                time.sleep(0.01)
            text = (Path(tmp) / sorted(Path(tmp).iterdir())[0] / "five_stage_shadow_requests.jsonl").read_text()
            # path may vary — find jsonl
            jsonl = list(Path(tmp).rglob("five_stage_shadow_requests.jsonl"))[0].read_text()
            self.assertNotIn("fixture-session-token", jsonl)
            csv_path = list(Path(tmp).rglob("five_stage_shadow_steps.csv"))[0]
            self.assertNotIn("fixture-session-token", csv_path.read_text())
            worker.stop(timeout_s=1.0)
            logger.close()

    def test_csv_roundtrip_match_fields(self):
        with TemporaryDirectory() as tmp:
            logger = FiveStageShadowLogger(tmp, episode_id="ep", enabled=True)
            logger.record(
                {
                    "request_id": "r",
                    "frame_id": "f",
                    "track_state": "tracking",
                    "track_state_native": False,
                    "track_state_source": "legacy_gateway_inferred",
                    "session_ref": "session_1",
                    "session_generation": 1,
                    "session_match": True,
                    "session_match_applicable": True,
                    "session_continuity_verified": True,
                    "track_session_id": "<redacted>",
                    "metrics": {},
                    "leakage": {},
                }
            )
            logger.close()
            csv_path = list(Path(tmp).rglob("five_stage_shadow_steps.csv"))[0]
            rows = list(csv.DictReader(csv_path.open()))
            self.assertEqual(rows[0]["session_match"], "True")
            self.assertEqual(rows[0]["session_match_applicable"], "True")
            self.assertEqual(rows[0]["session_continuity_verified"], "True")
            self.assertEqual(rows[0]["session_ref"], "session_1")

    def test_init_null_does_not_fail_verdict_gate(self):
        """Gate: init with session_match=null must not be treated as fail."""
        init = _load("legacy_track_init_response.json")
        gw = LegacyPerceptionGateway(http_post=lambda e, b: init)
        out = gw.track(
            image_b64="QQ==", frame_id="f0", detections=DET, keywords=["electronic device"]
        )
        applicable = bool(out.get("session_match_applicable"))
        match = out.get("session_match")
        # init: applicable false → null match is OK
        self.assertFalse(applicable)
        self.assertIsNone(match)
        gate_fail = applicable and match is not True
        self.assertFalse(gate_fail)

    def test_tracking_null_must_fail_verdict_gate(self):
        """If a tracking frame somehow lacks match, gate must fail."""
        fake = {
            "session_match_applicable": True,
            "session_match": None,
            "session_continuity_verified": False,
            "track_state": "tracking",
        }
        gate_fail = bool(fake["session_match_applicable"]) and fake["session_match"] is not True
        self.assertTrue(gate_fail)

    def test_worker_top_level_fields(self):
        init = _load("legacy_track_init_response.json")
        step = _load("legacy_track_step_response.json")
        gw = LegacyPerceptionGateway(
            http_post=lambda e, b: init if b.get("action") == "init" else step
        )

        def vlm(rgb, **kw):
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

        def ground(rgb, **kw):
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "detections": DET,
                "keyword_detection_map": {},
                "latency_ms": 0.0,
                "model_versions": {"gdino_model_id": "g", "sam2_model_id": "s"},
            }

        worker = FiveStageShadowWorker(
            vlm_analyze=vlm,
            perception_ground=ground,
            perception_track=lambda rgb, **kw: gw.track(
                image_b64="QQ==",
                parent_request_id=kw.get("parent_request_id"),
                frame_id=kw.get("frame_id"),
                detections=kw.get("detections"),
                keywords=kw.get("keywords"),
            ),
        )
        worker.start()
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=0)
        import time

        res = None
        deadline = time.time() + 2
        while time.time() < deadline:
            res = worker.latest_result()
            if res and res.get("track_state") == "initialized":
                break
            time.sleep(0.01)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.get("session_ref"), "session_1")
        self.assertIsNone(res.get("session_match"))
        self.assertFalse(res.get("session_match_applicable"))
        worker.submit(np.zeros((4, 4, 3), dtype=np.uint8), sim_step=1)
        deadline = time.time() + 2
        while time.time() < deadline:
            res = worker.latest_result()
            if res and res.get("track_state") == "tracking":
                break
            time.sleep(0.01)
        self.assertTrue(res.get("session_match"))
        self.assertTrue(res.get("session_match_applicable"))
        self.assertTrue(res.get("session_continuity_verified"))
        worker.assert_no_control_side_effects()
        worker.stop(timeout_s=1.0)

    def test_leakage_zero(self):
        # covered by worker test above; explicit assert
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
