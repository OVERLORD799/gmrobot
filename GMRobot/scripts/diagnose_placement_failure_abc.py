#!/usr/bin/env python3
"""Offline ABC placement-failure diagnosis (Part 5 / intrusion_positive).

Classifies placement-window steps into:
  C — conservative freeze (STOP/SLOW + hand blocking, task_ts frozen, hold gates)
  A — trajectory deviation (EE XY/Z vs scripted place path, often post-detour)
  B — tilted / misaligned part in gripper (part_pose or proxy signals)
  OK — release conditions met

Usage:
  # Simulation (no Isaac / no CSV) — default
  python scripts/diagnose_placement_failure_abc.py

  # Real run CSV
  python scripts/diagnose_placement_failure_abc.py --run-dir output/safety_logs/20260625_185118

  # JSON for automation
  python scripts/diagnose_placement_failure_abc.py --json
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pick_and_place_policy import (  # noqa: E402
    GRIPPER_CLOSED,
    GRIPPER_OPEN,
    GRASP_UPRIGHT_MIN_DOT,
    GRASP_XY_TOLERANCE_M,
    PLACE_ZONE_RADIUS_M,
    SingleEnvPickAndPlacePolicy,
)

from diagnose_intrusion_knockoff import (  # noqa: E402
    GateDecision,
    SafetyConfig,
    enrich_gate_metadata_from_envelope,
    hand_pose,
    load_safety_config,
    make_six_part_policy,
)

ABC = Literal["C", "A", "B", "OK"]

BLOCKED_DESCEND_Z_M = 0.55
Z_DEVIATION_TOL_M = 0.08
PLACE_UPRIGHT_MIN_DOT = 0.97
HAND_STATIC_SPEED_MPS = 0.02
CARRY_THRESHOLD = (GRIPPER_OPEN + GRIPPER_CLOSED) / 2.0
GATE_ALLOW = int(GateDecision.ALLOW)
GATE_SLOW = int(GateDecision.SLOW_DOWN)
GATE_STOP = int(GateDecision.STOP)


@dataclass
class StepRecord:
    task_ts: int
    label: ABC
    stage: str
    transport: str
    g_rule: int
    ee: np.ndarray
    script: np.ndarray
    grip_exec: float
    grip_script: float
    dist_ee: float | None
    dist_min_held: float | None
    hand_speed: float
    frozen: bool
    xy_err: float
    z_err: float
    upright_dot: float | None
    notes: str = ""


@dataclass
class ABCDiagnosis:
    source: str
    focus_part: int
    window: tuple[int, int]
    records: list[StepRecord] = field(default_factory=list)
    hand_hold_overlaps_place: bool = False
    recommendation: str = ""
    evidence: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {"C": 0, "A": 0, "B": 0, "OK": 0}
        for r in self.records:
            if r.label in out:
                out[r.label] += 1
        return out

    @property
    def risk_total(self) -> int:
        c = self.counts
        return c["C"] + c["A"] + c["B"]

    def pct(self, label: ABC) -> float:
        t = self.risk_total
        if t == 0:
            return 0.0
        return 100.0 * self.counts[label] / t

    @property
    def dominant(self) -> ABC | str:
        c = self.counts
        items = [(k, c[k]) for k in ("C", "A", "B")]
        best = max(items, key=lambda x: x[1])
        if best[1] == 0:
            return "none"
        if sum(1 for _, v in items if v == best[1]) > 1:
            return "mixed"
        return best[0]  # type: ignore[return-value]

    @property
    def unique_task_ts(self) -> set[int]:
        return {r.task_ts for r in self.records if r.label != "OK"}

    def to_dict(self) -> dict[str, Any]:
        c = self.counts
        return {
            "source": self.source,
            "focus_part": self.focus_part,
            "window": list(self.window),
            "counts": c,
            "risk_total": self.risk_total,
            "pct_C": round(self.pct("C"), 1),
            "pct_A": round(self.pct("A"), 1),
            "pct_B": round(self.pct("B"), 1),
            "dominant": self.dominant,
            "unique_at_risk_task_ts": sorted(self.unique_task_ts),
            "hand_hold_overlaps_place": self.hand_hold_overlaps_place,
            "recommendation": self.recommendation,
            "evidence": self.evidence,
        }


def _parse_vec(raw: str | None) -> np.ndarray | None:
    if raw is None or raw == "":
        return None
    try:
        v = ast.literal_eval(raw)
        arr = np.asarray(v, dtype=np.float64).reshape(-1)
        return arr[:3].copy()
    except Exception:
        return None


def _parse_float(raw: str | None, default: float | None = None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _part5_policy() -> SingleEnvPickAndPlacePolicy:
    return make_six_part_policy()


def _place_window(policy: SingleEnvPickAndPlacePolicy, part: int) -> tuple[int, int]:
    w = policy.part_stage_windows()[part]
    start = w["approach_start"]
    end = w.get("open_end", w.get("cycle_end", start))
    return int(start), int(end)


def hand_pose_at_step(step: int, cfg: SafetyConfig, *, hold_end_override: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Like diagnose_intrusion_knockoff.hand_pose with optional hold_end override."""
    traj = cfg.human_trajectory
    start = np.asarray(traj.start_pos, dtype=np.float64)
    end = np.asarray(traj.end_pos, dtype=np.float64)
    dt = max(cfg.control_dt, cfg.eps)
    approach_end = traj.approach_end_step()
    hold_end = hold_end_override if hold_end_override is not None else traj.hold_end_step()
    retreat_end = traj.retreat_end_step() if hold_end_override is None else (
        hold_end + max(traj.retreat_duration_steps, 0)
    )

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


