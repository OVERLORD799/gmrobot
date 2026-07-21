"""Event CSV schema and row formatting for run_phase3 §6.1 audit logs."""

from __future__ import annotations

import csv
import math
from typing import Any, Mapping, Sequence

from dynamic_sweep_proxy import time_to_risk_steps_from_ttc

# Header and data rows must stay in lockstep (P0-1).
EVENT_CSV_FIELDNAMES: tuple[str, ...] = (
    "sim_step",
    "event_type",
    "attempt_id",
    "event_id",
    "trigger_rule",
    "trigger_source",
    "applied_step",
    "protocol_phase",
    "stage_name",
    "dist_m",
    "warn_threshold",
    "dist_min_for_gating",
    "dist_min_envelope",
    "dist_min_held",
    "safe_dist_hard_stop_active",
    "safe_dist_warn_active",
    "slow_streak_length",
    "ee_x",
    "ee_y",
    "ee_z",
    "proxy_center_x",
    "proxy_center_y",
    "proxy_center_z",
    "proxy_surface_x",
    "proxy_surface_y",
    "proxy_surface_z",
    "attractor_x",
    "attractor_y",
    "attractor_z",
    "g1_head_x",
    "g1_head_y",
    "g1_head_z",
    "reach_clamped",
    "reach_radius_active",
    "proxy_radius_active",
    "head_to_attractor_distance",
    "reach_margin",
    "ttc_at_trigger",
    "time_to_risk_steps",
    "sweep_attempt_id",
    "sweep_progress",
    "sweep_velocity_x",
    "sweep_velocity_y",
    "sweep_velocity_z",
    "safety_enforcement_mode",
    "shadow_gate_decision",
    "shadow_replan_would_trigger",
)

EVENT_CSV_HEADER = ",".join(EVENT_CSV_FIELDNAMES) + "\n"


def _fmt_ttc_from_metadata(meta: Mapping[str, Any] | None, control_dt: float) -> tuple[str, str]:
    """Return (ttc_at_trigger, time_to_risk_steps) from RuleEngine metadata."""
    if not meta:
        return "", ""
    raw = meta.get("ttc")
    if raw in (None, "", "inf", "Infinity"):
        return "", ""
    try:
        ttc = float(raw)
    except (TypeError, ValueError):
        return "", ""
    if not math.isfinite(ttc) or ttc <= 0.0:
        return "", ""
    return f"{ttc:.4f}", time_to_risk_steps_from_ttc(ttc, control_dt)


