"""Deterministic Semantic Safety Supervisor (V1-B, shadow-only).

Maps canonical VLM results to a Semantic Safety Advisory and a
monotonic fusion shadow gate. Does **not** write robot action/gate/clock/replan.

Core invariants:
- 50 Hz geometry safety remains independent and authoritative
- VLM never outputs joint position/velocity/torque
- VLM cannot relax a geometry gate
- timeout/error/stale → pure geometry (reject semantic)
- V1-B only suggests SLOW_DOWN; STOP/replan/live action closed
- default enforcement_mode=shadow; intentional_control_effect always false
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

# ---------------------------------------------------------------------------
# Gate vocabulary (string form for advisory / shadow fusion)
# ---------------------------------------------------------------------------

GATE_ALLOW = "ALLOW"
GATE_SLOW_DOWN = "SLOW_DOWN"
GATE_STOP = "STOP"

_GATE_SEVERITY: dict[str, int] = {
    GATE_ALLOW: 0,
    GATE_SLOW_DOWN: 1,
    GATE_STOP: 2,
}

_INT_TO_GATE: dict[int, str] = {
    0: GATE_ALLOW,
    1: GATE_STOP,
    2: GATE_SLOW_DOWN,
}

ALLOWED_ENFORCEMENT_MODES = frozenset({"shadow"})

# Stable rejection reasons (unique, ordered checks).
REASON_DISABLED = "disabled"
REASON_INVALID_MODE = "invalid_mode"
REASON_SCHEMA_INVALID = "schema_invalid"
REASON_VLM_ERROR = "vlm_error"
REASON_STALE = "stale"
REASON_RESULT_TOO_OLD = "result_too_old"
REASON_MISSING_ID = "missing_id"
REASON_DUPLICATE_REQUEST = "duplicate_request"
REASON_ACTION_NOT_ALLOWED = "action_not_allowed"
REASON_RISK_TYPE_NOT_ALLOWED = "risk_type_not_allowed"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_INVALID_HORIZON = "invalid_horizon"
REASON_MISSING_CONSEQUENCE = "missing_consequence"
REASON_MISSING_ENTITIES = "missing_entities"
REASON_CONSISTENCY_PENDING = "consistency_pending"
REASON_COOLDOWN = "cooldown"
REASON_GEOMETRY_ALREADY_STRICTER = "geometry_already_stricter"
REASON_UNKNOWN_GATE = "unknown_gate"


class UnknownGateError(ValueError):
    """Raised by fuse_monotonic_gate when a gate token is unrecognized."""


def normalize_gate(gate: Any) -> str:
    """Normalize geometry/semantic gate tokens to ALLOW|SLOW_DOWN|STOP.

    Accepts strings (case-insensitive), empty/None → ALLOW for geometry side
    only when explicitly empty semantic request is handled separately.
    Integers follow GateDecision: ALLOW=0, STOP=1, SLOW_DOWN=2.
    """
    if gate is None:
        raise UnknownGateError("gate is None")
    if isinstance(gate, bool):
        raise UnknownGateError(f"bool gate not allowed: {gate}")
    if isinstance(gate, int):
        if gate in _INT_TO_GATE:
            return _INT_TO_GATE[gate]
        raise UnknownGateError(f"unknown int gate: {gate}")
    s = str(gate).strip()
    if not s:
        raise UnknownGateError("empty gate")
    key = s.upper().replace("-", "_")
    aliases = {
        "ALLOW": GATE_ALLOW,
        "SLOW_DOWN": GATE_SLOW_DOWN,
        "SLOWDOWN": GATE_SLOW_DOWN,
        "SLOW": GATE_SLOW_DOWN,
        "STOP": GATE_STOP,
        "HOLD": GATE_STOP,
    }
    if key not in aliases:
        raise UnknownGateError(f"unknown gate: {gate!r}")
    return aliases[key]


def fuse_monotonic_gate(
    geometry_gate: Any,
    semantic_requested_gate: Any | None,
) -> str:
    """Monotonic fusion: severity can only stay or increase.

    ALLOW < SLOW_DOWN < STOP. Empty/None semantic request → geometry only.
    Unknown gates raise UnknownGateError (no guessing).
    Replan is not a gate and must not be passed here.
    """
    geo = normalize_gate(geometry_gate)
    if semantic_requested_gate is None or str(semantic_requested_gate).strip() == "":
        return geo
    sem = normalize_gate(semantic_requested_gate)
    if _GATE_SEVERITY[sem] >= _GATE_SEVERITY[geo]:
        return sem
    return geo


def consequence_class(predicted_consequence: str) -> str:
    """Coarse consequence class for semantic_key (not free-text equality)."""
    text = (predicted_consequence or "").strip().lower()
    if not text:
        return "empty"
    if any(k in text for k in ("collision", "contact", "hit", "strike")):
        return "collision"
    if any(k in text for k in ("damage", "break", "crush", "destroy")):
        return "damage"
    if any(k in text for k in ("pinch", "squeeze", "trap")):
        return "pinch"
    return "other"


def normalize_entities(entities: Any) -> tuple[str, ...]:
    if entities is None:
        return ()
    if isinstance(entities, str):
        items = [entities]
    elif isinstance(entities, Sequence):
        items = list(entities)
    else:
        return ()
    out = sorted({str(x).strip().lower() for x in items if str(x).strip()})
    return tuple(out)


def build_semantic_key(
    *,
    risk_type: str,
    suggested_action: str,
    affected_entities: Any,
    predicted_consequence: str,
    spatial_hint: str,
) -> str:
    ents = "|".join(normalize_entities(affected_entities))
    cclass = consequence_class(predicted_consequence)
    hint = (spatial_hint or "").strip().lower() or "none"
    return "|".join(
        [
            (risk_type or "").strip().lower(),
            (suggested_action or "").strip().lower(),
            ents,
            cclass,
            hint,
        ]
    )


@dataclass(frozen=True)
class SemanticSupervisorConfig:
    enabled: bool = False
    enforcement_mode: str = "shadow"
    allowed_actions: tuple[str, ...] = ("slow_down",)
    allowed_risk_types: tuple[str, ...] = ("dynamic", "functional")
    min_risk_confidence: float = 0.85
    max_result_age_s: float = 2.0
    min_prediction_horizon_s: float = 0.0
    max_prediction_horizon_s: float = 3.0
    min_consistent_results: int = 2
    consistency_window_s: float = 10.0
    cooldown_s: float = 5.0
    limited_active_speed_scale: float = 0.5
    reject_static_risk_in_v1: bool = True
    allow_stop: bool = False
    allow_replan: bool = False
    # V1-D2A: "v1" (default) or "v2" — never auto-switch.
    semantic_key_version: str = "v1"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SemanticSupervisorConfig:
        d = dict(data or {})
        actions = d.get("allowed_actions", ("slow_down",))
        risks = d.get("allowed_risk_types", ("dynamic", "functional"))
        return cls(
            enabled=bool(d.get("enabled", False)),
            enforcement_mode=str(d.get("enforcement_mode", "shadow")).strip().lower(),
            allowed_actions=tuple(str(x).strip().lower() for x in actions),
            allowed_risk_types=tuple(str(x).strip().lower() for x in risks),
            min_risk_confidence=float(d.get("min_risk_confidence", 0.85)),
            max_result_age_s=float(d.get("max_result_age_s", 2.0)),
            min_prediction_horizon_s=float(d.get("min_prediction_horizon_s", 0.0)),
            max_prediction_horizon_s=float(d.get("max_prediction_horizon_s", 3.0)),
            min_consistent_results=int(d.get("min_consistent_results", 2)),
            consistency_window_s=float(d.get("consistency_window_s", 10.0)),
            cooldown_s=float(d.get("cooldown_s", 5.0)),
            limited_active_speed_scale=float(d.get("limited_active_speed_scale", 0.5)),
            reject_static_risk_in_v1=bool(d.get("reject_static_risk_in_v1", True)),
            allow_stop=bool(d.get("allow_stop", False)),
            allow_replan=bool(d.get("allow_replan", False)),
            semantic_key_version=str(d.get("semantic_key_version", "v1")).strip().lower() or "v1",
        )


def load_semantic_supervisor_config(path: str | Path | None = None) -> SemanticSupervisorConfig:
    if path is None:
        # .../GMRobot/source/GMRobot/GMRobot/safety/this.py → .../GMRobot/configs/
        path = Path(__file__).resolve().parents[4] / "configs" / "semantic_safety_supervisor.yaml"
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SemanticSupervisorConfig.from_dict(data)


@dataclass
class SemanticAdvisoryInput:
    episode_id: str = "0"
    sim_step: int = 0
    current_time_s: float = 0.0
    request_id: str = ""
    frame_id: str = ""
    result_completed_at_s: float = 0.0
    result_age_s: float = 0.0
    schema_version: str = ""
    prompt_version: str = ""
    model_id: str = ""
    gateway_parse_ok: bool = False
    risk_type: str = ""
    risk_confidence: float = 0.0
    affected_entities: tuple[str, ...] | list[str] = field(default_factory=tuple)
    predicted_consequence: str = ""
    prediction_horizon_s: float = 0.0
    suggested_action: str = ""
    spatial_hint: str = ""
    current_geometry_gate: Any = GATE_ALLOW
    current_geometry_reason: str = ""
    current_speed_scale: float = 1.0
    transport_phase: str = ""
    held_object: str = ""
    stale: bool = False
    error_type: str = ""
    synthetic: bool = False
    # V1-D2A optional key override (from fusion); empty → build per config version.
    semantic_key_override: str = ""
    canonical_entity: str = ""
    target_container: str = ""
    task_phase: str = ""
    motion_bucket: str = ""


@dataclass(frozen=True)
class SemanticAdvisoryDecision:
    advisory_event_id: str
    source_request_id: str
    source_frame_id: str
    accepted: bool
    rejection_reason: str
    semantic_key: str
    consistency_count: int
    result_age_s: float
    requested_gate: str
    requested_speed_scale: float | None
    current_geometry_gate: str
    effective_gate_shadow: str
    would_slow: bool
    would_stop: bool
    would_replan: bool
    intentional_control_effect: bool
    enforcement_mode: str
    cooldown_active: bool
    monotonicity_ok: bool
    decision_timestamp_s: float
    risk_type: str = ""
    risk_confidence: float = 0.0
    suggested_action: str = ""
    predicted_consequence: str = ""
    prediction_horizon_s: float = 0.0
    affected_entities: tuple[str, ...] = ()
    spatial_hint: str = ""
    episode_id: str = "0"
    sim_step: int = 0
    synthetic: bool = False

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "advisory_event_id": self.advisory_event_id,
            "source_request_id": self.source_request_id,
            "source_frame_id": self.source_frame_id,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "semantic_key": self.semantic_key,
            "consistency_count": self.consistency_count,
            "result_age_s": self.result_age_s,
            "requested_gate": self.requested_gate,
            "requested_speed_scale": self.requested_speed_scale,
            "current_geometry_gate": self.current_geometry_gate,
            "effective_gate_shadow": self.effective_gate_shadow,
            "would_slow": self.would_slow,
            "would_stop": self.would_stop,
            "would_replan": self.would_replan,
            "intentional_control_effect": self.intentional_control_effect,
            "enforcement_mode": self.enforcement_mode,
            "cooldown_active": self.cooldown_active,
            "monotonicity_ok": self.monotonicity_ok,
            "decision_timestamp_s": self.decision_timestamp_s,
            "risk_type": self.risk_type,
            "risk_confidence": self.risk_confidence,
            "suggested_action": self.suggested_action,
            "predicted_consequence": self.predicted_consequence,
            "prediction_horizon_s": self.prediction_horizon_s,
            "affected_entities": list(self.affected_entities),
            "spatial_hint": self.spatial_hint,
            "episode_id": self.episode_id,
            "sim_step": self.sim_step,
            "synthetic": self.synthetic,
        }


@dataclass
class _EpisodeConsistencyState:
    semantic_key: str = ""
    count: int = 0
    first_time_s: float = 0.0
    last_time_s: float = 0.0
    counted_request_ids: set[str] = field(default_factory=set)
    consumed_request_ids: set[str] = field(default_factory=set)
    last_accept_time_s: float | None = None
    last_accepted_event_id: str = ""


@dataclass
class SemanticSupervisorState:
    """Per-episode mutable state. Isolated by episode_id."""

    by_episode: dict[str, _EpisodeConsistencyState] = field(default_factory=dict)

    def get(self, episode_id: str) -> _EpisodeConsistencyState:
        eid = str(episode_id)
        if eid not in self.by_episode:
            self.by_episode[eid] = _EpisodeConsistencyState()
        return self.by_episode[eid]

    def reset(self, episode_id: str | None = None) -> None:
        if episode_id is None:
            self.by_episode.clear()
        else:
            self.by_episode.pop(str(episode_id), None)


class SemanticSafetySupervisor:
    """Deterministic V1-B semantic supervisor (single-thread with internal lock)."""

    def __init__(self, config: SemanticSupervisorConfig | None = None):
        self.config = config or SemanticSupervisorConfig()
        self.state = SemanticSupervisorState()
        self._lock = threading.RLock()
        self._call_thread_id: int | None = None

    def reset(self, episode_id: str | None = None) -> None:
        with self._lock:
            self.state.reset(episode_id)

    def evaluate(self, inp: SemanticAdvisoryInput) -> SemanticAdvisoryDecision:
        """Evaluate one canonical VLM result. Thread-safe via RLock; prefer single consumer."""
        with self._lock:
            tid = threading.get_ident()
            if self._call_thread_id is None:
                self._call_thread_id = tid
            # Multi-thread OK under lock; document preferred single consumer.
            return self._evaluate_locked(inp)

    def _reject(
        self,
        inp: SemanticAdvisoryInput,
        *,
        reason: str,
        semantic_key: str = "",
        consistency_count: int = 0,
        requested_gate: str = "",
        geo_gate: str = GATE_ALLOW,
        effective: str = GATE_ALLOW,
        cooldown_active: bool = False,
        monotonicity_ok: bool = True,
        speed_scale: float | None = None,
        event_id: str | None = None,
    ) -> SemanticAdvisoryDecision:
        return SemanticAdvisoryDecision(
            advisory_event_id=event_id or str(uuid.uuid4()),
            source_request_id=str(inp.request_id or ""),
            source_frame_id=str(inp.frame_id or ""),
            accepted=False,
            rejection_reason=reason,
            semantic_key=semantic_key,
            consistency_count=consistency_count,
            result_age_s=float(inp.result_age_s),
            requested_gate=requested_gate,
            requested_speed_scale=speed_scale,
            current_geometry_gate=geo_gate,
            effective_gate_shadow=effective,
            would_slow=False,
            would_stop=False,
            would_replan=False,
            intentional_control_effect=False,
            enforcement_mode=self.config.enforcement_mode,
            cooldown_active=cooldown_active,
            monotonicity_ok=monotonicity_ok,
            decision_timestamp_s=float(inp.current_time_s),
            risk_type=str(inp.risk_type or ""),
            risk_confidence=float(inp.risk_confidence or 0.0),
            suggested_action=str(inp.suggested_action or ""),
            predicted_consequence=str(inp.predicted_consequence or ""),
            prediction_horizon_s=float(inp.prediction_horizon_s or 0.0),
            affected_entities=normalize_entities(inp.affected_entities),
            spatial_hint=str(inp.spatial_hint or ""),
            episode_id=str(inp.episode_id),
            sim_step=int(inp.sim_step),
            synthetic=bool(inp.synthetic),
        )

    def _evaluate_locked(self, inp: SemanticAdvisoryInput) -> SemanticAdvisoryDecision:
        cfg = self.config

        # 1. enabled
        if not cfg.enabled:
            return self._reject(inp, reason=REASON_DISABLED)

        # 2. enforcement_mode
        mode = str(cfg.enforcement_mode or "").strip().lower()
        if mode not in ALLOWED_ENFORCEMENT_MODES:
            return self._reject(inp, reason=REASON_INVALID_MODE)

        # Resolve geometry gate early for logging (unknown → reject later if needed)
        try:
            geo_gate = normalize_gate(inp.current_geometry_gate)
        except UnknownGateError:
            return self._reject(
                inp,
                reason=REASON_UNKNOWN_GATE,
                effective=GATE_ALLOW,
                geo_gate=GATE_ALLOW,
                monotonicity_ok=False,
            )

        # 3. schema / gateway_parse_ok
        if not bool(inp.gateway_parse_ok) or not str(inp.schema_version or "").strip():
            return self._reject(inp, reason=REASON_SCHEMA_INVALID, geo_gate=geo_gate, effective=geo_gate)

        # 4. error_type
        if str(inp.error_type or "").strip():
            return self._reject(inp, reason=REASON_VLM_ERROR, geo_gate=geo_gate, effective=geo_gate)

        # 5. stale
        if bool(inp.stale):
            return self._reject(inp, reason=REASON_STALE, geo_gate=geo_gate, effective=geo_gate)

        # 6. result age
        if float(inp.result_age_s) > float(cfg.max_result_age_s):
            return self._reject(inp, reason=REASON_RESULT_TOO_OLD, geo_gate=geo_gate, effective=geo_gate)

        # 7. ids
        rid = str(inp.request_id or "").strip()
        fid = str(inp.frame_id or "").strip()
        if not rid or not fid:
            return self._reject(inp, reason=REASON_MISSING_ID, geo_gate=geo_gate, effective=geo_gate)

        ep = self.state.get(inp.episode_id)

        # 8. duplicate request consumption
        if rid in ep.consumed_request_ids:
            return self._reject(
                inp,
                reason=REASON_DUPLICATE_REQUEST,
                geo_gate=geo_gate,
                effective=geo_gate,
                consistency_count=ep.count,
                semantic_key=ep.semantic_key,
            )

        action = str(inp.suggested_action or "").strip().lower()
        risk = str(inp.risk_type or "").strip().lower()

        # 9. action allowlist (STOP/replan closed in V1)
        if action in ("stop", "replan") and not (
            (action == "stop" and cfg.allow_stop) or (action == "replan" and cfg.allow_replan)
        ):
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_ACTION_NOT_ALLOWED, geo_gate=geo_gate, effective=geo_gate)
        if action not in cfg.allowed_actions:
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_ACTION_NOT_ALLOWED, geo_gate=geo_gate, effective=geo_gate)

        # 10. risk type
        if cfg.reject_static_risk_in_v1 and risk == "static":
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_RISK_TYPE_NOT_ALLOWED, geo_gate=geo_gate, effective=geo_gate)
        if risk not in cfg.allowed_risk_types:
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_RISK_TYPE_NOT_ALLOWED, geo_gate=geo_gate, effective=geo_gate)

        # 11. confidence
        if float(inp.risk_confidence) < float(cfg.min_risk_confidence):
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_LOW_CONFIDENCE, geo_gate=geo_gate, effective=geo_gate)

        # 12. horizon
        hz = float(inp.prediction_horizon_s)
        if hz < float(cfg.min_prediction_horizon_s) or hz > float(cfg.max_prediction_horizon_s):
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_INVALID_HORIZON, geo_gate=geo_gate, effective=geo_gate)

        # 13. consequence
        if not str(inp.predicted_consequence or "").strip():
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_MISSING_CONSEQUENCE, geo_gate=geo_gate, effective=geo_gate)

        # 14. entities
        ents = normalize_entities(inp.affected_entities)
        if not ents:
            ep.consumed_request_ids.add(rid)
            return self._reject(inp, reason=REASON_MISSING_ENTITIES, geo_gate=geo_gate, effective=geo_gate)

        # Mark consumed before consistency accounting (same request never double-counts).
        ep.consumed_request_ids.add(rid)

        if str(inp.semantic_key_override or "").strip():
            key = str(inp.semantic_key_override).strip()
        elif str(cfg.semantic_key_version or "v1") == "v2":
            from .semantic_key_v2 import build_semantic_key_v2

            key = str(
                build_semantic_key_v2(
                    fused_risk_type=risk,
                    recommended_action=action,
                    canonical_entity=str(inp.canonical_entity or (ents[0] if ents else "unknown")),
                    target_container=str(inp.target_container or "unknown"),
                    task_phase=str(inp.task_phase or "unknown"),
                    motion_bucket=str(inp.motion_bucket or "none"),
                )["semantic_key"]
            )
        else:
            key = build_semantic_key(
                risk_type=risk,
                suggested_action=action,
                affected_entities=ents,
                predicted_consequence=str(inp.predicted_consequence),
                spatial_hint=str(inp.spatial_hint or ""),
            )
        now = float(inp.current_time_s)

        # 15. consistency / debounce
        if ep.semantic_key != key:
            ep.semantic_key = key
            ep.count = 0
            ep.first_time_s = now
            ep.last_time_s = now
            ep.counted_request_ids = set()
        elif (now - ep.first_time_s) > float(cfg.consistency_window_s):
            ep.count = 0
            ep.first_time_s = now
            ep.last_time_s = now
            ep.counted_request_ids = set()

        if rid not in ep.counted_request_ids:
            ep.counted_request_ids.add(rid)
            ep.count += 1
            ep.last_time_s = now

        if ep.count < int(cfg.min_consistent_results):
            return self._reject(
                inp,
                reason=REASON_CONSISTENCY_PENDING,
                semantic_key=key,
                consistency_count=ep.count,
                geo_gate=geo_gate,
                effective=geo_gate,
            )

        # 16. cooldown
        if ep.last_accept_time_s is not None and (now - ep.last_accept_time_s) < float(cfg.cooldown_s):
            return self._reject(
                inp,
                reason=REASON_COOLDOWN,
                semantic_key=key,
                consistency_count=ep.count,
                geo_gate=geo_gate,
                effective=geo_gate,
                cooldown_active=True,
                requested_gate=GATE_SLOW_DOWN if action == "slow_down" else "",
                speed_scale=cfg.limited_active_speed_scale if action == "slow_down" else None,
                event_id=ep.last_accepted_event_id or str(uuid.uuid4()),
            )

        # Requested gate (V1-B: only SLOW_DOWN)
        requested_gate = GATE_SLOW_DOWN if action == "slow_down" else ""
        if requested_gate not in ("", GATE_SLOW_DOWN):
            return self._reject(
                inp,
                reason=REASON_ACTION_NOT_ALLOWED,
                semantic_key=key,
                consistency_count=ep.count,
                geo_gate=geo_gate,
                effective=geo_gate,
            )

        # 17. monotonic fusion
        try:
            effective = fuse_monotonic_gate(geo_gate, requested_gate or None)
        except UnknownGateError:
            return self._reject(
                inp,
                reason=REASON_UNKNOWN_GATE,
                semantic_key=key,
                consistency_count=ep.count,
                geo_gate=geo_gate,
                effective=geo_gate,
                monotonicity_ok=False,
            )

        # Geometry already stricter than semantic request → no semantic escalation
        if requested_gate and _GATE_SEVERITY[geo_gate] > _GATE_SEVERITY[requested_gate]:
            return self._reject(
                inp,
                reason=REASON_GEOMETRY_ALREADY_STRICTER,
                semantic_key=key,
                consistency_count=ep.count,
                requested_gate=requested_gate,
                speed_scale=cfg.limited_active_speed_scale,
                geo_gate=geo_gate,
                effective=effective,
                monotonicity_ok=True,
            )

        event_id = str(uuid.uuid4())
        ep.last_accept_time_s = now
        ep.last_accepted_event_id = event_id

        return SemanticAdvisoryDecision(
            advisory_event_id=event_id,
            source_request_id=rid,
            source_frame_id=fid,
            accepted=True,
            rejection_reason="",
            semantic_key=key,
            consistency_count=ep.count,
            result_age_s=float(inp.result_age_s),
            requested_gate=requested_gate,
            requested_speed_scale=cfg.limited_active_speed_scale,
            current_geometry_gate=geo_gate,
            effective_gate_shadow=effective,
            would_slow=requested_gate == GATE_SLOW_DOWN,
            would_stop=False,
            would_replan=False,
            intentional_control_effect=False,
            enforcement_mode=mode,
            cooldown_active=False,
            monotonicity_ok=True,
            decision_timestamp_s=now,
            risk_type=risk,
            risk_confidence=float(inp.risk_confidence),
            suggested_action=action,
            predicted_consequence=str(inp.predicted_consequence),
            prediction_horizon_s=hz,
            affected_entities=ents,
            spatial_hint=str(inp.spatial_hint or ""),
            episode_id=str(inp.episode_id),
            sim_step=int(inp.sim_step),
            synthetic=bool(inp.synthetic),
        )


def advisory_input_from_shadow_row(
    row: Mapping[str, Any],
    *,
    episode_id: str = "0",
    sim_step: int | None = None,
    current_time_s: float | None = None,
    current_geometry_gate: Any = GATE_ALLOW,
    result_age_s: float | None = None,
    synthetic: bool = False,
) -> SemanticAdvisoryInput:
    """Build supervisor input from a five-stage shadow JSONL row (read-only)."""
    vlm = row.get("vlm") if isinstance(row.get("vlm"), Mapping) else {}
    vlm = vlm or {}

    def pick(*keys: str, default: Any = "") -> Any:
        for k in keys:
            if k in row and row[k] not in (None, ""):
                return row[k]
            if k in vlm and vlm[k] not in (None, ""):
                return vlm[k]
        return default

    step = int(row["sim_step"]) if sim_step is None and "sim_step" in row else int(sim_step or 0)
    # Prefer explicit ages; else derive a conservative 0 for offline replay unless provided.
    age = float(result_age_s) if result_age_s is not None else float(pick("result_age_s", default=0.0) or 0.0)
    t = float(current_time_s) if current_time_s is not None else float(step) * 0.02
    err = pick("error_type", "pipeline_error", default="")
    # Prefer fused fields when present (v2 temporal path).
    risk_type = str(pick("fused_risk_type", "risk_type", default="") or "")
    risk_conf = float(pick("fused_confidence", "risk_confidence", default=0.0) or 0.0)
    return SemanticAdvisoryInput(
        episode_id=str(row.get("episode_id", episode_id)),
        sim_step=step,
        current_time_s=t,
        request_id=str(pick("request_id", default="")),
        frame_id=str(pick("frame_id", default="")),
        result_completed_at_s=t - age,
        result_age_s=age,
        schema_version=str(pick("schema_version", default="")),
        prompt_version=str(pick("prompt_version", default="")),
        model_id=str(pick("model_id", "vlm_model_id", default="")),
        gateway_parse_ok=bool(pick("gateway_parse_ok", default=row.get("pipeline_ok", False))),
        risk_type=risk_type,
        risk_confidence=risk_conf,
        affected_entities=list(pick("affected_entities", default=[]) or []),
        predicted_consequence=str(pick("predicted_consequence", default="")),
        prediction_horizon_s=float(pick("prediction_horizon_s", default=0.0) or 0.0),
        suggested_action=str(pick("suggested_action", default="")),
        spatial_hint=str(pick("spatial_hint", default="")),
        current_geometry_gate=current_geometry_gate,
        current_geometry_reason="",
        current_speed_scale=1.0,
        transport_phase=str(row.get("transport_phase", "")),
        held_object=str(row.get("held_object", "")),
        stale=bool(pick("stale", default=False)),
        error_type=str(err or ""),
        synthetic=synthetic,
        semantic_key_override=str(pick("semantic_key", default="") or ""),
        canonical_entity=str(pick("canonical_entity", default="") or ""),
        target_container=str(pick("task_target", "target_container", default="") or ""),
        task_phase=str(pick("task_phase", default="") or ""),
        motion_bucket=str(pick("motion_bucket", "temporal_motion_bucket", default="") or ""),
    )
