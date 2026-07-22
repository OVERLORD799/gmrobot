"""Perception backends for five-stage contract (no FastAPI dependency)."""

from __future__ import annotations

import time
import uuid
from typing import Any, Protocol

from .schema import (
    SCHEMA_VERSION,
    TRACK_STATES,
    keywords_to_text_prompt,
    make_unavailable,
    normalize_keywords,
    validate_detection,
)


class PerceptionBackend(Protocol):
    def ground(self, req: dict[str, Any]) -> dict[str, Any]: ...

    def track_init(self, req: dict[str, Any]) -> dict[str, Any]: ...

    def track_step(self, req: dict[str, Any]) -> dict[str, Any]: ...

    def track_reset(self, req: dict[str, Any]) -> dict[str, Any]: ...

    @property
    def available(self) -> bool: ...

    @property
    def model_versions(self) -> dict[str, str]: ...


class UnavailableBackend:
    available = False
    model_versions = {"gdino_model_id": "", "sam2_model_id": ""}

    def ground(self, req: dict[str, Any]) -> dict[str, Any]:
        return make_unavailable(
            request_id=str(req.get("request_id") or ""),
            frame_id=str(req.get("frame_id") or ""),
        )

    def track_init(self, req: dict[str, Any]) -> dict[str, Any]:
        return make_unavailable(
            request_id=str(req.get("request_id") or ""),
            frame_id=str(req.get("frame_id") or ""),
        )

    def track_step(self, req: dict[str, Any]) -> dict[str, Any]:
        return make_unavailable(
            request_id=str(req.get("request_id") or ""),
            frame_id=str(req.get("frame_id") or ""),
        )

    def track_reset(self, req: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "request_id": str(req.get("request_id") or ""),
            "frame_id": str(req.get("frame_id") or ""),
            "track_session_id": str(req.get("track_session_id") or ""),
            "reset": True,
            "track_state": "terminated",
        }


class FakePerceptionBackend:
    """Deterministic offline backend for contract tests (not a real model)."""

    available = True
    model_versions = {"gdino_model_id": "fake-gdino", "sam2_model_id": "fake-sam2"}

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def ground(self, req: dict[str, Any]) -> dict[str, Any]:
        t0 = time.monotonic()
        keywords = normalize_keywords(req.get("keywords"))
        request_id = str(req.get("request_id") or uuid.uuid4())
        frame_id = str(req.get("frame_id") or uuid.uuid4())
        if not keywords:
            return {
                "ok": True,
                "request_id": request_id,
                "frame_id": frame_id,
                "detections": [],
                "keyword_detection_map": {},
                "latency_ms": (time.monotonic() - t0) * 1000.0,
                "model_versions": dict(self.model_versions),
                "schema_version": SCHEMA_VERSION,
                "perception_status": "skipped_no_keywords",
                "synthetic": True,
            }
        detections = []
        keyword_map: dict[str, list[str]] = {}
        for i, kw in enumerate(keywords):
            det_id = f"det-{i}"
            track_id = f"trk-{i}"
            det = validate_detection(
                {
                    "detection_id": det_id,
                    "label": kw,
                    "score": 0.91,
                    "box_xyxy": [10.0 + i, 20.0, 110.0 + i, 120.0],
                    "mask_available": bool(req.get("run_sam2", True)),
                    "track_id": track_id,
                    "track_state": "initialized",
                }
            )
            detections.append(det)
            keyword_map[kw] = [det_id]
        return {
            "ok": True,
            "request_id": request_id,
            "frame_id": frame_id,
            "detections": detections,
            "keyword_detection_map": keyword_map,
            "latency_ms": (time.monotonic() - t0) * 1000.0,
            "model_versions": dict(self.model_versions),
            "schema_version": SCHEMA_VERSION,
            "perception_status": "ok",
            "text_prompt_used": str(
                req.get("text_prompt") or keywords_to_text_prompt(keywords)
            ),
            "synthetic": True,
        }

    def track_init(self, req: dict[str, Any]) -> dict[str, Any]:
        t0 = time.monotonic()
        request_id = str(req.get("request_id") or uuid.uuid4())
        frame_id = str(req.get("frame_id") or uuid.uuid4())
        session_id = str(uuid.uuid4())
        track_id = str(req.get("track_id") or "trk-0")
        self._sessions[session_id] = {
            "track_id": track_id,
            "state": "initialized",
            "frame_index": int(req.get("frame_index") or 0),
        }
        return {
            "ok": True,
            "request_id": request_id,
            "frame_id": frame_id,
            "track_session_id": session_id,
            "frame_index": 0,
            "tracks": [
                {
                    "track_id": track_id,
                    "track_state": "initialized",
                    "label": str(req.get("target_label") or "object"),
                    "box_xyxy": [10.0, 20.0, 110.0, 120.0],
                    "center_xy": [60.0, 70.0],
                    "score": 0.9,
                }
            ],
            "latency_ms": (time.monotonic() - t0) * 1000.0,
            "model_versions": dict(self.model_versions),
            "schema_version": SCHEMA_VERSION,
            "synthetic": True,
        }

    def track_step(self, req: dict[str, Any]) -> dict[str, Any]:
        t0 = time.monotonic()
        request_id = str(req.get("request_id") or uuid.uuid4())
        frame_id = str(req.get("frame_id") or uuid.uuid4())
        session_id = str(req.get("track_session_id") or "")
        state = self._sessions.get(session_id)
        if state is None:
            return make_unavailable(
                request_id=request_id,
                frame_id=frame_id,
                error="unknown track_session_id",
                error_type="schema_error",
            )
        if bool(req.get("force_lost")):
            track_state = "lost"
        elif bool(req.get("force_reacquired")):
            track_state = "reacquired"
        else:
            track_state = "tracking"
        assert track_state in TRACK_STATES
        state["state"] = track_state
        state["frame_index"] = int(req.get("frame_index") or state["frame_index"] + 1)
        return {
            "ok": True,
            "request_id": request_id,
            "frame_id": frame_id,
            "track_session_id": session_id,
            "frame_index": state["frame_index"],
            "tracks": [
                {
                    "track_id": state["track_id"],
                    "track_state": track_state,
                    "label": "object",
                    "box_xyxy": [12.0, 22.0, 112.0, 122.0],
                    "center_xy": [62.0, 72.0],
                    "score": 0.88 if track_state != "lost" else 0.1,
                }
            ],
            "latency_ms": (time.monotonic() - t0) * 1000.0,
            "model_versions": dict(self.model_versions),
            "schema_version": SCHEMA_VERSION,
            "synthetic": True,
        }

    def track_reset(self, req: dict[str, Any]) -> dict[str, Any]:
        session_id = str(req.get("track_session_id") or "")
        self._sessions.pop(session_id, None)
        return {
            "ok": True,
            "request_id": str(req.get("request_id") or ""),
            "frame_id": str(req.get("frame_id") or ""),
            "track_session_id": session_id,
            "reset": True,
            "track_state": "terminated",
        }
