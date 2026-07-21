"""Offline tests: B1 held_critical replan wiring + RuleEngine distance audit."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_GM = _ROOT.parent / "GMRobot"
_SAFETY = _GM / "source" / "GMRobot" / "GMRobot" / "safety"
_REPLAN = _SAFETY / "replan"

sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_GM / "scripts"))

from _safety_import import bootstrap_safety, load_safety_module
from config_loader import load_config

bootstrap_safety()
load_safety_module("rule_engine")

types_mod = sys.modules["GMRobot.safety.types"]
config_mod = sys.modules["GMRobot.safety.config"]
rule_engine_mod = sys.modules["GMRobot.safety.rule_engine"]

GateDecision = types_mod.GateDecision
GateResult = types_mod.GateResult
SafetyState = types_mod.SafetyState
SafetyConfig = config_mod.SafetyConfig
RuleEngine = rule_engine_mod.RuleEngine

# Mirror safety.* aliases used by replan relative imports.
safety_pkg = types.ModuleType("safety")
safety_pkg.__path__ = [str(_SAFETY)]
sys.modules["safety"] = safety_pkg
sys.modules["safety.types"] = types_mod
safety_pkg.types = types_mod
for _name in ("config", "envelope", "gt_branches", "rule_engine"):
    _gm = sys.modules[f"GMRobot.safety.{_name}"]
    sys.modules[f"safety.{_name}"] = _gm
    setattr(safety_pkg, _name, _gm)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


replan_pkg = types.ModuleType("safety.replan")
replan_pkg.__path__ = [str(_REPLAN)]
sys.modules["safety.replan"] = replan_pkg
_load("safety.replan.types", _REPLAN / "types.py")
sys.modules["safety.replan.types"].__package__ = "safety.replan"
_load("safety.replan.strategy", _REPLAN / "strategy.py")
sys.modules["safety.replan.strategy"].__package__ = "safety.replan"
triggers_mod = _load("safety.replan.triggers", _REPLAN / "triggers.py")
triggers_mod.__package__ = "safety.replan"
L1WarnReplanTrigger = triggers_mod.L1WarnReplanTrigger
ReplanTriggerConfig = triggers_mod.ReplanTriggerConfig


def test_b1_yaml_enables_held_critical_b0_does_not():
    b1 = load_config(str(_ROOT / "paper_scenarios/static_occupancy_proxy_1part.yaml"))
    assert b1.safety.replan.held_critical_replan_enabled is True
    b0 = load_config(str(_ROOT / "paper_scenarios/baseline_safe.yaml"))
    assert b0.safety.replan.held_critical_replan_enabled is False


def test_rule_engine_emits_distance_audit_metadata():
    cfg = SafetyConfig(safe_dist_hard_stop=0.25, safe_dist_warn=0.28)
    cfg.envelope.gating_enabled = True
    state = SafetyState(
        ee_pos=np.array([0.4, 0.0, 0.5], dtype=np.float64),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.45, 0.0, 0.5], dtype=np.float64),
        human_hand_vel=np.zeros(3),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=0.0,
        step_index=1,
    )
    result = RuleEngine(cfg).evaluate(
        state,
        dist_for_gating=0.08,
        dist_min_held=0.08,
        held_object_active=True,
    )
    assert result.g_t == GateDecision.STOP
    assert result.metadata["trigger_rule"] == "held_critical"
    assert abs(result.metadata["dist_min_for_gating"] - 0.08) < 1e-9
    assert abs(result.metadata["dist_min_envelope"] - 0.08) < 1e-9
    assert abs(result.metadata["dist_min_held"] - 0.08) < 1e-9
    assert abs(result.metadata["safe_dist_hard_stop_active"] - 0.25) < 1e-9
    assert abs(result.metadata["safe_dist_warn_active"] - 0.28) < 1e-9


def test_held_critical_stop_replans_only_when_enabled():
    state = SafetyState(
        ee_pos=np.array([0.4, 0.0, 0.5], dtype=np.float64),
        ee_vel=np.zeros(3),
        human_hand_pos=np.array([0.45, 0.0, 0.5], dtype=np.float64),
        human_hand_vel=np.zeros(3),
        joint_pos=np.zeros(6),
        joint_vel=np.zeros(6),
        sim_time=1.0,
        step_index=10,
    )
    gate = GateResult(
        g_t=GateDecision.STOP,
        reason="held_critical: held envelope inside hard zone",
        metadata={
            "dist_min_for_gating": 0.08,
            "dist_min_envelope": 0.08,
            "dist_min_held": 0.08,
            "trigger_rule": "held_critical",
            "safe_dist_hard_stop_active": 0.25,
            "safe_dist_warn_active": 0.28,
        },
    )
    off = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=5,
            held_critical_replan_enabled=False,
            safe_dist_hard_stop=0.25,
            safe_dist_warn=0.28,
        )
    )
    assert off.update(state, gate, task_time_step=10, transport_phase="transit") is None

    on = L1WarnReplanTrigger(
        ReplanTriggerConfig(
            replan_trigger_threshold=5,
            held_critical_replan_enabled=True,
            safe_dist_hard_stop=0.25,
            safe_dist_warn=0.28,
        )
    )
    req = on.update(state, gate, task_time_step=10, transport_phase="transit")
    assert req is not None
    assert req.trigger_rule == "held_critical"
    # Static STOP must still not replan when flag is on (no global Tier0 STOP).
    static_gate = GateResult(
        g_t=GateDecision.STOP,
        reason="static_collision",
        metadata={
            "dist_min_for_gating": 0.08,
            "dist_min_envelope": 0.08,
            "trigger_rule": "static",
            "safe_dist_hard_stop_active": 0.25,
            "safe_dist_warn_active": 0.28,
        },
    )
    assert on.update(state, static_gate, task_time_step=11, transport_phase="transit") is None


def test_phase3_passes_held_critical_flag_into_trigger_config_kwargs():
    cfg = load_config(str(_ROOT / "paper_scenarios/static_occupancy_proxy_1part.yaml"))
    kwargs = dict(
        safe_dist_hard_stop=0.25,
        safe_dist_warn=0.28,
        lateral_offset_m=cfg.safety.replan.detour_lateral_m,
        detour_stage_duration=cfg.safety.replan.detour_duration,
        replan_trigger_threshold=cfg.safety.replan.trigger_threshold,
        ttc_replan_trigger_threshold=4,
        held_critical_replan_enabled=bool(
            cfg.safety.replan.held_critical_replan_enabled
        ),
    )
    assert kwargs["held_critical_replan_enabled"] is True
    trig_cfg = ReplanTriggerConfig(**kwargs)
    assert trig_cfg.held_critical_replan_enabled is True


def test_held_critical_scripted_vhand_counts_as_d_replan():
    from protocol_vhand import ReplanAttribution
    from test_metrics import EpisodeMetrics

    attr = ReplanAttribution.from_trigger(
        attempt_id=1,
        trigger_rule="held_critical",
        trigger_source="scripted_virtual_hand",
        trigger_step=201,
    )
    assert attr.is_geometry_related is True
    assert attr.counts_as_disturbance_replan("scripted_virtual_hand") is True

    m = EpisodeMetrics(episode_id=0)
    m.record_step(
        g1_root_z=0.8,
        g1_ur10e_distance=0.5,
        surface_distance=0.05,
        gate_decision="STOP",
        gate_trigger="held_critical",
        replan_success=True,
        replan_event_id=1,
        replan_attribution=attr,
        disturbance_source="scripted_virtual_hand",
        disturbance_attempt_id=1,
        replan_trigger_source="scripted_virtual_hand",
    )
    assert m.d_replan_caused == 1


if __name__ == "__main__":
    test_b1_yaml_enables_held_critical_b0_does_not()
    test_rule_engine_emits_distance_audit_metadata()
    test_held_critical_stop_replans_only_when_enabled()
    test_phase3_passes_held_critical_flag_into_trigger_config_kwargs()
    test_held_critical_scripted_vhand_counts_as_d_replan()
    print("OK")
