"""Unit tests for Phase 4a motion replan (no Isaac Sim / torch)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPLAN = ROOT / "source" / "GMRobot" / "GMRobot" / "safety" / "replan"
TYPES = ROOT / "source" / "GMRobot" / "GMRobot" / "safety" / "types.py"
sys.path.insert(0, str(ROOT / "scripts"))

from _safety_import import bootstrap_safety, load_safety_module

bootstrap_safety()
load_safety_module("envelope")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


types_mod = _load("safety_types", TYPES)
GateDecision = types_mod.GateDecision
GateResult = types_mod.GateResult
SafetyState = types_mod.SafetyState

import types as _types

safety_pkg = _types.ModuleType("safety")
safety_pkg.__path__ = [str(ROOT / "source" / "GMRobot" / "GMRobot" / "safety")]
safety_pkg.types = types_mod
sys.modules["safety"] = safety_pkg
sys.modules["safety.types"] = types_mod

# Mirror GMRobot.safety modules for relative imports in replan subpackage.
for _name in ("config", "envelope", "gt_branches"):
    _gm = sys.modules[f"GMRobot.safety.{_name}"]
    sys.modules[f"safety.{_name}"] = _gm
    setattr(safety_pkg, _name, _gm)

replan_pkg = _types.ModuleType("safety.replan")
replan_pkg.__path__ = [str(REPLAN)]
sys.modules["safety.replan"] = replan_pkg

replan_types_mod = _load("safety.replan.types", REPLAN / "types.py")
replan_types_mod.__package__ = "safety.replan"
replan_pkg.types = replan_types_mod

_strategy_mod = _load("safety.replan.strategy", REPLAN / "strategy.py")
_strategy_mod.__package__ = "safety.replan"
replan_pkg.strategy = _strategy_mod

_route_mod = _load("safety.replan.route_conflict", REPLAN / "route_conflict.py")
_route_mod.__package__ = "safety.replan"
replan_pkg.route_conflict = _route_mod

triggers_mod = _load("safety.replan.triggers", REPLAN / "triggers.py")
triggers_mod.__package__ = "safety.replan"
L1WarnReplanTrigger = triggers_mod.L1WarnReplanTrigger
ReplanTriggerConfig = triggers_mod.ReplanTriggerConfig
evaluate_route_conflict = _route_mod.evaluate_route_conflict
point_to_segment_distance_3d = _route_mod.point_to_segment_distance_3d
build_proactive_route_replan_request = _route_mod.build_proactive_route_replan_request

from pick_and_place_policy import GRASP_HEIGHT, SingleEnvPickAndPlacePolicy

SafetyConfig = sys.modules["GMRobot.safety.config"].SafetyConfig
load_safety_config = sys.modules["GMRobot.safety.config"].load_safety_config


def _six_part_intrusion_policy() -> SingleEnvPickAndPlacePolicy:
    policy = SingleEnvPickAndPlacePolicy()
    obs = {"slot_A_1_T": np.eye(4), "slot_B_1_T": np.eye(4)}
    obs["slot_A_1_T"][:3, 3] = [0.6, 0.0, 0.0]
    obs["slot_B_1_T"][:3, 3] = [0.8, 0.0, 0.0]
    for i in range(2, 7):
        obs[f"slot_A_{i}_T"] = obs["slot_A_1_T"].copy()
        obs[f"slot_B_{i}_T"] = obs["slot_B_1_T"].copy()
        obs[f"slot_A_{i}_T"][0, 3] += 0.01 * (i - 1)
        obs[f"slot_B_{i}_T"][1, 3] += 0.01 * (i - 1)
    obs["slot_A_5_T"][:3, 3] = [0.645, 0.147, 0.0]
    policy.user_commands = [{"pick": f"A@{i}", "place": f"B@{i}"} for i in range(1, 7)]
    policy.reset(obs)
    return policy


def test_point_to_segment_distance_on_axis():
    p = np.array([1.0, 1.0, 0.0])
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([2.0, 0.0, 0.0])
    assert abs(point_to_segment_distance_3d(p, a, b) - 1.0) < 1e-9


def test_proactive_route_replan_disabled_by_default():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    policy = _six_part_intrusion_policy()
    cfg = load_safety_config("configs/ivj/ivj_intrusion_positive.yaml")
    allow = GateResult(
        g_t=GateDecision.ALLOW,
        reason="ok",
        metadata={"dist_min_envelope": 0.40, "dist_ee_human": 0.55},
    )
    state = SafetyState(
        ee_pos=policy._action_at_step(1660)[:3],
        ee_vel=np.zeros(3),
        human_hand_pos=np.array(cfg.human_trajectory.start_pos),
        human_hand_vel=np.zeros(3),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=33.2,
        step_index=1660,
    )
    assert (
        trigger.update(
            state,
            allow,
            task_time_step=1660,
            transport_phase="transit",
            policy=policy,
            safety_config=cfg,
            sim_step_index=1660,
        )
        is None
    )


def test_proactive_route_replan_emits_before_hand_intrusion():
    cfg = load_safety_config("configs/ivj/ivj_intrusion_positive.yaml")
    policy = _six_part_intrusion_policy()
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            proactive_route_replan_enabled=True,
            proactive_route_horizon_steps=cfg.proactive_route_horizon_steps,
            proactive_route_warn_gap_m=cfg.proactive_route_warn_gap_m,
            proactive_route_hard_gap_m=cfg.proactive_route_hard_gap_m,
            replan_cooldown_steps=200,
        )
    )
    allow = GateResult(
        g_t=GateDecision.ALLOW,
        reason="ok",
        metadata={
            "dist_min_envelope": 0.55,
            "dist_min_held": 0.55,
            "dist_ee_human": 0.70,
            "closest_primitive_id": "held:fixed_box",
        },
    )
    state = SafetyState(
        ee_pos=policy._action_at_step(1660)[:3],
        ee_vel=np.zeros(3),
        human_hand_pos=np.array(cfg.human_trajectory.start_pos),
        human_hand_vel=np.zeros(3),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=33.2,
        step_index=1660,
    )
    conflict = evaluate_route_conflict(
        policy,
        cfg,
        task_time_step=1660,
        sim_step_index=1660,
        horizon_steps=cfg.proactive_route_horizon_steps,
    )
    assert conflict is not None
    assert conflict.min_gap_m < cfg.proactive_route_warn_gap_m
    req = trigger.update(
        state,
        allow,
        task_time_step=1660,
        transport_phase="transit",
        policy=policy,
        safety_config=cfg,
        sim_step_index=1660,
    )
    assert req is not None
    assert req.trigger_rule == "route_conflict"
    assert req.task_time_step == 1660
    assert req.dist_min_envelope is not None
    assert req.dist_min_envelope < cfg.proactive_route_warn_gap_m


def test_evaluate_route_conflict_skips_non_carry_segments():
    cfg = load_safety_config("configs/ivj/ivj_intrusion_positive.yaml")
    policy = _policy_with_single_pick_place()
    # Pick descend: not in carry window.
    conflict = evaluate_route_conflict(
        policy,
        cfg,
        task_time_step=120,
        sim_step_index=120,
        horizon_steps=10,
    )
    assert conflict is None


def _state(step: int = 100) -> SafetyState:
    return SafetyState(
        ee_pos=np.array([0.7, 0.2, 0.3]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.72, 0.22, 0.2]),
        human_hand_vel=np.zeros(3),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=step * 0.02,
        step_index=step,
    )


def test_tier0_stop_reads_dist_min_envelope_metadata():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    result = GateResult(
        g_t=GateDecision.STOP,
        reason="tier0",
        metadata={"dist_min_envelope": 0.10, "trigger_rule": "static_hard"},
    )
    assert trigger.update(_state(), result, task_time_step=500) is None


def test_warn_slow_reads_dist_min_envelope():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=3))
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={"dist_min_envelope": 0.15, "trigger_rule": "static_warn"},
    )
    assert trigger.update(_state(1), slow, task_time_step=500) is None
    assert trigger.update(_state(2), slow, task_time_step=500) is None
    req = trigger.update(_state(3), slow, task_time_step=500)
    assert req is not None
    assert abs(req.dist_ee_human - 0.15) < 1e-6


def test_tier0_stop_no_replan():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    result = GateResult(
        g_t=GateDecision.STOP,
        reason="tier0",
        metadata={"dist_ee_human": 0.10, "trigger_rule": "static_hard"},
    )
    assert trigger.update(_state(), result, task_time_step=500) is None


def test_warn_slow_emits_replan_after_threshold():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=3))
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={"dist_ee_human": 0.15, "trigger_rule": "static_warn"},
    )
    assert trigger.update(_state(1), slow, task_time_step=500) is None
    assert trigger.update(_state(2), slow, task_time_step=500) is None
    req = trigger.update(_state(3), slow, task_time_step=500)
    assert req is not None
    assert req.trigger_source == "l1_warn"
    assert req.g_rule == int(GateDecision.SLOW_DOWN)


def test_ttc_warn_uses_lower_replan_threshold_when_hand_moves():
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            ttc_replan_trigger_threshold=6,
            ttc_replan_hand_speed_min=0.05,
            safe_dist_hard_stop=0.13,
        )
    )
    ttc_slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="dynamic_ttc_warning: 1.0s",
        metadata={
            "dist_min_envelope": 0.35,
            "trigger_rule": "ttc",
            "dist_ee_human": 0.40,
        },
    )
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.0, 0.5]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.5, 0.0, 0.4]),
        human_hand_vel=np.array([0.2, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=0.1,
        step_index=1,
    )
    for step in range(1, 6):
        moving.step_index = step
        assert trigger.update(moving, ttc_slow, task_time_step=800) is None
    moving.step_index = 6
    req = trigger.update(moving, ttc_slow, task_time_step=800)
    assert req is not None
    assert req.trigger_rule == "ttc"


def test_ttc_forecast_early_replan_when_gates_met():
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            ttc_replan_trigger_threshold=6,
            ttc_forecast_replan_threshold=1.0,
            ttc_replan_hand_speed_min=0.05,
            safe_dist_hard_stop=0.13,
        )
    )
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="dynamic_ttc_warning",
        metadata={
            "dist_min_envelope": 0.32,
            "dist_ee_human": 0.35,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.5,
        },
    )
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.0, 0.5]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.5, 0.0, 0.4]),
        human_hand_vel=np.array([0.2, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=0.02,
        step_index=641,
    )
    assert trigger.update(moving, slow, task_time_step=800) is None
    slow_dec = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="dynamic_ttc_warning",
        metadata={
            "dist_min_envelope": 0.30,
            "dist_ee_human": 0.33,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.4,
        },
    )
    moving.step_index = 642
    req = trigger.update(moving, slow_dec, task_time_step=800)
    assert req is not None
    assert req.trigger_rule == "ttc_forecast"


def test_ttc_forecast_disabled_by_default():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=50))
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={
            "dist_min_envelope": 0.30,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.2,
        },
    )
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.0, 0.5]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.5, 0.0, 0.4]),
        human_hand_vel=np.array([0.2, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=0.02,
        step_index=2,
    )
    trigger.update(moving, slow, task_time_step=800)
    moving.step_index = 3
    slow2 = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={
            "dist_min_envelope": 0.28,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.1,
        },
    )
    assert trigger.update(moving, slow2, task_time_step=800) is None


def test_ttc_forecast_carry_approach_on_ttc_stop():
    """Part 5 grasp: fast ball TTC STOP (skip warn) still emits ttc_forecast replan."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            ttc_forecast_replan_threshold=1.0,
            ttc_replan_hand_speed_min=0.05,
            held_critical_replan_enabled=True,
            safe_dist_hard_stop=0.13,
        )
    )
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.0, 0.40]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.5, 0.0, 0.38]),
        human_hand_vel=np.array([2.5, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=33.4,
        step_index=1670,
    )
    ttc_stop = GateResult(
        g_t=GateDecision.STOP,
        reason="dynamic_ttc: 0.3s",
        metadata={
            "dist_min_envelope": 0.85,
            "dist_min_held": 0.85,
            "dist_ee_human": 0.99,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.5,
        },
    )
    assert trigger.update(
        moving, ttc_stop, task_time_step=1670, transport_phase="approach"
    ) is None
    moving.step_index = 1671
    moving.human_hand_pos = np.array([0.52, 0.0, 0.38])
    ttc_stop_closer = GateResult(
        g_t=GateDecision.STOP,
        reason="dynamic_ttc: 0.2s",
        metadata={
            "dist_min_envelope": 0.80,
            "dist_min_held": 0.80,
            "dist_ee_human": 0.94,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.4,
        },
    )
    # 8.5 fix: forecast replan only during transit (not approach/place).
    req = trigger.update(
        moving, ttc_stop_closer, task_time_step=1671, transport_phase="transit"
    )
    assert req is not None
    assert req.g_rule == int(GateDecision.STOP)
    # Verify: approach phase blocks forecast (avoids placement misalignment).
    req2 = trigger.update(
        moving, ttc_stop_closer, task_time_step=1671, transport_phase="approach"
    )
    assert req2 is None


def test_held_critical_carry_approach_emits_replan():
    """held_critical Tier0 during grasp approach (pre-lift) may still detour when enabled."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            held_critical_replan_enabled=True,
            safe_dist_hard_stop=0.13,
        )
    )
    stop = GateResult(
        g_t=GateDecision.STOP,
        reason="held_critical",
        metadata={
            "dist_min_envelope": 0.08,
            "dist_min_held": 0.08,
            "dist_ee_human": 0.20,
            "trigger_rule": "held_critical",
        },
    )
    req = trigger.update(
        _state(1684),
        stop,
        task_time_step=1684,
        transport_phase="approach",
    )
    assert req is not None
    assert req.trigger_rule == "held_critical"


def test_ttc_warn_static_hand_keeps_default_threshold():
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            ttc_replan_trigger_threshold=6,
            safe_dist_hard_stop=0.13,
        )
    )
    ttc_slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="dynamic_ttc_warning: 1.0s",
        metadata={"dist_min_envelope": 0.35, "trigger_rule": "ttc"},
    )
    for step in range(1, 20):
        assert trigger.update(_state(step), ttc_slow, task_time_step=100) is None


def test_ttc_transit_early_replan_when_hand_fast():
    """Fast TTC STOP in transit (dist still > hard) → immediate replan, not freeze."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            ttc_replan_hand_speed_min=0.05,
            safe_dist_hard_stop=0.13,
        )
    )
    ttc_stop = GateResult(
        g_t=GateDecision.STOP,
        reason="dynamic_ttc: 0.3s",
        metadata={
            "dist_min_envelope": 0.35,
            "dist_min_held": 0.30,
            "dist_ee_human": 0.40,
            "trigger_rule": "ttc",
        },
    )
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.0, 0.40]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.5, 0.0, 0.38]),
        human_hand_vel=np.array([0.5, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=33.4,
        step_index=1670,
    )
    req = trigger.update(moving, ttc_stop, task_time_step=1670, transport_phase="transit")
    assert req is not None
    assert req.trigger_rule == "ttc"
    assert req.g_rule == int(GateDecision.STOP)


def test_ttc_hard_stop_still_no_replan():
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(ttc_replan_trigger_threshold=1, safe_dist_hard_stop=0.13)
    )
    ttc_stop = GateResult(
        g_t=GateDecision.STOP,
        reason="dynamic_ttc: 0.3s",
        metadata={"dist_min_envelope": 0.35, "trigger_rule": "ttc"},
    )
    assert trigger.update(_state(1), ttc_stop, task_time_step=800) is None


