#!/usr/bin/env python3
"""Qwen2.5-VL-7B AWQ FastAPI service for gm-ai-server (Phase 3a MVP)."""

from __future__ import annotations

import base64
import io
import os
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from PIL import Image

app = FastAPI(title="GM-SafePick VLM", version="0.1.0")

MODEL_ID = os.environ.get("VLM_MODEL_ID", "Qwen2.5-VL-7B-Instruct-awq")
USE_STUB = os.environ.get("VLM_STUB", "0") == "1"
_model = None
_processor = None


class AnalyzeRequest(BaseModel):
    model_id: str = MODEL_ID
    prompt: str = ""
    image_b64: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


def _load_model():
    global _model, _processor
    if _model is not None:
        return
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
    import torch

    model_name = os.environ.get(
        "VLM_HF_MODEL",
        "Qwen/Qwen2.5-VL-7B-Instruct",
    )
    _processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
    _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    _model.eval()


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
        "loaded": _model is not None or USE_STUB,
    }


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    t0 = time.monotonic()
    if USE_STUB or not req.image_b64:
        return {
            "ok": True,
            "model_id": req.model_id,
            "vlm_risk_type": "static",
            "vlm_severity": "medium",
            "vlm_suggested_action": "slow_down",
            "vlm_explanation": "stub response (VLM_STUB=1 or empty image)",
            "vlm_stage": 1,
            "vlm_latency_ms": (time.monotonic() - t0) * 1000.0,
        }

    _load_model()
    raw = base64.b64decode(req.image_b64)
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    prompt = req.prompt or (
        "Describe human safety risks in this robot workspace scene. "
        "Reply JSON with risk_type, severity, suggested_action."
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
    generated = _model.generate(**inputs, max_new_tokens=128)
    out_text = _processor.batch_decode(generated, skip_special_tokens=True)[0]

    return {
        "ok": True,
        "model_id": req.model_id,
        "vlm_risk_type": "static",
        "vlm_severity": "medium",
        "vlm_suggested_action": "slow_down",
        "vlm_explanation": out_text[-512:],
        "vlm_stage": 1,
        "vlm_latency_ms": (time.monotonic() - t0) * 1000.0,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("VLM_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