def _hand_hold_overlaps_place(
    cfg: SafetyConfig,
    approach_start: int,
    descend_end: int,
    *,
    hold_end_override: int | None = None,
) -> bool:
    traj = cfg.human_trajectory
    hold_start = traj.approach_end_step()
    hold_end = hold_end_override if hold_end_override is not None else traj.hold_end_step()
    return hold_start <= descend_end and hold_end >= approach_start


def _script_gripper(policy: SingleEnvPickAndPlacePolicy, task_ts: int) -> float:
    return float(policy._gripper_at_step(task_ts))


def _part_pose_from_row(row: dict[str, str], part: int) -> np.ndarray | None:
    for key in (f"part_{part}_pos", f"part_{part}_pose", "part_pose"):
        if key in row and row[key]:
            v = _parse_vec(row[key])
            if v is not None and v.size >= 3:
                raw = row[key]
                try:
                    arr = np.asarray(ast.literal_eval(raw), dtype=np.float64).reshape(-1)
                    if arr.size >= 7:
                        return arr[:7]
                    if arr.size >= 3:
                        quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
                        return np.concatenate([arr[:3], quat])
                except Exception:
                    pass
    return None


def _classify_step(
    *,
    policy: SingleEnvPickAndPlacePolicy,
    task_ts: int,
    ee: np.ndarray,
    g_rule: int,
    grip_exec: float,
    dist_ee: float | None,
    dist_min_held: float | None,
    hand_speed: float,
    frozen: bool,
    part_pose: np.ndarray | None,
    cfg: SafetyConfig | None,
) -> tuple[ABC, str]:
    script = policy._action_at_step(task_ts)[:3]
    stage = policy.stage_name_at_step(task_ts)
    transport = policy.transport_phase_at_step(task_ts)
    grip_script = _script_gripper(policy, task_ts)
    wants_open = grip_script > CARRY_THRESHOLD

    xy_err = 0.0
    target_xy = policy.place_target_xy_at_step(task_ts)
    if target_xy is not None:
        xy_err = float(np.linalg.norm(ee[:2] - target_xy[:2]))
    z_err = float(ee[2] - script[2])

    in_zone = xy_err <= PLACE_ZONE_RADIUS_M
    z_ok = abs(z_err) <= Z_DEVIATION_TOL_M
    elevated = float(ee[2]) > BLOCKED_DESCEND_Z_M

    warn = cfg.safe_dist_warn if cfg is not None else 0.16
    hand_blocking = (
        (dist_ee is not None and dist_ee < warn)
        or (dist_min_held is not None and float(dist_min_held) < warn)
        or (
            hand_speed < HAND_STATIC_SPEED_MPS
            and dist_ee is not None
            and dist_ee < warn + 0.06
        )
    )

    wait_hold = policy.should_wait_hold_place_progress(
        ee,
        task_ts,
        dist_ee_human=dist_ee,
        safe_dist_warn=warn,
        blocked_descend_z_m=BLOCKED_DESCEND_Z_M,
    )
    hold_open_xy = policy.should_hold_open_gripper(ee, task_ts)

    upright_dot: float | None = None
    part_misaligned = False
    if part_pose is not None:
        upright_dot = SingleEnvPickAndPlacePolicy._pose_upright_dot(part_pose)
        part_ok = SingleEnvPickAndPlacePolicy.validate_grasp_hold(ee, part_pose)
        part_place_ok = SingleEnvPickAndPlacePolicy.validate_grasp_hold(
            ee,
            part_pose,
            xy_tolerance_m=GRASP_XY_TOLERANCE_M * 0.65,
            upright_min_dot=PLACE_UPRIGHT_MIN_DOT,
        )
        part_misaligned = not part_place_ok
        if in_zone and z_ok and part_misaligned:
            return "B", f"part_pose misaligned upright={upright_dot:.3f}"

    # --- C: conservative freeze ---
    if transport in ("approach", "place"):
        if g_rule == GATE_STOP and hand_blocking:
            return "C", "STOP + hand in warn zone"
        if frozen and g_rule != GATE_ALLOW and hand_blocking:
            return "C", "task_ts frozen under gate + hand blocking"
        if wait_hold and hand_blocking:
            return "C", "place_progress_hold + hand blocking"
        if elevated and stage.startswith(("move_above_box", "descend_to_box")) and hand_blocking:
            if g_rule != GATE_ALLOW or frozen:
                return "C", "elevated descend blocked by hand/gate"
        if wants_open and grip_exec <= CARRY_THRESHOLD and g_rule == GATE_STOP:
            return "C", "script open but STOP keeps gripper closed"

    # --- B: tilt / offset (proxy without part_pose) ---
    if part_misaligned:
        return "B", "part misaligned vs EE"

    # --- OK ---
    if wants_open and in_zone and z_ok and g_rule == GATE_ALLOW and not hold_open_xy:
        if part_pose is None or SingleEnvPickAndPlacePolicy.validate_grasp_hold(
            ee,
            part_pose,
            upright_min_dot=PLACE_UPRIGHT_MIN_DOT,
        ):
            return "OK", "release conditions met"

    # --- A: trajectory deviation (not primarily frozen by hand) ---
    traj_bad = (not in_zone and xy_err > PLACE_ZONE_RADIUS_M) or (
        not z_ok and abs(z_err) > Z_DEVIATION_TOL_M
    )
    if traj_bad:
        if not (g_rule == GATE_STOP and hand_blocking and frozen):
            return "A", f"EE off script xy_err={xy_err:.3f} z_err={z_err:.3f}"

    if hold_open_xy and not hand_blocking:
        return "A", "EE out of place zone (not hand-blocked)"

    if elevated and stage.startswith("descend_to_box") and g_rule == GATE_ALLOW:
        return "A", f"elevated descend z={ee[2]:.3f} without hand block"

    if frozen and g_rule == GATE_STOP:
        return "C", "STOP freeze (fallback)"

    if traj_bad:
        return "A", "trajectory deviation (fallback)"

    return "OK", "nominal"


