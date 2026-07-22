#!/usr/bin/env python3
"""Perception FastAPI contract (GDINO+SAM2) with injectable backends (V0-A)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_SRC_LEAF = Path(__file__).resolve().parents[2] / "source" / "GMRobot" / "GMRobot"
if str(_SRC_LEAF) not in sys.path:
    sys.path.insert(0, str(_SRC_LEAF))

from perception.backends import (  # noqa: E402
    FakePerceptionBackend,
    PerceptionBackend,
    UnavailableBackend,
)
from perception.schema import SCHEMA_VERSION, keywords_to_text_prompt, normalize_keywords  # noqa: E402

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "fastapi/pydantic required to run perception_service.py; "
        "offline tests use perception.backends directly"
    ) from exc

app = FastAPI(title="GM-SafePick Perception", version="0.1.0-v0a")
_BACKEND: PerceptionBackend = UnavailableBackend()


def set_backend(backend: PerceptionBackend) -> None:
    global _BACKEND
    _BACKEND = backend


def get_backend() -> PerceptionBackend:
    return _BACKEND


class GroundRequest(BaseModel):
    request_id: str | None = None
    frame_id: str | None = None
    image_b64: str = ""
    text_prompt: str = ""
    keywords: list[str] = Field(default_factory=list)
    run_sam2: bool = True
    confidence_threshold: float = 0.2
    schema_version: str = SCHEMA_VERSION
    meta: dict[str, Any] = Field(default_factory=dict)


class TrackInitRequest(BaseModel):
    request_id: str | None = None
    frame_id: str | None = None
    image_b64: str = ""
    track_id: str | None = None
    target_label: str = "hand"
    box_xyxy: list[float] | None = None
    keywords: list[str] = Field(default_factory=list)
    text_prompt: str = ""
    frame_index: int = 0
    schema_version: str = SCHEMA_VERSION
    meta: dict[str, Any] = Field(default_factory=dict)


class TrackStepRequest(BaseModel):
    request_id: str | None = None
    frame_id: str | None = None
    track_session_id: str
    image_b64: str = ""
    frame_index: int = 0
    force_lost: bool = False
    force_reacquired: bool = False
    schema_version: str = SCHEMA_VERSION
    meta: dict[str, Any] = Field(default_factory=dict)


class TrackResetRequest(BaseModel):
    request_id: str | None = None
    frame_id: str | None = None
    track_session_id: str
    schema_version: str = SCHEMA_VERSION


@app.get("/health")
def health():
    b = get_backend()
    return {
        "ok": True,
        "backend_available": bool(b.available),
        "model_versions": dict(b.model_versions),
        "schema_version": SCHEMA_VERSION,
    }


@app.post("/ground")
def ground(req: GroundRequest):
    b = get_backend()
    payload = req.model_dump()
    keywords = normalize_keywords(payload.get("keywords"))
    payload["keywords"] = keywords
    if not payload.get("text_prompt") and keywords:
        payload["text_prompt"] = keywords_to_text_prompt(keywords)
    if not b.available:
        raise HTTPException(status_code=503, detail=b.ground(payload))
    return b.ground(payload)


@app.post("/track/init")
def track_init(req: TrackInitRequest):
    b = get_backend()
    payload = req.model_dump()
    if not b.available:
        raise HTTPException(status_code=503, detail=b.track_init(payload))
    return b.track_init(payload)


@app.post("/track/step")
def track_step(req: TrackStepRequest):
    b = get_backend()
    payload = req.model_dump()
    if not b.available:
        raise HTTPException(status_code=503, detail=b.track_step(payload))
    return b.track_step(payload)


@app.post("/track/reset")
def track_reset(req: TrackResetRequest):
    return get_backend().track_reset(req.model_dump())


@app.post("/track")
def track_compat(body: dict[str, Any]):
    action = str(body.get("action") or "").lower()
    data = {k: v for k, v in body.items() if k != "action"}
    if action == "init":
        return track_init(TrackInitRequest(**data))
    if action == "step":
        return track_step(TrackStepRequest(**data))
    if action == "reset":
        return track_reset(TrackResetRequest(**data))
    raise HTTPException(status_code=400, detail="action must be init|step|reset")


if __name__ == "__main__":
    import uvicorn

    mode = os.environ.get("PERCEPTION_BACKEND", "unavailable").lower()
    if mode == "fake":
        set_backend(FakePerceptionBackend())
    port = int(os.environ.get("PERCEPTION_PORT", "8082"))
    uvicorn.run(app, host="0.0.0.0", port=port)
