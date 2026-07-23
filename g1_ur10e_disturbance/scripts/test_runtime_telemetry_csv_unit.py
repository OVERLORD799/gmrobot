#!/usr/bin/env python3
"""Schema + roundtrip test for runtime telemetry CSV."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_telemetry_csv import (  # noqa: E402
    RUNTIME_TELEMETRY_FIELDNAMES,
    init_runtime_telemetry_writer,
)


def test_runtime_telemetry_schema_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "telemetry" / "runtime.csv"
        fh, writer = init_runtime_telemetry_writer(str(out))
        writer.writerow(
            {
                "sim_step": 240,
                "frame_id": "frame_000240_env0.png",
                "scenario_phase": "lateral_negative_sweep_mirror",
                "commanded_vx": "0.020000",
                "commanded_vy": "-0.240000",
                "commanded_yaw": "0.000000",
                "actual_root_x": "0.123000",
                "actual_root_y": "-0.456000",
                "actual_root_z": "1.003000",
                "actual_root_yaw": "0.120000",
                "key_body_links_json": json.dumps({"torso_link": [0.1, -0.4, 0.95]}, ensure_ascii=True),
                "ur10_freeze_enabled": 1,
                "ur10_hold_hash": "abc123",
                "ur10_action_norm": "0.000000",
                "ur10_joint_delta_norm": "0.000000",
                "ur10_joint_delta_max_abs": "0.000000",
            }
        )
        fh.flush()
        fh.close()

        with out.open("r", encoding="utf-8", newline="") as rf:
            reader = csv.DictReader(rf)
            assert reader.fieldnames == RUNTIME_TELEMETRY_FIELDNAMES
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["sim_step"] == "240"
        assert rows[0]["frame_id"] == "frame_000240_env0.png"
        assert rows[0]["ur10_freeze_enabled"] == "1"


if __name__ == "__main__":
    test_runtime_telemetry_schema_roundtrip()
    print("PASS test_runtime_telemetry_csv_unit")