def _recommend(diag: ABCDiagnosis) -> tuple[str, list[str]]:
    evidence: list[str] = []
    if diag.hand_hold_overlaps_place:
        evidence.append(
            "v8 hand hold overlaps Part5 approach/descend "
            "(hold window intersects move_above_box / descend_to_box)"
        )

    c, a, b = diag.pct("C"), diag.pct("A"), diag.pct("B")
    dom = diag.dominant
    evidence.append(f"risk-step mix: C={c:.0f}% A={a:.0f}% B={b:.0f}% (dominant={dom})")

    if diag.risk_total == 0:
        return "no_action", evidence + ["No at-risk steps in placement window"]

    if dom == "mixed" or max(c, a, b) < 30:
        return "investigate_mixed", evidence + [
            "No clear dominant class — collect GUI CSV run before large changes",
        ]

    if dom == "C" and diag.hand_hold_overlaps_place and c >= 35:
        return "yaml_first", evidence + [
            "PRIMARY: adjust ivj_intrusion_positive v8 timing/geometry",
            "  - shorten hold_steps (120 -> 60) or start retreat before approach_start",
            "  - move end_pos off lift->B@5 corridor (test-only)",
            "SECONDARY (if still C after yaml): hand-static timeout + place release in code",
        ]

    if dom == "C" and c >= 35:
        return "code_first_conservative", evidence + [
            "PRIMARY: code — hand-static timeout, release _place_progress_hold when dist_ee>=warn",
            "  - limited post_replan_advance in approach phase",
            "YAML tweak alone unlikely sufficient (hold may not overlap place window)",
        ]

    if dom == "A" and a >= 35:
        return "code_first_trajectory", evidence + [
            "PRIMARY: code — place-realign splice after transit detour",
            "  - transit on_replan_splice_applied clears grasp + EE XY convergence",
            "SECONDARY: reduce replan_lateral_offset_m (0.10 -> 0.06-0.08)",
        ]

    if dom == "B" and b >= 35:
        return "code_first_pose", evidence + [
            "PRIMARY: code — should_hold_release(part_pose) before open_gripper",
            "  - detour-end carry re-validate; prefer retreat_then_arc when held close",
            "Log part_pose to CSV if B proxy dominates (no pose column in current logger)",
        ]

    return "investigate_mixed", evidence