def test_replan_cooldown_starts_on_apply_success():
    cfg = ReplanTriggerConfig(replan_trigger_threshold=1, replan_cooldown_steps=50)
    trigger = L1WarnReplanTrigger(cfg)
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={"dist_min_envelope": 0.15, "trigger_rule": "static_warn"},
    )
    req = trigger.update(_state(100), slow, task_time_step=500)
    assert req is not None
    assert trigger.update(_state(101), slow, task_time_step=500) is not None

    trigger.on_replan_applied(100, 500)
    assert trigger.update(_state(120), slow, task_time_step=600) is None
    assert trigger.update(_state(151), slow, task_time_step=600) is not None


def test_failed_apply_does_not_start_cooldown():
    cfg = ReplanTriggerConfig(replan_trigger_threshold=1, replan_cooldown_steps=200)
    trigger = L1WarnReplanTrigger(cfg)
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={"dist_min_envelope": 0.15, "trigger_rule": "static_warn"},
    )
    req = trigger.update(_state(100), slow, task_time_step=500)
    assert req is not None
    retry = trigger.update(_state(101), slow, task_time_step=500)
    assert retry is not None


def _policy_with_single_pick_place():
    policy = SingleEnvPickAndPlacePolicy()
    obs = {
        "slot_A_1_T": np.eye(4),
        "slot_B_1_T": np.eye(4),
    }
    obs["slot_A_1_T"][:3, 3] = [0.6, 0.0, 0.0]
    obs["slot_B_1_T"][:3, 3] = [0.8, 0.0, 0.0]
    policy.user_commands = [{"pick": "A@1", "place": "B@1"}]
    policy.reset(obs)
    return policy


def _descend_to_box_step(policy: SingleEnvPickAndPlacePolicy) -> int:
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"].startswith("descend_to_box_with_"):
            assert stage["gripper"] == policy.gripper_closed
            return int(policy.time_stamps[i]) + 10
    raise AssertionError("descend_to_box stage not found")


def test_policy_splice_extends_trajectory():
    policy = _policy_with_single_pick_place()
    old_len = int(policy.time_stamps[-1])
    at_step = 200
    policy.time_step = at_step
    ok = policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=np.array([0.7, 0.2, 0.25], dtype=np.float32),
        human_hand_pos=np.array([0.72, 0.22, 0.2], dtype=np.float32),
        raise_m=0.05,
        lateral_m=0.15,
        detour_duration=30,
    )
    assert ok
    assert int(policy.time_stamps[-1]) > old_len
    assert policy.time_step == at_step


def test_detour_during_descend_keeps_gripper_closed():
    policy = _policy_with_single_pick_place()
    at_step = _descend_to_box_step(policy)
    policy.time_step = at_step
    detour_duration = 30

    current_gripper = policy._gripper_at_step(at_step)
    carry_threshold = (policy.gripper_open + policy.gripper_closed) / 2.0
    assert current_gripper <= carry_threshold

    rejoin_step = min(at_step + 3 * detour_duration, int(policy.time_stamps[-1]) - 1)
    future_gripper = policy._gripper_at_step(rejoin_step)
    assert future_gripper == policy.gripper_open

    prefix_end = max(
        int(np.searchsorted(policy.time_stamps, at_step, side="right")) - 1,
        0,
    )
    policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=np.array([0.8, 0.0, 0.13], dtype=np.float32),
        human_hand_pos=np.array([0.82, 0.02, 0.2], dtype=np.float32),
        raise_m=0.05,
        lateral_m=0.15,
        detour_duration=detour_duration,
    )
    detour_grippers = policy.gripper_traj[prefix_end + 1 : prefix_end + 4]
    assert np.all(detour_grippers == policy.gripper_closed)


def _open_gripper_step(policy: SingleEnvPickAndPlacePolicy) -> int:
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"].startswith("open_gripper_to_release_"):
            return int(policy.time_stamps[i])
    raise AssertionError("open_gripper stage not found")


def test_validate_placement_xy():
    target = np.array([0.8, 0.0], dtype=np.float32)
    assert SingleEnvPickAndPlacePolicy.validate_placement_xy(
        np.array([0.8, 0.0]), target
    )
    assert SingleEnvPickAndPlacePolicy.validate_placement_xy(
        np.array([0.85, 0.0]), target, radius_m=0.08
    )
    assert not SingleEnvPickAndPlacePolicy.validate_placement_xy(
        np.array([0.95, 0.0]), target, radius_m=0.08
    )


def _stage_start_step(policy: SingleEnvPickAndPlacePolicy, name_prefix: str) -> int:
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"].startswith(name_prefix):
            return int(policy.time_stamps[i])
    raise AssertionError(f"stage {name_prefix!r} not found")


def test_is_carrying_object_uses_stage_window_not_gripper_interp():
    policy = _policy_with_single_pick_place()
    pick_descend = _stage_start_step(policy, "descend_to_slot_A_1") + 10
    close_step = _stage_start_step(policy, "close_gripper_")
    grasp_step = _stage_start_step(policy, "grasp_") + 10
    place_descend = _descend_to_box_step(policy)
    open_step = _open_gripper_step(policy)
    lift_after = _stage_start_step(policy, "lift_after_releasing_") + 10

    assert not policy.is_carrying_object(pick_descend)
    assert not policy.is_carrying_object(close_step)
    assert policy.is_carrying_object(grasp_step)
    assert policy.is_carrying_object(place_descend)
    assert not policy.is_carrying_object(open_step)
    assert not policy.is_carrying_object(lift_after)


def test_is_in_grasp_window_covers_pick_not_place():
    policy = _policy_with_single_pick_place()
    pick_descend = _stage_start_step(policy, "descend_to_slot_A_1") + 5
    close_step = _stage_start_step(policy, "close_gripper_") + 1
    grasp_step = _stage_start_step(policy, "grasp_") + 5
    place_descend = _descend_to_box_step(policy)
    lift_step = _stage_start_step(policy, "lift_slot_") + 5

    assert not policy.is_in_grasp_window(pick_descend)
    assert policy.is_in_grasp_window(close_step)
    assert policy.is_in_grasp_window(grasp_step)
    assert not policy.is_in_grasp_window(place_descend)
    assert not policy.is_in_grasp_window(lift_step)