def build_event_row(
    *,
    sim_step: int,
    event_type: str,
    attempt_id: int,
    event_id: str = "",
    trigger_rule: str = "",
    trigger_source: str = "",
    applied_step: str = "",
    protocol_phase: str = "",
    stage_name: str = "",
    gate_audit: Mapping[str, str] | None = None,
    geom: Mapping[str, str] | None = None,
    slow_streak_length: str = "",
    gate_metadata: Mapping[str, Any] | None = None,
    control_dt: float = 0.02,
    sweep_attempt_id: str = "",
    sweep_progress: str = "",
    sweep_velocity_xyz: Sequence[float] | None = None,
    safety_enforcement_mode: str = "active",
    shadow_gate_decision: str = "",
    shadow_replan_would_trigger: bool = False,
) -> dict[str, str]:
    """Build one event CSV row dict with every declared column present."""
    d = dict(gate_audit or {})
    g = dict(geom or {})
    ttc_s, ttr = _fmt_ttc_from_metadata(gate_metadata, control_dt)
    sv = list(sweep_velocity_xyz or (0.0, 0.0, 0.0))
    row = {name: "" for name in EVENT_CSV_FIELDNAMES}
    row.update({
        "sim_step": str(int(sim_step)),
        "event_type": str(event_type or ""),
        "attempt_id": str(int(attempt_id)),
        "event_id": str(event_id or ""),
        "trigger_rule": str(trigger_rule or ""),
        "trigger_source": str(trigger_source or ""),
        "applied_step": str(applied_step or ""),
        "protocol_phase": str(protocol_phase or ""),
        "stage_name": str(stage_name or ""),
        "dist_m": d.get("dist_m", ""),
        "warn_threshold": d.get("warn_threshold", ""),
        "dist_min_for_gating": d.get("dist_min_for_gating", ""),
        "dist_min_envelope": d.get("dist_min_envelope", ""),
        "dist_min_held": d.get("dist_min_held", ""),
        "safe_dist_hard_stop_active": d.get("safe_dist_hard_stop_active", ""),
        "safe_dist_warn_active": d.get("safe_dist_warn_active", ""),
        "slow_streak_length": str(slow_streak_length or ""),
        "ee_x": g.get("ee_x", ""),
        "ee_y": g.get("ee_y", ""),
        "ee_z": g.get("ee_z", ""),
        "proxy_center_x": g.get("proxy_center_x", ""),
        "proxy_center_y": g.get("proxy_center_y", ""),
        "proxy_center_z": g.get("proxy_center_z", ""),
        "proxy_surface_x": g.get("proxy_surface_x", ""),
        "proxy_surface_y": g.get("proxy_surface_y", ""),
        "proxy_surface_z": g.get("proxy_surface_z", ""),
        "attractor_x": g.get("attractor_x", ""),
        "attractor_y": g.get("attractor_y", ""),
        "attractor_z": g.get("attractor_z", ""),
        "g1_head_x": g.get("g1_head_x", ""),
        "g1_head_y": g.get("g1_head_y", ""),
        "g1_head_z": g.get("g1_head_z", ""),
        "reach_clamped": g.get("reach_clamped", ""),
        "reach_radius_active": g.get("reach_radius_active", ""),
        "proxy_radius_active": g.get("proxy_radius_active", ""),
        "head_to_attractor_distance": g.get("head_to_attractor_distance", ""),
        "reach_margin": g.get("reach_margin", ""),
        "ttc_at_trigger": ttc_s,
        "time_to_risk_steps": ttr,
        "sweep_attempt_id": str(sweep_attempt_id or ""),
        "sweep_progress": str(sweep_progress or ""),
        "sweep_velocity_x": f"{float(sv[0]):.6f}" if sweep_velocity_xyz is not None else "",
        "sweep_velocity_y": f"{float(sv[1]):.6f}" if sweep_velocity_xyz is not None else "",
        "sweep_velocity_z": f"{float(sv[2]):.6f}" if sweep_velocity_xyz is not None else "",
        "safety_enforcement_mode": str(safety_enforcement_mode or "active"),
        "shadow_gate_decision": str(shadow_gate_decision or ""),
        "shadow_replan_would_trigger": (
            "1" if shadow_replan_would_trigger else "0"
        ),
    })
    return row


def format_event_row(row: Mapping[str, str]) -> str:
    """Serialize a row dict to CSV (column order fixed)."""
    return ",".join(str(row.get(name, "") or "") for name in EVENT_CSV_FIELDNAMES) + "\n"


def validate_event_csv_rows(rows: list[dict[str, str]]) -> list[str]:
    """Return human-readable errors for schema / None-value violations."""
    errors: list[str] = []
    for i, row in enumerate(rows):
        if None in row.values():
            errors.append(f"row {i}: contains None value")
        for key in row:
            if key is None:
                errors.append(f"row {i}: None column key")
        missing = set(EVENT_CSV_FIELDNAMES) - set(row.keys())
        if missing:
            errors.append(f"row {i}: missing columns {sorted(missing)}")
        extra = set(row.keys()) - set(EVENT_CSV_FIELDNAMES)
        if extra:
            errors.append(f"row {i}: unexpected columns {sorted(extra)}")
    return errors


def read_event_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        rows = []
        for row in reader:
            clean = {k: ("" if v is None else str(v)) for k, v in row.items() if k}
            rows.append(clean)
        return rows
