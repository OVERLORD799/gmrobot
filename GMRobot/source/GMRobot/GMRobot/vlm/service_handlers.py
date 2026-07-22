"""VLM analyze handlers without FastAPI (for offline contract tests)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .schema import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    SchemaValidationError,
    make_error_result,
    parse_model_text_to_success,
)


def analyze_request_dict(
    req: dict[str, Any],
    *,
    use_stub: bool,
    model_id_default: str,
    run_model: Any | None = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    request_id = str(req.get("request_id") or (req.get("meta") or {}).get("request_id") or uuid.uuid4())
    frame_id = str(req.get("frame_id") or (req.get("meta") or {}).get("frame_id") or uuid.uuid4())
    model_id = str(req.get("model_id") or model_id_default)
    prompt_version = str(req.get("prompt_version") or PROMPT_VERSION)
    schema_version = str(req.get("schema_version") or SCHEMA_VERSION)

    if use_stub:
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type="stub_mode",
            error="VLM_STUB=1; stub does not fabricate structured risk outputs",
            model_id=model_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            synthetic=True,
            latency_ms=(time.monotonic() - t0) * 1000.0,
        )

    if not req.get("image_b64"):
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type="schema_error",
            error="empty image_b64",
            model_id=model_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            latency_ms=(time.monotonic() - t0) * 1000.0,
        )

    if run_model is None:
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type="backend_unavailable",
            error="no model runner configured",
            model_id=model_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            latency_ms=(time.monotonic() - t0) * 1000.0,
        )

    try:
        out_text = run_model(req)
    except Exception as exc:  # noqa: BLE001
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type="backend_unavailable",
            error=f"inference failed: {exc}",
            model_id=model_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            latency_ms=(time.monotonic() - t0) * 1000.0,
        )

    latency_ms = (time.monotonic() - t0) * 1000.0
    try:
        return parse_model_text_to_success(
            out_text,
            request_id=request_id,
            frame_id=frame_id,
            model_id=model_id,
            latency_ms=latency_ms,
            prompt_version=prompt_version,
            schema_version=schema_version,
        )
    except SchemaValidationError as exc:
        return make_error_result(
            request_id=request_id,
            frame_id=frame_id,
            error_type=exc.error_type,
            error=str(exc),
            model_id=model_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            raw_response=str(out_text),
            latency_ms=latency_ms,
        )
