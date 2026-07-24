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

# D5A: deterministic evidence-gated dynamic rule (path B). The dynamic
# detection decision is sunk into auditable code; the VLM is annotation-only
# on this path and cannot veto or mint the trigger.
EVIDENCE_GATED_RULE_VERSION_V1 = "evidence_gated_dynamic_rule_v1"

# D8A: rule v2 replaces the falsified motion components of v1 (last-frame
# instantaneous speed F10, D4A size-band drift gate F9) with the D7B
# window-aggregate translation verdict; identity/quality gates are retained.
EVIDENCE_GATED_RULE_VERSION_V2_WINDOW = "evidence_gated_dynamic_rule_v2_window"

# D9B: v2.1 adds the depth path (scale_rate + aspect_change, D9A calibration)
# as a second trigger channel alongside window translation.
EVIDENCE_GATED_RULE_VERSION_V2_1_DEPTH = "evidence_gated_dynamic_rule_v2_1_depth"

ALLOWED_PROMPT_VERSIONS = frozenset(
    {PROMPT_VERSION_V1, PROMPT_VERSION_V2_TEMPORAL, PROMPT_VERSION_V3_TEMPORAL}
)
ALLOWED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION_V1, SCHEMA_VERSION_V2})