def test_validate_grasp_hold_requires_part_near_ee():
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    aligned = np.array([0.6, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    shifted = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    assert SingleEnvPickAndPlacePolicy.validate_grasp_hold(ee, aligned)
    assert not SingleEnvPickAndPlacePolicy.validate_grasp_hold(ee, shifted)


def test_maybe_rewind_for_failed_grasp_before_transport():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    part_idx = policy.part_index_at_step(lift_step)
    assert part_idx is not None
    move_above_start = policy._move_above_pick_start_step(part_idx)
    assert move_above_start is not None
    # Cooldown: step past the 5-step grace period so needs_grasp_validation
    # returns True (still well inside the lift window).
    policy._grasp_disturbance_step = lift_step - 10

    rewound = policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    assert rewound
    assert policy.time_step == max(0, move_above_start - 1)
    assert policy.should_force_open_gripper()
    assert policy.consume_grasp_rewind_event() == "rewind"


def test_maybe_rewind_skips_valid_grasp_at_lift():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    # Cooldown: make the disturbance appear old enough for validation to proceed.
    policy._grasp_disturbance_step = lift_step - 10
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    aligned = np.array([0.6, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    assert not policy.maybe_rewind_for_failed_grasp(ee, aligned, lift_step)
    assert policy.time_step == lift_step
    assert not policy._grasp_disturbance_pending
    assert policy.is_grasp_hold_validated()


def test_validated_grasp_skips_validation_during_carry():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    carry_step = _stage_start_step(policy, "move_above_box_with_") + 10
    policy.note_grasp_disturbance()
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    aligned = np.array([0.6, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    policy.time_step = lift_step
    assert not policy.maybe_rewind_for_failed_grasp(ee, aligned, lift_step)
    assert policy.is_grasp_hold_validated()
    policy.time_step = carry_step
    assert not policy.needs_grasp_validation(carry_step)
    assert not policy.should_force_open_gripper()
    policy.note_grasp_disturbance()
    assert not policy._grasp_disturbance_pending


def test_force_open_suppressed_after_grasp_validated():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    policy._grasp_rewind_force_open = True
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    aligned = np.array([0.6, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert not policy.maybe_rewind_for_failed_grasp(ee, aligned, lift_step)
    assert not policy.should_force_open_gripper()


def test_carry_phase_does_not_require_grasp_validation():
    policy = _policy_with_single_pick_place()
    carry_step = _stage_start_step(policy, "move_above_box_with_") + 10
    assert not policy.is_in_grasp_window(carry_step)
    assert not policy.needs_grasp_validation(carry_step)


def test_lift_without_disturbance_skips_grasp_validation():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_") + 5
    assert not policy.needs_grasp_validation(lift_step)


def test_needs_grasp_validation_at_close_gripper_and_lift_entry():
    policy = _policy_with_single_pick_place()
    close_step = _stage_start_step(policy, "close_gripper_")
    grasp_end = _stage_start_step(policy, "grasp_") + 49
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.note_grasp_disturbance()
    assert policy.needs_grasp_validation(close_step)
    assert not policy.needs_grasp_validation(grasp_end - 10)
    assert policy.needs_grasp_validation(grasp_end)
    assert policy.needs_grasp_validation(lift_step)
    assert policy.needs_grasp_validation(lift_step + 5)
    assert not policy.needs_grasp_validation(lift_step + 55)


def test_needs_grasp_validation_before_first_lift_action():
    """Validation must fire on last grasp step (before lift is proposed)."""
    policy = _policy_with_single_pick_place()
    grasp_end = _stage_start_step(policy, "grasp_") + 49
    policy.note_grasp_disturbance()
    assert policy.needs_grasp_validation(grasp_end)


def test_rewind_peek_action_opens_gripper_not_lift():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    lift_action = policy.peek_action()
    assert float(lift_action[2]) > GRASP_HEIGHT + 0.05

    assert policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    rewind_action = policy.peek_action()
    # Gripper must be forced open during re-approach.
    assert float(rewind_action[7]) > 0.5
    # Z is approach height (move_above), not grasp height (descend) —
    # the rewind now targets move_above for orientation stabilisation.
    assert float(rewind_action[2]) > GRASP_HEIGHT + 0.05


def test_rewind_part_five_targets_move_above_not_descend():
    """Part 5 knock-off rewinds to move_above (not descend) for orientation stabilisation."""
    policy = _policy_with_six_parts()
    lift_step = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "lift_slot_A_5":
            lift_step = int(policy.time_stamps[i])
            break
    assert lift_step is not None
    move_above_start = policy._move_above_pick_start_step(5)
    assert move_above_start is not None
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    assert policy.time_step == max(0, move_above_start - 1)


def test_part5_knockoff_rewinds_at_close_gripper_before_ascent():
    """Part 5 knock-off must rewind at grasp depth, not commit empty carry."""
    policy = _policy_with_six_parts()
    close_step = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "close_gripper_slot_A_5":
            close_step = int(policy.time_stamps[i])
            break
    assert close_step == 1634
    policy.time_step = close_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = close_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    knocked = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert policy.needs_grasp_validation(close_step)
    assert not policy.validate_grasp_hold(ee, knocked)
    assert policy.maybe_rewind_for_failed_grasp(ee, knocked, close_step)
    assert not policy.is_grasp_hold_validated()
    assert policy._grasp_disturbance_pending


def test_mid_lift_knockoff_latches_and_rewinds_with_open_gripper():
    """Part 5 ivj: ball hits during lift_slot_* — must open and re-descend, not empty carry."""
    policy = _policy_with_six_parts()
    lift_mid = _stage_start_step(policy, "lift_slot_") + 15
    assert policy.should_latch_grasp_disturbance(lift_mid)
    policy.time_step = lift_mid
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_mid - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.25], dtype=np.float32)
    knocked = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert policy.needs_grasp_validation(lift_mid)
    assert policy.maybe_rewind_for_failed_grasp(ee, knocked, lift_mid)
    assert policy.should_force_open_gripper()
    rewind_action = policy.peek_action()
    assert float(rewind_action[7]) > 0.5


def test_needs_grasp_validation_through_pick_lift():
    policy = _policy_with_single_pick_place()
    lift_mid = _stage_start_step(policy, "lift_slot_") + 25
    policy.note_grasp_disturbance()
    assert policy.needs_grasp_validation(lift_mid)
    assert not policy.needs_grasp_validation(lift_mid + 60)


def test_part5_knockoff_at_grasp_end_rewinds_not_carry():
    """Late knock-off with part on table must not latch carry when EE already rose."""
    policy = _policy_with_six_parts()
    grasp_end = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "grasp_slot_A_5":
            grasp_end = int(policy.time_stamps[i]) + stage["duration"] - 1
            break
    assert grasp_end == 1684
    policy.time_step = grasp_end
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = grasp_end - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.53], dtype=np.float32)
    part_on_table = np.array([0.6, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert not policy.validate_grasp_hold(ee, part_on_table)
    assert not policy._should_commit_grasp_carry(ee, part_on_table, grasp_end)
    assert policy.maybe_rewind_for_failed_grasp(ee, part_on_table, grasp_end)
    assert not policy.is_grasp_hold_validated()


def test_both_elevated_commits_carry_without_rewind():
    """When EE and part are both lifted, skip descend rewind (4a0bb74 benefit)."""
    policy = _policy_with_six_parts()
    grasp_end = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "grasp_slot_A_5":
            grasp_end = int(policy.time_stamps[i]) + stage["duration"] - 1
            break
    policy.time_step = grasp_end
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = grasp_end - 10  # skip cooldown
    from pick_and_place_policy import GRASP_ASCENT_COMMIT_Z_M

    ee = np.array([0.6, 0.0, GRASP_ASCENT_COMMIT_Z_M + 0.05], dtype=np.float32)
    part_carried = np.array(
        [0.6, 0.0, GRASP_ASCENT_COMMIT_Z_M + 0.02, 1.0, 0.0, 0.0, 0.0],
        dtype=np.float32,
    )
    assert policy.validate_grasp_hold(ee, part_carried)
    assert not policy.maybe_rewind_for_failed_grasp(ee, part_carried, grasp_end)
    assert policy.is_grasp_hold_validated()


def test_validated_grasp_at_close_gripper_blocks_late_rewind():
    policy = _policy_with_single_pick_place()
    close_step = _stage_start_step(policy, "close_gripper_")
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.note_grasp_disturbance()
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    aligned = np.array([0.6, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    policy.time_step = close_step
    assert not policy.maybe_rewind_for_failed_grasp(ee, aligned, close_step)
    assert policy.is_grasp_hold_validated()
    policy.time_step = lift_step
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert not policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)


def test_knockoff_at_grasp_height_still_rewinds_when_xy_misaligned():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert not policy.validate_grasp_hold(ee, misaligned)
    assert policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)


def test_missing_part_pose_triggers_rewind_not_skip():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    assert policy.maybe_rewind_for_failed_grasp(ee, None, lift_step)
    assert policy._grasp_disturbance_pending


def test_rewind_keeps_disturbance_latch_for_revalidation():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    assert policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    assert policy._grasp_disturbance_pending


def test_validate_grasp_hold_warns_when_part_pose_none():
    import logging

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)
    log = logging.getLogger("pick_and_place_policy")
    log.addHandler(handler)
    log.setLevel(logging.WARNING)
    try:
        ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
        assert SingleEnvPickAndPlacePolicy.validate_grasp_hold(ee, None)
        assert any("part_pose missing" in r.getMessage() for r in records)
    finally:
        log.removeHandler(handler)


def test_grasp_rewind_exhausted_emits_event():
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = -10  # skip cooldown (negative = always passed)
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    for _ in range(2):
        policy.time_step = lift_step
        policy._grasp_disturbance_pending = True  # restore after rewind clears it
        policy._grasp_disturbance_step = -10
        assert policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    policy.time_step = lift_step
    policy._grasp_disturbance_pending = True
    policy._grasp_disturbance_step = -10
    assert not policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    assert policy.consume_grasp_rewind_event() == "exhausted"
    assert policy._grasp_carry_aborted
    assert not policy.is_carrying_object(lift_step)
    assert policy.should_force_open_gripper()
    assert policy.should_advance_empty_carry_abort(lift_step)


def test_stabilize_hold_blocks_advance_time_step():
    """advance_time_step must not move the clock while _stabilize_hold_steps > 0."""
    policy = _policy_with_single_pick_place()
    policy._stabilize_hold_steps = 3
    ts_before = policy.time_step
    policy.advance_time_step()
    assert policy.time_step == ts_before
    assert policy._stabilize_hold_steps == 2
    policy.advance_time_step()
    assert policy._stabilize_hold_steps == 1
    policy.advance_time_step()
    assert policy._stabilize_hold_steps == 0
    # Now advance should proceed normally.
    policy.advance_time_step()
    assert policy.time_step == ts_before + 1


def test_note_carry_knock_if_hit_rewinds_to_move_above_with_stabilize_hold():
    """Physics knock during carry rewinds to move_above start + sets hold."""
    policy = _policy_with_single_pick_place()
    # Place the policy in mid-carry: lift stage, carrying object.
    lift_step = _stage_start_step(policy, "lift_slot_") + 10
    policy.time_step = lift_step
    policy._grasp_hold_validated = True  # simulate validated grasp
    assert policy.is_carrying_object(lift_step)

    part_idx = policy.part_index_at_step(lift_step)
    assert part_idx is not None
    move_above_start = policy._move_above_pick_start_step(part_idx)
    assert move_above_start is not None
    assert move_above_start < lift_step

    # Hand touches held object: dist_min_held below threshold.
    rewound = policy.note_carry_knock_if_hit(0.03, lift_step)
    assert rewound
    assert policy.time_step == max(0, move_above_start - 1)
    assert policy._stabilize_hold_steps == 60  # GRASP_STABILIZE_HOLD_STEPS
    assert not policy.is_grasp_hold_validated()
    assert policy._grasp_rewind_event == "knock_rewind"
    assert policy.should_force_open_gripper()


def test_note_carry_knock_if_hit_ignores_when_dist_above_threshold():
    """dist_min_held above HAND_KNOCK_DIST_M must not trigger rewind."""
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_") + 10
    policy.time_step = lift_step
    policy._grasp_hold_validated = True
    orig_ts = policy.time_step

    # Hand is nearby but not touching: 0.10m > 0.06m threshold.
    rewound = policy.note_carry_knock_if_hit(0.10, lift_step)
    assert not rewound
    assert policy.time_step == orig_ts
    assert policy._stabilize_hold_steps == 0
    assert policy.is_grasp_hold_validated()


def test_trigger_vlm_retry_current_part_rewinds_with_stabilize_hold():
    """VLM-detected object loss rewinds to move_above start + sets hold."""
    policy = _policy_with_single_pick_place()
    # Simulate in transit (move_above_box) where VLM would detect loss.
    transit_step = _stage_start_step(policy, "move_above_box_with_") + 10
    policy.time_step = transit_step
    policy._grasp_hold_validated = True
    assert policy.is_carrying_object(transit_step)

    part_idx = policy.part_index_at_step(transit_step)
    assert part_idx is not None
    move_above_start = policy._move_above_pick_start_step(part_idx)
    assert move_above_start is not None

    ok = policy.trigger_vlm_retry_current_part()
    assert ok
    assert policy.time_step == max(0, move_above_start - 1)
    assert policy._stabilize_hold_steps == 60
    assert not policy.is_grasp_hold_validated()
    assert policy._grasp_rewind_event == "vlm_retry"
    assert policy._vlm_retry_count == 1


def test_vlm_retry_exhausted_refuses_rewind():
    """After VLM_MAX_RETRIES, trigger_vlm_retry_current_part returns False."""
    policy = _policy_with_single_pick_place()
    transit_step = _stage_start_step(policy, "move_above_box_with_") + 10
    policy.time_step = transit_step
    policy._grasp_hold_validated = True

    # Exhaust the retry budget.
    for _ in range(2):  # VLM_MAX_RETRIES = 2
        assert policy.trigger_vlm_retry_current_part()
        # Reset state so next call doesn't short-circuit on _grasp_carry_aborted.
        policy._grasp_hold_validated = True
        policy._grasp_carry_aborted = False
        policy.time_step = transit_step

    # Third call must be refused.
    assert not policy.trigger_vlm_retry_current_part()
    assert policy._vlm_retry_count == 2


def test_maybe_rewind_for_failed_grasp_rewinds_to_move_above_with_stabilize_hold():
    """Failed grasp validation rewinds to move_above (not descend) + hold."""
    policy = _policy_with_single_pick_place()
    lift_step = _stage_start_step(policy, "lift_slot_")
    policy.time_step = lift_step
    policy.note_grasp_disturbance()
    policy._grasp_disturbance_step = lift_step - 10  # skip cooldown
    ee = np.array([0.6, 0.0, 0.13], dtype=np.float32)
    misaligned = np.array([0.72, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    part_idx = policy.part_index_at_step(lift_step)
    assert part_idx is not None
    move_above_start = policy._move_above_pick_start_step(part_idx)
    assert move_above_start is not None
    # Verify the rewind target is move_above, not descend.
    descend_start = policy._descend_to_pick_start_step(part_idx)
    assert move_above_start < descend_start
    assert descend_start < lift_step

    assert policy.maybe_rewind_for_failed_grasp(ee, misaligned, lift_step)
    assert policy.time_step == max(0, move_above_start - 1)
    assert policy._stabilize_hold_steps == 60
    assert policy._grasp_rewind_attempts == 1
    assert policy._grasp_rewind_event == "rewind"


def test_clear_grasp_disturbance_resets_stabilize_hold():
    """clear_grasp_disturbance() must zero _stabilize_hold_steps."""
    policy = _policy_with_single_pick_place()
    policy._stabilize_hold_steps = 60
    policy._grasp_disturbance_pending = True
    policy._grasp_rewind_attempts = 1
    policy._grasp_rewind_force_open = True

    policy.clear_grasp_disturbance()
    assert policy._stabilize_hold_steps == 0
    assert not policy._grasp_disturbance_pending
    assert policy._grasp_rewind_attempts == 0
    assert not policy._grasp_rewind_force_open


def test_pick_descend_is_approach_not_transit():
    policy = _policy_with_six_parts()
    descend = _stage_start_step(policy, "descend_to_slot_A_5") + 10
    close_step = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "close_gripper_slot_A_5":
            close_step = int(policy.time_stamps[i])
            break
    lift_step = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "lift_slot_A_5":
            lift_step = int(policy.time_stamps[i])
            break
    assert policy.transport_phase_at_step(descend) == "approach"
    assert policy.transport_phase_at_step(close_step) == "approach"
    assert policy.transport_phase_at_step(lift_step) == "transit"


def test_pick_descend_blocks_transit_ttc_replan():
    """Part 5 @ ts~1625: pick descend must not emit ttc transit replan."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            ttc_replan_trigger_threshold=6,
            ttc_replan_hand_speed_min=0.05,
            ttc_forecast_replan_threshold=1.0,
            held_critical_replan_enabled=True,
        )
    )
    policy = _policy_with_six_parts()
    descend = _stage_start_step(policy, "descend_to_slot_A_5") + 25
    ttc_stop = GateResult(
        g_t=GateDecision.STOP,
        reason="ttc",
        metadata={
            "dist_min_envelope": 0.12,
            "dist_ee_human": 0.45,
            "trigger_rule": "ttc",
            "ttc_forecast_s": 0.5,
        },
    )
    req = trigger.update(
        _state(descend),
        ttc_stop,
        task_time_step=descend,
        transport_phase=policy.transport_phase_at_step(descend),
    )
    assert req is None


def test_should_latch_grasp_disturbance_only_at_grasp_depth():
    policy = _policy_with_six_parts()
    close_step = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "close_gripper_slot_A_5":
            close_step = int(policy.time_stamps[i])
            break
    grasp_start = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "grasp_slot_A_5":
            grasp_start = int(policy.time_stamps[i])
            break
    lift_step = None
    for i, stage in enumerate(policy.stage_sequence):
        if stage["name"] == "lift_slot_A_5":
            lift_step = int(policy.time_stamps[i])
            break
    assert close_step is not None and grasp_start is not None and lift_step is not None
    assert policy.should_latch_grasp_disturbance(close_step)
    assert policy.should_latch_grasp_disturbance(grasp_start)
    assert policy.should_latch_grasp_disturbance(lift_step + 10)
    assert not policy.should_latch_grasp_disturbance(
        _stage_start_step(policy, "lift_after_releasing_") + 5
    )
    policy._grasp_rewind_force_open = True
    assert not policy.should_latch_grasp_disturbance(close_step, replan_active=False)
    policy._grasp_rewind_force_open = False
    assert not policy.should_latch_grasp_disturbance(
        close_step, replan_active=True
    )


def test_replan_splice_clears_grasp_disturbance_on_pick_approach():
    policy = _policy_with_six_parts()
    descend = _stage_start_step(policy, "descend_to_slot_A_5") + 10
    policy.note_grasp_disturbance()
    policy.on_replan_splice_applied(descend)
    assert not policy._grasp_disturbance_pending


def test_replan_splice_clears_grasp_disturbance_on_transit_carry():
    policy = _policy_with_six_parts()
    carry = _stage_start_step(policy, "lift_slot_") + 10
    policy.mark_grasp_hold_validated()
    policy._grasp_disturbance_pending = True
    policy.on_replan_splice_applied(carry)
    assert policy._grasp_disturbance_pending

    policy2 = _policy_with_six_parts()
    carry2 = _stage_start_step(policy2, "lift_slot_") + 10
    policy2.note_grasp_disturbance()
    policy2.on_replan_splice_applied(carry2)
    assert policy2._grasp_disturbance_pending

    policy3 = _policy_with_six_parts()
    carry3 = _stage_start_step(policy3, "move_above_box_with_") + 10
    policy3.mark_grasp_hold_validated()
    policy3._grasp_disturbance_pending = True
    policy3.on_replan_splice_applied(carry3)
    assert not policy3._grasp_disturbance_pending


def test_transit_detour_inserts_place_realign_waypoints():
    policy = _policy_with_single_pick_place()
    at_step = _stage_start_step(policy, "lift_slot_") + 10
    assert policy.transport_phase_at_step(at_step) == "transit"
    old_len = len(policy.stage_sequence)
    policy.time_step = at_step
    ee = np.array([0.70, 0.20, 0.40], dtype=np.float32)
    policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=ee,
        human_hand_pos=np.array([0.72, 0.22, 0.2], dtype=np.float32),
        raise_m=0.05,
        lateral_m=0.15,
        detour_duration=20,
        detour_strategy="lateral_first",
        lateral_first_raise_m=0.02,
    )
    prefix_end = max(
        int(np.searchsorted(policy.time_stamps, at_step, side="right")) - 1,
        0,
    )
    names = [
        policy.stage_sequence[prefix_end + i]["name"]
        for i in range(1, len(policy.stage_sequence) - old_len + 1)
    ]
    assert "replan_realign_place" in names
    assert names.index("replan_realign_place") < names.index("replan_detour_rejoin")
    place_xy = policy._upcoming_place_target_at_rejoin(
        policy._compute_rejoin_step(at_step, 20)
    )
    realign_idx = names.index("replan_realign_place")
    realign_pos = policy.pos_traj[prefix_end + 1 + realign_idx]
    assert abs(float(realign_pos[2]) - 0.40) < 1e-5
    assert place_xy is not None
    assert float(np.linalg.norm(realign_pos[:2] - place_xy)) < 1e-4


def test_should_hold_release_blocks_tilted_part():
    policy = _policy_with_single_pick_place()
    open_step = _open_gripper_step(policy)
    ee = np.array([0.8, 0.0, 0.13], dtype=np.float32)
    upright_pose = np.array([0.8, 0.0, 0.13, 1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    tilted_pose = np.array(
        [0.8, 0.0, 0.13, 0.96, 0.28, 0.0, 0.0], dtype=np.float64
    )
    # PLACE_RELEASE_UPRIGHT_MIN_DOT = -1.0 is effectively disabled — tilt alone
    # does not block release during place.  XY proximity to slot is the primary gate.
    assert not policy.should_hold_release(ee, upright_pose, open_step)
    # Tilted but at correct XY → still allowed (upright check disabled for place).
    assert not policy.should_hold_release(ee, tilted_pose, open_step)
    # Outside place zone → blocked regardless of orientation.
    far_ee = np.array([0.95, 0.0, 0.13], dtype=np.float32)
    assert policy.should_hold_release(far_ee, tilted_pose, open_step)


def test_should_block_place_advance_only_when_hand_near():
    policy = _policy_with_single_pick_place()
    open_step = _open_gripper_step(policy)
    far_ee = np.array([0.95, 0.0, 0.13], dtype=np.float32)
    in_zone_ee = np.array([0.8, 0.0, 0.13], dtype=np.float32)
    assert policy.should_hold_open_gripper(far_ee, open_step)
    # Block when hand is near AND EE is outside the place zone.
    assert policy.should_block_place_advance_while_hand_near(
        far_ee, open_step, dist_ee_human=0.25, safe_dist_warn=0.19
    )
    # Block when hand is within warn distance AND EE is outside zone.
    assert policy.should_block_place_advance_while_hand_near(
        far_ee, open_step, dist_ee_human=0.12, safe_dist_warn=0.19
    )
    # When EE is inside the place zone, tilt alone does NOT block
    # (PLACE_RELEASE_UPRIGHT_MIN_DOT = -1.0 is disabled).
    tilted_pose = np.array(
        [0.8, 0.0, 0.13, 0.96, 0.28, 0.0, 0.0], dtype=np.float64
    )
    # In-zone EE + tilt → no hold (upright check disabled for place).
    assert not policy.should_hold_release(in_zone_ee, tilted_pose, open_step)
    # In-zone EE → block cleared when hand is outside warn distance.
    assert not policy.should_block_place_advance_while_hand_near(
        in_zone_ee,
        open_step,
        dist_ee_human=0.25,
        safe_dist_warn=0.19,
        part_pose=tilted_pose,
    )
    # When EE is inside the place zone, the block is lifted even if hand is
    # nearby — the EE is aligned with the slot so release can proceed safely.
    assert not policy.should_block_place_advance_while_hand_near(
        in_zone_ee,
        open_step,
        dist_ee_human=0.12,
        safe_dist_warn=0.19,
        part_pose=tilted_pose,
    )
    descend_step = _descend_to_box_step(policy)
    assert not policy.should_block_place_advance_while_hand_near(
        far_ee,
        descend_step,
        dist_ee_human=0.25,
        safe_dist_warn=0.19,
    )


def test_place_progress_hold_clears_when_hand_clears_warn():
    policy = _policy_with_single_pick_place()
    descend_step = _descend_to_box_step(policy)
    blocked_ee = np.array([0.8, 0.0, 0.60], dtype=np.float32)
    policy.should_wait_hold_place_progress(
        blocked_ee, descend_step, dist_ee_human=0.12, safe_dist_warn=0.19
    )
    assert policy._place_progress_hold
    assert not policy.should_wait_hold_place_progress(
        blocked_ee,
        descend_step + 1,
        dist_ee_human=0.20,
        safe_dist_warn=0.19,
    )
    assert not policy._place_progress_hold


def test_fast_hand_transit_carry_prefers_retreat_over_lateral():
    strategy_mod = _strategy_mod
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.45,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=0.09,
        closest_primitive_id="held:fixed_box",
        hand_speed=0.25,
        trigger_rule="held_critical_early",
        ee_pos=(0.7, 0.0, 0.45),
        human_hand_pos=(0.72, 0.02, 0.38),
    )
    assert plan.strategy == strategy_mod.DetourStrategy.RETREAT_THEN_ARC


def test_should_wait_hold_late_approach_when_elevated():
    policy = _policy_with_six_parts()
    at_step = 1784
    ee = np.array([0.8, 0.0, 0.60], dtype=np.float32)
    assert policy.should_wait_hold_place_progress(ee, at_step)
    assert policy._place_progress_hold


def test_should_wait_hold_place_progress_when_blocked_elevated():
    policy = _policy_with_single_pick_place()
    descend_step = _descend_to_box_step(policy)
    ee = np.array([0.8, 0.0, 0.60], dtype=np.float32)
    assert policy.should_wait_hold_place_progress(ee, descend_step)
    assert policy._place_progress_hold
    assert not policy.should_wait_hold_place_progress(
        np.array([0.8, 0.0, 0.53], dtype=np.float32), descend_step + 50
    )
    assert not policy._place_progress_hold

    policy2 = _policy_with_single_pick_place()
    ok_step = _descend_to_box_step(policy2)
    sim_ee = np.array([0.8, 0.0, 0.28], dtype=np.float32)
    assert not policy2.should_wait_hold_place_progress(sim_ee, ok_step)


def test_place_progress_hold_clears_when_human_moves_away():
    policy = _policy_with_single_pick_place()
    descend_step = _descend_to_box_step(policy)
    blocked_ee = np.array([0.8, 0.0, 0.60], dtype=np.float32)
    assert policy.should_wait_hold_place_progress(blocked_ee, descend_step)
    assert policy._place_progress_hold
    assert not policy.should_wait_hold_place_progress(
        blocked_ee,
        descend_step + 1,
        dist_ee_human=0.25,
        safe_dist_warn=0.19,
    )
    assert not policy._place_progress_hold


def test_should_hold_open_gripper_when_elevated():
    policy = _policy_with_single_pick_place()
    open_step = _open_gripper_step(policy)
    far_ee = np.array([0.95, 0.0, 0.53], dtype=np.float32)
    assert policy.should_hold_open_gripper(far_ee, open_step)


def test_should_hold_open_gripper_out_of_zone():
    policy = _policy_with_single_pick_place()
    open_step = _open_gripper_step(policy)
    far_ee = np.array([0.95, 0.0, 0.13], dtype=np.float32)
    assert policy.should_hold_open_gripper(far_ee, open_step)
    in_zone_ee = np.array([0.8, 0.0, 0.13], dtype=np.float32)
    assert not policy.should_hold_open_gripper(in_zone_ee, open_step)


def test_descend_gripper_stays_closed_no_interp_bleed():
    """Gripper must not interpolate open during descend before open_gripper stage."""
    policy = _policy_with_single_pick_place()
    descend_start = _descend_to_box_step(policy)
    open_start = _open_gripper_step(policy)
    descend_end = open_start - 1
    for step in range(descend_start, open_start):
        grip = policy._gripper_at_step(step)
        assert grip == policy.gripper_closed, f"step={step} grip={grip}"
    assert policy._gripper_at_step(open_start) == policy.gripper_open
    assert policy._gripper_at_step(descend_end) == policy.gripper_closed


def test_release_gripper_committed_through_lift_after():
    """Once release opens, hold_* must not re-close through lift_after_releasing."""
    policy = _policy_with_single_pick_place()
    open_start = _open_gripper_step(policy)
    lift_start = _stage_start_step(policy, "lift_after_releasing_")
    far_ee = np.array([0.95, 0.0, 0.13], dtype=np.float32)
    tilted_pose = np.array(
        [0.8, 0.0, 0.13, 0.96, 0.28, 0.0, 0.0], dtype=np.float64
    )

    assert policy.should_hold_open_gripper(far_ee, open_start)
    policy.mark_release_gripper_open()
    for step in range(open_start, lift_start + 10):
        assert not policy.should_hold_open_gripper(far_ee, step)
        assert not policy.should_hold_release(far_ee, tilted_pose, step)
        assert policy.should_keep_release_gripper_open(step)


def _simulate_agent_gripper(
    policy: SingleEnvPickAndPlacePolicy,
    *,
    task_time_step: int,
    ee_pos: np.ndarray,
    part_pose: np.ndarray | None = None,
    held_object_active: bool = False,
    gate_allow: bool = True,
) -> float:
    """Mirror gm_state_machine_agent gripper override order (gripper dim only)."""
    policy.time_step = task_time_step
    proposed_g = float(policy.get_action({}, advance=False)[7])
    safe_g = proposed_g
    eval_steps = policy.gripper_hold_eval_steps(task_time_step)
    if held_object_active and not gate_allow:
        boosted = policy.gripper_closed - 0.15
        if safe_g > boosted:
            safe_g = boosted
    if policy.should_force_open_gripper():
        return float(policy.gripper_open)
    keep_open = policy.should_keep_release_gripper_open(task_time_step + 1)
    if keep_open:
        safe_g = float(policy.gripper_open)
    elif (
        not policy._release_gripper_committed
        and policy.stage_name_at_step(task_time_step + 1).startswith(
            "open_gripper_to_release_"
        )
        and safe_g > (policy.gripper_open + policy.gripper_closed) / 2.0
        and not any(
            policy.should_hold_release(ee_pos, part_pose, step)
            or policy.should_hold_open_gripper(ee_pos, step)
            for step in eval_steps
        )
    ):
        policy.mark_release_gripper_open()
    if not keep_open and not policy._release_gripper_committed:
        for step in eval_steps:
            if policy.should_hold_open_gripper(ee_pos, step):
                safe_g = policy.gripper_closed
                break
            if policy.should_hold_release(ee_pos, part_pose, step):
                safe_g = policy.gripper_closed
                break
    return safe_g


def test_open_gripper_action_stays_at_grasp_height():
    """open_gripper stage must not interpolate Z toward lift_after before release."""
    policy = _policy_with_single_pick_place()
    open_start = _open_gripper_step(policy)
    open_end = open_start + int(
        policy.stage_sequence[
            next(
                i
                for i, s in enumerate(policy.stage_sequence)
                if s["name"].startswith("open_gripper_to_release_")
            )
        ]["duration"]
    ) - 1
    grasp_z = policy.stage_sequence[
        next(
            i
            for i, s in enumerate(policy.stage_sequence)
            if s["name"].startswith("open_gripper_to_release_")
        )
    ]["pos"][2]
    for step in range(open_start, open_end + 1):
        action = policy._action_at_step(step)
        assert abs(float(action[2]) - float(grasp_z)) < 1e-6, f"step={step} z={action[2]}"


def test_keep_release_requires_commit_not_lift_after_stage():
    policy = _policy_with_single_pick_place()
    lift_start = _stage_start_step(policy, "lift_after_releasing_")
    assert not policy.should_keep_release_gripper_open(lift_start)
    policy.mark_release_gripper_open()
    assert policy.should_keep_release_gripper_open(lift_start)


def test_get_action_gripper_does_not_lead_stage_at_descend_end():
    """Last descend task_ts must propose closed gripper (not next-stage open)."""
    policy = _policy_with_single_pick_place()
    open_start = _open_gripper_step(policy)
    descend_end = open_start - 1
    policy.time_step = descend_end
    action = policy.get_action({}, advance=False)
    assert action[7] == policy.gripper_closed
    assert policy._gripper_at_step(open_start) == policy.gripper_open


def test_action_at_step_descend_never_exceeds_carry_threshold():
    """Raw stage lookup stays closed for every descend step."""
    policy = _policy_with_single_pick_place()
    descend_start = _descend_to_box_step(policy) - 10
    open_start = _open_gripper_step(policy)
    carry_threshold = (policy.gripper_open + policy.gripper_closed) / 2.0
    for step in range(descend_start, open_start):
        if not policy.stage_name_at_step(step).startswith("descend_to_box_with_"):
            continue
        grip = float(policy._action_at_step(step)[7])
        assert grip <= carry_threshold, f"step={step} grip={grip}"


def test_release_committed_prevents_hold_reclose_agent_sim():
    """After mark_release, agent-style sim must not re-close in open/lift window."""
    policy = _policy_with_single_pick_place()
    open_start = _open_gripper_step(policy)
    lift_start = _stage_start_step(policy, "lift_after_releasing_")
    ee = np.array([0.8, 0.0, 0.13], dtype=np.float32)
    tilted = np.array([0.8, 0.0, 0.13, 0.96, 0.28, 0.0, 0.0], dtype=np.float64)
    carry_threshold = (policy.gripper_open + policy.gripper_closed) / 2.0

    policy.time_step = open_start
    policy.mark_release_gripper_open()
    for task_ts in range(open_start, lift_start + 15):
        g = _simulate_agent_gripper(
            policy,
            task_time_step=task_ts,
            ee_pos=ee,
            part_pose=tilted,
        )
        assert g > carry_threshold, f"re-close at task_ts={task_ts} g={g}"


def test_descend_gripper_stays_closed_no_interp_bleed():
    """Gripper must not interpolate open during descend before open_gripper stage."""
    policy = _policy_with_single_pick_place()
    descend_start = _descend_to_box_step(policy)
    open_start = _open_gripper_step(policy)
    for step in range(descend_start, open_start):
        grip = policy._gripper_at_step(step)
        assert grip == policy.gripper_closed, f"step={step} grip={grip}"
    assert policy._gripper_at_step(open_start) == policy.gripper_open
    assert policy._gripper_at_step(open_start - 1) == policy.gripper_closed


def test_gripper_open_stays_open_through_lift_after_offline():
    """Offline agent-style trace: no re-close after release opens for lift_after."""
    policy = _policy_with_single_pick_place()
    open_start = _open_gripper_step(policy)
    lift_start = _stage_start_step(policy, "lift_after_releasing_")
    far_ee = np.array([0.95, 0.0, 0.13], dtype=np.float32)
    tilted_pose = np.array(
        [0.8, 0.0, 0.13, 0.96, 0.28, 0.0, 0.0], dtype=np.float64
    )
    carry_threshold = (policy.gripper_open + policy.gripper_closed) / 2.0

    descend_trace: list[float] = []
    for task_ts in range(open_start - 5, open_start):
        policy.time_step = task_ts
        descend_trace.append(
            _simulate_agent_gripper(
                policy,
                task_time_step=task_ts,
                ee_pos=far_ee,
                part_pose=tilted_pose,
            )
        )
    assert all(g == policy.gripper_closed for g in descend_trace)

    policy.time_step = lift_start - 1
    policy.mark_release_gripper_open()
    policy.advance_time_step()
    assert policy._release_gripper_committed

    post_release_trace: list[float] = []
    for task_ts in range(lift_start, lift_start + 20):
        policy.time_step = task_ts
        post_release_trace.append(
            _simulate_agent_gripper(
                policy,
                task_time_step=task_ts,
                ee_pos=far_ee,
                part_pose=tilted_pose,
            )
        )
    assert all(g > carry_threshold for g in post_release_trace)


def test_should_hold_false_after_replan_stage_drift():
    """Replan splice shifts time_stamps; gripper_traj must gate open, not stage name."""
    policy = _policy_with_single_pick_place()
    obs = {
        "slot_A_1_T": np.eye(4),
        "slot_B_1_T": np.eye(4),
    }
    obs["slot_A_1_T"][:3, 3] = [0.6, 0.0, 0.0]
    obs["slot_B_1_T"][:3, 3] = [0.8, 0.0, 0.0]
    policy.user_commands = [{"pick": "A@1", "place": "B@1"}]
    policy.reset(obs)
    at_step = 200
    policy.time_step = at_step
    policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=np.array([0.7, 0.2, 0.4], dtype=np.float32),
        human_hand_pos=np.array([0.72, 0.22, 0.2], dtype=np.float32),
        raise_m=0.05,
        lateral_m=0.15,
        detour_duration=30,
    )
    check_step = at_step + 90
    ee = np.array([0.95, 0.0, 0.4], dtype=np.float32)
    grip = policy._gripper_at_step(check_step)
    carry_threshold = (policy.gripper_open + policy.gripper_closed) / 2.0
    if grip <= carry_threshold:
        assert not policy.should_hold_open_gripper(ee, check_step)


def _policy_with_six_parts():
    policy = SingleEnvPickAndPlacePolicy()
    obs = {
        "slot_A_1_T": np.eye(4),
        "slot_B_1_T": np.eye(4),
    }
    obs["slot_A_1_T"][:3, 3] = [0.6, 0.0, 0.0]
    obs["slot_B_1_T"][:3, 3] = [0.8, 0.0, 0.0]
    for i in range(2, 7):
        obs[f"slot_A_{i}_T"] = obs["slot_A_1_T"].copy()
        obs[f"slot_B_{i}_T"] = obs["slot_B_1_T"].copy()
        obs[f"slot_A_{i}_T"][0, 3] += 0.01 * (i - 1)
        obs[f"slot_B_{i}_T"][1, 3] += 0.01 * (i - 1)
    policy.user_commands = [{"pick": f"A@{i}", "place": f"B@{i}"} for i in range(1, 7)]
    policy.reset(obs)
    return policy


def test_approach_rejoin_stays_in_current_part():
    """Part 5 @ ts~1771: rejoin must not jump to part 6 pick transit."""
    policy = _policy_with_six_parts()
    at_step = 1771
    detour_duration = 60
    naive_rejoin = at_step + 3 * detour_duration
    capped = policy._compute_rejoin_step(at_step, detour_duration)
    assert capped < naive_rejoin
    assert policy.stage_name_at_step(capped).startswith("move_above_box_with_")

    old_times = policy.time_stamps.copy()
    old_pos = policy.pos_traj.copy()
    naive_xy = old_pos[
        np.searchsorted(old_times, naive_rejoin, side="right") - 1, :2
    ]
    place_xy = policy.place_target_xy_at_step(at_step)
    naive_dist = float(np.linalg.norm(naive_xy - place_xy))
    assert naive_dist > 0.1

    policy.time_step = at_step
    policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=np.array([0.8, 0.0, 0.35], dtype=np.float32),
        human_hand_pos=np.array([0.72, 0.22, 0.2], dtype=np.float32),
        raise_m=0.04,
        lateral_m=0.10,
        detour_duration=detour_duration,
    )
    prefix_end = max(
        int(np.searchsorted(old_times, at_step, side="right")) - 1,
        0,
    )
    rejoin_xy = policy.pos_traj[prefix_end + 3, :2]
    rejoin_dist = float(np.linalg.norm(rejoin_xy - place_xy))
    assert rejoin_dist < naive_dist
    assert rejoin_dist <= 0.15


def test_executor_poll_does_not_leave_stale_completed():
    executor_mod = _load("safety.replan.executor", REPLAN / "executor.py")
    executor_mod.__package__ = "safety.replan"
    GeometryReplanV0 = executor_mod.GeometryReplanV0
    ReplanHint = replan_types_mod.ReplanHint
    ReplanRequest = replan_types_mod.ReplanRequest

    executor = GeometryReplanV0()
    req_a = ReplanRequest(
        request_id="a",
        step_index=10,
        task_time_step=1771,
        trigger_source="l1_warn",
        trigger_rule="static_warn",
        dist_ee_human=0.15,
        dist_min=0.15,
        g_rule=2,
        ee_pos=(0.8, 0.0, 0.35),
        human_hand_pos=(0.72, 0.22, 0.2),
        hint=ReplanHint(),
        created_at_s=0.0,
    )
    executor.submit(req_a)
    done_a = executor.poll()
    assert done_a is not None
    assert executor.poll() is None

    req_b = ReplanRequest(
        request_id="b",
        step_index=3000,
        task_time_step=2666,
        trigger_source="l1_warn",
        trigger_rule="static_warn",
        dist_ee_human=0.15,
        dist_min=0.15,
        g_rule=2,
        ee_pos=(0.8, 0.0, 0.35),
        human_hand_pos=(0.72, 0.22, 0.2),
        hint=ReplanHint(),
        created_at_s=0.0,
    )
    executor.submit(req_b)
    done_b = executor.poll()
    assert done_b is not None
    assert done_b.request_id == "b"
    assert done_b.resume_time_step == 2666


def test_defer_replan_in_approach_when_hand_very_near():
    """Approach @ dist=0.14 (<0.15): defer → wait-hold, no splice."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(replan_trigger_threshold=3, safe_dist_warn=0.19)
    )
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={
            "dist_min_envelope": 0.10,
            "dist_ee_human": 0.14,
            "trigger_rule": "static_warn",
        },
    )
    for step in (1, 2):
        assert (
            trigger.update(
                _state(step),
                slow,
                task_time_step=1771,
                transport_phase="approach",
            )
            is None
        )
    req = trigger.update(
        _state(3),
        slow,
        task_time_step=1771,
        transport_phase="approach",
    )
    assert req is None


def test_approach_allows_replan_when_dist_above_defer():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=3))
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={"dist_ee_human": 0.173, "trigger_rule": "static_warn"},
    )
    # 8.5: approach/place non-held_critical replan blocked → uses transit.
    for step in (1, 2):
        trigger.update(_state(step), slow, task_time_step=1771, transport_phase="transit")
    req = trigger.update(
        _state(3), slow, task_time_step=1771, transport_phase="transit"
    )
    assert req is not None


def test_approach_place_post_replan_advance_disabled():
    executor_mod = _load("safety.replan.executor", REPLAN / "executor.py")
    executor_mod.__package__ = "safety.replan"
    GeometryReplanV0 = executor_mod.GeometryReplanV0
    ReplanHint = replan_types_mod.ReplanHint
    ReplanRequest = replan_types_mod.ReplanRequest

    policy = _policy_with_single_pick_place()
    # move_above_box stage start
    at_step = int(
        next(
            policy.time_stamps[i]
            for i, s in enumerate(policy.stage_sequence)
            if s["name"].startswith("move_above_box_with_")
        )
    )
    policy.time_step = at_step

    executor = GeometryReplanV0()
    request = ReplanRequest(
        request_id="test-approach",
        step_index=100,
        task_time_step=at_step,
        trigger_source="l1_warn",
        trigger_rule="static_warn",
        dist_ee_human=0.25,
        dist_min=0.25,
        g_rule=2,
        ee_pos=(0.8, 0.0, 0.35),
        human_hand_pos=(0.82, 0.02, 0.2),
        hint=ReplanHint(),
        created_at_s=0.0,
    )
    executor.submit(request)
    done = executor.poll()
    assert done is not None
    assert executor.apply(done, policy)
    applied = executor.result_after_apply(done.request_id)
    assert applied is not None
    assert applied.post_replan_advance_until == -1


def test_place_phase_replan_disables_post_replan_advance():
    executor_mod = _load("safety.replan.executor", REPLAN / "executor.py")
    executor_mod.__package__ = "safety.replan"
    GeometryReplanV0 = executor_mod.GeometryReplanV0
    ReplanHint = replan_types_mod.ReplanHint
    ReplanRequest = replan_types_mod.ReplanRequest
    ReplanResult = replan_types_mod.ReplanResult

    policy = _policy_with_single_pick_place()
    at_step = _descend_to_box_step(policy)
    policy.time_step = at_step

    executor = GeometryReplanV0()
    request = ReplanRequest(
        request_id="test-place",
        step_index=100,
        task_time_step=at_step,
        trigger_source="l1_warn",
        trigger_rule="static_warn",
        dist_ee_human=0.15,
        dist_min=0.15,
        g_rule=2,
        ee_pos=(0.8, 0.0, 0.13),
        human_hand_pos=(0.82, 0.02, 0.2),
        hint=ReplanHint(),
        created_at_s=0.0,
    )
    executor.submit(request)
    done = executor.poll()
    assert done is not None
    assert executor.apply(done, policy)
    applied = executor.result_after_apply(done.request_id)
    assert applied is not None
    assert applied.post_replan_advance_until == -1


def _load_replan_strategy():
    return _strategy_mod


def test_select_lateral_first_when_z_headroom_low():
    """LATERAL_FIRST wins when z headroom is tight (ee near ceiling).

    Uses explicit z_max=0.75 (original transit ceiling before R7 raised to 0.90)
    so the test is invariant to future ceiling adjustments.
    """
    strategy_mod = _load_replan_strategy()
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.70,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=0.18,
        closest_primitive_id="arm:shoulder_link",
        z_max=0.75,  # low ceiling → headroom=0.05 < 0.08 → lateral_first
        ee_pos=(0.7, 0.0, 0.70),
        human_hand_pos=(0.72, 0.02, 0.2),
    )
    assert plan.strategy == strategy_mod.DetourStrategy.LATERAL_FIRST
    assert plan.raise_m < 0.06


def test_select_retreat_arc_when_held_closest():
    strategy_mod = _load_replan_strategy()
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.45,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=0.09,
        closest_primitive_id="held:fixed_box",
        ee_pos=(0.7, 0.0, 0.45),
        human_hand_pos=(0.72, 0.02, 0.2),
    )
    assert plan.strategy == strategy_mod.DetourStrategy.RETREAT_THEN_ARC
    assert plan.lateral_m > 0.10
    assert plan.retreat_m > 0.0


