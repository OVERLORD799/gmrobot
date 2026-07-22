#!/usr/bin/env python3
"""Offline unit tests for Legacy VLM → canonical gateway."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "v0b3_legacy"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from vlm.legacy_gateway import (  # noqa: E402
    LegacyVLMGateway,
    convert_legacy_analyze_response,
)
from vlm.client import CONTRACT_MODE_CANONICAL, VLMClient, VLMClientConfig  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


class TestVLMLegacyGateway(unittest.TestCase):
    def test_full_text_to_canonical_pass(self):
        remote = _load("legacy_vlm_analyze_response.json")
        out = convert_legacy_analyze_response(
            remote, request_id="req-1", frame_id="frm-1"
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["request_id"], "req-1")
        self.assertEqual(out["frame_id"], "frm-1")
        self.assertEqual(out["schema_version"], "five_stage_vlm_v1")
        self.assertEqual(out["prompt_version"], "five_stage_safety_v1")
        self.assertEqual(out["remote_contract"], "legacy_v2")
        self.assertEqual(out["id_source"], "local_gateway")
        self.assertEqual(out["model_id"], "Qwen2.5-VL-7B-Instruct-4bit-nf4")
        self.assertGreater(out["latency_ms"], 0)
        self.assertIn("robotic arm", out["keywords"])
        self.assertTrue(out["gateway_parse_ok"])
        self.assertIn("vlm_risk_type", out["legacy_vlm_fields_ignored"])

    def test_fenced_json(self):
        remote = {
            "model_id": "m",
            "latency_ms": 2.0,
            "text": "```json\n"
            + json.dumps(
                {
                    "scene_summary": "s",
                    "keywords": ["a"],
                    "risk_type": "none",
                    "risk_confidence": 0.2,
                    "affected_entities": ["a"],
                    "predicted_consequence": "c",
                    "prediction_horizon_s": 1.0,
                    "explanation": "e",
                    "suggested_action": "continue",
                    "spatial_hint": "none",
                }
            )
            + "\n```",
        }
        out = convert_legacy_analyze_response(remote, request_id="r", frame_id="f")
        self.assertTrue(out["ok"])
        self.assertEqual(out["predicted_consequence"], "c")

    def test_missing_consequence_schema_error(self):
        remote = _load("legacy_vlm_missing_consequence.json")
        out = convert_legacy_analyze_response(remote, request_id="r", frame_id="f")
        self.assertFalse(out["ok"])
        self.assertEqual(out["error_type"], "schema_error")
        self.assertIn("predicted_consequence", out["error"])

    def test_legacy_fields_do_not_fill_missing(self):
        remote = {
            "model_id": "m",
            "latency_ms": 1.0,
            "text": json.dumps(
                {
                    "scene_summary": "s",
                    "keywords": ["a"],
                    "risk_type": "none",
                    "risk_confidence": 0.1,
                    "affected_entities": ["a"],
                    "prediction_horizon_s": 1.0,
                    "explanation": "e",
                    "suggested_action": "continue",
                    "spatial_hint": "none",
                    # no predicted_consequence
                }
            ),
            "vlm_explanation": "SHOULD_NOT_BECOME_CONSEQUENCE",
            "vlm_risk_type": "dynamic",
        }
        out = convert_legacy_analyze_response(remote, request_id="r", frame_id="f")
        self.assertFalse(out["ok"])
        self.assertNotEqual(out.get("predicted_consequence"), "SHOULD_NOT_BECOME_CONSEQUENCE")

    def test_local_ids_and_payload_meta(self):
        posted = []

        def fake_post(body):
            posted.append(body)
            return _load("legacy_vlm_analyze_response.json")

        gw = LegacyVLMGateway(http_post=fake_post)
        out = gw.analyze_b64(
            "AAA",
            request_id="local-req",
            frame_id="local-frm",
            meta={"probe": "unit"},
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["request_id"], "local-req")
        self.assertEqual(out["frame_id"], "local-frm")
        body = posted[0]
        self.assertNotIn("request_id", body)  # not top-level for legacy
        self.assertNotIn("schema_version", body)
        self.assertEqual(body["meta"]["local_request_id"], "local-req")
        self.assertEqual(body["meta"]["frame_id"], "local-frm")
        self.assertNotIn("image_b64", json.dumps(out))

    def test_raw_text_truncated(self):
        remote = _load("legacy_vlm_analyze_response.json")
        out = convert_legacy_analyze_response(remote, request_id="r", frame_id="f")
        self.assertIn("raw_response_truncated", out)
        self.assertLessEqual(len(out["raw_response_truncated"]), 512)

    def test_canonical_mode_default_unaffected(self):
        cfg = VLMClientConfig()
        self.assertEqual(cfg.contract_mode, CONTRACT_MODE_CANONICAL)
        client = VLMClient(cfg)
        self.assertEqual(client.config.contract_mode, CONTRACT_MODE_CANONICAL)

    def test_legacy_mode_not_auto_enabled(self):
        # Loading default client never flips to legacy without explicit config
        client = VLMClient()
        self.assertEqual(client.config.contract_mode, "canonical_v0a")


if __name__ == "__main__":
    unittest.main()
