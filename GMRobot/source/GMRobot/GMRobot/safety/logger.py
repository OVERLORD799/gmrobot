"""Structured safety decision logging for Layer 2 training."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, TextIO

import numpy as np

from .types import GateDecision, GateResult, SafetyState

# Large JSON array columns (ee_pos, joint_positions, …) can exceed default 128 KiB.
csv.field_size_limit(max(2**20, csv.field_size_limit()))

_COMPLEX_KEYS = ("ee_pos", "ee_vel", "human_hand_pos", "human_hand_vel")
_ARRAY_KEYS = ("joint_positions", "joint_velocities", "action_proposed", "action_executed")
# Layer 3 reserved columns (empty until VLM runtime is wired).
_VLM_COLUMN_KEYS = (
    "vlm_risk_class",
    "vlm_confidence",
    "vlm_suggested_action",
    "vlm_model_id",
    "rgb_frame_path",
    "vlm_explanation",
    "vlm_keywords",
    "vlm_risk_type",
    "vlm_risk_confidence",
    "vlm_parse_ok",  # C3: distinguishes server JSON parse success from defaults
)
_VLM_RESERVED_COLUMNS: dict[str, str] = {key: "" for key in _VLM_COLUMN_KEYS}
_PERCEPTION_COLUMN_KEYS = (
    "perception_detection_count",
    "perception_top_label",
    "perception_top_score",
    "perception_latency_ms",
    "perception_gdino_model_id",
    "perception_track_label",
    "perception_track_center_x",
    "perception_track_center_y",
    "perception_track_speed_px_s",
    "perception_track_direction_deg",
)
_PERCEPTION_RESERVED_COLUMNS: dict[str, str] = {key: "" for key in _PERCEPTION_COLUMN_KEYS}
_REPLAN_COLUMN_KEYS = (
    "replan_active",
    "replan_stage",
    "replan_event",
    "replan_trigger",
)
_REPLAN_RESERVED_COLUMNS: dict[str, str] = {key: "" for key in _REPLAN_COLUMN_KEYS}
_GRIPPER_TRACE_COLUMN_KEYS = (
    "gripper_hold_reason",
    "release_gripper_committed",
)
_GRIPPER_TRACE_RESERVED_COLUMNS: dict[str, str] = {
    key: "" for key in _GRIPPER_TRACE_COLUMN_KEYS
}
# VLM grasp supervisor columns — always present so mid-episode enrichment
# does not add fields after the CSV header is written.
_GRASP_SUPERVISOR_COLUMN_KEYS = (
    "vlm_object_held",
    "vlm_object_held_confidence",
    "vlm_object_held_desc",
    "vlm_grasp_lost_streak",
)
_GRASP_SUPERVISOR_RESERVED_COLUMNS: dict[str, str] = {
    key: "" for key in _GRASP_SUPERVISOR_COLUMN_KEYS
}
# VLM scene inventory columns (periodic full-scene part count).
_SCENE_INVENTORY_COLUMN_KEYS = (
    "vlm_scene_total_parts",
    "vlm_scene_parts_in_gripper",
    "vlm_scene_parts_in_source",
    "vlm_scene_parts_in_target",
    "vlm_scene_parts_elsewhere",
    "vlm_scene_inventory_latency_ms",
)
_SCENE_INVENTORY_RESERVED_COLUMNS: dict[str, str] = {
    key: "" for key in _SCENE_INVENTORY_COLUMN_KEYS
}
# W13: time-to-risk regression shadow columns (always present in CSV header).
_TTR_COLUMN_KEYS = (
    "time_to_risk_steps",
    "predictive_replan_trigger",
)
_TTR_RESERVED_COLUMNS: dict[str, str] = {
    key: "" for key in _TTR_COLUMN_KEYS
}
# Held-part position columns — per-step world-space pose of the part currently
# carried by the gripper (empty when not carrying).
_HELD_PART_COLUMN_KEYS = (
    "held_part_pos_x",
    "held_part_pos_y",
    "held_part_pos_z",
)
_HELD_PART_RESERVED_COLUMNS: dict[str, str] = {
    key: "" for key in _HELD_PART_COLUMN_KEYS
}


def replan_log_fields_for_step(
    *,
    replan_enabled: bool,
    transport_phase: str = "",
    stage_name: str = "",
    post_replan_advance_active: bool = False,
    event: str = "",
    trigger_rule: str = "",
) -> dict[str, str]:
    """Per-step replan observability for SafetyLogger CSV columns."""
    if not replan_enabled:
        return dict(_REPLAN_RESERVED_COLUMNS)

    in_detour = stage_name.startswith("replan_detour")
    active = post_replan_advance_active or in_detour
    stage = ""
    if in_detour:
        stage = stage_name
    elif active and transport_phase:
        stage = transport_phase

    return {
        "replan_active": "1" if active else "0",
        "replan_stage": stage,
        "replan_event": event,
        "replan_trigger": trigger_rule if event in ("trigger", "applied") else "",
    }


def perception_log_fields_from_result(
    result: Mapping[str, Any] | None,
    *,
    gdino_model_id: str = "",
) -> dict[str, str] | None:
    """Map PerceptionClient.ground() JSON to SafetyLogger CSV columns.

    Returns None on failure so callers forward-fill the last successful row.
    """
    if not result:
        return None
    if result.get("ok") is False or result.get("error"):
        return None

    detections = result.get("detections") or []
    top_label = ""
    top_score = ""
    if detections:
        best = max(detections, key=lambda d: float(d.get("score", 0) or 0))
        top_label = str(best.get("label", ""))
        score = best.get("score", "")
        top_score = "" if score in (None, "") else str(score)

    latency = result.get("latency_ms", "")
    resolved_model = result.get("gdino_model_id") or gdino_model_id

    return {
        "perception_detection_count": str(len(detections)),
        "perception_top_label": top_label,
        "perception_top_score": top_score,
        "perception_latency_ms": "" if latency in (None, "") else str(latency),
        "perception_gdino_model_id": str(resolved_model),
    }


def track_log_fields_from_result(
    result: Mapping[str, Any] | None,
    track: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    """Map PerceptionClient.track_* JSON to SafetyLogger CSV columns."""
    if not result or not track:
        return None
    if result.get("ok") is False or result.get("error"):
        return None

    center = track.get("center_xy")
    if center is None and track.get("box_xyxy"):
        x1, y1, x2, y2 = track["box_xyxy"]
        center = [(float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0]

    cx = "" if not center else str(center[0])
    cy = "" if not center else str(center[1])
    speed = track.get("speed_px_s", "")
    direction = track.get("direction_deg", "")

    return {
        "perception_track_label": str(track.get("label", "")),
        "perception_track_center_x": cx,
        "perception_track_center_y": cy,
        "perception_track_speed_px_s": "" if speed in (None, "") else str(speed),
        "perception_track_direction_deg": "" if direction in (None, "") else str(direction),
    }


def merge_perception_log_fields(
    ground_fields: Mapping[str, str] | None,
    track_fields: Mapping[str, str] | None,
) -> dict[str, str] | None:
    """Merge partial /ground and /track logger dicts (omit unset keys)."""
    if ground_fields is None and track_fields is None:
        return None
    merged: dict[str, str] = {}
    if ground_fields:
        merged.update({k: str(ground_fields[k]) for k in ground_fields})
    if track_fields:
        merged.update({k: str(track_fields[k]) for k in track_fields})
    return merged


def vlm_log_fields_from_result(
    result: Mapping[str, Any] | None,
    *,
    model_id: str = "",
    rgb_frame_path: str = "",
) -> dict[str, str] | None:
    """Map VLMClient.analyze() JSON to SafetyLogger CSV columns."""
    if not result:
        return None
    _error = str(result.get("error", ""))
    if result.get("ok") is False or _error:
        return {
            "vlm_risk_class": "error",
            "vlm_confidence": "",
            "vlm_suggested_action": "error",
            "vlm_model_id": str(result.get("model_id") or model_id),
            "rgb_frame_path": rgb_frame_path,
            "vlm_explanation": _error[:500],
            "vlm_keywords": "",
            "vlm_risk_type": "error",
            "vlm_risk_confidence": "",
            "vlm_parse_ok": "0",
        }

    # Structured fields — prefer server-returned keys, fall back to text.
    text = str(result.get("text") or result.get("vlm_explanation") or "")
    risk = str(result.get("vlm_risk_class") or result.get("vlm_risk_type") or "")
    confidence = result.get("vlm_confidence") or result.get("vlm_risk_confidence", "")
    action = str(result.get("vlm_suggested_action") or "")
    resolved_model = str(result.get("vlm_model_id") or result.get("model_id") or model_id)

    # If the VLM returned "replan" or "continue" in the text, use it as action.
    if not action and text:
        text_lower = text.lower()
        if "replan" in text_lower:
            action = "replan"
        elif "continue" in text_lower or "safe" in text_lower:
            action = "continue"
        elif "slow" in text_lower or "caution" in text_lower:
            action = "slow_down"

    # New structured fields from VLM v2 (G1–G4).
    keywords = result.get("vlm_keywords") or []
    if isinstance(keywords, list):
        keywords_str = ";".join(str(k) for k in keywords)
    else:
        keywords_str = str(keywords)
    risk_type = str(result.get("vlm_risk_type") or risk)
    risk_conf = result.get("vlm_risk_confidence")
    if risk_conf in (None, ""):
        risk_conf = ""
    else:
        risk_conf = str(risk_conf)
    # C3: server-side JSON parse succeeded if keywords/risk_type are non-empty.
    _parsed_ok = bool(keywords_str or risk_type not in ("", "none"))
    return {
        "vlm_risk_class": str(risk),
        "vlm_confidence": "" if confidence in (None, "") else str(confidence),
        "vlm_suggested_action": str(action),
        "vlm_model_id": str(resolved_model),
        "rgb_frame_path": rgb_frame_path,
        "vlm_explanation": text[:500],
        "vlm_keywords": keywords_str[:300],
        "vlm_risk_type": risk_type,
        "vlm_risk_confidence": risk_conf,
        "vlm_parse_ok": "1" if _parsed_ok else "0",
    }
# Envelope audit columns — always present so mid-episode held-object pickup
# does not add fields after the CSV header is written.
_ENVELOPE_RESERVED_COLUMNS: dict[str, str] = {
    "dist_min_envelope": "",
    "dist_min_arm": "",
    "dist_min_gripper": "",
    "dist_min_held": "",
    "closest_primitive_id": "",
}


class SafetyLogger:
    """Append per-step safety records; stream to CSV during the episode."""

    def __init__(
        self,
        log_dir: str,
        episode_id: int = 0,
        enabled: bool = True,
        flush_interval: int = 50,
    ):
        self.enabled = enabled
        self.episode_id = episode_id
        self._flush_interval = max(1, flush_interval)
        self._pending_rows: list[dict[str, Any]] = []
        self._rows_written = 0
        self._episode_outcome = ""
        self._outcome_env_index: int | None = None
        self._csv_file: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self._fieldnames: list[str] | None = None
        self._flushed: bool = False
        self._last_vlm_fields: dict[str, str] = dict(_VLM_RESERVED_COLUMNS)
        self._last_perception_fields: dict[str, str] = dict(_PERCEPTION_RESERVED_COLUMNS)
        if not enabled:
            self.session_dir = None
            self._csv_path = None
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = Path(log_dir) / timestamp
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = self.session_dir / f"episode_{episode_id:04d}.csv"

    def record(
        self,
        state: SafetyState,
        action_proposed: np.ndarray,
        result: GateResult,
        action_executed: np.ndarray,
        env_index: int = 0,
        *,
        g_ground_truth: int | None = None,
        dist_ee_human_gt: float | None = None,
        gt_branch_fields: Mapping[str, Any] | None = None,
        envelope_fields: Mapping[str, Any] | None = None,
        task_time_step: int | None = None,
        task_time_step_max: int | None = None,
        shadow_fields: Mapping[str, Any] | None = None,
        vlm_fields: Mapping[str, Any] | None = None,
        perception_fields: Mapping[str, Any] | None = None,
        replan_fields: Mapping[str, Any] | None = None,
        gripper_fields: Mapping[str, Any] | None = None,
        grasp_supervisor_fields: Mapping[str, Any] | None = None,
        held_part_fields: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        if self._flushed:
            raise RuntimeError(
                "SafetyLogger.record() called after flush() — CSV is finalized; "
                "create a new logger for the next episode."
            )

        if vlm_fields is not None:
            normalized = {
                key: str(vlm_fields.get(key, ""))
                for key in _VLM_COLUMN_KEYS
            }
            self._last_vlm_fields = normalized

        if perception_fields is not None:
            for key in _PERCEPTION_COLUMN_KEYS:
                if key in perception_fields:
                    self._last_perception_fields[key] = str(perception_fields.get(key, ""))

        row = state.to_log_dict()
        row.update(
            {
                "step_index": state.step_index,
                "env_index": env_index,
                "g_rule": int(result.g_t),
                "trigger_rule": result.metadata.get("trigger_rule", ""),
                "reason": result.reason,
                "dist_ee_human": result.metadata.get("dist_ee_human", ""),
                "ttc": result.metadata.get("ttc", ""),
                "ttc_forecast_s": result.metadata.get("ttc_forecast_s", ""),
                "action_proposed": np.asarray(action_proposed, dtype=np.float32).tolist(),
                "action_executed": np.asarray(action_executed, dtype=np.float32).tolist(),
                "outcome": self._episode_outcome,
                **self._last_vlm_fields,
                **self._last_perception_fields,
                **_ENVELOPE_RESERVED_COLUMNS,
                **_REPLAN_RESERVED_COLUMNS,
                **_GRIPPER_TRACE_RESERVED_COLUMNS,
                **_GRASP_SUPERVISOR_RESERVED_COLUMNS,
                **_SCENE_INVENTORY_RESERVED_COLUMNS,
                **_TTR_RESERVED_COLUMNS,
                **_HELD_PART_RESERVED_COLUMNS,
            }
        )
        if held_part_fields is not None:
            row.update(
                {
                    key: str(held_part_fields.get(key, ""))
                    for key in _HELD_PART_COLUMN_KEYS
                }
            )
        if g_ground_truth is not None:
            row["g_ground_truth"] = int(g_ground_truth)
            row["gt_collision"] = int(g_ground_truth)
        if dist_ee_human_gt is not None:
            row["dist_ee_human_gt"] = float(dist_ee_human_gt)
            # Dual-write: GT v1.2 uses dist_min (full envelope), not EE-only.
            # Legacy column name retained for backward compatibility.
            row["dist_min_gt"] = float(dist_ee_human_gt)
        if gt_branch_fields:
            row.update(gt_branch_fields)
        if envelope_fields:
            row.update(envelope_fields)
        if task_time_step is not None:
            row["task_time_step"] = int(task_time_step)
        if task_time_step_max is not None:
            row["task_time_step_max"] = int(task_time_step_max)
        if shadow_fields:
            row.update(shadow_fields)
        if replan_fields is not None:
            row.update(
                {
                    key: str(replan_fields.get(key, ""))
                    for key in _REPLAN_COLUMN_KEYS
                }
            )
        if gripper_fields is not None:
            row.update(
                {
                    key: str(gripper_fields.get(key, ""))
                    for key in _GRIPPER_TRACE_COLUMN_KEYS
                }
            )
        if grasp_supervisor_fields is not None:
            row.update(
                {
                    key: str(grasp_supervisor_fields.get(key, ""))
                    for key in _GRASP_SUPERVISOR_COLUMN_KEYS
                }
            )
            # Scene inventory columns ride on the same dict so the logger API
            # stays unchanged; caller merges scene_inventory_log_fields() into
            # grasp_supervisor_fields before passing it in.
            row.update(
                {
                    key: str(grasp_supervisor_fields.get(key, ""))
                    for key in _SCENE_INVENTORY_COLUMN_KEYS
                }
            )
        self._pending_rows.append(row)
        if len(self._pending_rows) >= self._flush_interval:
            self._write_pending()

    def set_outcome(self, outcome: str, env_index: int | None = None) -> None:
        if not self.enabled:
            return
        self._episode_outcome = outcome
        self._outcome_env_index = env_index
        for row in self._pending_rows:
            if env_index is None or row.get("env_index") == env_index:
                row["outcome"] = outcome

    def flush(self) -> Path | None:
        if not self.enabled:
            return None

        self._flushed = True
        self._write_pending()
        if self._rows_written == 0:
            self._close_csv()
            return None

        self._patch_outcome_if_needed()
        self._close_csv()

        try:
            import pandas as pd

            parquet_path = self._csv_path.with_suffix(".parquet")
            pd.read_csv(self._csv_path).to_parquet(parquet_path, index=False)
        except ImportError:
            pass

        return self._csv_path

    @staticmethod
    def is_intervention(g_rule: int) -> bool:
        return g_rule in (int(GateDecision.STOP), int(GateDecision.SLOW_DOWN))

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        serialized = dict(row)
        for key in _COMPLEX_KEYS + _ARRAY_KEYS:
            if isinstance(serialized.get(key), list):
                serialized[key] = json.dumps(serialized[key])
        return serialized

    def _write_pending(self) -> None:
        if not self._pending_rows:
            return

        if self._csv_file is None:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            self._csv_file = open(
                self._csv_path,
                "w",
                newline="",
                encoding="utf-8",
                buffering=1,
            )

        for row in self._pending_rows:
            serialized = self._serialize_row(row)
            if self._writer is None:
                self._fieldnames = list(serialized.keys())
                self._writer = csv.DictWriter(self._csv_file, fieldnames=self._fieldnames)
                self._writer.writeheader()
                self._csv_file.flush()
            self._writer.writerow(serialized)
            self._rows_written += 1

        self._pending_rows.clear()
        self._csv_file.flush()

    def _patch_outcome_if_needed(self) -> None:
        if not self._episode_outcome or self._csv_path is None:
            return

        self._close_csv()
        try:
            with open(self._csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = [c for c in (reader.fieldnames or []) if c is not None]
                rows = []
                for row in reader:
                    row.pop(None, None)
                    rows.append(row)
        except csv.Error:
            return
        if not fieldnames:
            return

        for row in rows:
            env_index = row.get("env_index")
            if self._outcome_env_index is None or (
                env_index is not None and int(env_index) == self._outcome_env_index
            ):
                row["outcome"] = self._episode_outcome

        with open(self._csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _close_csv(self) -> None:
        if self._csv_file is not None:
            self._csv_file.close()
            self._csv_file = None
            self._writer = None
