"""Perception (GDINO+SAM2) contract schema for five-stage shadow (V0-A)."""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "five_stage_perception_v1"

TRACK_STATES = frozenset(
    {"initialized", "tracking", "lost", "reacquired", "terminated"}
)


def normalize_keywords(keywords: Any) -> list[str]:
    if keywords is None:
        return []
    if isinstance(keywords, str):
        items = [keywords]
    elif isinstance(keywords, (list, tuple)):
        items = list(keywords)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def keywords_to_text_prompt(keywords: list[str]) -> str:
    return " . ".join(keywords)


def make_unavailable(
    *,
    request_id: str,
    frame_id: str,
    error: str = "perception backend unavailable",
    error_type: str = "backend_unavailable",
) -> dict[str, Any]:
    return {
        "ok": False,
        "request_id": str(request_id),
        "frame_id": str(frame_id),
        "error_type": error_type,
        "error": str(error)[:500],
        "schema_version": SCHEMA_VERSION,
        "detections": [],
        "keyword_detection_map": {},
    }


def validate_detection(det: dict[str, Any]) -> dict[str, Any]:
    required = (
        "detection_id",
        "label",
        "score",
        "box_xyxy",
        "mask_available",
        "track_id",
        "track_state",
    )
    missing = [k for k in required if k not in det]
    if missing:
        raise ValueError(f"detection missing fields: {missing}")
    state = str(det["track_state"])
    if state not in TRACK_STATES:
        raise ValueError(f"invalid track_state={state!r}")
    box = det["box_xyxy"]
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError("box_xyxy must be length-4")
    return {
        "detection_id": str(det["detection_id"]),
        "label": str(det["label"]),
        "score": float(det["score"]),
        "box_xyxy": [float(x) for x in box],
        "mask_available": bool(det["mask_available"]),
        "track_id": str(det["track_id"]),
        "track_state": state,
    }
