"""Unit tests for Phase 2.5a envelope distance audit (no Isaac Sim)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _safety_import import bootstrap_safety

safety = bootstrap_safety()
EnvelopeConfig = safety.config.EnvelopeConfig
SafetyConfig = safety.config.SafetyConfig
EnvelopeEvaluator = safety.envelope.EnvelopeEvaluator
EnvelopePrimitive = safety.envelope.EnvelopePrimitive
compute_min_dist = safety.envelope.compute_min_dist
held_box_bounding_sphere_radius = safety.envelope.held_box_bounding_sphere_radius
surface_gap_sphere = safety.envelope.surface_gap_sphere
SafetyState = safety.types.SafetyState


def _state(
    ee: np.ndarray,
    hand: np.ndarray,
    *,
    joints: np.ndarray | None = None,
) -> SafetyState:
    return SafetyState(
        ee_pos=ee.astype(np.float64),
        ee_vel=np.zeros(3, dtype=np.float64),
        human_hand_pos=hand.astype(np.float64),
        human_hand_vel=np.zeros(3, dtype=np.float64),
        joint_pos=np.zeros(6, dtype=np.float64) if joints is None else joints,
        joint_vel=np.zeros(6, dtype=np.float64),
        sim_time=0.0,
        step_index=0,
    )


def test_surface_gap_sphere_touching():
    gap = surface_gap_sphere([0.0, 0.0, 0.0], 0.05, [0.10, 0.0, 0.0], 0.05)
    assert abs(gap - 0.0) < 1e-9


def test_surface_gap_sphere_separated():
    gap = surface_gap_sphere([0.0, 0.0, 0.0], 0.05, [0.30, 0.0, 0.0], 0.05)
    assert abs(gap - 0.20) < 1e-9


def test_compute_min_dist_picks_closest_primitive():
    hand = np.array([0.0, 0.0, 0.0])
    primitives = [
        EnvelopePrimitive("arm:shoulder", "arm", np.array([0.50, 0.0, 0.0]), 0.05),
        EnvelopePrimitive("gripper:left", "gripper", np.array([0.20, 0.0, 0.0]), 0.035),
        EnvelopePrimitive("held:box", "held", np.array([0.35, 0.0, 0.0]), 0.09),
    ]
    dist_min, closest_id, group_mins, closest_pos = compute_min_dist(hand, 0.05, primitives)
    assert abs(dist_min - 0.115) < 1e-9
    assert closest_id == "gripper:left"
    assert closest_pos is not None
    assert abs(float(closest_pos[0]) - 0.20) < 1e-9
    assert abs(group_mins["arm"] - 0.40) < 1e-9
    assert abs(group_mins["gripper"] - 0.115) < 1e-9
    assert abs(group_mins["held"] - 0.21) < 1e-9


def test_envelope_evaluator_arm_only_fk_fallback():
    hand = np.array([0.70, 0.20, 0.30])
    ee = np.array([0.72, 0.22, 0.20])
    evaluator = EnvelopeEvaluator(SafetyConfig())
    result = evaluator.evaluate(
        _state(ee, hand),
        held_object_active=False,
    )
    assert math.isfinite(result.dist_min_envelope)
    assert result.dist_min_arm is not None
    assert result.dist_min_gripper is None
    assert result.dist_min_held is None
    assert result.closest_primitive_id.startswith("arm:")


def test_envelope_evaluator_with_fingertips_and_held():
    hand = np.array([0.0, 0.0, 0.0])
    ee = np.array([0.15, 0.0, 0.0])
    fingertips = {
        "left_outer_finger": np.array([0.12, 0.02, 0.0]),
        "right_outer_finger": np.array([0.12, -0.02, 0.0]),
    }
    evaluator = EnvelopeEvaluator(SafetyConfig())
    result = evaluator.evaluate(
        _state(ee, hand),
        fingertip_positions_w=fingertips,
        held_object_active=True,
    )
    assert result.dist_min_gripper is not None
    assert result.dist_min_held is not None
    assert result.dist_min_envelope == min(
        result.dist_min_arm,
        result.dist_min_gripper,
        result.dist_min_held,
    )


def test_held_box_bounding_sphere_radius():
    radius = held_box_bounding_sphere_radius([0.05, 0.05, 0.17])
    expected = 0.5 * math.sqrt(0.05**2 + 0.05**2 + 0.17**2)
    assert abs(radius - expected) < 1e-9


def test_envelope_partial_isaac_merges_fk_for_missing_links():
    hand = np.array([0.70, 0.20, 0.30])
    ee = np.array([0.72, 0.22, 0.20])
    partial_isaac = {
        "shoulder_link": np.array([0.50, 0.10, 0.40]),
        "upper_arm_link": np.array([0.55, 0.12, 0.35]),
    }
    evaluator = EnvelopeEvaluator(SafetyConfig())
    result = evaluator.evaluate(
        _state(ee, hand),
        arm_link_positions_w=partial_isaac,
        held_object_active=False,
    )
    assert math.isfinite(result.dist_min_envelope)
    assert result.dist_min_arm is not None
    arm_ids = [pid for pid in result.primitives_used if pid.startswith("arm:")]
    # D3: centroids (6) + interpolation spheres (5 gaps × 3 = 15) = 21
    assert len(arm_ids) >= len(SafetyConfig().envelope.arm_link_names)


def test_envelope_config_custom_radii():
    cfg = EnvelopeConfig(fingertip_radius=0.04, held_box_radius=0.10)
    evaluator = EnvelopeEvaluator(cfg)
    primitives = evaluator.build_primitives(
        _state(np.array([0.5, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])),
        fingertip_positions_w={"left_outer_finger": np.array([0.48, 0.0, 0.0])},
        held_object_active=True,
    )
    gripper_prim = next(p for p in primitives if p.group == "gripper")
    held_prim = next(p for p in primitives if p.group == "held")
    assert abs(gripper_prim.radius - 0.04) < 1e-9
    assert abs(held_prim.radius - 0.10) < 1e-9


def test_held_box_uses_part_pose_when_provided():
    """When held_part_pose is given, spheres centre on the part (not EE)."""
    hand = np.array([0.0, 0.0, 0.0])
    ee = np.array([0.15, 0.0, 0.0])
    # Part is offset +3 cm in X and rotated 90° around Y (so local Z → world X).
    part_pose = np.array([0.18, 0.0, 0.0, 0.7071, 0.0, 0.7071, 0.0], dtype=np.float64)
    evaluator = EnvelopeEvaluator(SafetyConfig())
    result = evaluator.evaluate(
        _state(ee, hand),
        held_object_active=True,
        held_part_pose=part_pose,
    )
    assert result.dist_min_held is not None
    # 3-sphere mode: the closest sphere is at part pos along the rotated long axis.
    # With part at (0.18,0,0) rotated so local Z→world X, the segment at -Z
    # is closer to hand at origin than the EE-centre-fallback sphere would be.
    # The gap should be finite and computed from the multi-sphere representation.
    assert result.dist_min_held > 0.0
    assert "held:box_center" in result.primitives_used or "held:box_seg1" in result.primitives_used


def test_held_box_multi_sphere_from_part_pose():
    """Part-pose path creates 3 held spheres (not 1) distributed along local Z."""
    evaluator = EnvelopeEvaluator(SafetyConfig())
    part_pose = np.array([0.15, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    primitives = evaluator.build_primitives(
        _state(np.array([0.15, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])),
        held_object_active=True,
        held_part_pose=part_pose,
    )
    held_prims = [p for p in primitives if p.group == "held"]
    assert len(held_prims) == 3
    ids = {p.primitive_id for p in held_prims}
    assert ids == {"held:box_center", "held:box_seg1", "held:box_seg2"}
    # All 3 spheres should be near the part X position.
    for p in held_prims:
        assert abs(float(p.pos[0]) - 0.15) < 0.10
        assert float(p.radius) < 0.092  # tighter than the legacy 9.16 cm


def test_held_box_fallback_without_part_pose():
    """Without held_part_pose, legacy single-sphere at EE position is used."""
    evaluator = EnvelopeEvaluator(SafetyConfig())
    primitives = evaluator.build_primitives(
        _state(np.array([0.15, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])),
        held_object_active=True,
        # held_part_pose not provided
    )
    held_prims = [p for p in primitives if p.group == "held"]
    assert len(held_prims) == 1
    assert held_prims[0].primitive_id == "held:fixed_box"


if __name__ == "__main__":
    test_surface_gap_sphere_touching()
    test_surface_gap_sphere_separated()
    test_compute_min_dist_picks_closest_primitive()
    test_envelope_evaluator_arm_only_fk_fallback()
    test_envelope_evaluator_with_fingertips_and_held()
    test_envelope_partial_isaac_merges_fk_for_missing_links()
    test_held_box_bounding_sphere_radius()
    test_envelope_config_custom_radii()
    test_held_box_uses_part_pose_when_provided()
    test_held_box_multi_sphere_from_part_pose()
    test_held_box_fallback_without_part_pose()
    print("test_envelope_unit: OK")