def test_lateral_first_splice_orders_waypoints():
    policy = _policy_with_single_pick_place()
    at_step = 200
    policy.time_step = at_step
    ee = np.array([0.7, 0.2, 0.68], dtype=np.float32)
    policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=ee,
        human_hand_pos=np.array([0.72, 0.22, 0.2], dtype=np.float32),
        raise_m=0.05,
        lateral_m=0.12,
        detour_duration=20,
        detour_strategy="lateral_first",
        lateral_first_raise_m=0.02,
    )
    prefix_end = max(
        int(np.searchsorted(policy.time_stamps, at_step, side="right")) - 1,
        0,
    )
    names = [policy.stage_sequence[prefix_end + i]["name"] for i in range(1, 4)]
    assert names[0] == "replan_detour_lateral"
    assert names[1] == "replan_detour_raise"
    z0 = policy.pos_traj[prefix_end + 1, 2]
    z1 = policy.pos_traj[prefix_end + 2, 2]
    assert abs(z0 - ee[2]) < 1e-5
    assert z1 > z0


def test_trigger_passes_envelope_fields():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={
            "dist_min_envelope": 0.14,
            "dist_min_held": 0.11,
            "closest_primitive_id": "held:fixed_box",
            "dist_ee_human": 0.20,
            "trigger_rule": "static_warn",
        },
    )
    req = trigger.update(_state(100), slow, task_time_step=640, transport_phase="transit")
    assert req is not None
    assert abs(req.dist_min_held - 0.11) < 1e-6
    assert req.closest_primitive_id == "held:fixed_box"
    assert req.dist_min_envelope == 0.14


