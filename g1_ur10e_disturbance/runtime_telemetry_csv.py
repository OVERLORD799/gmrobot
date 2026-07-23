"""Runtime telemetry CSV schema for Dyn-C motion-isolation runs."""

from __future__ import annotations

import csv
import os
from typing import IO


RUNTIME_TELEMETRY_FIELDNAMES = [
    "sim_step",
    "frame_id",
    "scenario_phase",
    "commanded_vx",
    "commanded_vy",
    "commanded_yaw",
    "actual_root_x",
    "actual_root_y",
    "actual_root_z",
    "actual_root_yaw",
    "key_body_links_json",
    "ur10_freeze_enabled",
    "ur10_hold_hash",
    "ur10_action_norm",
    "ur10_joint_delta_norm",
    "ur10_joint_delta_max_abs",
]


def init_runtime_telemetry_writer(csv_path: str) -> tuple[IO[str], csv.DictWriter]:
    """Create runtime telemetry CSV and write canonical header."""
    out_dir = os.path.dirname(csv_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fh = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=RUNTIME_TELEMETRY_FIELDNAMES)
    writer.writeheader()
    fh.flush()
    return fh, writer