def analyze_csv(
    csv_path: Path,
    *,
    focus_part: int = 5,
    cfg: SafetyConfig | None = None,
) -> ABCDiagnosis:
    policy = _part5_policy()
    w = policy.part_stage_windows()[focus_part]
    win_start = int(w["approach_start"])
    win_end = int(w["open_end"])
    if cfg is None:
        cfg = load_safety_config("configs/ivj/ivj_intrusion_positive.yaml")

    diag = ABCDiagnosis(
        source=str(csv_path),
        focus_part=focus_part,
        window=(win_start, win_end),
        hand_hold_overlaps_place=_hand_hold_overlaps_place(
            cfg, win_start, int(w["descend_end"])
        ),
    )

    rows = list(csv.DictReader(open(csv_path)))
    prev_task: int | None = None
    b_proxy_latched = False

    for row in rows:
        task_ts = int(_parse_float(row.get("task_time_step"), 0) or 0)
        if task_ts < win_start or task_ts > win_end:
            prev_task = task_ts
            continue

        part = policy.part_index_at_step(task_ts)
        if part != focus_part:
            prev_task = task_ts
            continue

        ee = _parse_vec(row.get("action_executed"))
        if ee is None:
            ee = _parse_vec(row.get("ee_pos"))
        if ee is None:
            prev_task = task_ts
            continue

        action = _parse_vec(row.get("action_executed"))
        grip_exec = float(action[7]) if action is not None and action.size >= 8 else GRIPPER_CLOSED

        g_rule = int(_parse_float(row.get("g_rule"), GATE_ALLOW) or GATE_ALLOW)
        dist_ee = _parse_float(row.get("dist_ee_human"))
        dist_min_held = _parse_float(row.get("dist_min_held"))
        if dist_min_held is None:
            dist_min_held = _parse_float(row.get("dist_min_envelope"))

        hand_vel = _parse_vec(row.get("human_hand_vel"))
        hand_speed = float(np.linalg.norm(hand_vel)) if hand_vel is not None else 0.0
        if hand_speed == 0.0 and dist_ee is not None:
            hand_pos = _parse_vec(row.get("human_hand_pos"))
            if hand_pos is not None:
                _, hv = hand_pose_at_step(task_ts, cfg)
                hand_speed = float(np.linalg.norm(hv))

        frozen = prev_task is not None and task_ts == prev_task
        part_pose = _part_pose_from_row(row, focus_part)

        if row.get("grasp_rewind_event") == "exhausted":
            b_proxy_latched = True
        if row.get("replan_event") == "applied" and policy.transport_phase_at_step(task_ts) == "transit":
            b_proxy_latched = True

        label, note = _classify_step(
            policy=policy,
            task_ts=task_ts,
            ee=ee,
            g_rule=g_rule,
            grip_exec=grip_exec,
            dist_ee=dist_ee,
            dist_min_held=dist_min_held,
            hand_speed=hand_speed,
            frozen=frozen,
            part_pose=part_pose,
            cfg=cfg,
        )

        if (
            label == "A"
            and b_proxy_latched
            and part_pose is None
            and policy.should_hold_open_gripper(ee, task_ts)
            and float(ee[2]) <= BLOCKED_DESCEND_Z_M
        ):
            label = "B"
            note = "B-proxy: post-detour + in-zone height but open blocked (tilt likely; no part_pose col)"

        script = policy._action_at_step(task_ts)[:3]
        target_xy = policy.place_target_xy_at_step(task_ts)
        xy_err = float(np.linalg.norm(ee[:2] - target_xy[:2])) if target_xy is not None else 0.0
        z_err = float(ee[2] - script[2])
        upright = (
            SingleEnvPickAndPlacePolicy._pose_upright_dot(part_pose)
            if part_pose is not None
            else None
        )

        diag.records.append(
            StepRecord(
                task_ts=task_ts,
                label=label,
                stage=policy.stage_name_at_step(task_ts),
                transport=policy.transport_phase_at_step(task_ts),
                g_rule=g_rule,
                ee=ee,
                script=script,
                grip_exec=grip_exec,
                grip_script=_script_gripper(policy, task_ts),
                dist_ee=dist_ee,
                dist_min_held=dist_min_held,
                hand_speed=hand_speed,
                frozen=frozen,
                xy_err=xy_err,
                z_err=z_err,
                upright_dot=upright,
                notes=note,
            )
        )
        prev_task = task_ts

    diag.recommendation, diag.evidence = _recommend(diag)
    return diag


