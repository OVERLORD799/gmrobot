"""Perception client — GDINO + SAM2 remote backend (Phase 3b / S9 MVP)."""

from __future__ import annotations

import base64
import io
import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image


CONTRACT_MODE_CANONICAL = "canonical_v0a"
CONTRACT_MODE_LEGACY = "legacy_v2"
_VALID_CONTRACT_MODES = frozenset({CONTRACT_MODE_CANONICAL, CONTRACT_MODE_LEGACY})


@dataclass
class PerceptionClientConfig:
    backend: str = "remote_http"
    base_url: str = "http://127.0.0.1:18082"
    endpoint: str = "/ground"
    track_endpoint: str = "/track"
    health_endpoint: str = "/health"
    text_prompt: str = "gloved hand . robot gripper"
    box_threshold: float = 0.2
    text_threshold: float = 0.25
    max_detections: int = 10
    run_sam2: bool = True
    timeout_s: float = 30.0
    track_target_label: str = "hand"
    track_re_detect_every_n: int = 100
    track_dt_s: float = 0.02
    # Explicit protocol mode — never auto-switch from health.
    contract_mode: str = CONTRACT_MODE_CANONICAL


@dataclass
class PerceptionTrackSession:
    """Client-side SAM2 /track session state (mirrors server session_id)."""

    session_id: str | None = None
    frame_index: int = 0
    last_center_xy: tuple[float, float] | None = None
    last_frame_index: int | None = None

    def reset(self) -> None:
        self.session_id = None
        self.frame_index = 0
        self.last_center_xy = None
        self.last_frame_index = None


