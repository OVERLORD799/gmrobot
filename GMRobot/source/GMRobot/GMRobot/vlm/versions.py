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

ALLOWED_PROMPT_VERSIONS = frozenset({PROMPT_VERSION_V1, PROMPT_VERSION_V2_TEMPORAL})
ALLOWED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})
