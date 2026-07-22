"""Deterministic five_stage_safety_v2_temporal prompt construction."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .task_context import TaskSemanticContext
from .temporal_evidence import TemporalTrackEvidence
from .versions import PROMPT_VERSION_V2_TEMPORAL, SCHEMA_VERSION_V2

_SECRET_PAT = re.compile(
    r"(api[_-]?key|authorization|bearer|password|secret|/home/|/opt/|session_id\s*[:=])",
    re.I,
)

PROMPT_PREAMBLE = """Analyze robot workspace human-safety risks from the image and the provided structured context.
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

Risk type definitions (mutually exclusive):
- static: static geometric / occupancy proximity risk visible in the current frame without requiring verified motion evidence.
- dynamic: approach, crossing, or motion risk that requires credible temporal motion evidence from an external tracker.
- functional: task/goal/container-state execution risk that cannot be decided from distance alone (e.g., placement target occupied).

Rules:
- Temporal track evidence below is an EXTERNAL tracker observation (SAM2), not a native visual measurement invented by you.
- Without valid motion evidence, do NOT guess risk_type=dynamic.
- Without task/goal occupancy evidence, do NOT guess risk_type=functional.
- risk_confidence is your confidence in the final safety classification (0..1).
- Output must satisfy schema_version=""" + SCHEMA_VERSION_V2 + """ and prompt_version=""" + PROMPT_VERSION_V2_TEMPORAL + """.
Do not invent legacy fields. Do not wrap the JSON in code fences."""


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_temporal_prompt_v2(
    *,
    task_context: TaskSemanticContext | None,
    track_evidence: TemporalTrackEvidence | None,
) -> tuple[str, str]:
    """Return (prompt_text, prompt_sha256). Deterministic serialization."""
    tc = (task_context or TaskSemanticContext()).to_dict()
    # Strip any accidental path-like strings
    for k, v in list(tc.items()):
        if isinstance(v, str) and ("/" in v or "\\" in v):
            tc[k] = "unknown"

    if track_evidence is None:
        te: dict[str, Any] = {"valid": False, "evidence_source": "none", "present": False}
    else:
        te = track_evidence.to_dict()
        te["present"] = True
        # Never include raw secrets
        te.pop("raw_session_id", None)

    body = {
        "prompt_version": PROMPT_VERSION_V2_TEMPORAL,
        "schema_version": SCHEMA_VERSION_V2,
        "task_semantic_context": tc,
        "temporal_track_evidence": te,
    }
    serialized = _safe_json(body)
    prompt = (
        PROMPT_PREAMBLE
        + "\n\nStructuredTaskSemanticContext(JSON):\n"
        + _safe_json(tc)
        + "\n\nPreviousFrameTemporalTrackEvidence(JSON):\n"
        + _safe_json(te)
        + "\n"
    )
    if _SECRET_PAT.search(prompt):
        # Fail closed: scrub by rebuilding without suspicious strings
        raise ValueError("prompt_v2 contains forbidden secret/path/session patterns")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    # Also hash the structured body for audit
    _ = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return prompt, digest


def assert_prompt_safe(prompt: str) -> None:
    if _SECRET_PAT.search(prompt):
        raise ValueError("unsafe prompt content")
