#!/usr/bin/env python3
"""Qwen2.5-VL FastAPI service with strict five-stage schema (V0-A)."""

from __future__ import annotations

import base64
import io
import os
import sys
import uuid
from pathlib import Path
from typing import Any

_SRC_LEAF = Path(__file__).resolve().parents[2] / "source" / "GMRobot" / "GMRobot"
if str(_SRC_LEAF) not in sys.path:
    sys.path.insert(0, str(_SRC_LEAF))

from vlm.schema import PROMPT_VERSION, SCHEMA_VERSION  # noqa: E402
from vlm.service_handlers import analyze_request_dict  # noqa: E402

try:
    from fastapi import FastAPI
    from pydantic import BaseModel, Field
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "fastapi/pydantic/PIL required to run vlm_service.py; "
        "offline tests use vlm.service_handlers directly"
    ) from exc

app = FastAPI(title="GM-SafePick VLM", version="0.2.0-v0a")

MODEL_ID = os.environ.get("VLM_MODEL_ID", "Qwen2.5-VL-7B-Instruct-awq")
USE_STUB = os.environ.get("VLM_STUB", "0") == "1"
_model = None
_processor = None


class AnalyzeRequest(BaseModel):
    model_id: str = MODEL_ID
    prompt: str = ""
    image_b64: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    frame_id: str | None = None
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION


def _load_model():
    global _model, _processor
    if _model is not None:
        return
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
    import torch

    model_name = os.environ.get("VLM_HF_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
    _processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
    _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    _model.eval()


def _run_model(req: dict[str, Any]) -> str:
    _load_model()
    raw_bytes = base64.b64decode(req["image_b64"])
    image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    prompt = req.get("prompt") or (
        "Analyze robot workspace human-safety risks. "
        "Reply with ONLY JSON containing: scene_summary, keywords (list), "
        "risk_type (static|dynamic|functional|none), risk_confidence (0-1), "
        "affected_entities (list), predicted_consequence, prediction_horizon_s, "
        "explanation, suggested_action (continue|slow_down|stop|replan|alert), "
        "spatial_hint (left|right|above|retreat|none)."
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    text = _processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = _processor(text=[text], images=[image], return_tensors="pt").to(_model.device)
    generated = _model.generate(**inputs, max_new_tokens=256)
    return _processor.batch_decode(generated, skip_special_tokens=True)[0]


@app.get("/health")
def health():
    gpu_ok = False
    try:
        import torch

        gpu_ok = torch.cuda.is_available()
    except Exception:
        pass
    return {
        "ok": True,
        "model_id": MODEL_ID,
        "stub": USE_STUB,
        "gpu": gpu_ok,
        "loaded": _model is not None and not USE_STUB,
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
    }


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    payload = req.model_dump()
    payload.setdefault("request_id", str(uuid.uuid4()))
    payload.setdefault("frame_id", str(uuid.uuid4()))
    return analyze_request_dict(
        payload,
        use_stub=USE_STUB,
        model_id_default=MODEL_ID,
        run_model=None if USE_STUB else _run_model,
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("VLM_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
