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
    "gate_evaluated",
    "gate_effective",
    "trigger_rule",
    "stop_flag",
    "slow_flag",
    "replan_flag",
    "dist_min_g1_body_m",
    "margin_to_gate_m",
    "g1_fell_flag",
    "g1_root_x",
    "g1_root_y",
    "g1_root_z",
    "g1_tilt_rad",
    "motion_source_label",
    "camera_capture_marker",
    "body_pose_marker",
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
