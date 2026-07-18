"""Offline diagnosis: Part 5 lift-path knock-off + early replan (ivj_intrusion_positive v8)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _safety_import import bootstrap_safety, load_safety_module

safety = bootstrap_safety()
load_safety_module("rule_engine")
load_safety_module("envelope")

import numpy as np
from pick_and_place_policy import SingleEnvPickAndPlacePolicy

SafetyConfig = safety.config.SafetyConfig
load_safety_config = safety.config.load_safety_config
EnvelopeEvaluator = safety.envelope.EnvelopeEvaluator
RuleEngine = safety.rule_engine.RuleEngine
SafetyState = safety.types.SafetyState
GateDecision = safety.types.GateDecision

def _load_replan_trigger():
    import importlib.util
    import types as _types

    replan_dir = ROOT / "source" / "GMRobot" / "GMRobot" / "safety" / "replan"
    replan_pkg = _types.ModuleType("GMRobot.safety.replan")
    replan_pkg.__path__ = [str(replan_dir)]
    sys.modules["GMRobot.safety.replan"] = replan_pkg

    rt_spec = importlib.util.spec_from_file_location(
        "GMRobot.safety.replan.types", replan_dir / "types.py"
    )
    rt_mod = importlib.util.module_from_spec(rt_spec)
    rt_mod.__package__ = "GMRobot.safety.replan"
    sys.modules["GMRobot.safety.replan.types"] = rt_mod
    assert rt_spec.loader is not None
    rt_spec.loader.exec_module(rt_mod)
    replan_pkg.types = rt_mod

    st_spec = importlib.util.spec_from_file_location(
        "GMRobot.safety.replan.strategy", replan_dir / "strategy.py"
    )
    st_mod = importlib.util.module_from_spec(st_spec)
    st_mod.__package__ = "GMRobot.safety.replan"
    sys.modules["GMRobot.safety.replan.strategy"] = st_mod
    assert st_spec.loader is not None
    st_spec.loader.exec_module(st_mod)
    replan_pkg.strategy = st_mod

    rc_spec = importlib.util.spec_from_file_location(
        "GMRobot.safety.replan.route_conflict", replan_dir / "route_conflict.py"
    )
    rc_mod = importlib.util.module_from_spec(rc_spec)
    rc_mod.__package__ = "GMRobot.safety.replan"
    sys.modules["GMRobot.safety.replan.route_conflict"] = rc_mod
    assert rc_spec.loader is not None
    rc_spec.loader.exec_module(rc_mod)
    replan_pkg.route_conflict = rc_mod

    tr_spec = importlib.util.spec_from_file_location(
        "GMRobot.safety.replan.triggers", replan_dir / "triggers.py"
    )
    tr_mod = importlib.util.module_from_spec(tr_spec)
    tr_mod.__package__ = "GMRobot.safety.replan"
    sys.modules["GMRobot.safety.replan.triggers"] = tr_mod
    assert tr_spec.loader is not None
    tr_spec.loader.exec_module(tr_mod)
    return tr_mod


replan_triggers = _load_replan_trigger()
L1WarnReplanTrigger = replan_triggers.L1WarnReplanTrigger
ReplanTriggerConfig = replan_triggers.ReplanTriggerConfig
enrich_gate_metadata_from_envelope = replan_triggers.enrich_gate_metadata_from_envelope

G_LABEL = {
    int(GateDecision.ALLOW): "ALLOW",
    int(GateDecision.STOP): "STOP",
    int(GateDecision.SLOW_DOWN): "SLOW",
}


def hand_pose(step: int, cfg: SafetyConfig) -> tuple[np.ndarray, np.ndarray]:
    """Mirror HumanMotionController.compute_pose (incl. hold + retreat)."""
    traj = cfg.human_trajectory
    start = np.asarray(traj.start_pos, dtype=np.float64)
    end = np.asarray(traj.end_pos, dtype=np.float64)
    dt = max(cfg.control_dt, cfg.eps)
    approach_end = traj.approach_end_step()
    hold_end = traj.hold_end_step()
    retreat_end = traj.retreat_end_step()

    if step < traj.start_step:
        pos = start.copy()
        vel = np.zeros(3)
    elif step < approach_end:
        alpha = (step - traj.start_step) / max(traj.duration_steps, 1)
        pos = start + alpha * (end - start)
        vel = (end - start) / max(traj.duration_steps * dt, cfg.eps)
    elif step < hold_end:
        pos = end.copy()
        vel = np.zeros(3)
    elif traj.retreat_pos is not None and step < retreat_end:
        retreat = np.asarray(traj.retreat_pos, dtype=np.float64)
        alpha = (step - hold_end) / max(traj.retreat_duration_steps, 1)
        pos = end + alpha * (retreat - end)
        vel = (retreat - end) / max(traj.retreat_duration_steps * dt, cfg.eps)
    elif traj.retreat_pos is not None:
        pos = np.asarray(traj.retreat_pos, dtype=np.float64)
        vel = np.zeros(3)
    else:
        pos = end.copy()
        vel = np.zeros(3)
    return pos, vel


def make_six_part_policy() -> SingleEnvPickAndPlacePolicy:
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


def simulate(
    config_path: str,
    *,
    force_gating: bool | None = None,
    with_replan: bool = False,
) -> list[dict]:
    cfg = load_safety_config(config_path)
    if force_gating is not None:
        cfg.envelope.gating_enabled = force_gating

    policy = make_six_part_policy()
    envelope_eval = EnvelopeEvaluator(cfg)
    engine = RuleEngine(cfg)
    trigger = None
    if with_replan:
        trigger = L1WarnReplanTrigger(
            ReplanTriggerConfig(
                safe_dist_hard_stop=cfg.safe_dist_hard_stop,
                safe_dist_warn=cfg.safe_dist_warn,
                replan_trigger_threshold=cfg.replan_trigger_threshold,
                ttc_replan_trigger_threshold=cfg.ttc_replan_trigger_threshold,
                ttc_replan_hand_speed_min=cfg.ttc_replan_hand_speed_min,
                ttc_forecast_replan_threshold=cfg.ttc_forecast_replan_threshold,
                lateral_offset_m=cfg.replan_lateral_offset_m,
                detour_stage_duration=cfg.replan_detour_stage_duration,
                held_critical_replan_enabled=cfg.held_critical_replan_enabled,
                proactive_route_replan_enabled=cfg.proactive_route_replan_enabled,
                proactive_route_horizon_steps=cfg.proactive_route_horizon_steps,
                proactive_route_warn_gap_m=cfg.proactive_route_warn_gap_m,
                proactive_route_hard_gap_m=cfg.proactive_route_hard_gap_m,
            )
        )

    rows: list[dict] = []
    for task_step in range(1600, 1760):
        eval_step = task_step + 1
        ee = policy._action_at_step(task_step)[:3]
        hand_pos, hand_vel = hand_pose(task_step, cfg)
        held_active = policy.is_carrying_object(eval_step)
        transport = policy.transport_phase_at_step(task_step)

        state = SafetyState(
            ee_pos=ee.astype(np.float32),
            ee_vel=np.zeros(3, dtype=np.float32),
            human_hand_pos=hand_pos.astype(np.float32),
            human_hand_vel=hand_vel.astype(np.float32),
            joint_pos=np.zeros(6, dtype=np.float32),
            joint_vel=np.zeros(6, dtype=np.float32),
            sim_time=task_step * cfg.control_dt,
            step_index=task_step,
        )
        env_result = envelope_eval.evaluate(state, held_object_active=held_active)
        dist_gating = (
            float(env_result.dist_min_envelope) if cfg.envelope.gating_enabled else None
        )
        result = engine.evaluate(
            state,
            dist_for_gating=dist_gating,
            dist_min_held=env_result.dist_min_held,
            held_object_active=held_active,
        )
        enrich_gate_metadata_from_envelope(
            result.metadata,
            {
                "dist_min_envelope": env_result.dist_min_envelope,
                "dist_min_held": env_result.dist_min_held,
                "dist_min_arm": env_result.dist_min_arm,
                "dist_min_gripper": env_result.dist_min_gripper,
                "closest_primitive_id": env_result.closest_primitive_id,
            },
        )

        replan_rule = ""
        route_min_gap = ""
        if trigger is not None:
            req = trigger.update(
                state,
                result,
                task_time_step=task_step,
                transport_phase=transport,
                policy=policy,
                safety_config=cfg,
                sim_step_index=task_step,
            )
            if req is not None:
                replan_rule = req.trigger_rule
                if req.dist_min_envelope is not None:
                    route_min_gap = f"{req.dist_min_envelope:.4f}"

        hand_speed = float(np.linalg.norm(hand_vel))
        rows.append(
            {
                "task_ts": task_step,
                "held": held_active,
                "hand_speed": hand_speed,
                "dist_ee": float(result.metadata["dist_ee_human"]),
                "dist_min": float(env_result.dist_min_envelope),
                "dist_held": env_result.dist_min_held,
                "closest": env_result.closest_primitive_id,
                "g_rule": int(result.g_t),
                "trigger": result.metadata.get("trigger_rule", ""),
                "ttc_forecast_s": result.metadata.get("ttc_forecast_s", ""),
                "replan": replan_rule,
                "route_min_gap": route_min_gap,
            }
        )
    return rows


def summarize(label: str, rows: list[dict], cfg: SafetyConfig) -> None:
    stop = [r for r in rows if r["g_rule"] == int(GateDecision.STOP)]
    replans = [r for r in rows if r.get("replan")]
    early = [
        r
        for r in replans
        if r["replan"]
        in ("held_critical_early", "ttc_forecast", "ttc", "route_conflict")
    ]
    route_early = [r for r in replans if r["replan"] == "route_conflict"]
    min_row = min(rows, key=lambda r: r["dist_min"])
    held_rows = [r for r in rows if r["dist_held"] is not None]
    init_held_min = min(held_rows, key=lambda r: r["dist_held"])
    traj = cfg.human_trajectory
    print(f"\n=== {label} ===")
    print(
        f"gating={cfg.envelope.gating_enabled} hard={cfg.safe_dist_hard_stop} "
        f"warn={cfg.safe_dist_warn} ttc_forecast={cfg.ttc_forecast_replan_threshold} "
        f"route_proactive={cfg.proactive_route_replan_enabled}"
    )
    print(
        f"hand: start={traj.start_step} dur={traj.duration_steps} "
        f"hold={traj.hold_steps} retreat={traj.retreat_pos is not None}"
    )
    print(f"STOP steps: {len(stop)}, replan emits: {len(replans)}, early: {len(early)}")
    if route_early:
        first_route = route_early[0]
        print(
            f"first route_conflict ts={first_route['task_ts']} "
            f"route_min_gap={first_route.get('route_min_gap', '?')} "
            f"dist_min={first_route['dist_min']:.4f} g={G_LABEL.get(first_route['g_rule'])}"
        )
    if replans:
        first = replans[0]
        print(
            f"first replan ts={first['task_ts']} rule={first['replan']} "
            f"g={G_LABEL.get(first['g_rule'])} hand_speed={first['hand_speed']:.3f}"
        )
    print(
        f"min dist_min ts={min_row['task_ts']}: "
        f"dist_min={min_row['dist_min']:.4f} dist_ee={min_row['dist_ee']:.4f} "
        f"g={G_LABEL.get(min_row['g_rule'], min_row['g_rule'])} closest={min_row['closest']}"
    )
    print(
        f"initial min dist_held ts={init_held_min['task_ts']}: "
        f"dist_held={init_held_min['dist_held']:.4f}"
    )
    for ts in [1660, 1665, 1670, 1675, 1680, 1685, 1688, 1690, 1700, 1720, 1750, 1840]:
        match = [x for x in rows if x["task_ts"] == ts]
        if not match:
            continue
        r = match[0]
        held_s = f"{r['dist_held']:.3f}" if r["dist_held"] is not None else "—"
        repl = f" replan={r['replan']}" if r.get("replan") else ""
        route_gap = (
            f" route_gap={r['route_min_gap']}" if r.get("route_min_gap") else ""
        )
        print(
            f"  ts={ts} held={r['held']} spd={r['hand_speed']:.2f} dist_ee={r['dist_ee']:.3f} "
            f"dist_min={r['dist_min']:.3f} dist_held={held_s} "
            f"g={G_LABEL.get(r['g_rule'], r['g_rule'])} trigger={r['trigger']}{repl}{route_gap}"
        )


def main() -> None:
    intrusion_cfg = load_safety_config("configs/ivj/ivj_intrusion_positive.yaml")
    summarize(
        "intrusion_positive v8 (gating ON, replan sim)",
        simulate("configs/ivj/ivj_intrusion_positive.yaml", with_replan=True),
        intrusion_cfg,
    )
    summarize(
        "intrusion_positive v8 (gating ON)",
        simulate("configs/ivj/ivj_intrusion_positive.yaml"),
        intrusion_cfg,
    )
    summarize(
        "fast_sweep (no gating)",
        simulate("configs/ivj/ivj_dynamic_fast_sweep.yaml"),
        load_safety_config("configs/ivj/ivj_dynamic_fast_sweep.yaml"),
    )


if __name__ == "__main__":
    main()
