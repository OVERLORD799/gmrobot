#!/usr/bin/env python3
"""Unit tests for V0-B4 replay init vs step validation semantics (offline)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

# Load replay module by path (script, not package)
_SPEC = importlib.util.spec_from_file_location(
    "run_v0b4_legacy_gateway_replay",
    ROOT / "scripts" / "run_v0b4_legacy_gateway_replay.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = _MOD  # required for @dataclass under importlib
_SPEC.loader.exec_module(_MOD)
validate_frame = _MOD.validate_frame

from perception.legacy_gateway import select_detection_for_track  # noqa: E402


def _base_result(**overrides):
    track = {
        "ok": True,
        "parent_request_id": "req",
        "tracks": [
            {
                "track_id": 0,
                "label": "electronic device",
                "box_xyxy": [1, 2, 3, 4],
                "mask_area": 100,
                "sam2_score": 0.9,
                "track_state": "initialized",
            }
        ],
        "track_session_id": "<redacted>",
        "session_present": True,
        "track_state": "initialized",
        "track_state_native": False,
        "track_state_source": "legacy_gateway_inferred",
    }
    base = {
        "request_id": "req",
        "frame_id": "frm",
        "parent_request_id": "req",
        "keywords": ["electronic device", "robotic arm"],
        "id_source": "local_gateway",
        "track_id": 0,
        "track_state": "initialized",
        "track_state_native": False,
        "track_state_source": "legacy_gateway_inferred",
        "track_session_id": "<redacted>",
        "vlm": {
            "ok": True,
            "request_id": "req",
            "frame_id": "frm",
            "keywords": ["electronic device", "robotic arm"],
            "predicted_consequence": "c",
            "prediction_horizon_s": 1.0,
            "spatial_hint": "none",
            "risk_type": "none",
            "suggested_action": "continue",
            "id_source": "local_gateway",
        },
        "ground": {
            "ok": True,
            "parent_request_id": "req",
            "detections": [{"label": "electronic device", "score": 0.5, "box_xyxy": [1, 2, 3, 4]}],
            "model_versions": {
                "gdino_model_id": "IDEA-Research/grounding-dino-base",
                "sam2_model_id": "sam2.1_hiera_small.pt",
            },
            "id_source": "local_gateway",
        },
        "track": track,
    }
    base.update(overrides)
    return base


class TestInitStepValidation(unittest.TestCase):
    def test_init_requires_keyword_match(self):
        r = _base_result()
        r["track"]["tracks"][0]["label"] = "unrelated"
        errs = validate_frame(r, frame_idx=0, expected_request_id="req", expected_frame_id="frm")
        self.assertIn("selected_label_not_keyword_matched", errs)

    def test_init_keyword_match_beats_high_score_nonmatch(self):
        dets = [
            {"label": "noise", "score": 0.99, "box_xyxy": [0, 0, 1, 1]},
            {"label": "electronic device", "score": 0.2, "box_xyxy": [2, 2, 3, 3]},
        ]
        chosen = select_detection_for_track(dets, ["electronic device"])
        self.assertEqual(chosen["label"], "electronic device")

    def test_step_allows_changed_keywords_with_continuity(self):
        r = _base_result()
        r["keywords"] = ["container", "small objects"]  # different from init label
        r["vlm"]["keywords"] = ["container", "small objects"]
        r["track_state"] = "tracking"
        r["track"]["track_state"] = "tracking"
        r["track"]["tracks"][0]["track_state"] = "tracking"
        # still electronic device from init
        errs = validate_frame(
            r,
            frame_idx=1,
            expected_request_id="req",
            expected_frame_id="frm",
            prev_track_id=0,
        )
        self.assertNotIn("selected_label_not_keyword_matched", errs)
        self.assertEqual(errs, [])

    def test_step_track_id_loss_fails(self):
        r = _base_result()
        r["track_state"] = "tracking"
        r["track"]["track_state"] = "tracking"
        r["track_id"] = 7
        r["track"]["tracks"][0]["track_id"] = 7
        errs = validate_frame(
            r, frame_idx=1, expected_request_id="req", expected_frame_id="frm", prev_track_id=0
        )
        self.assertIn("track_id_not_associated_across_frames", errs)

    def test_step_session_mismatch_fails(self):
        r = _base_result()
        r["track_state"] = "tracking"
        r["track"]["track_state"] = "tracking"
        r["track"]["session_match"] = False
        errs = validate_frame(
            r, frame_idx=1, expected_request_id="req", expected_frame_id="frm", prev_track_id=0
        )
        self.assertIn("session_mismatch", errs)

    def test_step_empty_tracks_fails(self):
        r = _base_result()
        r["track_state"] = "lost"
        r["track"]["track_state"] = "lost"
        r["track"]["tracks"] = []
        errs = validate_frame(
            r, frame_idx=1, expected_request_id="req", expected_frame_id="frm", prev_track_id=0
        )
        self.assertIn("step_tracks_empty", errs)


if __name__ == "__main__":
    unittest.main()