def simulate_part5(
    config_path: str = "configs/ivj/ivj_intrusion_positive.yaml",
    *,
    with_replan: bool = True,
    inject_tilt_deg: float = 0.0,
    focus_part: int = 5,
    hold_end_override: int | None = None,
    label_suffix: str = "",
) -> ABCDiagnosis:
    """Lightweight Part5 place-window sim: scripted gate + EE lag + optional detour offset."""
    from diagnose_intrusion_knockoff import EnvelopeEvaluator, RuleEngine, SafetyState

    cfg = load_safety_config(config_path)
    policy = _part5_policy()
    w = policy.part_stage_windows()[focus_part]
    win_start = int(w["approach_start"])
    win_end = int(w["open_end"])

    diag = ABCDiagnosis(
        source=f"simulate:{config_path}{label_suffix}",
        focus_part=focus_part,
        window=(win_start, win_end),
        hand_hold_overlaps_place=_hand_hold_overlaps_place(
            cfg, win_start, int(w["descend_end"]), hold_end_override=hold_end_override
        ),
    )

    engine = RuleEngine(cfg)
    envelope = EnvelopeEvaluator(cfg)

    # Post-detour EE offset entering place (mirrors lateral_first + STOP lag).
    lateral_off = np.zeros(3, dtype=np.float64)
    z_lag = 0.0
    if with_replan:
        detour_at = 1670
        ee_d = policy._action_at_step(detour_at)[:3]
        hand_d, _ = hand_pose(detour_at, cfg)
        delta = ee_d[:2] - hand_d[:2]
        norm = float(np.linalg.norm(delta))
        away = np.array([0.0, 1.0]) if norm < 1e-6 else delta[:2] / norm
        lat_m = float(cfg.replan_lateral_offset_m)
        lateral_off[:2] = away * lat_m
        lateral_off[2] = 0.02
        z_lag = 0.14

    task_ts = win_start
    policy.time_step = task_ts - 1
    sim_ee = policy._action_at_step(task_ts)[:3].astype(np.float64) + lateral_off
    sim_ee[2] += z_lag

    part_quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    if inject_tilt_deg > 0:
        tilt_rad = math.radians(inject_tilt_deg)
        part_quat = np.array(
            [math.cos(tilt_rad / 2), 0.0, math.sin(tilt_rad / 2), 0.0],
            dtype=np.float64,
        )

    prev_task: int | None = None
    post_detour = with_replan

    for _ in range(win_end - win_start + 1):
        eval_step = task_ts + 1
        script_action = policy._action_at_step(eval_step)
        script_pos = script_action[:3].astype(np.float64) + lateral_off
        script_pos[2] += z_lag if with_replan else 0.0

        hand_pos, hand_vel = hand_pose_at_step(
            task_ts, cfg, hold_end_override=hold_end_override
        )
        hand_speed = float(np.linalg.norm(hand_vel))
        held = policy.is_carrying_object(eval_step)

        state = SafetyState(
            ee_pos=sim_ee.astype(np.float32),
            ee_vel=np.zeros(3, dtype=np.float32),
            human_hand_pos=hand_pos.astype(np.float32),
            human_hand_vel=hand_vel.astype(np.float32),
            joint_pos=np.zeros(6, dtype=np.float32),
            joint_vel=np.zeros(6, dtype=np.float32),
            sim_time=task_ts * cfg.control_dt,
            step_index=task_ts,
        )
        env_result = envelope.evaluate(state, held_object_active=held)
        dist_gating = (
            float(env_result.dist_min_envelope) if cfg.envelope.gating_enabled else None
        )
        gate = engine.evaluate(
            state,
            dist_for_gating=dist_gating,
            dist_min_held=env_result.dist_min_held,
            held_object_active=held,
        )
        enrich_gate_metadata_from_envelope(
            gate.metadata,
            {
                "dist_min_envelope": env_result.dist_min_envelope,
                "dist_min_held": env_result.dist_min_held,
                "dist_min_arm": env_result.dist_min_arm,
                "dist_min_gripper": env_result.dist_min_gripper,
                "closest_primitive_id": env_result.closest_primitive_id,
            },
        )

        g_rule = int(gate.g_t)
        dist_ee = float(gate.metadata.get("dist_ee_human", 0.0))
        dist_min_held = env_result.dist_min_held

        advance = g_rule == GATE_ALLOW
        transport = policy.transport_phase_at_step(task_ts)
        if with_replan and transport == "transit" and g_rule != GATE_ALLOW:
            advance = True  # post_replan_advance during detour (already past for place window)

        alpha = 1.0
        if g_rule == GATE_SLOW:
            alpha = float(gate.metadata.get("slow_down_alpha", cfg.slow_down_alpha))
        elif g_rule == GATE_STOP:
            alpha = 0.05

        target = script_pos if advance else sim_ee
        sim_ee = sim_ee + alpha * (target - sim_ee)

        part_pos = sim_ee.copy()
        part_pos[0] += 0.015 if inject_tilt_deg > 0 else 0.0
        part_pose = np.concatenate([part_pos, part_quat])

        frozen = prev_task is not None and task_ts == prev_task
        grip_script = _script_gripper(policy, eval_step)
        grip_exec = GRIPPER_CLOSED if grip_script <= CARRY_THRESHOLD else GRIPPER_OPEN
        if policy.should_hold_open_gripper(sim_ee, eval_step):
            grip_exec = GRIPPER_CLOSED

        label, note = _classify_step(
            policy=policy,
            task_ts=task_ts,
            ee=sim_ee,
            g_rule=g_rule,
            grip_exec=grip_exec,
            dist_ee=dist_ee,
            dist_min_held=dist_min_held,
            hand_speed=hand_speed,
            frozen=frozen,
            part_pose=part_pose if inject_tilt_deg > 0 else None,
            cfg=cfg,
        )
        if inject_tilt_deg > 0 and label == "A" and policy.is_in_place_window(task_ts):
            if not SingleEnvPickAndPlacePolicy.validate_grasp_hold(
                sim_ee, part_pose, upright_min_dot=PLACE_UPRIGHT_MIN_DOT
            ):
                label = "B"
                note = f"injected tilt {inject_tilt_deg}deg fails place upright gate"

        target_xy = policy.place_target_xy_at_step(task_ts)
        xy_err = (
            float(np.linalg.norm(sim_ee[:2] - target_xy[:2])) if target_xy is not None else 0.0
        )
        z_err = float(sim_ee[2] - policy._action_at_step(task_ts)[2])

        diag.records.append(
            StepRecord(
                task_ts=task_ts,
                label=label,
                stage=policy.stage_name_at_step(task_ts),
                transport=transport,
                g_rule=g_rule,
                ee=sim_ee.copy(),
                script=policy._action_at_step(task_ts)[:3],
                grip_exec=grip_exec,
                grip_script=grip_script,
                dist_ee=dist_ee,
                dist_min_held=dist_min_held,
                hand_speed=hand_speed,
                frozen=frozen,
                xy_err=xy_err,
                z_err=z_err,
                upright_dot=(
                    SingleEnvPickAndPlacePolicy._pose_upright_dot(part_pose)
                    if inject_tilt_deg > 0
                    else None
                ),
                notes=note,
            )
        )

        if advance and task_ts < win_end:
            task_ts += 1
            policy.time_step = task_ts - 1
        prev_task = task_ts

    if post_detour and inject_tilt_deg == 0:
        diag.evidence.append(
            "Simulation assumes post-detour lateral offset "
            f"{float(cfg.replan_lateral_offset_m):.2f}m + z_lag {z_lag:.2f}m"
        )

    diag.recommendation, diag.evidence = _recommend(diag)
    return diag


