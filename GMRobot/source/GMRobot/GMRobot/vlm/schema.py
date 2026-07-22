"""Structured VLM five-stage schema (V0-A). Strict parse; no silent fallbacks."""

from __future__ import annotations

import json
import re
from typing import Any

SCHEMA_VERSION = "five_stage_vlm_v1"
PROMPT_VERSION = "five_stage_safety_v1"

RISK_TYPES = frozenset({"static", "dynamic", "functional", "none"})
SUGGESTED_ACTIONS = frozenset({"continue", "slow_down", "stop", "replan", "alert"})
SPATIAL_HINTS = frozenset({"left", "right", "above", "retreat", "none"})
ERROR_TYPES = frozenset(
    {
        "parse_error",
        "timeout",
        "transport_error",
        "schema_error",
        "backend_unavailable",
        "stub_mode",
    }
)

_SUCCESS_REQUIRED = (
    "ok",
    "request_id",
    "frame_id",
    "scene_summary",
    "keywords",
    "risk_type",
    "risk_confidence",
    "affected_entities",
    "predicted_consequence",
    "prediction_horizon_s",
    "explanation",
    "suggested_action",
    "spatial_hint",
    "prompt_version",
    "schema_version",
    "model_id",
    "latency_ms",
)

_RAW_MAX_CHARS = 512


class SchemaValidationError(ValueError):
    """Raised when structured VLM output fails validation."""

    def __init__(self, message: str, *, error_type: str = "schema_error"):
        super().__init__(message)
        self.error_type = error_type


def normalize_keywords(keywords: Any) -> list[str]:
    """Deduplicate keywords, drop empties, preserve first-seen order."""
    if keywords is None:
        return []
    if isinstance(keywords, str):
        raw = [keywords]
    elif isinstance(keywords, (list, tuple)):
        raw = list(keywords)
    else:
        raise SchemaValidationError(
            f"keywords must be list[str], got {type(keywords).__name__}",
            error_type="schema_error",
        )
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
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
    """Grounding-DINO style prompt: 'a . b . c'."""
    return " . ".join(keywords)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse pure JSON or Markdown fenced JSON object."""
    if text is None:
        raise SchemaValidationError("empty response text", error_type="parse_error")
    raw = str(text).strip()
    if not raw:
        raise SchemaValidationError("empty response text", error_type="parse_error")

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"JSON decode error: {exc}", error_type="parse_error") from exc
    if not isinstance(obj, dict):
        raise SchemaValidationError("JSON root must be an object", error_type="parse_error")
    return obj


def truncate_raw(text: str, *, max_chars: int = _RAW_MAX_CHARS) -> str:
    s = str(text).replace("\x00", "")
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def make_error_result(
    *,
    request_id: str,
    frame_id: str,
    error_type: str,
    error: str,
    model_id: str = "",
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    raw_response: str | None = None,
    synthetic: bool = False,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    if error_type not in ERROR_TYPES:
        error_type = "schema_error"
    out: dict[str, Any] = {
        "ok": False,
        "request_id": str(request_id),
        "frame_id": str(frame_id),
        "error_type": error_type,
        "error": str(error)[:500],
        "raw_response_available": raw_response is not None,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "model_id": str(model_id or ""),
    }
    if raw_response is not None:
        out["raw_response_truncated"] = truncate_raw(raw_response)
    if synthetic:
        out["synthetic"] = True
    if latency_ms is not None:
        out["latency_ms"] = float(latency_ms)
    return out


def validate_success_payload(
    payload: dict[str, Any],
    *,
    request_id: str | None = None,
    frame_id: str | None = None,
    default_model_id: str = "",
    default_prompt_version: str = PROMPT_VERSION,
    default_schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Validate and normalize a successful structured VLM payload."""
    if not isinstance(payload, dict):
        raise SchemaValidationError("payload must be a dict", error_type="schema_error")

    # Reject legacy hardcoded stub fingerprints if they omit required fields.
    missing = [k for k in _SUCCESS_REQUIRED if k not in payload]
    # Allow callers to inject ids if absent.
    if "request_id" in missing and request_id is not None:
        payload = {**payload, "request_id": request_id}
        missing = [k for k in missing if k != "request_id"]
    if "frame_id" in missing and frame_id is not None:
        payload = {**payload, "frame_id": frame_id}
        missing = [k for k in missing if k != "frame_id"]
    if "prompt_version" in missing:
        payload = {**payload, "prompt_version": default_prompt_version}
        missing = [k for k in missing if k != "prompt_version"]
    if "schema_version" in missing:
        payload = {**payload, "schema_version": default_schema_version}
        missing = [k for k in missing if k != "schema_version"]
    if "model_id" in missing and default_model_id:
        payload = {**payload, "model_id": default_model_id}
        missing = [k for k in missing if k != "model_id"]
    if "latency_ms" in missing:
        payload = {**payload, "latency_ms": 0.0}
        missing = [k for k in missing if k != "latency_ms"]

    if missing:
        raise SchemaValidationError(
            f"missing required fields: {', '.join(missing)}",
            error_type="schema_error",
        )

    if payload.get("ok") is not True:
        raise SchemaValidationError("ok must be true for success payload", error_type="schema_error")

    risk_type = str(payload["risk_type"]).strip().lower()
    if risk_type not in RISK_TYPES:
        raise SchemaValidationError(
            f"invalid risk_type={risk_type!r}", error_type="schema_error"
        )
    action = str(payload["suggested_action"]).strip().lower()
    if action not in SUGGESTED_ACTIONS:
        raise SchemaValidationError(
            f"invalid suggested_action={action!r}", error_type="schema_error"
        )
    hint = str(payload["spatial_hint"]).strip().lower()
    if hint not in SPATIAL_HINTS:
        raise SchemaValidationError(
            f"invalid spatial_hint={hint!r}", error_type="schema_error"
        )

    try:
        conf = float(payload["risk_confidence"])
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(
            "risk_confidence must be float", error_type="schema_error"
        ) from exc
    if not (0.0 <= conf <= 1.0):
        raise SchemaValidationError(
            f"risk_confidence out of range: {conf}", error_type="schema_error"
        )

    try:
        horizon = float(payload["prediction_horizon_s"])
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(
            "prediction_horizon_s must be float", error_type="schema_error"
        ) from exc
    if horizon < 0.0:
        raise SchemaValidationError(
            "prediction_horizon_s must be >= 0", error_type="schema_error"
        )

    entities = payload["affected_entities"]
    if not isinstance(entities, list) or any(not isinstance(x, str) for x in entities):
        raise SchemaValidationError(
            "affected_entities must be list[str]", error_type="schema_error"
        )

    keywords = normalize_keywords(payload["keywords"])
    try:
        latency = float(payload["latency_ms"])
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError("latency_ms must be float", error_type="schema_error") from exc

    return {
        "ok": True,
        "request_id": str(payload["request_id"]),
        "frame_id": str(payload["frame_id"]),
        "scene_summary": str(payload["scene_summary"]),
        "keywords": keywords,
        "risk_type": risk_type,
        "risk_confidence": conf,
        "affected_entities": [str(x) for x in entities],
        "predicted_consequence": str(payload["predicted_consequence"]),
        "prediction_horizon_s": horizon,
        "explanation": str(payload["explanation"]),
        "suggested_action": action,
        "spatial_hint": hint,
        "prompt_version": str(payload.get("prompt_version") or default_prompt_version),
        "schema_version": str(payload.get("schema_version") or default_schema_version),
        "model_id": str(payload.get("model_id") or default_model_id),
        "latency_ms": latency,
    }


