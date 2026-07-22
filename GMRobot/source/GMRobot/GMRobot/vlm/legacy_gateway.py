#!/usr/bin/env python3
"""Legacy VLM v2 → V0-A canonical schema gateway (offline-capable)."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from .schema import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    SchemaValidationError,
    extract_json_object,
    make_error_result,
    truncate_raw,
    validate_success_payload,
)

REMOTE_CONTRACT = "legacy_v2"
ID_SOURCE = "local_gateway"

# Strict five-stage prompt (same contract as V0-B2B probe). Never invent defaults.
STRICT_FIVE_STAGE_PROMPT = """Analyze robot workspace human-safety risks from the image.
Reply with ONLY a single JSON object (no markdown, no prose) with exactly these keys:
{
  "scene_summary": "...",
  "keywords": ["..."],
  "risk_type": "static|dynamic|functional|none",
  "risk_confidence": 0.0,
  "affected_entities": ["..."],
  "predicted_consequence": "...",
  "prediction_horizon_s": 1.5,
  "explanation": "...",
  "suggested_action": "continue|slow_down|stop|replan|alert",
  "spatial_hint": "left|right|above|retreat|none"
}
Do not invent legacy fields. Do not wrap the JSON in code fences."""

# Fields that must come from model text JSON — never from remote vlm_* fillers.
_TEXT_REQUIRED = (
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
)

HttpPostFn = Callable[[dict[str, Any]], dict[str, Any]]


def convert_legacy_analyze_response(
    remote: dict[str, Any] | None,
    *,
    request_id: str,
    frame_id: str,
    default_model_id: str = "",
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Map legacy /analyze JSON to canonical success or explicit schema_error.

    Uses only the ``text`` (or explicit model_output) field. Never fills
    consequence/horizon/affected_entities/spatial_hint from remote ``vlm_*``.
    """
    if not remote:
        return _annotate_error(
            make_error_result(
                request_id=request_id,
                frame_id=frame_id,
                error_type="transport_error",
                error="empty legacy response",
                model_id=default_model_id,
                prompt_version=prompt_version,
                schema_version=schema_version,
            )
        )

    if remote.get("ok") is False or remote.get("error_type"):
        return _annotate_error(
            make_error_result(
                request_id=request_id,
                frame_id=frame_id,
                error_type=str(remote.get("error_type") or "transport_error"),
                error=str(remote.get("error") or "legacy request failed"),
                model_id=str(remote.get("model_id") or default_model_id),
                prompt_version=prompt_version,
                schema_version=schema_version,
                latency_ms=remote.get("latency_ms"),
            )
        )

    text = remote.get("text")
    if not isinstance(text, str) or not text.strip():
        for alt in ("model_output", "output", "content"):
            if isinstance(remote.get(alt), str) and str(remote.get(alt)).strip():
                text = remote[alt]
                break
    if not isinstance(text, str) or not text.strip():
        return _annotate_error(
            make_error_result(
                request_id=request_id,
                frame_id=frame_id,
                error_type="schema_error",
                error="legacy response missing model text JSON",
                model_id=str(remote.get("model_id") or default_model_id),
                prompt_version=prompt_version,
                schema_version=schema_version,
                raw_response=json.dumps(
                    {k: v for k, v in remote.items() if not str(k).startswith("vlm_")},
                    ensure_ascii=False,
                ),
                latency_ms=remote.get("latency_ms"),
            )
        )

    try:
        obj = extract_json_object(text)
    except SchemaValidationError as exc:
        return _annotate_error(
            make_error_result(
                request_id=request_id,
                frame_id=frame_id,
                error_type=exc.error_type,
                error=str(exc),
                model_id=str(remote.get("model_id") or default_model_id),
                prompt_version=prompt_version,
                schema_version=schema_version,
                raw_response=text,
                latency_ms=remote.get("latency_ms"),
            )
        )

    # Refuse to synthesize from remote top-level vlm_* (explicit audit).
    ignored_legacy = [k for k in remote if str(k).startswith("vlm_")]
    missing = [k for k in _TEXT_REQUIRED if k not in obj]
    if missing:
        return _annotate_error(
            make_error_result(
                request_id=request_id,
                frame_id=frame_id,
                error_type="schema_error",
                error=f"model text missing fields: {', '.join(missing)}",
                model_id=str(remote.get("model_id") or default_model_id),
                prompt_version=prompt_version,
                schema_version=schema_version,
                raw_response=text,
                latency_ms=remote.get("latency_ms"),
            ),
            mapping_errors=missing,
            ignored_legacy_fields=ignored_legacy,
        )

    # Do NOT map obj's vlm_* alternates — require canonical keys in text.
    try:
        latency = float(remote.get("latency_ms", 0.0) or 0.0)
    except (TypeError, ValueError):
        latency = 0.0
    model_id = str(remote.get("model_id") or default_model_id)

    candidate = {
        "ok": True,
        "request_id": request_id,
        "frame_id": frame_id,
        "scene_summary": obj["scene_summary"],
        "keywords": obj["keywords"],
        "risk_type": obj["risk_type"],
        "risk_confidence": obj["risk_confidence"],
        "affected_entities": obj["affected_entities"],
        "predicted_consequence": obj["predicted_consequence"],
        "prediction_horizon_s": obj["prediction_horizon_s"],
        "explanation": obj["explanation"],
        "suggested_action": obj["suggested_action"],
        "spatial_hint": obj["spatial_hint"],
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "model_id": model_id,
        "latency_ms": latency,
    }
    try:
        validated = validate_success_payload(
            candidate,
            request_id=request_id,
            frame_id=frame_id,
            default_model_id=model_id,
            default_prompt_version=prompt_version,
            default_schema_version=schema_version,
        )
    except SchemaValidationError as exc:
        return _annotate_error(
            make_error_result(
                request_id=request_id,
                frame_id=frame_id,
                error_type=exc.error_type,
                error=str(exc),
                model_id=model_id,
                prompt_version=prompt_version,
                schema_version=schema_version,
                raw_response=text,
                latency_ms=latency,
            ),
            ignored_legacy_fields=ignored_legacy,
        )

    validated["remote_contract"] = REMOTE_CONTRACT
    validated["id_source"] = ID_SOURCE
    validated["gateway_parse_ok"] = True
    validated["gateway_mapping_errors"] = []
    validated["legacy_vlm_fields_ignored"] = ignored_legacy
    validated["raw_response_truncated"] = truncate_raw(text)
    return validated


