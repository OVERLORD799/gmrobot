"""Previous-frame TemporalTrackEvidence (SAM2-only; never sim GT)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

ENTITY_CLASSES = frozenset(
    {
        "human_hand",
        "container",
        "industrial_part",
        "robotic_arm",
        "humanoid",
        "sphere",
        "device",
        "unknown",
        "none",
    }
)
TRACK_STATES = frozenset(
    {"initialized", "tracking", "lost", "reset", "unknown", "none"}
)
MOTION_BUCKETS = frozenset({"none", "L", "R", "toward", "away", "unknown"})

# Iteration order matters for the substring fallback in canonicalize_entity:
# more specific keys must come before shorter/ambiguous ones. In particular
# "humanoid robot" and "robotic arm" must precede the bare "robot" alias
# (F7 fix: bare "robot" used to substring-match "robotic arm").
_LABEL_ALIASES: dict[str, str] = {
    "humanoid robot": "humanoid",
    "humanoid": "humanoid",
    "bare human hand": "human_hand",
    "human hand": "human_hand",
    "hand": "human_hand",
    "orange sphere": "sphere",
    "spherical object": "sphere",
    "red sphere": "sphere",
    "container": "container",
    "green containers": "container",
    "green compartments": "container",
    "device": "device",
    "robotic arm": "robotic_arm",
    "robot": "unknown",  # bare "robot" is ambiguous (arm vs humanoid)
    "industrial part": "industrial_part",
    "part": "industrial_part",
    "small objects": "industrial_part",
    "black objects": "industrial_part",
}


def canonicalize_entity(label: Any) -> str:
    text = str(label or "").strip().lower()
    if not text:
        return "unknown"
    if text in ENTITY_CLASSES:
        return text
    if text in _LABEL_ALIASES:
        return _LABEL_ALIASES[text]
    for key, canon in _LABEL_ALIASES.items():
        if key in text or text in key:
            return canon
    return "unknown"


def motion_bucket_from_track(
    *,
    speed_px_s: float,
    direction_deg: float | None,
    min_speed_px_s: float,
) -> str:
    if float(speed_px_s) < float(min_speed_px_s):
        return "none"
    if direction_deg is None or (isinstance(direction_deg, float) and math.isnan(direction_deg)):
        return "unknown"
    d = float(direction_deg) % 360.0
    # Image coords: 0°=+x (right), 90°=+y (down) typical; keep coarse buckets only.
    if 45.0 <= d < 135.0:
        return "toward"  # downward / into scene proxy
    if 135.0 <= d < 225.0:
        return "L"
    if 225.0 <= d < 315.0:
        return "away"
    return "R"


@dataclass(frozen=True)
class TemporalTrackEvidence:
    source_request_id: str = ""
    source_frame_id: str = ""
    track_id: str = ""  # local alias / stringified id; never raw session
    canonical_entity: str = "unknown"
    selected_label: str = ""
    track_state: str = "unknown"
    session_continuity_verified: bool = False
    score: float = 0.0
    speed_px_s: float = 0.0
    direction_deg: float | None = None
    motion_bucket: str = "none"
    re_detected: bool = False
    evidence_age_s: float = 0.0
    evidence_source: str = "sam2_track"
    track_state_native: bool = False
    valid: bool = False
    session_ref: str = ""  # redacted local alias only (e.g. session_1)
    session_generation: int | None = None
    rejection_reason: str = ""
    # Geometric mask-leak drift flag (see track_drift.assess_box_drift).
    # Default False keeps prior behavior; producers opt in by setting it.
    drift_suspect: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def invalid(cls, reason: str, **kwargs: Any) -> TemporalTrackEvidence:
        base = cls(valid=False, rejection_reason=str(reason), **kwargs)
        return base


@dataclass(frozen=True)
class TemporalEvidenceConfig:
    """Independent motion/evidence thresholds — NOT semantic confidence."""

    max_evidence_age_s: float = 2.0
    min_track_score: float = 0.5
    min_speed_px_s: float = 10.0
    require_session_continuity_when_applicable: bool = True
    allow_initialized_without_continuity: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TemporalEvidenceConfig:
        d = dict(data or {})
        return cls(
            max_evidence_age_s=float(d.get("max_evidence_age_s", 2.0)),
            min_track_score=float(d.get("min_track_score", 0.5)),
            min_speed_px_s=float(d.get("min_speed_px_s", 10.0)),
            require_session_continuity_when_applicable=bool(
                d.get("require_session_continuity_when_applicable", True)
            ),
            allow_initialized_without_continuity=bool(
                d.get("allow_initialized_without_continuity", True)
            ),
        )


def extract_primary_track(track_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not track_result:
        return {}
    tracks = track_result.get("tracks") or []
    if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
        return dict(tracks[0])
    return {}


def build_temporal_evidence_from_track_result(
    track_result: Mapping[str, Any] | None,
    *,
    source_request_id: str,
    source_frame_id: str,
    config: TemporalEvidenceConfig | None = None,
    now_age_s: float = 0.0,
    drift_suspect: bool = False,
) -> TemporalTrackEvidence:
    """Build evidence snapshot from a *completed* track result (frame N)."""
    cfg = config or TemporalEvidenceConfig()
    if not track_result or track_result.get("ok") is False:
        return TemporalTrackEvidence.invalid(
            "track_missing_or_failed",
            source_request_id=source_request_id,
            source_frame_id=source_frame_id,
            evidence_age_s=float(now_age_s),
        )

    primary = extract_primary_track(track_result)
    track_id_val = primary.get("track_id", track_result.get("track_id"))
    # track_id=0 is legal
    track_id_str = "" if track_id_val is None else str(track_id_val)

    state = str(
        primary.get("track_state") or track_result.get("track_state") or "unknown"
    ).strip().lower()
    label = str(primary.get("label") or "")
    canon = canonicalize_entity(label)
    try:
        score = float(primary.get("sam2_score", primary.get("score", 0.0)) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        speed = float(primary.get("speed_px_s", 0.0) or 0.0)
    except (TypeError, ValueError):
        speed = 0.0
    direction: float | None
    try:
        raw_dir = primary.get("direction_deg")
        direction = None if raw_dir is None else float(raw_dir)
    except (TypeError, ValueError):
        direction = None

    session_ref = str(track_result.get("session_ref") or "")
    # Never persist raw session ids into evidence
    raw_sid = track_result.get("track_session_id") or track_result.get("session_id")
    if raw_sid and str(raw_sid) not in ("", "<redacted>") and not session_ref:
        session_ref = "session_local"  # alias only

    continuity = bool(track_result.get("session_continuity_verified", False))
    re_detected = bool(primary.get("re_detected", track_result.get("re_detected", False)))
    gen = track_result.get("session_generation")
    try:
        generation = None if gen is None else int(gen)
    except (TypeError, ValueError):
        generation = None

    bucket = motion_bucket_from_track(
        speed_px_s=speed, direction_deg=direction, min_speed_px_s=cfg.min_speed_px_s
    )

    ev = TemporalTrackEvidence(
        source_request_id=str(source_request_id),
        source_frame_id=str(source_frame_id),
        track_id=track_id_str,
        canonical_entity=canon,
        selected_label=label,
        track_state=state if state in TRACK_STATES else "unknown",
        session_continuity_verified=continuity,
        score=score,
        speed_px_s=speed,
        direction_deg=direction,
        motion_bucket=bucket,
        re_detected=re_detected,
        evidence_age_s=float(now_age_s),
        evidence_source="sam2_track",
        track_state_native=bool(
            primary.get("track_state_native", track_result.get("track_state_native", False))
        ),
        # Snapshot only — validity is decided at frame N+1 consume time.
        valid=False,
        session_ref=session_ref,
        session_generation=generation,
        rejection_reason="pending_validation",
        drift_suspect=bool(drift_suspect),
    )
    return ev


def validate_temporal_evidence(
    evidence: TemporalTrackEvidence,
    *,
    config: TemporalEvidenceConfig | None = None,
    entity_hint: str | None = None,
    current_session_ref: str | None = None,
    current_session_generation: int | None = None,
) -> TemporalTrackEvidence:
    """Re-validate evidence for use at frame N+1 (age/session/entity/speed)."""
    cfg = config or TemporalEvidenceConfig()
    reason = ""

    if evidence.evidence_source != "sam2_track":
        reason = "evidence_source_not_sam2"
    elif evidence.track_state in ("lost", "reset", "none"):
        reason = f"track_state_{evidence.track_state}"
    elif evidence.track_state not in ("initialized", "tracking"):
        reason = "track_state_invalid"
    elif float(evidence.evidence_age_s) > float(cfg.max_evidence_age_s):
        reason = "evidence_stale"
    elif float(evidence.score) < float(cfg.min_track_score):
        reason = "score_below_threshold"
    elif float(evidence.speed_px_s) < float(cfg.min_speed_px_s):
        reason = "speed_below_threshold"
    elif evidence.re_detected:
        reason = "re_detected_reset_required"
    elif evidence.drift_suspect:
        reason = "track_drift_suspect"
    else:
        # session continuity
        if evidence.track_state == "tracking":
            if cfg.require_session_continuity_when_applicable:
                if not evidence.session_continuity_verified:
                    reason = "session_continuity_not_verified"
        elif evidence.track_state == "initialized":
            if not cfg.allow_initialized_without_continuity:
                if not evidence.session_continuity_verified:
                    reason = "initialized_without_continuity"

        if not reason and current_session_ref is not None and evidence.session_ref:
            if str(current_session_ref) != str(evidence.session_ref):
                reason = "session_mismatch"
        if (
            not reason
            and current_session_generation is not None
            and evidence.session_generation is not None
            and int(current_session_generation) != int(evidence.session_generation)
        ):
            reason = "session_generation_mismatch"

        if not reason and entity_hint is not None:
            hint_canon = canonicalize_entity(entity_hint)
            if hint_canon not in ("unknown", "none") and evidence.canonical_entity not in (
                "unknown",
                "none",
            ):
                if hint_canon != evidence.canonical_entity:
                    # also allow robotic_arm always mismatched against obstacle class
                    if not entities_compatible(hint_canon, evidence.canonical_entity):
                        reason = "entity_mismatch"

    if reason:
        return replace(evidence, valid=False, rejection_reason=reason)

    bucket = motion_bucket_from_track(
        speed_px_s=evidence.speed_px_s,
        direction_deg=evidence.direction_deg,
        min_speed_px_s=cfg.min_speed_px_s,
    )
    if bucket == "none":
        return replace(
            evidence, valid=False, motion_bucket=bucket, rejection_reason="motion_bucket_none"
        )
    return replace(evidence, valid=True, motion_bucket=bucket, rejection_reason="")


def entities_compatible(a: str, b: str) -> bool:
    """True if semantic entity and tracked entity refer to the same obstacle class."""
    ca, cb = canonicalize_entity(a), canonicalize_entity(b)
    if ca in ("unknown", "none") or cb in ("unknown", "none"):
        return False
    if ca == cb:
        return True
    # robotic_arm is usually the robot, not the risk entity — not compatible with obstacles
    return False


def age_evidence(evidence: TemporalTrackEvidence, *, age_s: float) -> TemporalTrackEvidence:
    return replace(evidence, evidence_age_s=float(age_s))
