#!/usr/bin/env python3
"""Perception service contract tests with FakeBackend (no FastAPI/models)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))

from perception.backends import FakePerceptionBackend, UnavailableBackend  # noqa: E402
from perception.client import PerceptionClient  # noqa: E402
from perception.schema import TRACK_STATES  # noqa: E402


def test_unavailable_backend_explicit():
    out = UnavailableBackend().ground(
        {"request_id": "r", "frame_id": "f", "keywords": ["hand"]}
    )
    assert out["ok"] is False
    assert out["error_type"] == "backend_unavailable"


def test_fake_ground_keywords_map():
    fake = FakePerceptionBackend()
    out = fake.ground(
        {
            "request_id": "req-1",
            "frame_id": "frm-1",
            "keywords": ["bare human hand", "tool"],
            "run_sam2": True,
            "text_prompt": "bare human hand . tool",
        }
    )
    assert out["ok"] is True
    assert out["request_id"] == "req-1"
    assert out["frame_id"] == "frm-1"
    assert out["synthetic"] is True
    assert "bare human hand" in out["keyword_detection_map"]
    assert out["text_prompt_used"] == "bare human hand . tool"
    assert all(d["track_state"] in TRACK_STATES for d in out["detections"])


def test_empty_keywords_skip():
    out = FakePerceptionBackend().ground({"request_id": "r", "frame_id": "f", "keywords": []})
    assert out["perception_status"] == "skipped_no_keywords"
    assert out["detections"] == []


def test_track_lost_reacquired():
    fake = FakePerceptionBackend()
    init = fake.track_init({"request_id": "r", "frame_id": "f0"})
    sid = init["track_session_id"]
    lost = fake.track_step(
        {
            "request_id": "r",
            "frame_id": "f1",
            "track_session_id": sid,
            "frame_index": 1,
            "force_lost": True,
        }
    )
    assert lost["tracks"][0]["track_state"] == "lost"
    reacq = fake.track_step(
        {
            "request_id": "r",
            "frame_id": "f2",
            "track_session_id": sid,
            "frame_index": 2,
            "force_reacquired": True,
        }
    )
    assert reacq["tracks"][0]["track_state"] == "reacquired"


def test_client_keywords_enter_payload():
    captured = {}
    client = PerceptionClient()

    def fake_request(method, endpoint, *, body):
        captured["body"] = body
        return {"ok": True, "detections": [], "keyword_detection_map": {}, "perception_status": "ok"}

    client._request_json = fake_request  # type: ignore[method-assign]
    client.ground(
        np.zeros((8, 8, 3), dtype=np.uint8),
        keywords=["bare human hand", "bare human hand", "gripper"],
        request_id="req-x",
        frame_id="frm-x",
        allow_default_prompt=False,
    )
    assert captured["body"]["keywords"] == ["bare human hand", "gripper"]
    assert captured["body"]["text_prompt"] == "bare human hand . gripper"
    assert captured["body"]["request_id"] == "req-x"
    assert captured["body"]["frame_id"] == "frm-x"


def test_empty_keywords_no_default_prompt_not_success_chain():
    client = PerceptionClient()
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not call network on empty keywords")

    client._request_json = boom  # type: ignore[method-assign]
    out = client.ground(np.zeros((4, 4, 3), dtype=np.uint8), keywords=[], allow_default_prompt=False)
    assert called["n"] == 0
    assert out["perception_status"] == "skipped_no_keywords"


if __name__ == "__main__":
    test_unavailable_backend_explicit()
    test_fake_ground_keywords_map()
    test_empty_keywords_skip()
    test_track_lost_reacquired()
    test_client_keywords_enter_payload()
    test_empty_keywords_no_default_prompt_not_success_chain()
    print("All perception service contract unit tests passed.")
