"""Per-step dynamic sweep audit CSV schema and formatting."""

from __future__ import annotations

import csv
import math
from typing import Mapping


DYNAMIC_AUDIT_FIELDNAMES: tuple[str, ...] = (
    "sim_step",
    "policy_step",
    "protocol_phase",
    "stage_name",
    "disturbance_attempt_id",
    "disturbance_trajectory_id",
    "gate_decision",
    "trigger_rule",
    "sweep_progress",
    "ee_x",
    "ee_y",
    "ee_z",
    "proxy_center_x",
    "proxy_center_y",
    "proxy_center_z",
    "proxy_surface_x",
    "proxy_surface_y",
    "proxy_surface_z",
    "surface_velocity_x",
    "surface_velocity_y",
    "surface_velocity_z",
    "hand_speed",
    "dist_min_proxy",
    "dist_min_for_gating",
    "dist_min_envelope",
    "dist_min_held",
    "hard_stop_active",
    "warn_active",
    "ttc_s",
    "ttc_forecast_s",
    "approach_rate",
)

DYNAMIC_AUDIT_HEADER = ",".join(DYNAMIC_AUDIT_FIELDNAMES) + "\n"


def _fmt_float(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ""
    if math.isfinite(num):
        return f"{num:.6f}"
    if num > 0:
        return "inf"
    if num < 0:
        return "-inf"
    return ""


def build_dynamic_audit_row(**kwargs: object) -> dict[str, str]:
    row = {name: "" for name in DYNAMIC_AUDIT_FIELDNAMES}
    for name in (
        "sim_step",
        "policy_step",
        "protocol_phase",
        "stage_name",
        "disturbance_attempt_id",
        "disturbance_trajectory_id",
        "gate_decision",
        "trigger_rule",
        "sweep_progress",
    ):
        if name in kwargs:
            row[name] = str(kwargs.get(name, "") or "")
    for name in (
        "ee_x",
        "ee_y",
        "ee_z",
        "proxy_center_x",
        "proxy_center_y",
        "proxy_center_z",
        "proxy_surface_x",
        "proxy_surface_y",
        "proxy_surface_z",
        "surface_velocity_x",
        "surface_velocity_y",
        "surface_velocity_z",
        "hand_speed",
        "dist_min_proxy",
        "dist_min_for_gating",
        "dist_min_envelope",
        "dist_min_held",
        "hard_stop_active",
        "warn_active",
        "ttc_s",
        "ttc_forecast_s",
        "approach_rate",
    ):
        if name in kwargs:
            row[name] = _fmt_float(kwargs.get(name))
    return row


def format_dynamic_audit_row(row: Mapping[str, str]) -> str:
    return ",".join(str(row.get(name, "") or "") for name in DYNAMIC_AUDIT_FIELDNAMES) + "\n"


def validate_dynamic_audit_rows(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(rows):
        if None in row.values():
            errors.append(f"row {i}: contains None value")
        missing = set(DYNAMIC_AUDIT_FIELDNAMES) - set(row.keys())
        if missing:
            errors.append(f"row {i}: missing columns {sorted(missing)}")
        extra = set(row.keys()) - set(DYNAMIC_AUDIT_FIELDNAMES)
        if extra:
            errors.append(f"row {i}: unexpected columns {sorted(extra)}")
    return errors


def read_dynamic_audit_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        rows = []
        for row in reader:
            clean = {k: ("" if v is None else str(v)) for k, v in row.items() if k}
            rows.append(clean)
        return rows
