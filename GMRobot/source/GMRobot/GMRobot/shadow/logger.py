"""Five-stage shadow audit logger (separate from frozen physical CSVs)."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def _sanitize_for_log(obj: Any) -> Any:
    """Drop/redact raw remote session identifiers before persistence."""
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk == "session_id":
                out[k] = "<redacted>" if v else v
            elif lk == "track_session_id":
                out[k] = "<redacted>" if v else ""
            else:
                out[k] = _sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_log(x) for x in obj]
    return obj


SHADOW_STEP_FIELDS = [
    "episode_id",
    "sim_step",
    "frame_id",
    "request_id",
    "parent_request_id",
    "track_session_id",
    "track_id",
    "track_state",
    "track_state_native",
    "track_state_source",
    "session_ref",
    "session_generation",
    "session_match",
    "session_match_applicable",
    "session_continuity_verified",
    "scene_summary",
    "keywords",
    "risk_type",
    "risk_confidence",
    "predicted_consequence",
    "prediction_horizon_s",
    "suggested_action",
    "spatial_hint",
    "keyword_detection_map",
    "status",
    "error_type",
    "perception_status",
    "would_stop",
    "would_replan",
    "vlm_latency_ms",
    "ground_latency_ms",
    "track_latency_ms",
    "end_to_end_latency_ms",
    "queue_wait_ms",
    "submitted_frames",
    "processed_frames",
    "dropped_frames",
    "stale",
    "stale_result_count",
    "shadow_gate_override_count",
    "shadow_action_override_count",
    "shadow_clock_blocked_steps",
    "shadow_replan_applied_count",
    "shadow_protocol_override_count",
    "schema_version",
    "prompt_version",
    "prompt_hash",
    "temporal_context_present",
    "temporal_source_frame_id",
    "temporal_evidence_age_s",
    "temporal_entity",
    "temporal_speed_px_s",
    "temporal_motion_bucket",
    "temporal_valid",
    "task_context_present",
    "task_phase",
    "task_target",
    "native_risk_type",
    "native_risk_confidence",
    "fused_risk_type",
    "fused_confidence",
    "risk_type_source",
    "motion_evidence_source",
    "task_context_source",
    "fusion_rule",
    "fusion_rejection_reason",
    "semantic_key_version",
    "semantic_key",
    "intentional_control_effect",
    "vlm_model_id",
    "gdino_model_id",
    "sam2_model_id",
]


class FiveStageShadowLogger:
    def __init__(self, log_dir: str, *, episode_id: str = "0", enabled: bool = True):
        self.enabled = enabled
        self.episode_id = str(episode_id)
        if not enabled:
            self.session_dir = None
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = Path(log_dir) / f"five_stage_shadow_{stamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._requests_path = self.session_dir / "five_stage_shadow_requests.jsonl"
        self._steps_path = self.session_dir / "five_stage_shadow_steps.csv"
        self._summary_path = self.session_dir / "five_stage_shadow_summary.json"
        self._steps_file = self._steps_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._steps_file, fieldnames=SHADOW_STEP_FIELDS)
        self._writer.writeheader()
        self._n = 0

    def record(self, result: Mapping[str, Any]) -> None:
        if not self.enabled or self.session_dir is None:
            return
        metrics = result.get("metrics") or {}
        leakage = result.get("leakage") or {}
        row = {k: "" for k in SHADOW_STEP_FIELDS}
        row.update(
            {
                "episode_id": str(result.get("episode_id", self.episode_id)),
                "sim_step": str(result.get("sim_step", "")),
                "frame_id": str(result.get("frame_id", "")),
                "request_id": str(result.get("request_id", "")),
                "parent_request_id": str(result.get("parent_request_id", "")),
                "track_session_id": str(result.get("track_session_id", "")),
                "track_id": str(result.get("track_id", "")),
                "track_state": str(result.get("track_state", "")),
                "track_state_native": str(bool(result.get("track_state_native"))),
                "track_state_source": str(result.get("track_state_source", "")),
                "session_ref": str(result.get("session_ref", "")),
                "session_generation": str(result.get("session_generation", "")),
                "session_match": ""
                if result.get("session_match") is None
                else str(bool(result.get("session_match"))),
                "session_match_applicable": str(
                    bool(result.get("session_match_applicable"))
                ),
                "session_continuity_verified": str(
                    bool(result.get("session_continuity_verified"))
                ),
                "scene_summary": str(result.get("scene_summary", ""))[:300],
                "keywords": ";".join(result.get("keywords") or []),
                "risk_type": str(result.get("risk_type", "")),
                "risk_confidence": str(result.get("risk_confidence", "")),
                "predicted_consequence": str(result.get("predicted_consequence", ""))[:300],
                "prediction_horizon_s": str(result.get("prediction_horizon_s", "")),
                "suggested_action": str(result.get("suggested_action", "")),
                "spatial_hint": str(result.get("spatial_hint", "")),
                "keyword_detection_map": json.dumps(
                    result.get("keyword_detection_map") or {}, ensure_ascii=False
                ),
                "status": str(result.get("status", "")),
                "error_type": str(result.get("error_type", "")),
                "perception_status": str(result.get("perception_status", "")),
                "would_stop": str(bool(result.get("would_stop"))),
                "would_replan": str(bool(result.get("would_replan"))),
                "vlm_latency_ms": str(result.get("vlm_latency_ms", "")),
                "ground_latency_ms": str(result.get("ground_latency_ms", "")),
                "track_latency_ms": str(result.get("track_latency_ms", "")),
                "end_to_end_latency_ms": str(result.get("end_to_end_latency_ms", "")),
                "queue_wait_ms": str(result.get("queue_wait_ms", "")),
                "submitted_frames": str(metrics.get("submitted_frames", "")),
                "processed_frames": str(metrics.get("processed_frames", "")),
                "dropped_frames": str(metrics.get("dropped_frames", "")),
                "stale": str(bool(result.get("stale"))),
                "stale_result_count": str(metrics.get("stale_result_count", "")),
                "shadow_gate_override_count": str(leakage.get("shadow_gate_override_count", 0)),
                "shadow_action_override_count": str(leakage.get("shadow_action_override_count", 0)),
                "shadow_clock_blocked_steps": str(leakage.get("shadow_clock_blocked_steps", 0)),
                "shadow_replan_applied_count": str(leakage.get("shadow_replan_applied_count", 0)),
                "shadow_protocol_override_count": str(
                    leakage.get("shadow_protocol_override_count", 0)
                ),
                "schema_version": str(result.get("schema_version", "")),
                "prompt_version": str(result.get("prompt_version", "")),
                "prompt_hash": str(result.get("prompt_hash", "")),
                "temporal_context_present": str(bool(result.get("temporal_context_present"))),
                "temporal_source_frame_id": str(result.get("temporal_source_frame_id", "")),
                "temporal_evidence_age_s": str(result.get("temporal_evidence_age_s", "")),
                "temporal_entity": str(result.get("temporal_entity", "")),
                "temporal_speed_px_s": str(result.get("temporal_speed_px_s", "")),
                "temporal_motion_bucket": str(result.get("temporal_motion_bucket", "")),
                "temporal_valid": str(bool(result.get("temporal_valid"))),
                "task_context_present": str(bool(result.get("task_context_present"))),
                "task_phase": str(result.get("task_phase", "")),
                "task_target": str(result.get("task_target", "")),
                "native_risk_type": str(result.get("native_risk_type", "")),
                "native_risk_confidence": str(result.get("native_risk_confidence", "")),
                "fused_risk_type": str(result.get("fused_risk_type", "")),
                "fused_confidence": str(result.get("fused_confidence", "")),
                "risk_type_source": str(result.get("risk_type_source", "")),
                "motion_evidence_source": str(result.get("motion_evidence_source", "")),
                "task_context_source": str(result.get("task_context_source", "")),
                "fusion_rule": str(result.get("fusion_rule", "")),
                "fusion_rejection_reason": str(result.get("fusion_rejection_reason", "")),
                "semantic_key_version": str(result.get("semantic_key_version", "")),
                "semantic_key": str(result.get("semantic_key", "")),
                "intentional_control_effect": str(
                    bool(result.get("intentional_control_effect", False))
                ),
                "vlm_model_id": str(result.get("vlm_model_id", "")),
                "gdino_model_id": str(result.get("gdino_model_id", "")),
                "sam2_model_id": str(result.get("sam2_model_id", "")),
            }
        )
        self._writer.writerow(row)
        self._steps_file.flush()
        safe = _sanitize_for_log(dict(result))
        with self._requests_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe, ensure_ascii=False, default=str) + "\n")
        self._n += 1

    def flush_summary(self, extra: Mapping[str, Any] | None = None) -> Path | None:
        if not self.enabled or self.session_dir is None:
            return None
        payload = {
            "episode_id": self.episode_id,
            "rows": self._n,
            "note": "V0-A offline/shadow only; not LIVE-VALIDATED; not paper stats",
        }
        if extra:
            payload.update(dict(extra))
        self._summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return self._summary_path

    def close(self) -> None:
        if getattr(self, "_steps_file", None) is not None:
            self._steps_file.close()
            self._steps_file = None
