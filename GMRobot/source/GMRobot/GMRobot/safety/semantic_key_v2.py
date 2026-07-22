"""Stable semantic_key_v2 (canonical JSON + SHA-256; no free-text hint/explanation)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

SEMANTIC_KEY_VERSION_V2 = "semantic_key_v2"


def _canon_entity(label: Any) -> str:
    from GMRobot.vlm.temporal_evidence import canonicalize_entity

    return canonicalize_entity(label)


def build_semantic_key_v2(
    *,
    fused_risk_type: str,
    recommended_action: str,
    canonical_entity: str,
    target_container: str,
    task_phase: str,
    motion_bucket: str,
) -> dict[str, Any]:
    """Return versioned key material. semantic_key is SHA-256 of canonical JSON."""
    payload = {
        "fused_risk_type": str(fused_risk_type or "").strip().lower(),
        "recommended_action": str(recommended_action or "").strip().lower(),
        "canonical_entity": _canon_entity(canonical_entity),
        "target_container": str(target_container or "unknown").strip().lower() or "unknown",
        "task_phase": str(task_phase or "unknown").strip().lower() or "unknown",
        "motion_bucket": str(motion_bucket or "none").strip() or "none",
    }
    canonical_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return {
        "semantic_key_version": SEMANTIC_KEY_VERSION_V2,
        "semantic_key_payload": payload,
        "semantic_key_canonical_json": canonical_json,
        "semantic_key": digest,
    }