def compare_yaml_scenarios(config_path: str = "configs/ivj/ivj_intrusion_positive.yaml") -> None:
    """Counterfactual v8 yaml variants — quick yaml-first vs code-first triage."""
    cfg = load_safety_config(config_path)
    traj = cfg.human_trajectory
    hold_end_v8 = traj.hold_end_step()
    hold_end_short = traj.approach_end_step() + 60
    hold_end_early = 1730  # before Part5 approach_start=1735

    scenarios = [
        ("v8 baseline (hold=120)", None),
        (f"hold_steps=60 (hold_end={hold_end_short})", hold_end_short),
        (f"hold_end={hold_end_early} (pre-approach)", hold_end_early),
    ]

    print("=== YAML counterfactual ABC (simulation) ===")
    print(f"v8 hold window: {traj.approach_end_step()}–{hold_end_v8}  |  Part5 approach=1735")
    print("")
    print(f"{'scenario':<36} | {'C%':>5} | {'A%':>5} | {'B%':>5} | dominant | recommendation")
    print("-" * 88)

    for name, hold_override in scenarios:
        diag = simulate_part5(
            config_path,
            hold_end_override=hold_override,
            label_suffix=f" [{name}]",
        )
        print(
            f"{name:<36} | {diag.pct('C'):5.1f} | {diag.pct('A'):5.1f} | "
            f"{diag.pct('B'):5.1f} | {str(diag.dominant):8s} | {diag.recommendation}"
        )

    print("")
    print("Interpretation:")
    print("  - C drops sharply when hold ends before approach → yaml_first validated")
    print("  - C stays high but A rises when hold clears but detour offset remains → code trajectory")
    print("  - B rises with part_pose logging + post-detour tilt → code pose gate")