def _annotate_error(
    err: dict[str, Any],
    *,
    mapping_errors: list[str] | None = None,
    ignored_legacy_fields: list[str] | None = None,
) -> dict[str, Any]:
    err = dict(err)
    err["remote_contract"] = REMOTE_CONTRACT
    err["id_source"] = ID_SOURCE
    err["gateway_parse_ok"] = False
    err["gateway_mapping_errors"] = list(mapping_errors or [])
    if ignored_legacy_fields is not None:
        err["legacy_vlm_fields_ignored"] = list(ignored_legacy_fields)
    return err


class LegacyVLMGateway:
    """Build legacy /analyze requests and convert responses to canonical."""

    def __init__(
        self,
        *,
        http_post: HttpPostFn | None = None,
        model_id: str = "Qwen2.5-VL-7B-Instruct",
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
        default_prompt: str = STRICT_FIVE_STAGE_PROMPT,
    ):
        self._http_post = http_post
        self.model_id = model_id
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.default_prompt = default_prompt

    def build_legacy_payload(
        self,
        *,
        image_b64: str,
        request_id: str,
        frame_id: str,
        prompt: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta_out = dict(meta or {})
        meta_out["local_request_id"] = request_id
        meta_out["frame_id"] = frame_id
        meta_out["schema_version"] = self.schema_version
        meta_out["prompt_version"] = self.prompt_version
        meta_out["remote_contract"] = REMOTE_CONTRACT
        # IDs only in meta — legacy server rejects unknown top-level ID fields.
        return {
            "image_b64": image_b64,
            "prompt": prompt or self.default_prompt,
            "meta": meta_out,
        }

    def analyze_b64(
        self,
        image_b64: str,
        *,
        request_id: str | None = None,
        frame_id: str | None = None,
        prompt: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rid = str(request_id or uuid.uuid4())
        fid = str(frame_id or uuid.uuid4())
        payload = self.build_legacy_payload(
            image_b64=image_b64,
            request_id=rid,
            frame_id=fid,
            prompt=prompt,
            meta=meta,
        )
        if self._http_post is None:
            return _annotate_error(
                make_error_result(
                    request_id=rid,
                    frame_id=fid,
                    error_type="transport_error",
                    error="legacy VLM gateway has no http_post transport",
                    model_id=self.model_id,
                    prompt_version=self.prompt_version,
                    schema_version=self.schema_version,
                )
            )
        try:
            remote = self._http_post(payload)
        except Exception as exc:  # noqa: BLE001
            return _annotate_error(
                make_error_result(
                    request_id=rid,
                    frame_id=fid,
                    error_type="transport_error",
                    error=str(exc),
                    model_id=self.model_id,
                    prompt_version=self.prompt_version,
                    schema_version=self.schema_version,
                )
            )
        return convert_legacy_analyze_response(
            remote,
            request_id=rid,
            frame_id=fid,
            default_model_id=self.model_id,
            prompt_version=self.prompt_version,
            schema_version=self.schema_version,
        )
