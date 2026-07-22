"""Offline temporal / task-context semantic fusion (pure functions; no network)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .semantic_key_v2 import build_semantic_key_v2

from GMRobot.vlm.task_context import TaskSemanticContext
from GMRobot.vlm.temporal_evidence import (
    TemporalTrackEvidence,
    canonicalize_entity,
    entities_compatible,
    validate_temporal_evidence,
    TemporalEvidenceConfig,
)
from GMRobot.vlm.versions import FUSION_VERSION_V1

MIN_CONFIDENCE = 0.85  # frozen; never lower

RISK_TYPE_SOURCE_VLM_NATIVE = "vlm_native"
RISK_TYPE_SOURCE_TEMPORAL = "temporal_fusion"
RISK_TYPE_SOURCE_TASK = "task_context_fusion"
MOTION_SOURCE_SAM2 = "sam2_track"
MOTION_SOURCE_NONE = "none"


@dataclass(frozen=True)
class FusedSemanticEvidence:
    native_risk_type: str
    native_risk_confidence: float
    fused_risk_type: str
    fused_confidence: float
    recommended_action: str
    canonical_entity: str
    task_target: str
    task_phase: str
    motion_bucket: str
    risk_type_source: str
    motion_evidence_source: str
    task_context_source: str
    fusion_rule: str
    fusion_accepted: bool
    rejection_reason: str
    fusion_version: str
    semantic_key_version: str
    semantic_key: str
    semantic_key_payload: dict[str, Any]
    synthetic: bool
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _entities_from_vlm(vlm: Mapping[str, Any]) -> list[str]:
    raw = vlm.get("affected_entities") or []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, Sequence):
        return [str(x) for x in raw]
    return []


def _primary_vlm_entity(vlm: Mapping[str, Any]) -> str:
    ents = _entities_from_vlm(vlm)
    # Prefer non-arm obstacle
    for e in ents:
        c = canonicalize_entity(e)
        if c not in ("robotic_arm", "unknown", "none"):
            return c
    if ents:
        return canonicalize_entity(ents[0])
    kws = vlm.get("keywords") or []
    for k in kws:
        c = canonicalize_entity(k)
        if c not in ("robotic_arm", "unknown", "none"):
            return c
    return "unknown"


def fuse_semantic_evidence(
    vlm: Mapping[str, Any],
    *,
    task_context: TaskSemanticContext | None = None,
    track_evidence: TemporalTrackEvidence | None = None,
    temporal_config: TemporalEvidenceConfig | None = None,
    synthetic: bool = False,
) -> FusedSemanticEvidence:
    """Fuse native VLM output with optional previous-frame track + task context.

    Never raises VLM confidence. Never invents risk_type without rule match.
    """
    tc = task_context or TaskSemanticContext()
    native_type = str(vlm.get("risk_type") or "").strip().lower()
    try:
        native_conf = float(vlm.get("risk_confidence") or 0.0)
    except (TypeError, ValueError):
        native_conf = 0.0
    action = str(vlm.get("suggested_action") or vlm.get("recommended_action") or "").strip().lower()
    entity = _primary_vlm_entity(vlm)
    motion_bucket = "none"
    motion_src = MOTION_SOURCE_NONE
    task_src = str(tc.context_source or "none")

    def _reject(reason: str, *, fused_type: str = "none", rule: str = "reject") -> FusedSemanticEvidence:
        key = build_semantic_key_v2(
            fused_risk_type=fused_type,
            recommended_action=action or "none",
            canonical_entity=entity,
            target_container=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket=motion_bucket,
        )
        return FusedSemanticEvidence(
            native_risk_type=native_type,
            native_risk_confidence=native_conf,
            fused_risk_type=fused_type,
            fused_confidence=native_conf,
            recommended_action=action,
            canonical_entity=entity,
            task_target=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket=motion_bucket,
            risk_type_source="none",
            motion_evidence_source=motion_src,
            task_context_source=task_src,
            fusion_rule=rule,
            fusion_accepted=False,
            rejection_reason=reason,
            fusion_version=FUSION_VERSION_V1,
            semantic_key_version=str(key["semantic_key_version"]),
            semantic_key=str(key["semantic_key"]),
            semantic_key_payload=dict(key["semantic_key_payload"]),
            synthetic=bool(synthetic),
            provenance={
                "vlm_ok": bool(vlm.get("ok", True)),
                "track_valid": bool(track_evidence.valid) if track_evidence else False,
            },
        )

    # Hard bans: action alone / missing conf never pass
    if action != "slow_down":
        return _reject("action_not_slow_down")

    if native_conf < MIN_CONFIDENCE:
        # Explicitly still reject even with fast track (tracker must not mint confidence)
        return _reject("native_confidence_below_threshold")

    # --- Path C: task_context_fusion (functional native + matching task) ---
    if native_type == "functional":
        if tc.target_container in ("unknown", "none"):
            return _reject("functional_target_mismatch", fused_type="functional", rule="task_context_fusion")
        if tc.task_phase in ("unknown", "none"):
            return _reject("functional_phase_mismatch", fused_type="functional", rule="task_context_fusion")
        if tc.task_goal_type not in ("place_into_container",) and tc.task_phase not in (
            "place",
            "transit",
            "approach",
        ):
            return _reject("functional_task_mismatch", fused_type="functional", rule="task_context_fusion")
        key = build_semantic_key_v2(
            fused_risk_type="functional",
            recommended_action=action,
            canonical_entity=entity,
            target_container=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket="none",
        )
        return FusedSemanticEvidence(
            native_risk_type=native_type,
            native_risk_confidence=native_conf,
            fused_risk_type="functional",
            fused_confidence=native_conf,
            recommended_action=action,
            canonical_entity=entity,
            task_target=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket="none",
            risk_type_source=RISK_TYPE_SOURCE_TASK,
            motion_evidence_source=MOTION_SOURCE_NONE,
            task_context_source=task_src,
            fusion_rule="task_context_fusion",
            fusion_accepted=True,
            rejection_reason="",
            fusion_version=FUSION_VERSION_V1,
            semantic_key_version=str(key["semantic_key_version"]),
            semantic_key=str(key["semantic_key"]),
            semantic_key_payload=dict(key["semantic_key_payload"]),
            synthetic=bool(synthetic),
            provenance={"path": "C_task_context_fusion"},
        )

    # --- Path A: vlm_native dynamic ---
    if native_type == "dynamic":
        key = build_semantic_key_v2(
            fused_risk_type="dynamic",
            recommended_action=action,
            canonical_entity=entity,
            target_container=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket=motion_bucket,
        )
        return FusedSemanticEvidence(
            native_risk_type=native_type,
            native_risk_confidence=native_conf,
            fused_risk_type="dynamic",
            fused_confidence=native_conf,
            recommended_action=action,
            canonical_entity=entity,
            task_target=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket=motion_bucket,
            risk_type_source=RISK_TYPE_SOURCE_VLM_NATIVE,
            motion_evidence_source=MOTION_SOURCE_NONE,
            task_context_source=task_src,
            fusion_rule="vlm_native",
            fusion_accepted=True,
            rejection_reason="",
            fusion_version=FUSION_VERSION_V1,
            semantic_key_version=str(key["semantic_key_version"]),
            semantic_key=str(key["semantic_key"]),
            semantic_key_payload=dict(key["semantic_key_payload"]),
            synthetic=bool(synthetic),
            provenance={"path": "A_vlm_native_dynamic"},
        )

    # --- Path B: temporal_fusion elevate static/unknown → dynamic ---
    if native_type in ("static", "none", "unknown", ""):
        if track_evidence is None:
            return _reject("static_without_track", fused_type="static", rule="static_alone")
        validated = validate_temporal_evidence(
            track_evidence,
            config=temporal_config,
            entity_hint=entity,
        )
        motion_bucket = validated.motion_bucket
        motion_src = MOTION_SOURCE_SAM2 if validated.evidence_source == "sam2_track" else MOTION_SOURCE_NONE
        if not validated.valid:
            return _reject(
                validated.rejection_reason or "track_invalid",
                fused_type="static",
                rule="temporal_fusion",
            )
        if not entities_compatible(entity, validated.canonical_entity):
            # also try matching any VLM entity
            matched = False
            for e in _entities_from_vlm(vlm):
                if entities_compatible(e, validated.canonical_entity):
                    entity = canonicalize_entity(e)
                    matched = True
                    break
            if not matched:
                return _reject("entity_mismatch", fused_type="static", rule="temporal_fusion")

        # Conservative confidence: min(vlm, track_score capped as conf proxy)
        track_conf_proxy = min(1.0, max(0.0, float(validated.score)))
        fused_conf = min(native_conf, track_conf_proxy)
        if fused_conf < MIN_CONFIDENCE:
            return _reject(
                "fused_confidence_below_threshold",
                fused_type="static",
                rule="temporal_fusion",
            )
        # Must not raise above native
        if fused_conf > native_conf + 1e-9:
            fused_conf = native_conf

        motion_bucket = validated.motion_bucket
        key = build_semantic_key_v2(
            fused_risk_type="dynamic",
            recommended_action=action,
            canonical_entity=entity,
            target_container=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket=motion_bucket,
        )
        return FusedSemanticEvidence(
            native_risk_type=native_type or "static",
            native_risk_confidence=native_conf,
            fused_risk_type="dynamic",
            fused_confidence=fused_conf,
            recommended_action=action,
            canonical_entity=entity,
            task_target=tc.target_container,
            task_phase=tc.task_phase,
            motion_bucket=motion_bucket,
            risk_type_source=RISK_TYPE_SOURCE_TEMPORAL,
            motion_evidence_source=MOTION_SOURCE_SAM2,
            task_context_source=task_src,
            fusion_rule="temporal_fusion",
            fusion_accepted=True,
            rejection_reason="",
            fusion_version=FUSION_VERSION_V1,
            semantic_key_version=str(key["semantic_key_version"]),
            semantic_key=str(key["semantic_key"]),
            semantic_key_payload=dict(key["semantic_key_payload"]),
            synthetic=bool(synthetic),
            provenance={
                "path": "B_temporal_fusion",
                "source_frame_id": validated.source_frame_id,
                "track_speed_px_s": validated.speed_px_s,
            },
        )

    # static alone (already high conf but no track path)
    if native_type == "static":
        return _reject("static_alone_not_allowed", fused_type="static", rule="static_alone")

    return _reject(f"unsupported_native_risk_type:{native_type}")
