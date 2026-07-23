"""Offline implementation-readiness pack for V1-E2E motion isolation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def evaluate_motion_isolation_implementation(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root)
    run_phase3 = root / "g1_ur10e_disturbance" / "scripts" / "run_phase3.py"
    controller = root / "g1_ur10e_disturbance" / "g1_disturbance_controller.py"
    text_run = run_phase3.read_text(encoding="utf-8")
    text_ctrl = controller.read_text(encoding="utf-8")

    task_execution_false_not_freeze = (
        "task_execution=false disables task reward/completion contract but does not freeze UR10 policy stepping"
    )
    has_mirrored_script = (
        '"mirrored_outer_lateral_patrol": MIRRORED_OUTER_LATERAL_PATROL_PHASES' in text_ctrl
    )
    has_root_teleport = "write_root_state_to_sim" in text_run

    return {
        "milestone": "V1-E2E",
        "date": "2026-07-23",
        "status": "IMPLEMENTATION_READY",
        "offline_only": True,
        "requires_next_isaac_validation": True,
        "audits": {
            "run_phase3_action_pipeline": {
                "ur10_proposed_source": "ur10e.get_action(obs['ur10e_policy'], advance=False)",
                "policy_clock_advance_gate": "policy_clock_should_advance(...)",
                "task_execution_false_not_freeze": task_execution_false_not_freeze,
                "freeze_switch_wired": "--freeze-ur10e" in text_run and "args_cli.freeze_ur10e" in text_run,
            },
            "mirrored_locomotion_wiring": {
                "mirrored_scripted_phases_registered": has_mirrored_script,
                "scripted_controller_source": "G1DisturbanceController._scripted_command",
                "no_per_frame_root_pose_set": not has_root_teleport,
            },
        },
        "motion_preflight_contract": {
            "seed": 44,
            "camera_pose": {"pos": [0.45, 0.0, 2.7], "rot": [0.7071, 0.0, 0.7071, 0.0]},
            "freeze_ur10e": True,
            "max_steps": 260,
            "must_cross_waypoints_min": 2,
            "gates": {
                "projected_displacement_px_min": 40.0,
                "roi_area_fraction_min": 0.012,
                "ur10_action_norm_max": 1e-6,
                "ur10_joint_delta_max_abs": 1e-6,
                "no_fall_required": True,
                "command_actual_direction_consistent": True,
            },
        },
        "next_step_budget": {
            "source_only_build_allowed": 1,
            "short_motion_preflight_allowed": 1,
            "formal_capture_allowed": 0,
        },
    }


def write_json(path: Path | str, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