def print_report(diag: ABCDiagnosis, *, verbose: bool = False) -> None:
    c = diag.counts
    print(f"=== ABC placement diagnosis ({diag.source}) ===")
    print(f"Part {diag.focus_part} window: task_ts {diag.window[0]}–{diag.window[1]}")
    print(
        f"hand_hold_overlaps_place={diag.hand_hold_overlaps_place}  "
        f"risk_steps={diag.risk_total}  unique_at_risk_ts={len(diag.unique_task_ts)}  "
        f"(OK steps={c['OK']})"
    )
    print("")
    print(f"  C conservative : {c['C']:4d}  ({diag.pct('C'):5.1f}%)")
    print(f"  A trajectory   : {c['A']:4d}  ({diag.pct('A'):5.1f}%)")
    print(f"  B tilt/part    : {c['B']:4d}  ({diag.pct('B'):5.1f}%)")
    print(f"  dominant       : {diag.dominant}")
    print("")
    print(f"RECOMMENDATION: {diag.recommendation}")
    for line in diag.evidence:
        print(f"  - {line}")

    if verbose and diag.records:
        print("")
        print("Sample at-risk steps (first 12 non-OK):")
        shown = 0
        for r in diag.records:
            if r.label == "OK":
                continue
            print(
                f"  ts={r.task_ts} {r.label} g={r.g_rule} {r.stage[:28]:28s} "
                f"xy_err={r.xy_err:.3f} z_err={r.z_err:+.3f} frozen={r.frozen} | {r.notes}"
            )
            shown += 1
            if shown >= 12:
                break


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Safety log run dir (episode_0000.csv) or direct CSV path",
    )
    parser.add_argument("--config", default="configs/ivj/ivj_intrusion_positive.yaml")
    parser.add_argument("--focus-part", type=int, default=5)
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Force simulation even if --run-dir exists",
    )
    parser.add_argument(
        "--no-replan-offset",
        action="store_true",
        help="Simulation: disable post-detour EE offset",
    )
    parser.add_argument(
        "--inject-tilt-deg",
        type=float,
        default=0.0,
        help="Simulation: inject part tilt (degrees) for B-class testing",
    )
    parser.add_argument(
        "--compare-yaml",
        action="store_true",
        help="Run v8 vs shortened-hold counterfactual simulations",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.compare_yaml:
        compare_yaml_scenarios(args.config)
        return 0

    if args.run_dir is not None and not args.simulate:
        path = args.run_dir
        csv_path = path / "episode_0000.csv" if path.is_dir() else path
        if not csv_path.is_file():
            print(f"ERROR: missing {csv_path}", file=sys.stderr)
            return 2
        cfg = load_safety_config(args.config)
        diag = analyze_csv(csv_path, focus_part=args.focus_part, cfg=cfg)
    else:
        diag = simulate_part5(
            args.config,
            with_replan=not args.no_replan_offset,
            inject_tilt_deg=args.inject_tilt_deg,
            focus_part=args.focus_part,
        )

    if args.json:
        print(json.dumps(diag.to_dict(), indent=2))
    else:
        print_report(diag, verbose=args.verbose)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
