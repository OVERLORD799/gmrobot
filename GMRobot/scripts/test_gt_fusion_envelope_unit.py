"""Unit tests for GT v1.2 and fusion Tier0 envelope gating."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _safety_import import bootstrap_safety, load_safety_module

safety = bootstrap_safety()
load_safety_module("fusion")
SafetyConfig = safety.config.SafetyConfig
compute_ground_truth_v12 = safety.ground_truth.compute_ground_truth_v12
compute_fusion = safety.fusion.compute_fusion
GateDecision = safety.types.GateDecision


def test_ground_truth_v12_stop_below_hard_stop():
    g_gt, dist = compute_ground_truth_v12(0.10, intrusion_threshold=0.13)
    assert g_gt == int(GateDecision.STOP)
    assert abs(dist - 0.10) < 1e-9


def test_ground_truth_v12_allow_above_hard_stop():
    g_gt, dist = compute_ground_truth_v12(0.20, intrusion_threshold=0.13)
    assert g_gt == int(GateDecision.ALLOW)


def test_fusion_tier0_uses_dist_min_when_gating():
    fusion = compute_fusion(
        g_rule=int(GateDecision.ALLOW),
        g_ml=int(GateDecision.ALLOW),
        dist_ee_human=0.25,
        dist_min_envelope=0.10,
        envelope_gating=True,
        safe_dist_hard_stop=0.13,
    )
    assert fusion.tier0_would_stop
    assert fusion.would_fuse == int(GateDecision.STOP)
    assert fusion.fusion_tier == 0


def test_fusion_tier0_ee_only_when_gating_off():
    fusion = compute_fusion(
        g_rule=int(GateDecision.ALLOW),
        g_ml=int(GateDecision.ALLOW),
        dist_ee_human=0.25,
        dist_min_envelope=0.10,
        envelope_gating=False,
        safe_dist_hard_stop=0.13,
    )
    assert not fusion.tier0_would_stop


def test_fusion_tier1_static_far_downgrade():
    """Static bubble STOP while EE beyond warn → ALLOW even if g_ml=STOP."""
    fusion = compute_fusion(
        g_rule=int(GateDecision.STOP),
        g_ml=int(GateDecision.STOP),
        g_ml_confidence=0.705,
        dist_ee_human=0.25,
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        ml_override_theta=0.65,
        trigger_rule="static",
    )
    assert fusion.would_fuse == int(GateDecision.ALLOW)
    assert fusion.fusion_tier == 1


def test_fusion_tier1_static_near_warn_keeps_stop():
    fusion = compute_fusion(
        g_rule=int(GateDecision.STOP),
        g_ml=int(GateDecision.STOP),
        g_ml_confidence=0.90,
        dist_ee_human=0.18,
        safe_dist_hard_stop=0.13,
        safe_dist_warn=0.19,
        ml_override_theta=0.65,
        trigger_rule="static",
    )
    assert fusion.would_fuse == int(GateDecision.STOP)


if __name__ == "__main__":
    test_ground_truth_v12_stop_below_hard_stop()
    test_ground_truth_v12_allow_above_hard_stop()
    test_fusion_tier0_uses_dist_min_when_gating()
    test_fusion_tier0_ee_only_when_gating_off()
    test_fusion_tier1_static_far_downgrade()
    test_fusion_tier1_static_near_warn_keeps_stop()
    print("test_gt_fusion_envelope_unit: OK")