def parse_model_text_to_success(
    text: str,
    *,
    request_id: str,
    frame_id: str,
    model_id: str,
    latency_ms: float,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Parse model free-text into a validated success payload."""
    obj = extract_json_object(text)
    # Map alternate keys from prompts.
    if "vlm_risk_type" in obj and "risk_type" not in obj:
        obj["risk_type"] = obj["vlm_risk_type"]
    if "vlm_suggested_action" in obj and "suggested_action" not in obj:
        obj["suggested_action"] = obj["vlm_suggested_action"]
    if "vlm_keywords" in obj and "keywords" not in obj:
        obj["keywords"] = obj["vlm_keywords"]
    if "vlm_explanation" in obj and "explanation" not in obj:
        obj["explanation"] = obj["vlm_explanation"]
    if "vlm_risk_confidence" in obj and "risk_confidence" not in obj:
        obj["risk_confidence"] = obj["vlm_risk_confidence"]

    obj["ok"] = True
    obj["request_id"] = request_id
    obj["frame_id"] = frame_id
    obj["model_id"] = model_id
    obj["latency_ms"] = latency_ms
    obj.setdefault("prompt_version", prompt_version)
    obj.setdefault("schema_version", schema_version)
    return validate_success_payload(
        obj,
        request_id=request_id,
        frame_id=frame_id,
        default_model_id=model_id,
        default_prompt_version=prompt_version,
        default_schema_version=schema_version,
    )


def coerce_analyze_response(
    raw: dict[str, Any] | None,
    *,
    request_id: str,
    frame_id: str,
    model_id: str = "",
) -> dict[str, Any]:
    """Normalize a service/client response into success or explicit error."""
    if not raw:
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type="transport_error",
            error="empty response",
            model_id=model_id,
        )
    if raw.get("ok") is False or raw.get("error") or raw.get("error_type"):
        et = str(raw.get("error_type") or "transport_error")
        if et not in ERROR_TYPES:
            et = "transport_error"
        return make_error_result(
            request_id=str(raw.get("request_id") or request_id),
            frame_id=str(raw.get("frame_id") or frame_id),
            error_type=et,
            error=str(raw.get("error") or "request failed"),
            model_id=str(raw.get("model_id") or model_id),
            prompt_version=str(raw.get("prompt_version") or PROMPT_VERSION),
            schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
            raw_response=raw.get("raw_response_truncated") or raw.get("vlm_explanation"),
            synthetic=bool(raw.get("synthetic")),
            latency_ms=raw.get("latency_ms"),
        )
    try:
        return validate_success_payload(
            raw,
            request_id=request_id,
            frame_id=frame_id,
            default_model_id=model_id,
        )
    except SchemaValidationError as exc:
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type=exc.error_type,
            error=str(exc),
            model_id=model_id,
            raw_response=json.dumps(raw, ensure_ascii=False)[:_RAW_MAX_CHARS],
        )
