"""five_stage_safety_v3_temporal_directive prompt construction (V1-D4C).

Identical to prompt v2 except for an explicit evidence-trust directive.
D4B ablation showed the v2 contract presents temporal evidence as data with
no usage instruction and the VLM ignores it entirely (static@0.70 across all
evidence variants); adding this directive unlocked dynamic@0.90.

SAFETY COUPLING: the directive makes the VLM trust any evidence marked
valid=true, including confidently-drifted tracks (D3C). Prompt v3 must only
be used on evidence that has passed drift rejection (temporal_evidence
``drift_suspect`` / track_drift.assess_box_drift).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .prompt_v2 import PROMPT_PREAMBLE, _SECRET_PAT
from .task_context import TaskSemanticContext
from .temporal_evidence import TemporalTrackEvidence
from .versions import (
    PROMPT_VERSION_V2_TEMPORAL,
    PROMPT_VERSION_V3_TEMPORAL,
    SCHEMA_VERSION_V2,
)

# Wording frozen to match the D4B V6 probe exactly (comparability).
EVIDENCE_TRUST_DIRECTIVE = (
    "\n\nIMPORTANT OVERRIDE-SAFE RULE: temporal_track_evidence is produced by a"
    " separate verified motion tracker. If temporal_track_evidence.valid is true"
    " and speed_px_s >= 10, a real object in the scene IS moving even if a single"
    " image cannot show motion; you must then classify risk_type as dynamic and"
    " set risk_confidence accordingly."
)

# v3 keeps the directive at the very end of the prompt (after the evidence
# JSON block) — the exact placement validated by the D4B V6 probe.
PROMPT_PREAMBLE_V3 = PROMPT_PREAMBLE.replace(
    PROMPT_VERSION_V2_TEMPORAL, PROMPT_VERSION_V3_TEMPORAL
)


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_temporal_prompt_v3(
    *,
    task_context: TaskSemanticContext | None,
    track_evidence: TemporalTrackEvidence | None,
) -> tuple[str, str]:
    """Return (prompt_text, prompt_sha256). Deterministic serialization."""
    tc = (task_context or TaskSemanticContext()).to_dict()
    for k, v in list(tc.items()):
        if isinstance(v, str) and ("/" in v or "\\" in v):
            tc[k] = "unknown"

    if track_evidence is None:
        te: dict[str, Any] = {"valid": False, "evidence_source": "none", "present": False}
    else:
        te = track_evidence.to_dict()
        te["present"] = True
        te.pop("raw_session_id", None)

    prompt = (
        PROMPT_PREAMBLE_V3
        + "\n\nStructuredTaskSemanticContext(JSON):\n"
        + _safe_json(tc)
        + "\n\nPreviousFrameTemporalTrackEvidence(JSON):\n"
        + _safe_json(te)
        + "\n"
        + EVIDENCE_TRUST_DIRECTIVE
    )
    if _SECRET_PAT.search(prompt):
        raise ValueError("prompt_v3 contains forbidden secret/path/session patterns")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return prompt, digest
