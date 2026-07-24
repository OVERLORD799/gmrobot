"""Evidence-gated dynamic rule (V1-D5A, path B): deterministic detection.

Design (recorded in vlm-v1d4c / F8): prompting cannot make the VLM a reliable
dynamic-risk classifier. This module sinks the *detection* decision into an
auditable one-line rule and demotes the VLM to semantic annotation:

    dynamic_triggered  <=>  validate_temporal_evidence(evidence).valid

All complexity (score/speed/age/session/drift thresholds) lives in the
already-tested evidence layer, including D4A drift rejection. Consequently
this rule is exactly as good as the evidence layer — deploying it without
drift rejection would reproduce the D4C P2 false positive, so evidence built
from box histories MUST carry the drift_suspect assessment.

Authority contract:
- The VLM cannot veto a rule trigger and cannot mint one (its output only
  annotates entity/description and may *escalate* the recommended action).
- gate_confidence is the tracker score — an evidence-quality number,
  deliberately NOT a semantic confidence; it never touches the frozen 0.85
  semantic gate, and fusion v1 (`semantic_temporal_fusion`) is untouched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from GMRobot.vlm.temporal_evidence import (
    TemporalEvidenceConfig,
    TemporalTrackEvidence,
    validate_temporal_evidence,
)
from GMRobot.vlm.versions import (
    EVIDENCE_GATED_RULE_VERSION_V1,
    EVIDENCE_GATED_RULE_VERSION_V2_1_DEPTH,
    EVIDENCE_GATED_RULE_VERSION_V2_WINDOW,
)

# Strictness ordering for action escalation (VLM may escalate, never relax).
_ACTION_RANK = {"none": 0, "continue": 1, "alert": 2, "replan": 3, "slow_down": 4, "stop": 5}
DEFAULT_TRIGGERED_ACTION = "slow_down"


@dataclass(frozen=True)
class EvidenceGatedDecision:
    dynamic_triggered: bool
    rejection_reason: str
    gate_confidence: float  # tracker score; evidence quality, NOT semantic confidence
    speed_px_s: float
    motion_bucket: str
    canonical_entity: str
    drift_suspect: bool
    recommended_action: str
    action_source: str
    vlm_annotation: dict[str, Any]  # non-authoritative semantic enrichment
    rule_version: str
    trigger_source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_annotation(vlm: Mapping[str, Any] | None) -> dict[str, Any]:
    if not vlm:
        return {}
    return {
        "risk_type": vlm.get("risk_type"),
        "risk_confidence": vlm.get("risk_confidence"),
        "keywords": vlm.get("keywords"),
        "affected_entities": vlm.get("affected_entities"),
        "scene_summary": vlm.get("scene_summary"),
        "suggested_action": vlm.get("suggested_action"),
    }


def decide_dynamic_from_evidence(
    track_evidence: TemporalTrackEvidence | None,
    *,
    vlm_annotation: Mapping[str, Any] | None = None,
    config: TemporalEvidenceConfig | None = None,
) -> EvidenceGatedDecision:
    """Deterministic dynamic detection from validated SAM2 evidence.

    The VLM annotation is attached for downstream semantics and may escalate
    (never relax) the recommended action. It has no influence on the trigger.
    """
    annotation = _extract_annotation(vlm_annotation)

    if track_evidence is None:
        return EvidenceGatedDecision(
            dynamic_triggered=False,
            rejection_reason="no_track_evidence",
            gate_confidence=0.0,
            speed_px_s=0.0,
            motion_bucket="none",
            canonical_entity="none",
            drift_suspect=False,
            recommended_action="none",
            action_source="rule_no_trigger",
            vlm_annotation=annotation,
            rule_version=EVIDENCE_GATED_RULE_VERSION_V1,
            trigger_source="evidence_gated_rule",
        )

    validated = validate_temporal_evidence(track_evidence, config=config)
    if not validated.valid:
        return EvidenceGatedDecision(
            dynamic_triggered=False,
            rejection_reason=validated.rejection_reason or "evidence_invalid",
            gate_confidence=float(validated.score),
            speed_px_s=float(validated.speed_px_s),
            motion_bucket=validated.motion_bucket,
            canonical_entity=validated.canonical_entity,
            drift_suspect=bool(validated.drift_suspect),
            recommended_action="none",
            action_source="rule_no_trigger",
            vlm_annotation=annotation,
            rule_version=EVIDENCE_GATED_RULE_VERSION_V1,
            trigger_source="evidence_gated_rule",
        )

    # Triggered: conservative action floor; VLM may only escalate.
    action = DEFAULT_TRIGGERED_ACTION
    action_source = "rule_floor"
    vlm_action = str((vlm_annotation or {}).get("suggested_action") or "").strip().lower()
    if vlm_action in _ACTION_RANK and _ACTION_RANK[vlm_action] > _ACTION_RANK[action]:
        action = vlm_action
        action_source = "vlm_escalation"

    return EvidenceGatedDecision(
        dynamic_triggered=True,
        rejection_reason="",
        gate_confidence=float(validated.score),
        speed_px_s=float(validated.speed_px_s),
        motion_bucket=validated.motion_bucket,
        canonical_entity=validated.canonical_entity,
        drift_suspect=False,
        recommended_action=action,
        action_source=action_source,
        vlm_annotation=annotation,
        rule_version=EVIDENCE_GATED_RULE_VERSION_V1,
        trigger_source="evidence_gated_rule",
    )


def decide_dynamic_from_window_motion(
    window_metrics: Mapping[str, Any] | None,
    *,
    track_score: float = 0.0,
    canonical_entity: str = "none",
    min_track_score: float = 0.5,
    enable_depth_path: bool = False,
    vlm_annotation: Mapping[str, Any] | None = None,
) -> EvidenceGatedDecision:
    """Rule v2/v2.1: dynamic detection from D7B window-aggregate motion.

    Replaces the two v1 motion components falsified in D7A — last-frame
    instantaneous speed (F10) and the D4A size-band drift gate (F9) — with the
    window translation verdict from ``assess_window_motion`` (F11). Track
    identity/quality gating (score) is retained. Fail-closed on missing or
    invalid window metrics. The VLM remains annotation-only (may escalate the
    action, never veto or mint the trigger).

    With ``enable_depth_path`` (v2.1, D9B) the depth channel
    (``depth_motion_suspect``: scale_rate + aspect_change, D9A calibration)
    is a second trigger path for camera-axis motion. Known residual risk: a
    width-only mask leak can mimic the aspect signature (only ever observed in
    the retired top-down viewpoint); a false trigger yields a conservative
    slow_down (safe-side error).
    """
    annotation = _extract_annotation(vlm_annotation)
    wm = dict(window_metrics or {})
    translation_rate = float(wm.get("translation_rate_px_s") or 0.0)
    scale_rate = float(wm.get("scale_rate_px_s") or 0.0)
    rule_version = (
        EVIDENCE_GATED_RULE_VERSION_V2_1_DEPTH if enable_depth_path
        else EVIDENCE_GATED_RULE_VERSION_V2_WINDOW
    )

    def _no_trigger(reason: str) -> EvidenceGatedDecision:
        return EvidenceGatedDecision(
            dynamic_triggered=False,
            rejection_reason=reason,
            gate_confidence=float(track_score),
            speed_px_s=translation_rate,
            motion_bucket="none",
            canonical_entity=canonical_entity,
            drift_suspect=False,
            recommended_action="none",
            action_source="rule_no_trigger",
            vlm_annotation=annotation,
            rule_version=rule_version,
            trigger_source="evidence_gated_rule_window",
        )

    if not wm:
        return _no_trigger("no_window_metrics")
    if not wm.get("valid"):
        return _no_trigger(str(wm.get("reason") or "window_metrics_invalid"))
    if float(track_score) < min_track_score:
        return _no_trigger("track_score_below_min")
    depth_hit = enable_depth_path and bool(wm.get("depth_motion_suspect"))
    if not wm.get("dynamic_by_translation") and not depth_hit:
        # Camera-axis depth motion without depth path stays fail-closed.
        if scale_rate > translation_rate:
            return _no_trigger("translation_below_threshold_scale_dominant")
        return _no_trigger("translation_below_threshold")
    motion_bucket = (
        "window_translation" if wm.get("dynamic_by_translation") else "window_depth_scale"
    )

    action = DEFAULT_TRIGGERED_ACTION
    action_source = "rule_floor"
    vlm_action = str((vlm_annotation or {}).get("suggested_action") or "").strip().lower()
    if vlm_action in _ACTION_RANK and _ACTION_RANK[vlm_action] > _ACTION_RANK[action]:
        action = vlm_action
        action_source = "vlm_escalation"

    return EvidenceGatedDecision(
        dynamic_triggered=True,
        rejection_reason="",
        gate_confidence=float(track_score),
        speed_px_s=translation_rate,
        motion_bucket=motion_bucket,
        canonical_entity=canonical_entity,
        drift_suspect=False,
        recommended_action=action,
        action_source=action_source,
        vlm_annotation=annotation,
        rule_version=rule_version,
        trigger_source="evidence_gated_rule_window",
    )
