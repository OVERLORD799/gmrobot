"""Server-side /track endpoint for gm-ai-server perception-service (W5).

Drop-in module — copy to ``/root/gpufree-data/perception-service/`` and import
in ``app.py`` to add the ``/track`` FastAPI route.

API contract: [AI 部署 §7.6](../docs/GM-SafePick_AI服务器部署.md#76-http-apigmrobot-客户端草案)
Client:  [GMRobot/perception/client.py](../GMRobot/perception/client.py) ``PerceptionClient.track_frame()``
"""

from __future__ import annotations

import base64
import io
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import torch
from PIL import Image


# ---------------------------------------------------------------------------
# Session state — one per active SAM2 video predictor
# ---------------------------------------------------------------------------

@dataclass
class TrackSession:
    session_id: str
    frame_index: int = 0
    # SAM2 predictor state (lazy-init on first init frame)
    predictor: Any = None
    inference_state: Any = None
    # GDINO model reference (shared across sessions via app state)
    gdino_model: Any = None
    gdino_processor: Any = None
    # Config carried from init
    target_label: str = "hand"
    text_prompt: str = "gloved hand . robot gripper"
    box_threshold: float = 0.2
    re_detect_every_n: int = 100
    # Last known box for re-detection seeding
    last_box_xyxy: list[float] | None = None

    @property
    def needs_re_detect(self) -> bool:
        if self.re_detect_every_n <= 0:
            return False
        return self.frame_index > 0 and self.frame_index % self.re_detect_every_n == 0


