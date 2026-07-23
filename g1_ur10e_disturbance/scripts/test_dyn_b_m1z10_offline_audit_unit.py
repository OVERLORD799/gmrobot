#!/usr/bin/env python3
"""Unit tests for dyn_b_m1z10_offline_audit."""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_m1z10_offline_audit import classify_step  # noqa: E402


def _row(step: int, body: str, gate: str, ttc: str, appr: str, psv: str, eev: str) -> dict[str, str]:
    return {
        "sim_step": str(step),
        "policy_step": str(step),
        "gate_effective": gate,
        "phase": "lateral_positive_sweep",
        "ur10e_stage": "lift_slot_A_1",
        "closest_g1_body": body,
        "dist_min_for_gating_m": "1.0",
        "dist_min_g1_body_m": "1.0",
        "dist_min_proxy_m": "1.0",
        "ttc_observed_s": ttc,
        "approach_rate_mps": appr,
        "proxy_surface_velocity_mps": psv,
        "robot_ee_velocity_mps": eev,
        "approach_rate_source": "gate_result.metadata.approach_rate",
        "ttc_observed_source": "gate_result.metadata.ttc",
        "relative_velocity_source": "not_exposed_in_runtime_gate_metadata",
    }


def test_classify_switch_with_spike() -> None:
    rows: dict[int, dict[str, str]] = {}
    for s in range(157, 178):
        rows[s] = _row(s, "left_wrist_pitch_link", "ALLOW", "inf", "-0.1", "0.2", "0.3")
    rows[166] = _row(166, "left_wrist_pitch_link", "ALLOW", "inf", "-0.2", "0.2", "0.3")
    rows[167] = _row(167, "right_wrist_pitch_link", "STOP", "0.06", "10.0", "6.0", "0.4")

    out = classify_step(rows, 167)
    assert out["classification"] == "CLOSEST_LINK_SWITCH_WITH_PROXY_SPIKE"
    assert out["closest_body_switched"] is True
    assert math.isclose(out["evidence"]["ttc_observed_s"], 0.06, rel_tol=1e-9)


if __name__ == "__main__":
    test_classify_switch_with_spike()
    print("ok")
