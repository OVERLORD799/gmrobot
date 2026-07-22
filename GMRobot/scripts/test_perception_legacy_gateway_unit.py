#!/usr/bin/env python3
"""Offline unit tests for Legacy perception gateway + track lifecycle."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "v0b3_legacy"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from perception.legacy_gateway import (  # noqa: E402
    LegacyPerceptionGateway,
    build_keyword_detection_map,
    convert_legacy_ground_response,
    is_valid_track_id,
    normalize_track_id,
    select_detection_for_track,
)


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


class TestTrackIdZero(unittest.TestCase):
    def test_track_id_zero_valid(self):
        self.assertTrue(is_valid_track_id(0))
        self.assertEqual(normalize_track_id(0), "0")
        self.assertFalse(bool(0))
        self.assertFalse(is_valid_track_id(None))
        self.assertFalse(is_valid_track_id(""))


class TestKeywordPreferredSelection(unittest.TestCase):
    def test_keyword_match_beats_higher_score_nonmatch(self):
        dets = [
            {
                "label": "unrelated clutter",
                "score": 0.99,
                "box_xyxy": [0.0, 0.0, 10.0, 10.0],
            },
            {
                "label": "electronic device",
                "score": 0.40,
                "box_xyxy": [20.0, 20.0, 40.0, 40.0],
            },
            {
                "label": "",
                "score": 0.95,
                "box_xyxy": [50.0, 50.0, 60.0, 60.0],
            },
        ]
        chosen = select_detection_for_track(dets, ["electronic device"])
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["label"], "electronic device")
        self.assertAlmostEqual(float(chosen["score"]), 0.40)

    def test_empty_keywords_falls_back_to_highest_labeled_score(self):
        dets = [
            {"label": "b", "score": 0.3, "box_xyxy": [0, 0, 1, 1]},
            {"label": "a", "score": 0.8, "box_xyxy": [0, 0, 2, 2]},
            {"label": "", "score": 0.99, "box_xyxy": [0, 0, 3, 3]},
        ]
        chosen = select_detection_for_track(dets, [])
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["label"], "a")
        self.assertAlmostEqual(float(chosen["score"]), 0.8)


class TestGroundMapping(unittest.TestCase):
    def test_ground_detection_mapping(self):
        remote = _load("legacy_ground_response.json")
        keywords = ["robotic arm", "electronic device", "human safety"]
        out = convert_legacy_ground_response(
            remote,
            request_id="g1",
            frame_id="f1",
            parent_request_id="v1",
            keywords=keywords,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["remote_contract"], "legacy_v0_1")
        self.assertEqual(out["id_source"], "local_gateway")
        self.assertEqual(out["model_versions"]["gdino_model_id"], "IDEA-Research/grounding-dino-base")
        self.assertTrue(out["detections"])
        for d in out["detections"]:
            self.assertIn("detection_id", d)
            self.assertIn("mask_available", d)
            self.assertIs(d["track_state_native"], False)

    def test_empty_label_not_keyword_match(self):
        dets = [
            {
                "detection_id": "x",
                "label": "",
                "score": 0.9,
                "box_xyxy": [0, 0, 1, 1],
            }
        ]
        kmap = build_keyword_detection_map(["robot"], dets)
        self.assertEqual(kmap["robot"], [])

    def test_keyword_detection_map(self):
        remote = _load("legacy_ground_response.json")
        out = convert_legacy_ground_response(
            remote,
            request_id="g",
            frame_id="f",
            keywords=["electronic device", "robotic arm"],
        )
        kmap = out["keyword_detection_map"]
        self.assertTrue(kmap["electronic device"])
        self.assertTrue(kmap["robotic arm"])
        self.assertEqual(out["mapping_source"], "local_gateway")

    def test_keywords_to_legacy_ground_request(self):
        posts = []

        def fake(endpoint, body):
            posts.append((endpoint, body))
            return _load("legacy_ground_response.json")

        gw = LegacyPerceptionGateway(http_post=fake)
        out = gw.ground(
            image_b64="QUJD",
            keywords=["robotic arm", "electronic device"],
            request_id="r",
            frame_id="f",
            parent_request_id="p",
        )
        self.assertTrue(out["ok"])
        ep, body = posts[0]
        self.assertEqual(ep, "/ground")
        self.assertEqual(body["text_prompt"], "robotic arm . electronic device")
        self.assertEqual(body["meta"]["keywords"], ["robotic arm", "electronic device"])
        self.assertNotIn("QUJD", json.dumps(out))


class TestTrackLifecycle(unittest.TestCase):
    def _gateway(self):
        init = _load("legacy_track_init_response.json")
        step = _load("legacy_track_step_response.json")
        state = {"n": 0}

        def fake(endpoint, body):
            self.assertEqual(endpoint, "/track")
            # never log secrets in assertions via print
            if body.get("action") == "init":
                state["n"] += 1
                return init
            if body.get("action") == "step":
                state["n"] += 1
                return step
            raise AssertionError(body)

        gw = LegacyPerceptionGateway(http_post=fake)
        return gw, state, init

    def test_init_initialized(self):
        gw, state, _ = self._gateway()
        dets = convert_legacy_ground_response(
            _load("legacy_ground_response.json"),
            request_id="g",
            frame_id="f0",
            keywords=["electronic device"],
        )["detections"]
        out = gw.track(
            image_b64="QQ==",
            frame_id="f0",
            parent_request_id="p",
            detections=dets,
            keywords=["electronic device"],
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["track_state"], "initialized")
        self.assertFalse(out["track_state_native"])
        self.assertEqual(out["track_state_source"], "legacy_gateway_inferred")
        # track_id=0 must survive
        self.assertTrue(is_valid_track_id(out["track_id"]))
        self.assertEqual(int(out["track_id"]), 0)
        self.assertEqual(out["track_id_str"], "0")
        self.assertEqual(state["n"], 1)

    def test_step_tracking(self):
        gw, state, _ = self._gateway()
        dets = convert_legacy_ground_response(
            _load("legacy_ground_response.json"),
            request_id="g",
            frame_id="f0",
            keywords=["electronic device"],
        )["detections"]
        gw.track(image_b64="QQ==", frame_id="f0", parent_request_id="p", detections=dets, keywords=["electronic device"])
        out = gw.track(image_b64="QQ==", frame_id="f1", parent_request_id="p", detections=dets)
        self.assertEqual(out["track_state"], "tracking")
        self.assertEqual(int(out["track_id"]), 0)
        self.assertEqual(state["n"], 2)

    def test_step_no_track_lost(self):
        init = _load("legacy_track_init_response.json")

        def fake(endpoint, body):
            if body.get("action") == "init":
                return init
            return {"session_id": "fixture-session-token", "frame_index": 1, "tracks": []}

        gw = LegacyPerceptionGateway(http_post=fake)
        dets = [{"label": "electronic device", "score": 0.5, "box_xyxy": [1, 2, 3, 4]}]
        gw.track(image_b64="QQ==", frame_id="f0", detections=dets, keywords=["electronic device"])
        out = gw.track(image_b64="QQ==", frame_id="f1", detections=dets)
        self.assertEqual(out["track_state"], "lost")
        self.assertFalse(out["track_state_native"])

    def test_lost_then_init_reacquired(self):
        init = _load("legacy_track_init_response.json")
        calls = []

        def fake(endpoint, body):
            calls.append(body.get("action"))
            if body.get("action") == "init":
                return init
            return {"session_id": "fixture-session-token", "frame_index": 1, "tracks": []}

        gw = LegacyPerceptionGateway(http_post=fake, reinit_after_lost=True)
        dets = [{"label": "electronic device", "score": 0.5, "box_xyxy": [1, 2, 3, 4]}]
        gw.track(image_b64="QQ==", frame_id="f0", detections=dets, keywords=["electronic device"])
        lost = gw.track(image_b64="QQ==", frame_id="f1", detections=dets)
        self.assertEqual(lost["track_state"], "lost")
        again = gw.track(image_b64="QQ==", frame_id="f2", detections=dets, keywords=["electronic device"])
        self.assertEqual(again["track_state"], "reacquired")
        self.assertEqual(calls, ["init", "step", "init"])

    def test_reset_terminated(self):
        gw, _, _ = self._gateway()
        out = gw.reset()
        self.assertEqual(out["track_state"], "terminated")
        self.assertFalse(out["track_state_native"])

    def test_session_fail_no_same_frame_retry(self):
        n = {"c": 0}

        def fake(endpoint, body):
            n["c"] += 1
            return {"error": "boom", "ok": False}

        gw = LegacyPerceptionGateway(http_post=fake)
        dets = [{"label": "electronic device", "score": 0.5, "box_xyxy": [1, 2, 3, 4]}]
        a = gw.track(image_b64="QQ==", frame_id="same", detections=dets, keywords=["electronic device"])
        b = gw.track(image_b64="QQ==", frame_id="same", detections=dets, keywords=["electronic device"])
        self.assertFalse(a["ok"])
        self.assertIn("same_frame", b["error"])
        self.assertEqual(n["c"], 1)  # no second POST


if __name__ == "__main__":
    unittest.main()