def test_defer_replan_when_held_critical_in_place():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="warn",
        metadata={
            "dist_min_envelope": 0.16,
            "dist_min_held": 0.08,
            "dist_ee_human": 0.25,
            "trigger_rule": "static_warn",
        },
    )
    req = trigger.update(
        _state(100),
        slow,
        task_time_step=500,
        transport_phase="place",
    )
    assert req is None


def test_held_critical_early_warn_emits_replan_before_stop():
    """Fast hand + held warn zone in transit → replan before Tier0 held_critical STOP."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            safe_dist_warn=0.19,
            ttc_replan_hand_speed_min=0.05,
            safe_dist_hard_stop=0.13,
            held_critical_replan_enabled=True,
        )
    )
    slow = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="static_warning",
        metadata={
            "dist_min_envelope": 0.16,
            "dist_min_held": 0.15,
            "closest_primitive_id": "held:fixed_box",
            "dist_ee_human": 0.22,
            "trigger_rule": "static",
        },
    )
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.0, 0.40]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.72, 0.02, 0.38]),
        human_hand_vel=np.array([0.3, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=33.4,
        step_index=1670,
    )
    trigger.update(moving, slow, task_time_step=1670, transport_phase="transit")
    moving.step_index = 1671
    moving.human_hand_pos = np.array([0.725, 0.02, 0.38])
    slow_closer = GateResult(
        g_t=GateDecision.SLOW_DOWN,
        reason="static_warning",
        metadata={
            "dist_min_envelope": 0.14,
            "dist_min_held": 0.14,
            "closest_primitive_id": "held:fixed_box",
            "dist_ee_human": 0.20,
            "trigger_rule": "static",
        },
    )
    req = trigger.update(moving, slow_closer, task_time_step=1671, transport_phase="transit")
    assert req is not None
    assert req.trigger_rule == "held_critical_early"
    assert req.g_rule == int(GateDecision.SLOW_DOWN)


def test_fast_hand_speed_boosts_lateral_or_retreat():
    strategy_mod = _strategy_mod
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.45,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=0.14,
        closest_primitive_id="held:fixed_box",
        hand_speed=0.25,
        trigger_rule="held_critical_early",
        ee_pos=(0.7, 0.0, 0.45),
        human_hand_pos=(0.72, 0.02, 0.38),
    )
    assert plan.strategy in (
        strategy_mod.DetourStrategy.LATERAL_FIRST,
        strategy_mod.DetourStrategy.RETREAT_THEN_ARC,
    )


def test_held_critical_stop_transit_emits_immediate_replan():
    """Transit carry/lift: held_critical Tier0 STOP may trigger detour (ivj_intrusion_positive v7)."""
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=50,
            held_critical_replan_enabled=True,
        )
    )
    stop = GateResult(
        g_t=GateDecision.STOP,
        reason="held_critical",
        metadata={
            "dist_min_envelope": 0.08,
            "dist_min_held": 0.08,
            "closest_primitive_id": "held:fixed_box",
            "dist_ee_human": 0.20,
            "trigger_rule": "held_critical",
        },
    )
    req = trigger.update(
        _state(1696),
        stop,
        task_time_step=1696,
        transport_phase="transit",
    )
    assert req is not None
    assert req.trigger_rule == "held_critical"
    assert req.g_rule == int(GateDecision.STOP)
    assert req.dist_min_held == 0.08
    assert req.closest_primitive_id == "held:fixed_box"


def test_held_critical_stop_transit_blocked_without_opt_in():
    """block_place / fast_sweep: held_critical replan stays off unless preset enables it."""
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=50))
    stop = GateResult(
        g_t=GateDecision.STOP,
        reason="held_critical",
        metadata={
            "dist_min_envelope": 0.08,
            "dist_min_held": 0.08,
            "closest_primitive_id": "held:fixed_box",
            "dist_ee_human": 0.20,
            "trigger_rule": "held_critical",
        },
    )
    req = trigger.update(
        _state(1696),
        stop,
        task_time_step=1696,
        transport_phase="transit",
    )
    assert req is None


def test_held_critical_stop_place_still_blocks_replan():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    stop = GateResult(
        g_t=GateDecision.STOP,
        reason="held_critical",
        metadata={
            "dist_min_envelope": 0.08,
            "dist_min_held": 0.08,
            "dist_ee_human": 0.20,
            "trigger_rule": "held_critical",
        },
    )
    req = trigger.update(
        _state(100),
        stop,
        task_time_step=500,
        transport_phase="place",
    )
    assert req is None


def test_static_tier0_stop_transit_still_blocks_replan():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    stop = GateResult(
        g_t=GateDecision.STOP,
        reason="tier0",
        metadata={
            "dist_min_envelope": 0.10,
            "dist_ee_human": 0.10,
            "trigger_rule": "static",
        },
    )
    req = trigger.update(
        _state(100),
        stop,
        task_time_step=500,
        transport_phase="transit",
    )
    assert req is None


def test_raise_then_lateral_default_unchanged_for_block_place():
    """block_place S1 accept: default strategy preserves raise→lateral ordering."""
    policy = _policy_with_single_pick_place()
    at_step = 200
    policy.time_step = at_step
    policy.splice_replan_detour(
        at_step=at_step,
        ee_pos=np.array([0.7, 0.2, 0.25], dtype=np.float32),
        human_hand_pos=np.array([0.72, 0.22, 0.2], dtype=np.float32),
        raise_m=0.05,
        lateral_m=0.15,
        detour_duration=30,
    )
    prefix_end = max(
        int(np.searchsorted(policy.time_stamps, at_step, side="right")) - 1,
        0,
    )
    names = [policy.stage_sequence[prefix_end + i]["name"] for i in range(1, 4)]
    assert names == [
        "replan_detour_raise",
        "replan_detour_lateral",
        "replan_detour_rejoin",
    ]


def test_merge_envelope_audit_metadata_populates_replan_fields():
    metadata: dict = {"dist_min_envelope": 0.14, "trigger_rule": "ttc"}
    triggers_mod.enrich_gate_metadata_from_envelope(
        metadata,
        {
            "dist_min_envelope": 0.14,
            "dist_min_held": 0.265,
            "closest_primitive_id": "held:fixed_box",
            "dist_min_arm": 0.30,
        },
    )
    assert metadata["dist_min_held"] == 0.265
    assert metadata["closest_primitive_id"] == "held:fixed_box"
    assert metadata["dist_min_arm"] == 0.30


def test_ttc_without_held_metadata_selects_lateral_first():
    """Regression: gate metadata missing held audit → TTC boost wins over retreat."""
    strategy_mod = _strategy_mod
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.5462,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=None,
        closest_primitive_id=None,
        hand_speed=1.0,
        trigger_rule="ttc",
    )
    assert plan.strategy == strategy_mod.DetourStrategy.LATERAL_FIRST


def test_run_20260622_185352_apply_selects_retreat_when_held_in_metadata():
    """Offline replay @ step_index=645: held closest + dist_min_held → retreat_then_arc."""
    strategy_mod = _strategy_mod
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.5462185144424438,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=0.2650096049227132,
        closest_primitive_id="held:fixed_box",
        hand_speed=1.00101988807742,
        trigger_rule="ttc",
        ee_pos=(0.550172746181488, 0.052364036440849304, 0.5462185144424438),
        human_hand_pos=(0.445, -0.225, 0.41000000000000003),
    )
    assert plan.strategy == strategy_mod.DetourStrategy.RETREAT_THEN_ARC
    assert plan.retreat_m > 0.0


def test_trigger_reads_merged_envelope_metadata():
    metadata = {
        "dist_min_envelope": 0.265,
        "dist_ee_human": 0.30,
        "trigger_rule": "ttc",
    }
    triggers_mod.enrich_gate_metadata_from_envelope(
        metadata,
        {
            "dist_min_envelope": 0.265,
            "dist_min_held": 0.265,
            "closest_primitive_id": "held:fixed_box",
        },
    )
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    slow = GateResult(g_t=GateDecision.SLOW_DOWN, reason="warn", metadata=metadata)
    req = trigger.update(_state(645), slow, task_time_step=591, transport_phase="transit")
    assert req is not None
    assert req.closest_primitive_id == "held:fixed_box"
    assert abs(req.dist_min_held - 0.265) < 1e-6


def test_merge_perception_track_metadata_into_gate():
    metadata: dict = {"trigger_rule": "ttc", "dist_min_envelope": 0.20}
    triggers_mod.enrich_gate_metadata_from_perception_track(
        metadata,
        {
            "perception_track_speed_px_s": "22.5",
            "perception_track_direction_deg": "88.0",
            "perception_track_center_x": "320.0",
        },
    )
    assert metadata["perception_track_speed_px_s"] == "22.5"
    assert metadata["perception_track_direction_deg"] == "88.0"
    assert metadata["perception_track_center_x"] == "320.0"


def test_trigger_passes_perception_track_fields_when_enabled():
    moving = SafetyState(
        ee_pos=np.array([0.7, 0.2, 0.3]),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.72, 0.22, 0.2]),
        human_hand_vel=np.array([0.2, 0.0, 0.0]),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=2.0,
        step_index=640,
    )
    metadata = {
        "dist_min_envelope": 0.20,
        "dist_ee_human": 0.25,
        "trigger_rule": "static_warn",
        "perception_track_speed_px_s": "25.0",
        "perception_track_direction_deg": "85.0",
    }
    trigger = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=1,
            use_perception_track_strategy=True,
        )
    )
    slow = GateResult(g_t=GateDecision.SLOW_DOWN, reason="warn", metadata=metadata)
    req = trigger.update(moving, slow, task_time_step=591, transport_phase="transit")
    assert req is not None
    assert req.perception_track_speed_px_s == 25.0
    assert req.perception_track_direction_deg == 85.0
    assert req.use_perception_track_strategy is True


def test_perception_track_strategy_disabled_by_default():
    trigger = L1WarnReplanTrigger(ReplanTriggerConfig(replan_trigger_threshold=1))
    metadata = {
        "dist_min_envelope": 0.20,
        "dist_ee_human": 0.25,
        "trigger_rule": "static_warn",
        "perception_track_speed_px_s": "99.0",
    }
    slow = GateResult(g_t=GateDecision.SLOW_DOWN, reason="warn", metadata=metadata)
    req = trigger.update(_state(100), slow, task_time_step=640, transport_phase="transit")
    assert req is not None
    assert req.use_perception_track_strategy is False


def test_perception_track_bonus_ignored_when_flag_off():
    strategy_mod = _strategy_mod
    kwargs = dict(
        transport_phase="transit",
        ee_z=0.68,
        raise_m=0.06,
        lateral_m=0.10,
        trigger_rule="static_warn",
        perception_track_speed_px_s=40.0,
        perception_track_direction_deg=90.0,
        z_max=0.75,  # low ceiling → headroom=0.07 < 0.08 → lateral_first base
    )
    off = strategy_mod.select_detour_strategy(use_perception_track_strategy=False, **kwargs)
    on = strategy_mod.select_detour_strategy(use_perception_track_strategy=True, **kwargs)
    assert off.strategy == strategy_mod.DetourStrategy.LATERAL_FIRST
    assert on.strategy == strategy_mod.DetourStrategy.LATERAL_FIRST
    assert on.score > off.score
    assert "track" in on.reason


def test_perception_track_inward_direction_boosts_retreat():
    strategy_mod = _strategy_mod
    lat, ret, reason = strategy_mod.perception_track_strategy_bonus(
        enabled=True,
        speed_px_s=10.0,
        direction_deg=10.0,
    )
    assert lat == 0.0
    assert ret == strategy_mod.PERCEPTION_TRACK_INWARD_BONUS
    assert "track_inward" in reason


def test_perception_track_lateral_sweep_bonus():
    strategy_mod = _strategy_mod
    lat, ret, reason = strategy_mod.perception_track_strategy_bonus(
        enabled=True,
        speed_px_s=25.0,
        direction_deg=90.0,
    )
    assert lat == (
        strategy_mod.PERCEPTION_TRACK_SPEED_BONUS
        + strategy_mod.PERCEPTION_TRACK_LATERAL_SWEEP_BONUS
    )
    assert ret == 0.0
    assert "track_lateral_sweep" in reason


def test_perception_track_does_not_override_held_closest_retreat():
    strategy_mod = _strategy_mod
    plan = strategy_mod.select_detour_strategy(
        transport_phase="transit",
        ee_z=0.45,
        raise_m=0.06,
        lateral_m=0.10,
        dist_min_held=0.09,
        closest_primitive_id="held:fixed_box",
        ee_pos=(0.7, 0.0, 0.45),
        human_hand_pos=(0.72, 0.02, 0.2),
        trigger_rule="ttc",
        hand_speed=1.0,
        use_perception_track_strategy=True,
        perception_track_speed_px_s=50.0,
        perception_track_direction_deg=90.0,
    )
    assert plan.strategy == strategy_mod.DetourStrategy.RETREAT_THEN_ARC


if __name__ == "__main__":
    test_tier0_stop_reads_dist_min_envelope_metadata()
    test_warn_slow_reads_dist_min_envelope()
    test_tier0_stop_no_replan()
    test_warn_slow_emits_replan_after_threshold()
    test_ttc_warn_uses_lower_replan_threshold_when_hand_moves()
    test_ttc_forecast_early_replan_when_gates_met()
    test_ttc_forecast_disabled_by_default()
    test_ttc_forecast_carry_approach_on_ttc_stop()
    test_held_critical_carry_approach_emits_replan()
    test_ttc_warn_static_hand_keeps_default_threshold()
    test_ttc_hard_stop_still_no_replan()
    test_replan_cooldown_starts_on_apply_success()
    test_failed_apply_does_not_start_cooldown()
    test_policy_splice_extends_trajectory()
    test_detour_during_descend_keeps_gripper_closed()
    test_get_action_gripper_does_not_lead_stage_at_descend_end()
    test_open_gripper_action_stays_at_grasp_height()
    test_keep_release_requires_commit_not_lift_after_stage()
    test_action_at_step_descend_never_exceeds_carry_threshold()
    test_descend_gripper_stays_closed_no_interp_bleed()
    test_release_gripper_committed_through_lift_after()
    test_release_committed_prevents_hold_reclose_agent_sim()
    test_gripper_open_stays_open_through_lift_after_offline()
    test_validate_placement_xy()
    test_is_carrying_object_uses_stage_window_not_gripper_interp()
    test_is_in_grasp_window_covers_pick_not_place()
    test_validate_grasp_hold_requires_part_near_ee()
    test_validate_grasp_hold_warns_when_part_pose_none()
    test_maybe_rewind_for_failed_grasp_before_transport()
    test_maybe_rewind_skips_valid_grasp_at_lift()
    test_validated_grasp_skips_validation_during_carry()
    test_force_open_suppressed_after_grasp_validated()
    test_grasp_rewind_exhausted_emits_event()
    test_stabilize_hold_blocks_advance_time_step()
    test_note_carry_knock_if_hit_rewinds_to_move_above_with_stabilize_hold()
    test_note_carry_knock_if_hit_ignores_when_dist_above_threshold()
    test_trigger_vlm_retry_current_part_rewinds_with_stabilize_hold()
    test_vlm_retry_exhausted_refuses_rewind()
    test_maybe_rewind_for_failed_grasp_rewinds_to_move_above_with_stabilize_hold()
    test_clear_grasp_disturbance_resets_stabilize_hold()
    test_pick_descend_is_approach_not_transit()
    test_pick_descend_blocks_transit_ttc_replan()
    test_should_latch_grasp_disturbance_only_at_grasp_depth()
    test_mid_lift_knockoff_latches_and_rewinds_with_open_gripper()
    test_needs_grasp_validation_through_pick_lift()
    test_replan_splice_clears_grasp_disturbance_on_pick_approach()
    test_replan_splice_clears_grasp_disturbance_on_transit_carry()
    test_transit_detour_inserts_place_realign_waypoints()
    test_should_hold_release_blocks_tilted_part()
    test_should_block_place_advance_only_when_hand_near()
    test_place_progress_hold_clears_when_hand_clears_warn()
    test_fast_hand_transit_carry_prefers_retreat_over_lateral()
    test_carry_phase_does_not_require_grasp_validation()
    test_lift_without_disturbance_skips_grasp_validation()
    test_needs_grasp_validation_at_close_gripper_and_lift_entry()
    test_needs_grasp_validation_before_first_lift_action()
    test_rewind_peek_action_opens_gripper_not_lift()
    test_rewind_part_five_targets_move_above_not_descend()
    test_part5_knockoff_rewinds_at_close_gripper_before_ascent()
    test_part5_knockoff_at_grasp_end_rewinds_not_carry()
    test_both_elevated_commits_carry_without_rewind()
    test_validated_grasp_at_close_gripper_blocks_late_rewind()
    test_knockoff_at_grasp_height_still_rewinds_when_xy_misaligned()
    test_missing_part_pose_triggers_rewind_not_skip()
    test_rewind_keeps_disturbance_latch_for_revalidation()
    test_should_wait_hold_late_approach_when_elevated()
    test_should_wait_hold_place_progress_when_blocked_elevated()
    test_place_progress_hold_clears_when_human_moves_away()
    test_should_hold_open_gripper_when_elevated()
    test_should_hold_open_gripper_out_of_zone()
    test_should_hold_false_after_replan_stage_drift()
    test_approach_rejoin_stays_in_current_part()
    test_defer_replan_in_approach_when_hand_very_near()
    test_approach_allows_replan_when_dist_above_defer()
    test_approach_place_post_replan_advance_disabled()
    test_executor_poll_does_not_leave_stale_completed()
    test_place_phase_replan_disables_post_replan_advance()
    test_select_lateral_first_when_z_headroom_low()
    test_select_retreat_arc_when_held_closest()
    test_lateral_first_splice_orders_waypoints()
    test_trigger_passes_envelope_fields()
    test_defer_replan_when_held_critical_in_place()
    test_held_critical_early_warn_emits_replan_before_stop()
    test_fast_hand_speed_boosts_lateral_or_retreat()
    test_ttc_transit_early_replan_when_hand_fast()
    test_held_critical_stop_transit_emits_immediate_replan()
    test_held_critical_stop_transit_blocked_without_opt_in()
    test_held_critical_stop_place_still_blocks_replan()
    test_static_tier0_stop_transit_still_blocks_replan()
    test_raise_then_lateral_default_unchanged_for_block_place()
    test_merge_envelope_audit_metadata_populates_replan_fields()
    test_ttc_without_held_metadata_selects_lateral_first()
    test_run_20260622_185352_apply_selects_retreat_when_held_in_metadata()
    test_trigger_reads_merged_envelope_metadata()
    test_merge_perception_track_metadata_into_gate()
    test_trigger_passes_perception_track_fields_when_enabled()
    test_perception_track_strategy_disabled_by_default()
    test_perception_track_bonus_ignored_when_flag_off()
    test_perception_track_inward_direction_boosts_retreat()
    test_perception_track_lateral_sweep_bonus()
    test_perception_track_does_not_override_held_closest_retreat()
    test_point_to_segment_distance_on_axis()
    test_proactive_route_replan_disabled_by_default()
    test_proactive_route_replan_emits_before_hand_intrusion()
    test_evaluate_route_conflict_skips_non_carry_segments()
    print("All replan unit tests passed.")
