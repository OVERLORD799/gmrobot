#!/usr/bin/env python3
"""Offline unit test for Dyn-B per-step CSV writer path."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_per_step_audit_writer import (  # noqa: E402
    DYN_B_PER_STEP_AUDIT_FIELDNAMES,
    init_dyn_b_per_step_audit_writer,
)


def test_writer_init_header_one_row_flush_close() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "audit" / "dyn_b_per_step.csv"
        fh, writer = init_dyn_b_per_step_audit_writer(str(out))
        writer.writerow(
            {
                "sim_step": 1,
                "policy_step": 1,
                "phase": "smoke_step",
                "gate_evaluated": "ALLOW",
                "gate_effective": "ALLOW",
                "trigger_rule": "",
                "stop_flag": 0,
                "slow_flag": 0,
                "replan_flag": 0,
                "dist_min_g1_body_m": "0.200000",
                "margin_to_gate_m": "0.100000",
                "g1_fell_flag": 0,
                "g1_root_x": "0.000000",
                "g1_root_y": "0.000000",
                "g1_root_z": "1.000000",
                "g1_tilt_rad": "0.000000",
                "motion_source_label": "unit_test",
                "camera_capture_marker": 0,
                "body_pose_marker": 0,
            }
        )
        fh.flush()
        fh.close()

        with out.open("r", encoding="utf-8", newline="") as rf:
            reader = csv.DictReader(rf)
            assert reader.fieldnames == DYN_B_PER_STEP_AUDIT_FIELDNAMES
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["sim_step"] == "1"
        assert rows[0]["gate_effective"] == "ALLOW"
        assert rows[0]["motion_source_label"] == "unit_test"


def main() -> None:
    test_writer_init_header_one_row_flush_close()
    print("PASS test_dyn_b_per_step_audit_writer_unit")


if __name__ == "__main__":
    main()