# Global session store (module-level; in production use a TTL cache or DB)
_SESSIONS: dict[str, TrackSession] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64_to_image(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return np.array(img)


def _box_xyxy_to_xywh(box_xyxy: list[float]) -> list[float]:
    x1, y1, x2, y2 = box_xyxy
    return [x1, y1, x2 - x1, y2 - y1]


def _sam2_mask_to_box(mask: np.ndarray, pad: float = 4.0) -> list[float] | None:
    """Extract bounding box from a SAM2 binary mask."""
    ys, xs = np.where(mask > 0.5)
    if len(xs) == 0:
        return None
    x1, x2 = float(xs.min()), float(xs.max())
    y1, y2 = float(ys.min()), float(ys.max())
    w, h = x2 - x1, y2 - y1
    return [max(0, x1 - pad), max(0, y1 - pad),
            x2 + pad, y2 + pad]


def _box_center(box_xyxy: list[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box_xyxy
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


# ---------------------------------------------------------------------------
# GDINO detection (shared helper — extracts one box matching target_label)
# ---------------------------------------------------------------------------

def _gdino_detect(
    image: np.ndarray,
    text_prompt: str,
    box_threshold: float,
    target_label: str,
    gdino_model,
    gdino_processor,
    device: str = "cuda",
) -> dict[str, Any] | None:
    """Run GDINO on a single image; return the best-matching detection or None."""
    try:
        from PIL import Image as PILImage
        pil = PILImage.fromarray(image.astype(np.uint8))
        inputs = gdino_processor(images=pil, text=text_prompt, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = gdino_model(**inputs)
        # Simple post-process: take top-1 box
        # NOTE: adjust post-processing to match your GDINO wrapper.
        # This is a minimal reference implementation.
        logits = outputs.logits[0] if hasattr(outputs, "logits") else None
        boxes = outputs.pred_boxes[0] if hasattr(outputs, "pred_boxes") else None
        if logits is None or boxes is None or len(boxes) == 0:
            return None
        probs = torch.sigmoid(logits).cpu().numpy()
        best_idx = int(probs.argmax())
        if float(probs[best_idx]) < box_threshold:
            return None
        box = boxes[best_idx].cpu().tolist()  # [cx, cy, w, h] in normalized coords
        h, w = image.shape[:2]
        cx, cy, bw, bh = box
        x1 = (cx - bw / 2) * w
        y1 = (cy - bh / 2) * h
        x2 = (cx + bw / 2) * w
        y2 = (cy + bh / 2) * h
        return {
            "label": target_label,
            "score": float(probs[best_idx]),
            "box_xyxy": [max(0, x1), max(0, y1), min(w, x2), min(h, y2)],
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SAM2 init / propagate (reference — adapt to your SAM2 wrapper)
# ---------------------------------------------------------------------------

def _sam2_init_state(image: np.ndarray, box_xyxy: list[float], predictor) -> Any:
    """Create SAM2 inference state from first frame + prompt box."""
    box_xywh = _box_xyxy_to_xywh(box_xyxy)
    # SAM2 expects: [np.array(H,W,3), {prompts}]
    inference_state = predictor.init_state(image)
    # Add new prompt on frame 0
    predictor.add_new_prompt(
        inference_state,
        frame_idx=0,
        obj_id=0,
        bbox=box_xywh,
    )
    return inference_state


def _sam2_propagate(
    image: np.ndarray,
    session: TrackSession,
) -> dict[str, Any] | None:
    """Propagate SAM2 to the next frame; return track dict or None."""
    try:
        predictor = session.predictor
        inference_state = session.inference_state
        # Propagate
        outputs = predictor.propagate_in_video(
            inference_state,
            frame_idx=session.frame_index,
        )
        # Extract mask
        mask = None
        if outputs and "segmentation" in outputs:
            seg = outputs["segmentation"]
            if isinstance(seg, torch.Tensor):
                mask = seg.cpu().numpy()
            elif isinstance(seg, np.ndarray):
                mask = seg

        if mask is None or mask.sum() == 0:
            return None

        # Mask -> box
        box_xyxy = _sam2_mask_to_box(mask)
        if box_xyxy is None:
            return None

        session.last_box_xyxy = box_xyxy
        cx, cy = _box_center(box_xyxy)
        mask_area = int(mask.sum())

        return {
            "track_id": 0,
            "label": session.target_label,
            "box_xyxy": box_xyxy,
            "center_xy": [cx, cy],
            "mask_area": mask_area,
            "sam2_score": 0.99,  # SAM2 doesn't output per-frame scores
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# FastAPI route handler (add to perception-service app.py)
# ---------------------------------------------------------------------------

def register_track_endpoint(app, gdino_model=None, gdino_processor=None,
                            sam2_predictor=None, device: str = "cuda"):
    """Register POST /track on a FastAPI app instance.

    Call from ``app.py`` after models are loaded::

        from perception_track_endpoint import register_track_endpoint
        register_track_endpoint(app, gdino_model, gdino_processor, sam2_predictor)
    """
    from fastapi import Request

    @app.post("/track")
    async def track(request: Request):
        import time as _time
        t0 = _time.monotonic()
        try:
            body = await request.json()
        except Exception:
            return {"ok": False, "error": "invalid JSON"}

        action = str(body.get("action", "init"))
        meta = body.get("meta", {})

        # --- init ---
        if action == "init":
            b64 = body.get("image_b64", "")
            if not b64:
                return {"ok": False, "error": "image_b64 required"}
            try:
                image = _b64_to_image(b64)
            except Exception as exc:
                return {"ok": False, "error": f"image decode error: {exc}"}

            init_cfg = body.get("init", {})
            session_id = str(uuid.uuid4())
            session = TrackSession(
                session_id=session_id,
                frame_index=0,
                predictor=sam2_predictor,
                gdino_model=gdino_model,
                gdino_processor=gdino_processor,
                target_label=str(init_cfg.get("target_label", "hand")),
                text_prompt=str(init_cfg.get("text_prompt", "gloved hand . robot gripper")),
                box_threshold=float(init_cfg.get("box_threshold", 0.2)),
                re_detect_every_n=int(init_cfg.get("re_detect_every_n", 100)),
            )

            # Get initial box: explicit box_xyxy > GDINO detection
            box_xyxy = init_cfg.get("box_xyxy")
            detection = None
            if box_xyxy is None and gdino_model is not None:
                detection = _gdino_detect(
                    image, session.text_prompt, session.box_threshold,
                    session.target_label, gdino_model, gdino_processor, device,
                )
                if detection is not None:
                    box_xyxy = detection["box_xyxy"]

            if box_xyxy is None:
                return {
                    "ok": False,
                    "error": "no box_xyxy provided and GDINO detection failed",
                    "latency_ms": (_time.monotonic() - t0) * 1000,
                }

            session.last_box_xyxy = list(box_xyxy)

            # Init SAM2
            if sam2_predictor is not None:
                try:
                    session.inference_state = _sam2_init_state(image, box_xyxy, sam2_predictor)
                except Exception as exc:
                    return {
                        "ok": False,
                        "error": f"SAM2 init error: {exc}",
                        "latency_ms": (_time.monotonic() - t0) * 1000,
                    }

            cx, cy = _box_center(box_xyxy)
            track_data = {
                "track_id": 0,
                "label": session.target_label,
                "box_xyxy": list(box_xyxy),
                "center_xy": [cx, cy],
                "mask_area": 0,
                "sam2_score": float(detection.get("score", 0.99)) if detection else 0.99,
            }

            _SESSIONS[session_id] = session

            return {
                "ok": True,
                "session_id": session_id,
                "frame_index": 0,
                "tracks": [track_data],
                "re_detected": detection is not None,
                "latency_ms": (_time.monotonic() - t0) * 1000,
                "meta": meta,
            }

        # --- step ---
        elif action == "step":
            session_id = str(body.get("session_id", ""))
            session = _SESSIONS.get(session_id)
            if session is None:
                return {"ok": False, "error": f"unknown session_id: {session_id}"}

            b64 = body.get("image_b64", "")
            if not b64:
                return {"ok": False, "error": "image_b64 required"}
            try:
                image = _b64_to_image(b64)
            except Exception as exc:
                return {"ok": False, "error": f"image decode error: {exc}"}

            target_index = int(body.get("frame_index", session.frame_index + 1))
            session.frame_index = target_index

            re_detected = False

            # Re-detect periodically
            if session.needs_re_detect and gdino_model is not None:
                detection = _gdino_detect(
                    image, session.text_prompt, session.box_threshold,
                    session.target_label, gdino_model, gdino_processor, device,
                )
                if detection is not None:
                    re_detected = True
                    box_xyxy = detection["box_xyxy"]
                    session.last_box_xyxy = list(box_xyxy)
                    # Re-init SAM2 with the new box
                    if sam2_predictor is not None:
                        session.inference_state = _sam2_init_state(image, box_xyxy, sam2_predictor)

            # Propagate SAM2
            track_data = None
            if sam2_predictor is not None and session.inference_state is not None:
                track_data = _sam2_propagate(image, session)

            if track_data is None and session.last_box_xyxy is not None:
                # Fallback: return last known box
                cx, cy = _box_center(session.last_box_xyxy)
                track_data = {
                    "track_id": 0,
                    "label": session.target_label,
                    "box_xyxy": list(session.last_box_xyxy),
                    "center_xy": [cx, cy],
                    "mask_area": 0,
                    "sam2_score": 0.5,
                }

            if track_data is None:
                return {
                    "ok": False,
                    "error": "track lost",
                    "session_id": session_id,
                    "frame_index": target_index,
                    "latency_ms": (_time.monotonic() - t0) * 1000,
                }

            return {
                "ok": True,
                "session_id": session_id,
                "frame_index": target_index,
                "tracks": [track_data],
                "re_detected": re_detected,
                "latency_ms": (_time.monotonic() - t0) * 1000,
                "meta": meta,
            }

        else:
            return {"ok": False, "error": f"unknown action: {action}"}
