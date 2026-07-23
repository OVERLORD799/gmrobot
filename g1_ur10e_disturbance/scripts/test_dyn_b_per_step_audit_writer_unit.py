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
                "protocol_phase": "transit",
                "ur10e_stage": "approach",
                "gate_evaluated": "ALLOW",
                "gate_effective": "ALLOW",
                "trigger_rule": "",
                "trigger_reason": "",
                "stop_flag": 0,
                "slow_flag": 0,
                "replan_flag": 0,
                "dist_min_g1_body_m": "0.200000",
                "margin_to_gate_m": "0.100000",
                "dist_min_for_gating_m": "0.200000",
                "dist_min_proxy_m": "0.200000",
                "closest_g1_body": "head_link",
                "safe_dist_warn_active_m": "0.280000",
                "safe_dist_hard_stop_active_m": "0.250000",
                "ttc_observed_s": "null",
                "ttc_forecast_s": "null",
                "approach_rate_mps": "null",
                "relative_velocity_mps": "null",
                "proxy_surface_velocity_mps": "0.000000",
                "proxy_surface_velocity_x_mps": "0.000000",
                "proxy_surface_velocity_y_mps": "0.000000",
                "proxy_surface_velocity_z_mps": "0.000000",
                "robot_ee_velocity_mps": "0.010000",
                "robot_ee_velocity_x_mps": "0.010000",
                "robot_ee_velocity_y_mps": "0.000000",
                "robot_ee_velocity_z_mps": "0.000000",
                "disturbance_active": 1,
                "disturbance_source": "scripted_virtual_hand",
                "disturbance_attempt_id": 3,
                "g1_fell_flag": 0,
                "g1_root_x": "0.000000",
                "g1_root_y": "0.000000",
                "g1_root_z": "1.000000",
                "g1_tilt_rad": "0.000000",
                "motion_source_label": "unit_test",
                "camera_capture_marker": 0,
                "body_pose_marker": 0,
                "ttc_observed_availability": "missing",
                "ttc_observed_source": "gate_result.metadata.ttc",
                "ttc_forecast_availability": "missing",
                "ttc_forecast_source": "gate_result.metadata.ttc_forecast_s",
                "approach_rate_availability": "missing",
                "approach_rate_source": "gate_result.metadata.approach_rate",
                "relative_velocity_availability": "missing",
                "relative_velocity_source": "not_exposed_in_runtime_gate_metadata",
                "proxy_surface_velocity_availability": "present",
                "proxy_surface_velocity_source": "adapter.human_hand_vel",
                "robot_ee_velocity_availability": "present",
                "robot_ee_velocity_source": "obs.safety.ee_vel",
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
        with out.open("r", encoding="utf-8") as rf:
            lines = [line.rstrip("\n") for line in rf if line.strip()]
        assert len(lines) == 2
        assert lines[0].count(",") == lines[1].count(",")


def main() -> None:
    test_writer_init_header_one_row_flush_close()
    print("PASS test_dyn_b_per_step_audit_writer_unit")


if __name__ == "__main__":
    main()
