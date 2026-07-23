#!/usr/bin/env python3
"""Dyn-B per-step audit CSV writer helpers."""

from __future__ import annotations

import csv
import os
from typing import IO


DYN_B_PER_STEP_AUDIT_FIELDNAMES = [
    "sim_step",
    "policy_step",
    "phase",
    "protocol_phase",
    "ur10e_stage",
    "gate_evaluated",
    "gate_effective",
    "trigger_rule",
    "trigger_reason",
    "stop_flag",
    "slow_flag",
    "replan_flag",
    "dist_min_g1_body_m",
    "margin_to_gate_m",
    "dist_min_for_gating_m",
    "dist_min_proxy_m",
    "closest_g1_body",
    "safe_dist_warn_active_m",
    "safe_dist_hard_stop_active_m",
    "ttc_observed_s",
    "ttc_forecast_s",
    "approach_rate_mps",
    "relative_velocity_mps",
    "proxy_surface_velocity_mps",
    "proxy_surface_velocity_x_mps",
    "proxy_surface_velocity_y_mps",
    "proxy_surface_velocity_z_mps",
    "robot_ee_velocity_mps",
    "robot_ee_velocity_x_mps",
    "robot_ee_velocity_y_mps",
    "robot_ee_velocity_z_mps",
    "disturbance_active",
    "disturbance_source",
    "disturbance_attempt_id",
    "g1_fell_flag",
    "g1_root_x",
    "g1_root_y",
    "g1_root_z",
    "g1_tilt_rad",
    "motion_source_label",
    "camera_capture_marker",
    "body_pose_marker",
    "ttc_observed_availability",
    "ttc_observed_source",
    "ttc_forecast_availability",
    "ttc_forecast_source",
    "approach_rate_availability",
    "approach_rate_source",
    "relative_velocity_availability",
    "relative_velocity_source",
    "proxy_surface_velocity_availability",
    "proxy_surface_velocity_source",
    "robot_ee_velocity_availability",
    "robot_ee_velocity_source",
]


def init_dyn_b_per_step_audit_writer(
    csv_path: str,
) -> tuple[IO[str], csv.DictWriter]:
    """Create a per-step audit CSV file and write canonical header."""
    out_dir = os.path.dirname(csv_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fh = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=DYN_B_PER_STEP_AUDIT_FIELDNAMES)
    writer.writeheader()
    fh.flush()
    return fh, writer