class PerceptionClient:
    """HTTP client for gm-ai-server perception-service (GDINO + SAM2)."""

    def __init__(self, config: PerceptionClientConfig | None = None):
        self.config = config or PerceptionClientConfig()
        mode = str(self.config.contract_mode or CONTRACT_MODE_CANONICAL).strip()
        if mode not in _VALID_CONTRACT_MODES:
            raise ValueError(
                f"contract_mode must be one of {sorted(_VALID_CONTRACT_MODES)}, got {mode!r}"
            )
        self.config.contract_mode = mode
        self._legacy_gateway = None
        if mode == CONTRACT_MODE_LEGACY:
            from .legacy_gateway import LegacyPerceptionGateway

            self._legacy_gateway = LegacyPerceptionGateway(
                http_post=self._legacy_http_post,
                box_threshold=self.config.box_threshold,
                text_threshold=self.config.text_threshold,
                max_detections=self.config.max_detections,
                run_sam2=self.config.run_sam2,
            )

    def _legacy_http_post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", endpoint, body=body)

    def legacy_track_callback(self, rgb: np.ndarray, **kwargs: Any) -> dict[str, Any]:
        """Worker-facing stateful track callback (legacy contract_mode only)."""
        if self._legacy_gateway is None:
            raise RuntimeError("legacy_track_callback requires contract_mode=legacy_v2")
        return self._legacy_gateway.track(
            image_b64=self._frame_to_b64(rgb),
            **kwargs,
        )

    @classmethod
    def from_yaml(cls, path: str) -> PerceptionClient:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(
            PerceptionClientConfig(
                **{k: v for k, v in raw.items() if hasattr(PerceptionClientConfig, k)}
            )
        )

    def _url(self, endpoint: str) -> str:
        base = self.config.base_url.rstrip("/")
        ep = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{base}{ep}"

    def health_check(self) -> dict[str, Any]:
        """GET /health — returns JSON or error dict on failure."""
        return self._request_json("GET", self.config.health_endpoint, body=None)

    @staticmethod
    def _frame_to_b64(rgb: np.ndarray) -> str:
        """Encode a numpy image (H,W,C) or batch to base64 PNG."""
        if rgb.ndim == 3:
            frame = rgb
        elif rgb.ndim == 2:
            # Grayscale — replicate to 3-channel for PNG encoding.
            frame = np.stack([rgb] * 3, axis=-1)
        else:
            frame = rgb[0]
            if frame.ndim == 2:
                frame = np.stack([frame] * 3, axis=-1)
        buf = io.BytesIO()
        Image.fromarray(frame.astype(np.uint8)).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def ground(
        self,
        rgb: np.ndarray,
        *,
        text_prompt: str | None = None,
        keywords: list[str] | None = None,
        box_threshold: float | None = None,
        run_sam2: bool | None = None,
        meta: dict[str, Any] | None = None,
        request_id: str | None = None,
        frame_id: str | None = None,
        allow_default_prompt: bool = False,
    ) -> dict[str, Any]:
        """POST /ground with base64 PNG, keywords, and text prompt.

        Five-stage shadow must pass ``keywords`` from VLM. When keywords are
        empty and ``allow_default_prompt`` is False, returns an explicit skip
        without using unrelated default categories.
        """
        from .schema import keywords_to_text_prompt, normalize_keywords

        kw = normalize_keywords(keywords)
        meta_out = dict(meta or {})
        if request_id:
            meta_out.setdefault("request_id", request_id)
        if frame_id:
            meta_out.setdefault("frame_id", frame_id)

        if not kw and not allow_default_prompt and text_prompt is None:
            return {
                "ok": True,
                "request_id": str(request_id or meta_out.get("request_id") or ""),
                "frame_id": str(frame_id or meta_out.get("frame_id") or ""),
                "detections": [],
                "keyword_detection_map": {},
                "perception_status": "skipped_no_keywords",
                "latency_ms": 0.0,
            }

        if self._legacy_gateway is not None:
            parent = str(meta_out.get("parent_request_id") or request_id or "")
            return self._legacy_gateway.ground(
                image_b64=self._frame_to_b64(rgb),
                keywords=kw,
                request_id=str(request_id or meta_out.get("request_id") or ""),
                frame_id=str(frame_id or meta_out.get("frame_id") or ""),
                parent_request_id=parent,
                run_sam2=run_sam2,
                meta=meta_out,
                allow_default_prompt=allow_default_prompt,
            )

        if text_prompt is not None:
            prompt = text_prompt
        elif kw:
            prompt = keywords_to_text_prompt(kw)
        elif allow_default_prompt:
            prompt = self.config.text_prompt
        else:
            prompt = ""

        payload: dict[str, Any] = {
            "text_prompt": prompt,
            "keywords": kw,
            "image_b64": self._frame_to_b64(rgb),
            "box_threshold": (
                box_threshold if box_threshold is not None else self.config.box_threshold
            ),
            "confidence_threshold": (
                box_threshold if box_threshold is not None else self.config.box_threshold
            ),
            "run_sam2": run_sam2 if run_sam2 is not None else self.config.run_sam2,
            "meta": meta_out,
            "request_id": request_id or meta_out.get("request_id"),
            "frame_id": frame_id or meta_out.get("frame_id"),
        }
        return self._request_json("POST", self.config.endpoint, body=payload)

    def track_init(
        self,
        rgb: np.ndarray,
        *,
        box_xyxy: list[float] | None = None,
        text_prompt: str | None = None,
        box_threshold: float | None = None,
        target_label: str | None = None,
        re_detect_every_n: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /track action=init — seed SAM2 video state from bbox or GDINO prompt."""
        init: dict[str, Any] = {
            "target_label": target_label if target_label is not None else self.config.track_target_label,
            "text_prompt": text_prompt if text_prompt is not None else self.config.text_prompt,
            "box_threshold": (
                box_threshold if box_threshold is not None else self.config.box_threshold
            ),
            "re_detect_every_n": (
                re_detect_every_n
                if re_detect_every_n is not None
                else self.config.track_re_detect_every_n
            ),
        }
        if box_xyxy is not None:
            init["box_xyxy"] = box_xyxy
        payload: dict[str, Any] = {
            "action": "init",
            "frame_index": 0,
            "image_b64": self._frame_to_b64(rgb),
            "init": init,
            "meta": meta or {},
        }
        return self._request_json("POST", self.config.track_endpoint, body=payload)

    def track_step(
        self,
        rgb: np.ndarray,
        session_id: str,
        *,
        frame_index: int,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /track action=step — propagate SAM2 mask/bbox to the next frame."""
        payload: dict[str, Any] = {
            "action": "step",
            "session_id": session_id,
            "frame_index": frame_index,
            "image_b64": self._frame_to_b64(rgb),
            "meta": meta or {},
        }
        return self._request_json("POST", self.config.track_endpoint, body=payload)

    def track_frame(
        self,
        rgb: np.ndarray,
        session: PerceptionTrackSession | None = None,
        *,
        box_xyxy: list[float] | None = None,
        text_prompt: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], PerceptionTrackSession]:
        """Advance or start a /track session; returns (response, updated session)."""
        state = session or PerceptionTrackSession()
        if state.session_id is None:
            result = self.track_init(
                rgb,
                box_xyxy=box_xyxy,
                text_prompt=text_prompt,
                meta=meta,
            )
            if result.get("ok") is False or result.get("error"):
                return result, state
            state.session_id = str(result.get("session_id", "") or "")
            state.frame_index = int(result.get("frame_index", 0) or 0)
        else:
            next_index = state.frame_index + 1
            result = self.track_step(
                rgb,
                state.session_id,
                frame_index=next_index,
                meta=meta,
            )
            if result.get("ok") is False or result.get("error"):
                # Reset session on failure so the next call re-inits
                state.reset()
                return result, state
            state.frame_index = int(result.get("frame_index", next_index) or next_index)
            if result.get("session_id"):
                state.session_id = str(result["session_id"])
        return result, state

    @staticmethod
    def pick_primary_track(
        result: dict[str, Any],
        *,
        target_label: str = "hand",
    ) -> dict[str, Any] | None:
        """Return the best-matching track dict from a /track response."""
        tracks = result.get("tracks") or []
        if not tracks:
            return None
        label_lower = target_label.lower()
        labeled = [
            t
            for t in tracks
            if label_lower in str(t.get("label", "")).lower()
        ]
        pool = labeled or tracks
        return max(pool, key=lambda t: float(t.get("sam2_score", t.get("score", 0)) or 0))

    @staticmethod
    def enrich_track_kinematics(
        track: dict[str, Any],
        *,
        session: PerceptionTrackSession,
        dt_s: float,
    ) -> dict[str, Any]:
        """Fill speed/direction when the server omits velocity fields."""
        enriched = dict(track)
        center = track.get("center_xy")
        if center is None and track.get("box_xyxy"):
            x1, y1, x2, y2 = track["box_xyxy"]
            center = [(float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0]
            enriched["center_xy"] = center
        if center is None:
            return enriched

        cx, cy = float(center[0]), float(center[1])
        if track.get("velocity_xy_px_s") is not None:
            vx, vy = track["velocity_xy_px_s"]
        elif track.get("velocity_xy") is not None:
            vx, vy = track["velocity_xy"]
        elif (
            session.last_center_xy is not None
            and session.last_frame_index is not None
            and session.frame_index > session.last_frame_index
        ):
            steps = session.frame_index - session.last_frame_index
            elapsed = max(steps * dt_s, 1e-6)
            lx, ly = session.last_center_xy
            vx = (cx - lx) / elapsed
            vy = (cy - ly) / elapsed
            enriched["velocity_xy_px_s"] = [vx, vy]
        else:
            vx = vy = 0.0

        speed = track.get("speed_px_s")
        if speed in (None, ""):
            speed = math.hypot(float(vx), float(vy))
            enriched["speed_px_s"] = speed
        direction = track.get("direction_deg")
        if direction in (None, "") and (vx or vy):
            enriched["direction_deg"] = math.degrees(math.atan2(vy, vx))
        session.last_center_xy = (cx, cy)
        session.last_frame_index = session.frame_index
        return enriched

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
        except (URLError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"JSON decode error: {exc}"}
