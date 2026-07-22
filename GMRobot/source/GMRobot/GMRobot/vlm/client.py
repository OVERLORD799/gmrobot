"""VLM client — single Qwen remote backend (Phase 3 MVP + V0-A schema)."""

from __future__ import annotations

import base64
import io
import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

from .schema import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    coerce_analyze_response,
    make_error_result,
)


CONTRACT_MODE_CANONICAL = "canonical_v0a"
CONTRACT_MODE_LEGACY = "legacy_v2"
_VALID_CONTRACT_MODES = frozenset({CONTRACT_MODE_CANONICAL, CONTRACT_MODE_LEGACY})


@dataclass
class VLMClientConfig:
    backend: str = "remote_http"
    base_url: str = "http://127.0.0.1:18080"
    endpoint: str = "/analyze"
    health_endpoint: str = "/health"
    model_id: str = "Qwen2.5-VL-7B-Instruct-awq"
    timeout_s: float = 5.0
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION
    # Explicit protocol mode — never auto-switch from health.
    contract_mode: str = CONTRACT_MODE_CANONICAL


class VLMClient:
    """HTTP client for dedicated Qwen VLM server.

    Network I/O is synchronous and must only run on a shadow worker thread,
    never on the 50 Hz control loop.
    """

    def __init__(self, config: VLMClientConfig | None = None):
        self.config = config or VLMClientConfig()
        mode = str(self.config.contract_mode or CONTRACT_MODE_CANONICAL).strip()
        if mode not in _VALID_CONTRACT_MODES:
            raise ValueError(
                f"contract_mode must be one of {sorted(_VALID_CONTRACT_MODES)}, got {mode!r}"
            )
        self.config.contract_mode = mode

    @classmethod
    def from_yaml(cls, path: str) -> VLMClient:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(
            VLMClientConfig(**{k: v for k, v in raw.items() if hasattr(VLMClientConfig, k)})
        )

    def _url(self, endpoint: str) -> str:
        base = self.config.base_url.rstrip("/")
        ep = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{base}{ep}"

    def health_check(self) -> dict[str, Any]:
        return self._request_json("GET", self.config.health_endpoint, body=None)

    @staticmethod
    def _frame_to_b64(rgb: np.ndarray) -> str:
        if rgb.ndim == 3:
            frame = rgb
        elif rgb.ndim == 2:
            frame = np.stack([rgb] * 3, axis=-1)
        else:
            frame = rgb[0]
            if frame.ndim == 2:
                frame = np.stack([frame] * 3, axis=-1)
        buf = io.BytesIO()
        Image.fromarray(frame.astype(np.uint8)).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def analyze(
        self,
        rgb: np.ndarray,
        *,
        prompt: str = "",
        meta: dict[str, Any] | None = None,
        request_id: str | None = None,
        frame_id: str | None = None,
    ) -> dict[str, Any]:
        rid = str(request_id or uuid.uuid4())
        fid = str(frame_id or uuid.uuid4())
        if self.config.contract_mode == CONTRACT_MODE_LEGACY:
            return self._analyze_legacy(
                rgb, prompt=prompt, meta=meta, request_id=rid, frame_id=fid
            )
        return self._analyze_canonical(
            rgb, prompt=prompt, meta=meta, request_id=rid, frame_id=fid
        )

    def _analyze_canonical(
        self,
        rgb: np.ndarray,
        *,
        prompt: str,
        meta: dict[str, Any] | None,
        request_id: str,
        frame_id: str,
    ) -> dict[str, Any]:
        rid, fid = request_id, frame_id
        meta_out = dict(meta or {})
        meta_out.setdefault("request_id", rid)
        meta_out.setdefault("frame_id", fid)
        meta_out.setdefault("prompt_version", self.config.prompt_version)
        meta_out.setdefault("schema_version", self.config.schema_version)
        payload = {
            "model_id": self.config.model_id,
            "prompt": prompt,
            "image_b64": self._frame_to_b64(rgb),
            "meta": meta_out,
            "request_id": rid,
            "frame_id": fid,
            "prompt_version": self.config.prompt_version,
            "schema_version": self.config.schema_version,
        }
        try:
            raw = self._request_json("POST", self.config.endpoint, body=payload)
        except Exception as exc:  # noqa: BLE001 — convert to structured error
            return make_error_result(
                request_id=rid,
                frame_id=fid,
                error_type="transport_error",
                error=str(exc),
                model_id=self.config.model_id,
                prompt_version=self.config.prompt_version,
                schema_version=self.config.schema_version,
            )
        out = coerce_analyze_response(
            raw,
            request_id=rid,
            frame_id=fid,
            model_id=self.config.model_id,
        )
        out.setdefault("remote_contract", CONTRACT_MODE_CANONICAL)
        out.setdefault("id_source", "remote_or_local")
        return out

    def _analyze_legacy(
        self,
        rgb: np.ndarray,
        *,
        prompt: str,
        meta: dict[str, Any] | None,
        request_id: str,
        frame_id: str,
    ) -> dict[str, Any]:
        from .legacy_gateway import STRICT_FIVE_STAGE_PROMPT, LegacyVLMGateway

        def _post(body: dict[str, Any]) -> dict[str, Any]:
            return self._request_json("POST", self.config.endpoint, body=body)

        gateway = LegacyVLMGateway(
            http_post=_post,
            model_id=self.config.model_id,
            prompt_version=self.config.prompt_version,
            schema_version=self.config.schema_version,
            default_prompt=STRICT_FIVE_STAGE_PROMPT,
        )
        return gateway.analyze_b64(
            self._frame_to_b64(rgb),
            request_id=request_id,
            frame_id=frame_id,
            prompt=prompt or STRICT_FIVE_STAGE_PROMPT,
            meta=meta,
        )

    def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        url = self._url(endpoint)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.config.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except (URLError, OSError, TimeoutError) as exc:
            return {
                "ok": False,
                "error_type": "timeout" if "timed out" in str(exc).lower() else "transport_error",
                "error": str(exc),
            }
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "error_type": "parse_error",
                "error": f"JSON decode error: {exc}",
            }
