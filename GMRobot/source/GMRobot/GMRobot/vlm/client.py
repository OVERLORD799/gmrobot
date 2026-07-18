"""VLM client — single Qwen remote backend (Phase 3 MVP)."""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image


@dataclass
class VLMClientConfig:
    backend: str = "remote_http"
    base_url: str = "http://120.209.70.195:8080"
    endpoint: str = "/analyze"
    health_endpoint: str = "/health"
    model_id: str = "Qwen2.5-VL-7B-Instruct-awq"
    timeout_s: float = 5.0


class VLMClient:
    """HTTP client for dedicated Qwen VLM server.

    Uses synchronous ``analyze()`` with periodic refresh (every ~200 steps)
    to keep the 50 Hz control loop simple.  The ~1.5 s blocking cost per
    call is amortised over 200 steps (4 s of wall time at 50 Hz).
    """

    def __init__(self, config: VLMClientConfig | None = None):
        self.config = config or VLMClientConfig()

    @classmethod
    def from_yaml(cls, path: str) -> VLMClient:
        import yaml
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(VLMClientConfig(**{k: v for k, v in raw.items() if hasattr(VLMClientConfig, k)}))

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
        self, rgb: np.ndarray, *, prompt: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model_id": self.config.model_id, "prompt": prompt,
            "image_b64": self._frame_to_b64(rgb), "meta": meta or {},
        }
        return self._request_json("POST", self.config.endpoint, body=payload)

    def _request_json(
        self, method: str, endpoint: str, *,
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
        except (URLError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"JSON decode error: {exc}"}
