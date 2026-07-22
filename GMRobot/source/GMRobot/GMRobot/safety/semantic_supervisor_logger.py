"""Audit logger for Semantic Safety Supervisor (V1-B/V1-C0 shadow).

No raw images, base64, raw session IDs, credentials, or unbounded explanations.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .semantic_supervisor import SemanticAdvisoryDecision

SENSITIVE_KEYS = frozenset(
    {
        "session_id",
        "track_session_id",
        "password",
        "token",
        "credential",
        "credentials",
        "authorization",
        "api_key",
        "image",
        "rgb",
        "base64",
        "image_b64",
        "raw_image",
    }
)

MAX_CONSEQUENCE_CHARS = 240

SEMANTIC_SUPERVISOR_FIELDS = [
    "episode_id",
    "sim_step",
    "advisory_event_id",
    "request_id",
    "frame_id",
    "source_capture_sim_step",
    "source_capture_time",
    "result_completed_time",
    "decision_sim_step",
    "decision_time",
    "result_age",
    "risk_type",
    "confidence",
    "action",
    "consequence",
    "horizon",
    "entities",
    "accepted",
    "rejection_reason",
    "consistency_count",
    "geometry_gate",
    "geometry_gate_reason",
    "requested_gate",
    "evaluated_semantic_gate",
    "effective_control_gate",
    "effective_gate_shadow",
    "requested_speed_scale",
    "cooldown",
    "monotonicity_ok",
    "enforcement_mode",
    "intentional_control_effect",
    "would_slow",
    "would_slow_down",
    "would_stop",
    "would_replan",
    "semantic_key",
    "control_decision_hash",
    "synthetic",
]


def _truncate(text: str, n: int = MAX_CONSEQUENCE_CHARS) -> str:
    s = str(text or "")
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def sanitize_for_semantic_log(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in SENSITIVE_KEYS or any(s in lk for s in ("base64", "password", "token", "secret")):
                out[k] = "<redacted>"
            elif lk in ("explanation", "raw_response_truncated", "raw_explanation"):
                continue
            else:
                out[k] = sanitize_for_semantic_log(v)
        return out
    if isinstance(obj, list):
        return [sanitize_for_semantic_log(x) for x in obj]
    return obj


def decision_to_row(
    decision: SemanticAdvisoryDecision,
    *,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ents = ";".join(decision.affected_entities)
    audit = dict(audit or {})
    evaluated = audit.get("evaluated_semantic_gate", decision.requested_gate)
    effective_control = audit.get("effective_control_gate", decision.current_geometry_gate)
    return {
        "episode_id": decision.episode_id,
        "sim_step": decision.sim_step,
        "advisory_event_id": decision.advisory_event_id,
        "request_id": decision.source_request_id,
        "frame_id": decision.source_frame_id,
        "source_capture_sim_step": audit.get("source_capture_sim_step", ""),
        "source_capture_time": audit.get("source_capture_time", ""),
        "result_completed_time": audit.get("result_completed_time", ""),
        "decision_sim_step": audit.get("decision_sim_step", decision.sim_step),
        "decision_time": audit.get("decision_time", decision.decision_timestamp_s),
        "result_age": audit.get("result_age_s", decision.result_age_s),
        "risk_type": decision.risk_type,
        "confidence": decision.risk_confidence,
        "action": decision.suggested_action,
        "consequence": _truncate(decision.predicted_consequence),
        "horizon": decision.prediction_horizon_s,
        "entities": ents,
        "accepted": decision.accepted,
        "rejection_reason": decision.rejection_reason,
        "consistency_count": decision.consistency_count,
        "geometry_gate": audit.get("geometry_gate_decision", decision.current_geometry_gate),
        "geometry_gate_reason": audit.get("geometry_gate_reason", ""),
        "requested_gate": decision.requested_gate,
        "evaluated_semantic_gate": evaluated,
        "effective_control_gate": effective_control,
        "effective_gate_shadow": decision.effective_gate_shadow,
        "requested_speed_scale": (
            "" if decision.requested_speed_scale is None else decision.requested_speed_scale
        ),
        "cooldown": decision.cooldown_active,
        "monotonicity_ok": decision.monotonicity_ok,
        "enforcement_mode": decision.enforcement_mode,
        "intentional_control_effect": False,
        "would_slow": decision.would_slow,
        "would_slow_down": bool(audit.get("would_slow_down", decision.would_slow)),
        "would_stop": False,
        "would_replan": False,
        "semantic_key": decision.semantic_key,
        "control_decision_hash": audit.get("control_decision_hash", ""),
        "synthetic": decision.synthetic,
    }


class SemanticSupervisorLogger:
    def __init__(self, log_dir: str | Path, *, enabled: bool = True):
        self.enabled = enabled
        if not enabled:
            self.session_dir = None
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = Path(log_dir) / f"semantic_supervisor_{stamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self.session_dir / "semantic_supervisor_decisions.jsonl"
        self._csv_path = self.session_dir / "semantic_supervisor_steps.csv"
        self._summary_path = self.session_dir / "semantic_supervisor_summary.json"
        self._csv_file = self._csv_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._csv_file, fieldnames=SEMANTIC_SUPERVISOR_FIELDS)
        self._writer.writeheader()
        self._n = 0
        self._accepted = 0
        self._reasons: dict[str, int] = {}

    def log_decision(
        self,
        decision: SemanticAdvisoryDecision,
        *,
        audit: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled or self.session_dir is None:
            return
        row = decision_to_row(decision, audit=audit)
        safe = sanitize_for_semantic_log(row)
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe, ensure_ascii=False) + "\n")
        self._writer.writerow(safe)
        self._csv_file.flush()
        self._n += 1
        if decision.accepted:
            self._accepted += 1
        reason = decision.rejection_reason or ("accepted" if decision.accepted else "")
        if reason:
            self._reasons[reason] = self._reasons.get(reason, 0) + 1

    def close(self) -> dict[str, Any]:
        summary = {
            "rows": self._n,
            "accepted_count": self._accepted,
            "rejection_reasons": dict(self._reasons),
            "intentional_control_effect_count": 0,
            "note": "V1-B/C0 shadow audit only; not LIVE; not paper stats",
        }
        if self.enabled and self.session_dir is not None:
            self._csv_file.close()
            self._summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary
