"""Explicit VLM/prompt/schema/fusion version constants (no silent switching)."""

from __future__ import annotations

# v1 (default / frozen path)
PROMPT_VERSION_V1 = "five_stage_safety_v1"
SCHEMA_VERSION_V1 = "five_stage_vlm_v1"

# v2 temporal (must be explicitly enabled)
PROMPT_VERSION_V2_TEMPORAL = "five_stage_safety_v2_temporal"
SCHEMA_VERSION_V2 = "five_stage_vlm_v2"
FUSION_VERSION_V1 = "five_stage_temporal_fusion_v1"
SEMANTIC_KEY_VERSION_V2 = "semantic_key_v2"

# v3 temporal + evidence-trust directive (D4B finding: v2 renders evidence as
# data with no usage instruction; the model ignores it entirely).
# MUST be deployed together with drift rejection (track_drift / D4A).
PROMPT_VERSION_V3_TEMPORAL = "five_stage_safety_v3_temporal_directive"

ALLOWED_PROMPT_VERSIONS = frozenset(
    {PROMPT_VERSION_V1, PROMPT_VERSION_V2_TEMPORAL, PROMPT_VERSION_V3_TEMPORAL}
)
ALLOWED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})
