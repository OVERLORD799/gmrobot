# Copyright (c) 2022-2025, The Isaac Lab Project Developers
# (https://github.com/isaac-sim/IsaacLab/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Run a scripted pick-and-place policy in an Isaac Lab environment."""

import argparse
import math
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from isaaclab.app import AppLauncher


# -----------------------------------------------------------------------------
# CLI setup and simulator launch
# -----------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Run a scripted pick-and-place policy for Isaac Lab environments."
    )
    parser.add_argument(
        "--disable_fabric",
        action="store_true",
        default=False,
        help="Disable fabric and use USD I/O operations.",
    )
    parser.add_argument(
        "--num_envs",
        type=int,
        default=None,
        help="Number of environments to simulate.",
    )
    parser.add_argument(
        "--task",
        type=str,
        default="gm",
        help="Name of the task (default: gm).",
    )
    parser.add_argument(
        "--save_camera",
        action="store_true",
        default=False,
        help="Save scene camera RGB frames to disk (requires --enable_cameras).",
    )
    parser.add_argument(
        "--camera_output_dir",
        type=str,
        default=os.path.join(os.environ.get("GMROBOT_OUTPUT_DIR", "/root/GMRobot/output"), "camera_frames"),
        help="Directory for saved camera PNG frames.",
    )
    parser.add_argument(
        "--camera_save_interval",
        type=int,
        default=10,
        help="Save one camera frame every N environment steps.",
    )
    parser.add_argument(
        "--record_video",
        action="store_true",
        default=False,
        help="Compile saved camera frames into MP4 video after simulation (auto-enables --save_camera).",
    )
    parser.add_argument(
        "--record_fps",
        type=int,
        default=25,
        help="Output video framerate (default: 25).",
    )
    parser.add_argument(
        "--enable_safety",
        action="store_true",
        default=False,
        help="Enable Layer 1 rule-based safety gating.",
    )
    parser.add_argument(
        "--safety_config",
        type=str,
        default=None,
        help="Path to safety_layer1.yaml (default: configs/safety_layer1.yaml).",
    )
    parser.add_argument(
        "--max_steps",
        type=int,
        default=None,
        help="Stop after N environment steps (for short regression runs).",
    )
    parser.add_argument(
        "--progress_interval",
        type=int,
        default=500,
        help="Print step_counter / time_step / g_rule every N steps (0 to disable).",
    )
    parser.add_argument(
        "--enable_layer2_shadow",
        action="store_true",
        default=False,
        help="Run Layer 2 predictor in旁路 (log g_ml/would_fuse; gate unchanged).",
    )
    parser.add_argument(
        "--enable_layer2_fusion",
        action="store_true",
        default=False,
        help="Apply tier fusion (not OR) to live gate; requires --enable_safety and --layer2_model_dir.",
    )
    parser.add_argument(
        "--fusion_config",
        type=str,
        default=None,
        help="Path to safety_fusion.yaml (default: configs/safety_fusion.yaml).",
    )
    parser.add_argument(
        "--layer2_model_dir",
        type=str,
        default=None,
        help="Directory with model.joblib + feature_schema.json (required with --enable_layer2_shadow).",
    )
    parser.add_argument(
        "--enable_replan",
        action="store_true",
        default=False,
        help="Enable Phase 4a geometry motion replan on L1 warn/SLOW.",
    )
    parser.add_argument(
        "--enable_vlm",
        action="store_true",
        default=False,
        help="Enable Layer 3 VLM client (remote Qwen backend; non-blocking).",
    )
    parser.add_argument(
        "--vlm_config",
        type=str,
        default=None,
        help="Path to vlm_client.yaml (default: configs/vlm_client.yaml).",
    )
    parser.add_argument(
        "--vlm_interval",
        type=int,
        default=50,
        help="Call VLM every N control steps (~1 Hz at 50).",
    )
    parser.add_argument(
        "--enable_perception",
        action="store_true",
        default=False,
        help="Enable Layer 3 perception client (GDINO+SAM2 shadow; non-blocking, no gate).",
    )
    parser.add_argument(
        "--perception_config",
        type=str,
        default=None,
        help="Path to perception_client.yaml (default: configs/perception_client.yaml).",
    )
    parser.add_argument(
        "--perception_interval",
        type=int,
        default=100,
        help="Call /ground every N control steps (~0.5 Hz at 50; first call may be slow).",
    )
    parser.add_argument(
        "--enable_perception_track",
        action="store_true",
        default=False,
        help="Enable SAM2 /track shadow (requires --enable_perception + cameras).",
    )
    parser.add_argument(
        "--perception_track_interval",
        type=int,
        default=1,
        help="Call /track every N control steps when --enable_perception_track (default: every step).",
    )
    parser.add_argument(
        "--enable_vlm_grasp_supervisor",
        action="store_true",
        default=False,
        help="Enable VLM global grasp supervisor (checks object-in-gripper during carry; requires --enable_vlm).",
    )
    parser.add_argument(
        "--vlm_grasp_interval",
        type=int,
        default=100,
        help="Call VLM grasp check every N control steps during carry phase (default: 100, i.e. ~0.5 Hz).",
    )
    parser.add_argument(
        "--vlm_grasp_confidence_threshold",
        type=float,
        default=0.7,
        help="Min VLM confidence to act on 'object lost' detection (default: 0.7).",
    )
    parser.add_argument(
        "--vlm_scene_inventory_interval",
        type=int,
        default=500,
        help="Call VLM full-scene inventory check every N control steps (default: 500, ~0.1 Hz).",
    )
    parser.add_argument(
        "--enable_time_to_risk",
        action="store_true",
        default=False,
        help="Enable W13 time-to-risk regression shadow + predictive replan trigger.",
    )
    parser.add_argument(
        "--time_to_risk_model_dir",
        type=str,
        default=os.path.join(os.environ.get("GMROBOT_OUTPUT_DIR", "/root/GMRobot/output"), "safety_models", "time_to_risk_v1"),
        help="Directory with time_to_risk_model.joblib.",
    )
    parser.add_argument(
        "--time_to_risk_threshold_steps",
        type=int,
        default=50,
        help="Trigger predictive replan when predicted time_to_risk < threshold steps.",
    )

    AppLauncher.add_app_launcher_args(parser)
    return parser


parser = build_arg_parser()
args_cli = parser.parse_args()

# Isaac Sim must be launched before importing other simulation-related modules.
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app


# -----------------------------------------------------------------------------
# Remaining imports
# -----------------------------------------------------------------------------

import gymnasium as gym
import numpy as np
import torch
from PIL import Image

import GMRobot.tasks  # noqa: F401
import isaaclab_tasks  # noqa: F401
from GMRobot.safety import (
    EnvelopeEvaluator,
    GateDecision,
    GateResult,
    HumanMotionController,
    RuleEngine,
    SafetyGate,
    SafetyLogger,
    SafetyMetrics,
    SafetyState,
    compute_ground_truth_from_state,
    compute_ground_truth_v12_from_envelope,
    compute_gt_branches,
    episode_outcome_from_ground_truth,
    load_safety_config,
)
from GMRobot.safety.part_tracker import PartTracker
from GMRobot.safety.logger import (
    merge_perception_log_fields,
    perception_log_fields_from_result,
    replan_log_fields_for_step,
    track_log_fields_from_result,
    vlm_log_fields_from_result,
)
from GMRobot.safety.vlm_grasp_supervisor import (
    VLMGraspSupervisor,
    VLMGraspSupervisorConfig,
    grasp_supervisor_log_fields,
    scene_inventory_log_fields,
)
from GMRobot.safety.fusion import compute_fusion, load_fusion_config, row_for_predictor
from GMRobot.safety.hand_trajectory_filter import (
    HandTrajectoryFilter,
    HandTrajectoryFilterConfig,
)
from GMRobot.safety.layer2.predictor import TimeToRiskPredictor
from GMRobot.safety.replan import (
    GeometryReplanV0,
    L1WarnReplanTrigger,
    ReplanRuntimeState,
    ReplanTriggerConfig,
    enrich_gate_metadata_from_envelope,
    enrich_gate_metadata_from_perception_track,
)
from GMRobot.perception import PerceptionClient, PerceptionTrackSession
from GMRobot.vlm import VLMClient
from isaaclab_tasks.utils import parse_env_cfg

from pick_and_place_policy import (
    DEFAULT_USER_COMMANDS,
    SingleEnvPickAndPlacePolicy,
)


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------

def to_numpy(obj):
    """Recursively convert torch tensors in a nested structure to NumPy arrays."""
    if torch.is_tensor(obj):
        return obj.detach().cpu().numpy()

    if isinstance(obj, Mapping):
        return {key: to_numpy(value) for key, value in obj.items()}

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes)):
        return type(obj)(to_numpy(item) for item in obj)

    return obj


def to_tensor(obj, dtype=None, device=None, clone=False):
    """Recursively convert NumPy arrays in a nested structure to torch tensors."""
    if isinstance(obj, Mapping):
        return {
            key: to_tensor(value, dtype=dtype, device=device, clone=clone)
            for key, value in obj.items()
        }

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes)):
        return type(obj)(
            to_tensor(item, dtype=dtype, device=device, clone=clone)
            for item in obj
        )

    if isinstance(obj, np.ndarray):
        obj = torch.from_numpy(obj)

    if torch.is_tensor(obj):
        if device is not None or dtype is not None:
            obj = obj.to(device=device, dtype=dtype)
        if clone:
            obj = obj.clone()

    return obj


# -----------------------------------------------------------------------------
# Policy classes
# -----------------------------------------------------------------------------

class MultiEnvPickAndPlacePolicy:
    """Wrapper that runs one scripted pick-and-place policy per environment."""

    def __init__(self, num_envs: int):
        self.single_env_policies = [
            SingleEnvPickAndPlacePolicy() for _ in range(num_envs)
        ]

    def get_action(self, obs, *, advance: bool = True):
        """Compute actions for all environments."""
        policy_obs = to_numpy(obs)["policy"]

        actions = []
        for env_idx, policy in enumerate(self.single_env_policies):
            env_obs = {key: value[env_idx] for key, value in policy_obs.items()}
            env_action = policy.get_action(env_obs, advance=advance)
            actions.append(env_action)

        return np.stack(actions, axis=0)

    def advance_time_steps(self, advance_mask) -> None:
        """Advance scripted trajectory indices only for environments that executed motion."""
        for env_idx, policy in enumerate(self.single_env_policies):
            if advance_mask[env_idx]:
                policy.advance_time_step()

    def reset(self, obs, mask=None):
        """Reset all policies, or only those selected by a mask."""
        policy_obs = to_numpy(obs)["policy"]

        for env_idx, policy in enumerate(self.single_env_policies):
            env_obs = {key: value[env_idx] for key, value in policy_obs.items()}
            if mask is None or mask[env_idx]:
                policy.reset(env_obs)

    def is_success(self):
        """Return success flags for all environments."""
        return [policy.success for policy in self.single_env_policies]


# -----------------------------------------------------------------------------
# Environment execution
# -----------------------------------------------------------------------------

def create_env_cfg():
    """Build the environment configuration from CLI arguments."""
    return parse_env_cfg(
        args_cli.task,
        device=args_cli.device,
        num_envs=args_cli.num_envs,
        use_fabric=not args_cli.disable_fabric,
    )


def save_camera_frames(obs, output_dir: str, step: int) -> None:
    """Save RGB frames from obs['camera']['scene_rgb'] as PNG files."""
    if "camera" not in obs or "scene_rgb" not in obs["camera"]:
        return

    os.makedirs(output_dir, exist_ok=True)
    rgb = to_numpy(obs["camera"]["scene_rgb"])

    for env_idx in range(rgb.shape[0]):
        frame_path = os.path.join(output_dir, f"frame_{step:06d}_env{env_idx}.png")
        Image.fromarray(rgb[env_idx]).save(frame_path)


def vlm_rgb_frame_path(
    *,
    save_camera: bool,
    camera_output_dir: str,
    step: int,
    env_index: int = 0,
) -> str:
    """Return on-disk PNG path or a minimal step reference for CSV logging."""
    if save_camera:
        return os.path.join(camera_output_dir, f"frame_{step:06d}_env{env_index}.png")
    return f"vlm:step={step}"


def run_perception_ground_shadow(
    perception_client: PerceptionClient,
    obs,
    *,
    step_counter: int,
    save_camera: bool,
    camera_output_dir: str,
    text_prompt: str | None = None,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Call /ground on scene RGB and map the response to logger columns."""
    obs_np = to_numpy(obs)
    if "camera" not in obs_np or "scene_rgb" not in obs_np["camera"]:
        return None, None

    if save_camera:
        save_camera_frames(obs, camera_output_dir, step_counter)

    result = perception_client.ground(
        obs_np["camera"]["scene_rgb"],
        text_prompt=text_prompt,
        meta={"step": step_counter},
    )
    fields = perception_log_fields_from_result(
        result,
        gdino_model_id=result.get("gdino_model_id", ""),
    )
    return fields, result


def run_perception_track_shadow(
    perception_client: PerceptionClient,
    obs,
    *,
    step_counter: int,
    track_session: PerceptionTrackSession,
    seed_box_xyxy: list[float] | None = None,
) -> tuple[dict[str, str] | None, PerceptionTrackSession]:
    """Call /track on scene RGB; map primary hand track to logger columns."""
    obs_np = to_numpy(obs)
    if "camera" not in obs_np or "scene_rgb" not in obs_np["camera"]:
        return None, track_session

    rgb = obs_np["camera"]["scene_rgb"]
    track_result, session = perception_client.track_frame(
        rgb,
        track_session,
        box_xyxy=seed_box_xyxy if track_session.session_id is None else None,
        meta={"step": step_counter},
    )
    if track_result.get("ok") is False or track_result.get("error"):
        return None, session

    primary = perception_client.pick_primary_track(
        track_result,
        target_label=perception_client.config.track_target_label,
    )
    if primary is None:
        return None, session

    primary = perception_client.enrich_track_kinematics(
        primary,
        session=session,
        dt_s=perception_client.config.track_dt_s,
    )
    fields = track_log_fields_from_result(track_result, primary) or {}
    if track_result.get("latency_ms") is not None:
        fields["perception_latency_ms"] = str(track_result["latency_ms"])
    return fields, session


_force_vlm_refresh = False  # 8.6: force VLM query after placement

def run_vlm_inference(
    vlm_client: VLMClient,
    obs,
    *,
    step_counter: int,
    save_camera: bool,
    camera_output_dir: str,
) -> dict[str, str] | None:
    """Fire async VLM request; return last completed result (non-blocking)."""
    obs_np = to_numpy(obs)
    if "camera" not in obs_np or "scene_rgb" not in obs_np["camera"]:
        return None

    rgb_frame_path = vlm_rgb_frame_path(
        save_camera=save_camera,
        camera_output_dir=camera_output_dir,
        step=step_counter,
    )
    if save_camera:
        save_camera_frames(obs, camera_output_dir, step_counter)

    # Refresh VLM every 200 steps (4s at 50Hz), or on force-refresh
    # after placement (8.6).  First call at step 0 seeds the cache.
    _vlm_refresh_interval = 200
    if (
        not hasattr(run_vlm_inference, "_cached_result")
        or step_counter % _vlm_refresh_interval == 0
        or run_vlm_inference._force_vlm_refresh
    ):
        run_vlm_inference._force_vlm_refresh = False
        run_vlm_inference._cached_result = vlm_client.analyze(
            obs_np["camera"]["scene_rgb"],
            meta={"step": step_counter},
        )
    last_vlm_result = run_vlm_inference._cached_result
    return vlm_log_fields_from_result(
        last_vlm_result,
        model_id=vlm_client.config.model_id,
        rgb_frame_path=rgb_frame_path,
    )


def read_link_positions_w(env, env_index: int, link_names: list[str]) -> dict[str, np.ndarray] | None:
    """Read UR10e link world positions from Isaac scene (best-effort)."""
    try:
        robot = env.unwrapped.scene["robot"]
        body_ids, _ = robot.find_bodies(link_names, preserve_order=True)
        positions = robot.data.body_link_pos_w[env_index, body_ids].detach().cpu().numpy()
        return {
            name: positions[i].copy()
            for i, name in enumerate(link_names)
            if i < len(positions)
        }
    except Exception:
        return None


def read_arm_link_positions_w(env, env_index: int, link_names: list[str]) -> dict[str, np.ndarray] | None:
    """Backward-compatible alias for arm link pose reads."""
    return read_link_positions_w(env, env_index, link_names)


def _gripper_hold_eval_steps(pol, task_time_step: int) -> list[int]:
    if hasattr(pol, "gripper_hold_eval_steps"):
        return pol.gripper_hold_eval_steps(task_time_step)
    return [task_time_step + 1]


def _apply_policy_gripper_overrides(
    pol,
    safe: np.ndarray,
    *,
    ee_pos: np.ndarray,
    task_time_step: int | None,
    env_policy: dict,
    gate_decision: GateDecision | None = None,
) -> tuple[np.ndarray, str]:
    """Apply scripted gripper holds / release latch.

    Order (after held-object boost in caller):
      1. ``should_force_open_gripper`` (grasp rewind) — suppressed during STOP/SLOW_DOWN
      2. ``should_keep_release_gripper_open`` OR ``mark_release_gripper_open``
      3. ``should_hold_open_gripper`` / ``should_hold_release`` (skipped when keep/latched)
    """
    reasons: list[str] = []
    cur_step = task_time_step or 0
    release_step = cur_step + 1
    eval_steps = _gripper_hold_eval_steps(pol, cur_step)
    carry_threshold = (pol.gripper_open + pol.gripper_closed) / 2.0

    # During STOP/SLOW_DOWN the robot cannot re-descend for re-grasp —
    # force-opening the gripper would drop an object that may still be held.
    gate_allows_motion = gate_decision is None or gate_decision == GateDecision.ALLOW
    if gate_allows_motion and pol.should_force_open_gripper():
        safe[7] = pol.gripper_open
        return safe, "force_open"

    release_part_pose = None
    part_idx = pol.part_index_at_step(release_step)
    if part_idx is not None:
        part_key = f"part_{part_idx}_pos"
        if part_key in env_policy:
            release_part_pose = env_policy[part_key]

    keep_open = pol.should_keep_release_gripper_open(release_step)
    if keep_open:
        safe[7] = pol.gripper_open
        reasons.append("keep_release")
    elif (
        hasattr(pol, "mark_release_gripper_open")
        and not pol._release_gripper_committed
        and pol.stage_name_at_step(release_step).startswith("open_gripper_to_release_")
        and float(safe[7]) > carry_threshold
        and not any(
            pol.should_hold_release(ee_pos, release_part_pose, step)
            or pol.should_hold_open_gripper(ee_pos, step)
            for step in eval_steps
        )
    ):
        pol.mark_release_gripper_open()
        reasons.append("mark_release")

    if not keep_open and not pol._release_gripper_committed:
        for step in eval_steps:
            if pol.should_hold_open_gripper(ee_pos, step):
                safe[7] = pol.gripper_closed
                reasons.append("hold_open")
                break
            if pol.should_hold_release(ee_pos, release_part_pose, step):
                safe[7] = pol.gripper_closed
                reasons.append("hold_release")
                break

    return safe, "+".join(reasons) if reasons else "script"



def _resolve_advance(
    *,
    gate_result,
    replan_states: list | None,
    env_idx: int,
    task_time_step: int | None,
    transport_phase: str,
    result,
    safety_config,
    pol,
    state,
    env_policy: dict,
) -> bool:
    """Determine whether the policy clock should advance this step.

    Gate ALLOW is the baseline; replan overrides can force advance during transit;
    place-advance blockers and empty-carry abort can override further.
    """
    advance = gate_result.g_t in (GateDecision.ALLOW, GateDecision.SLOW_DOWN)

    # Replan in transit: override gate to keep the policy clock moving.
    if (
        replan_states is not None
        and replan_states[env_idx].allows_advance(task_time_step or 0)
        and transport_phase == "transit"
    ):
        advance = True

    # Resolve effective distance for warn-zone checks.
    dist_hold = result.metadata.get("dist_min_envelope")
    if dist_hold is None:
        dist_hold = result.metadata.get("dist_min")
    if dist_hold is None:
        dist_hold = result.metadata.get("dist_ee_human")
    dist_f = float(dist_hold) if dist_hold not in (None, "") else None
    warn_dist = safety_config.safe_dist_warn if safety_config is not None else 0.16

    if pol is not None and hasattr(pol, "should_block_place_advance_while_hand_near"):
        release_part_pose = None
        release_step = (task_time_step or 0) + 1
        part_idx = pol.part_index_at_step(release_step)
        if part_idx is not None:
            part_key = f"part_{part_idx}_pos"
            if part_key in env_policy:
                release_part_pose = env_policy[part_key]
        if pol.should_block_place_advance_while_hand_near(
            state.ee_pos,
            release_step,
            dist_ee_human=dist_f,
            safe_dist_warn=warn_dist,
            part_pose=release_part_pose,
        ):
            advance = False

    if pol is not None and hasattr(pol, "should_wait_hold_place_progress"):
        if pol.should_wait_hold_place_progress(
            state.ee_pos,
            task_time_step or 0,
            dist_ee_human=dist_f,
            safe_dist_warn=warn_dist,
        ):
            advance = False

    if pol is not None and hasattr(pol, "should_advance_empty_carry_abort"):
        if pol.should_advance_empty_carry_abort(task_time_step or 0):
            advance = True

    return advance

@dataclass
class _EnvContext:
    """Per-environment extracted state (D2: extracted from god function)."""
    state: SafetyState
    pol: Any
    task_time_step: int | None
    task_time_step_max: int | None
    in_place_window: bool
    defer_late_approach: bool
    transport_phase: str
    held_object_active: bool
    held_part_pose: np.ndarray | None
    eval_task_step: int


def _build_env_context(
    env_idx: int,
    env_policy: dict,
    env_safety: dict,
    policy: Any,
    hand_pos: np.ndarray | None,
    hand_vel: np.ndarray | None,
    torso_pos: np.ndarray | None,
    torso_vel: np.ndarray | None,
    sim_time: float,
    step_counter: int,
    prev_ee_pos: np.ndarray | None,
    control_dt: float,
) -> _EnvContext:
    """Extract per-environment state from raw observation dicts."""
    state = SafetyState.from_runtime(
        env_policy, env_safety,
        human_hand_pos=hand_pos,
        human_hand_vel=hand_vel,
        human_torso_pos=torso_pos,
        human_torso_vel=torso_vel,
        sim_time=sim_time, step_index=step_counter,
        prev_ee_pos=prev_ee_pos, control_dt=control_dt,
    )
    pol = None
    task_time_step = None
    task_time_step_max = None
    in_place_window = False
    defer_late_approach = False
    transport_phase = "transit"
    if policy is not None:
        pol = policy.single_env_policies[env_idx]
        task_time_step = pol.time_step
        if pol.time_stamps is not None and len(pol.time_stamps) > 0:
            task_time_step_max = int(pol.time_stamps[-1])
        if hasattr(pol, "is_in_place_window"):
            in_place_window = pol.is_in_place_window(task_time_step or 0)
        if hasattr(pol, "transport_phase_at_step"):
            transport_phase = pol.transport_phase_at_step(task_time_step or 0)
        if hasattr(pol, "is_late_approach_to_place"):
            defer_late_approach = pol.is_late_approach_to_place(task_time_step or 0)
    held_object_active = False
    held_part_pose = None
    eval_task_step = (task_time_step or 0) + 1
    if pol is not None and hasattr(pol, "is_carrying_object"):
        held_object_active = pol.is_carrying_object(eval_task_step)
        if held_object_active:
            part_idx = pol.part_index_at_step(task_time_step or 0)
            if part_idx is not None:
                part_key = f"part_{part_idx}_pos"
                if part_key in env_policy:
                    held_part_pose = np.asarray(env_policy[part_key], dtype=np.float64)
    return _EnvContext(
        state=state, pol=pol,
        task_time_step=task_time_step, task_time_step_max=task_time_step_max,
        in_place_window=in_place_window, defer_late_approach=defer_late_approach,
        transport_phase=transport_phase,
        held_object_active=held_object_active, held_part_pose=held_part_pose,
        eval_task_step=eval_task_step,
    )


def _try_replan(
    replan_executor,
    replan_trigger,
    replan_states,
    pol,
    state,
    env_idx: int,
    request,
    *,
    task_time_step_max,
) -> str:
    """Submit a ReplanRequest and poll/apply.  Returns event string.

    Replaces 3 duplicates of the submit/poll/apply logic (C4+H7).
    """
    replan_executor.submit(request)
    done = replan_executor.poll()
    if done is None:
        return "trigger"
    runtime_state = replan_states[env_idx] if replan_states is not None else None
    if not replan_executor.apply(done, pol, runtime_state=runtime_state):
        return "failed"
    replan_trigger.on_replan_applied(state.step_index, done.resume_time_step)
    # apply_result() is called inside apply() now (cumulative lateral tracking)
    if hasattr(pol, "on_replan_splice_applied"):
        pol.on_replan_splice_applied(done.resume_time_step)
    return "applied"


# ---------------------------------------------------------------------------
# F6: helpers extracted from apply_safety_gate (was one 741-line function)
# ---------------------------------------------------------------------------


def _run_kalman_shadow(
    hand_trajectory_filter: Any | None,
    hand_pos: np.ndarray | None,
    _multi_env: bool,
    _ttr_step: bool,
) -> dict[str, str]:
    """Kalman filter update + horizon prediction (S13 P2 / W9-P2)."""
    fields: dict[str, str] = {}
    if _multi_env or hand_trajectory_filter is None or hand_pos is None:
        return fields
    try:
        pred = hand_trajectory_filter.update(hand_pos)
        if pred.ok and _ttr_step:
            # Always write position columns so CSV DictWriter header is stable
            # across rows (avoids ValueError when fields appear mid-stream).
            p = pred.predicted_pos_at_0_5s
            fields["kalman_pred_x_0_5s"] = f"{p[0]:.4f}" if p is not None else ""
            fields["kalman_pred_y_0_5s"] = f"{p[1]:.4f}" if p is not None else ""
            fields["kalman_pred_z_0_5s"] = f"{p[2]:.4f}" if p is not None else ""
            fields["kalman_cov_trace"] = f"{pred.filter_cov_trace:.4f}"
            fields["kalman_obs_count"] = str(pred.filter_obs_count)
    except Exception:
        hand_trajectory_filter.reset()
    return fields


def _run_ttr_shadow(
    time_to_risk_predictor: Any | None,
    time_to_risk_history: Any | None,
    time_to_risk_threshold_steps: int,
    state: Any,
    gate_result: Any,
    hand_vel: np.ndarray | None,
    task_time_step: int | None,
    _ttr_step: bool,
    transport_phase: str,
) -> dict[str, str]:
    """Time-to-risk regression shadow prediction (W13)."""
    fields: dict[str, str] = {}
    if time_to_risk_predictor is None or time_to_risk_history is None:
        return fields
    if not _ttr_step or transport_phase != "transit":
        return fields

    import math as _math
    raw_feats: dict[str, float] = {}
    _ee_arr = np.asarray(state.ee_pos, dtype=np.float64).reshape(-1)[:3]
    _hand_arr = np.asarray(state.human_hand_pos, dtype=np.float64).reshape(-1)[:3]
    raw_feats["dist_ee_human"] = float(_math.dist(_ee_arr.tolist(), _hand_arr.tolist()))
    raw_feats["g_rule"] = float(int(gate_result.g_t))
    if hand_vel is not None and len(hand_vel) >= 3:
        raw_feats["human_hand_vel_x"] = float(hand_vel[0])
        raw_feats["human_hand_vel_y"] = float(hand_vel[1])
        raw_feats["human_hand_vel_z"] = float(hand_vel[2])
    else:
        raw_feats["human_hand_vel_x"] = raw_feats["human_hand_vel_y"] = raw_feats["human_hand_vel_z"] = 0.0
    raw_feats["task_time_step"] = float(task_time_step or 0)
    raw_feats["ttc"] = float(gate_result.metadata.get("ttc", 999))
    raw_feats["approach_rate"] = float(gate_result.metadata.get("approach_rate", 0))
    raw_feats["ttc_forecast_s"] = float(gate_result.metadata.get("ttc_forecast_s", 999))
    trigger_rule = str(gate_result.metadata.get("trigger_rule", ""))
    raw_feats["trigger_rule_cat"] = float(
        {"static": 1, "ttc": 2, "held_critical": 3, "workspace": 4}.get(trigger_rule, 0)
    )
    raw_feats["replan_active"] = 0.0
    raw_feats["replan_event_cat"] = 0.0
    raw_feats["track_speed_px_s"] = 0.0
    raw_feats["track_direction_deg"] = 0.0

    time_to_risk_history.append(raw_feats)
    if len(time_to_risk_history) >= 5:
        lag_feats: dict[str, float] = {}
        history_list = list(time_to_risk_history)
        for lag, hist in enumerate(reversed(history_list)):
            for k, v in hist.items():
                lag_feats[f"{k}_lag{lag}"] = v
        try:
            time_to_risk_steps = time_to_risk_predictor.predict(lag_feats)
            fields["time_to_risk_steps"] = f"{time_to_risk_steps:.1f}"
            fields["predictive_replan_trigger"] = (
                "1" if time_to_risk_steps < time_to_risk_threshold_steps else "0"
            )
        except Exception:
            # F6: shadow prediction failure — skip, don't crash the safety loop.
            pass
    return fields


def _build_replan_log_fields(
    replan_states: list | None,
    env_idx: int,
    replan_event: str,
    replan_trigger_rule: str,
    transport_phase: str,
    stage_name: str,
    task_time_step: int | None,
) -> dict[str, str] | None:
    """Produce replan_log_fields_for_step dict (G3 trigger-rule carry-forward)."""
    if replan_states is None:
        return None
    effective_trigger = replan_trigger_rule
    if not effective_trigger and replan_event in ("trigger", "applied"):
        effective_trigger = replan_states[env_idx].last_trigger_rule
    return replan_log_fields_for_step(
        replan_enabled=True,
        transport_phase=transport_phase,
        stage_name=stage_name,
        post_replan_advance_active=replan_states[env_idx].allows_advance(
            task_time_step or 0
        ),
        event=replan_event,
        trigger_rule=effective_trigger,
    )



def apply_safety_gate(
    obs,
    proposed_actions: np.ndarray,
    prev_actions: np.ndarray,
    prev_ee_positions: list[np.ndarray | None],
    *,
    step_counter: int,
    rule_engine: RuleEngine,
    safety_gate: SafetyGate,
    human_motion: HumanMotionController | None,
    safety_config,
    logger: SafetyLogger | None,
    metrics: SafetyMetrics,
    episode_had_collision: list[bool] | None = None,
    env=None,
    policy=None,
    layer2_predictor: Any | None = None,
    fusion_config=None,
    enable_layer2_fusion: bool = False,
    replan_trigger: L1WarnReplanTrigger | None = None,
    replan_executor: GeometryReplanV0 | None = None,
    replan_states: list[ReplanRuntimeState] | None = None,
    envelope_evaluator: EnvelopeEvaluator | None = None,
    vlm_fields: Mapping[str, Any] | None = None,
    perception_fields: Mapping[str, Any] | None = None,
    grasp_supervisor_fields: Mapping[str, Any] | None = None,
    hand_trajectory_filter: Any | None = None,
    time_to_risk_predictor: Any | None = None,
    time_to_risk_history: Any | None = None,
    time_to_risk_threshold_steps: int = 50,
    part_tracker: Any | None = None,
) -> tuple[np.ndarray, list[np.ndarray | None], list[bool], list[int], list[bool]]:
    """Run Layer 1 safety for each environment."""
    obs_np = to_numpy(obs)
    policy_obs = obs_np["policy"]
    safety_obs = obs_np.get("safety", {})
    control_dt = safety_config.control_dt
    sim_time = step_counter * control_dt

    safe_actions = []
    new_prev_ee = []
    advance_mask = []
    g_rules = []
    gt_collisions = []

    hand_pos_batch, _, hand_vel_batch = (
        human_motion.compute_pose(step_counter)
        if human_motion is not None
        else (None, None, None)
    )
    torso_pose = (
        human_motion.compute_torso_pose(step_counter)
        if human_motion is not None
        else None
    )
    torso_pos_batch, _, torso_vel_batch = torso_pose if torso_pose is not None else (None, None, None)

    num_envs = proposed_actions.shape[0]
    # F7+F8: per-env state leakage guard.  Shared-state modules
    # (RuleEngine._prev_dist_min, HandTrajectoryFilter) are safe
    # for num_envs=1 (production).  For num_envs>1, suppress
    # forecast TTC and Kalman to avoid cross-env corruption.
    _multi_env = num_envs > 1
    if _multi_env and not hasattr(apply_safety_gate, "_warned_multi_env"):
        print("[WARN] num_envs>1: TTC forecast and Kalman disabled (shared state)", flush=True)
        apply_safety_gate._warned_multi_env = True
    for env_idx in range(num_envs):
        env_policy = {key: value[env_idx] for key, value in policy_obs.items()}
        env_safety = {key: value[env_idx] for key, value in safety_obs.items()} if safety_obs else {}

        if hand_pos_batch is not None:
            hand_pos = hand_pos_batch[env_idx]
            hand_vel = hand_vel_batch[env_idx]
        else:
            hand_pos = env_safety.get("human_hand_pos", np.zeros(3))
            hand_vel = env_safety.get("human_hand_vel", np.zeros(3))

        torso_pos = torso_pos_batch[env_idx] if torso_pos_batch is not None else None
        torso_vel = torso_vel_batch[env_idx] if torso_vel_batch is not None else None
        ctx = _build_env_context(
            env_idx, env_policy, env_safety, policy,
            hand_pos, hand_vel, torso_pos, torso_vel,
            sim_time, step_counter, prev_ee_positions[env_idx], control_dt,
        )
        state = ctx.state
        pol = ctx.pol
        task_time_step = ctx.task_time_step
        task_time_step_max = ctx.task_time_step_max
        in_place_window = ctx.in_place_window
        defer_late_approach = ctx.defer_late_approach
        transport_phase = ctx.transport_phase
        held_object_active = ctx.held_object_active
        held_part_pose = ctx.held_part_pose
        eval_task_step = ctx.eval_task_step

        # Resolve stage name once for TTC skip + replan + part-tracker consumers.
        stage_name = pol.stage_name_at_step(task_time_step or 0) if pol is not None else ""

        arm_link_positions = None
        fingertip_positions = None
        if env is not None:
            arm_link_positions = read_arm_link_positions_w(
                env,
                env_idx,
                safety_config.envelope.arm_link_names,
            )
            fingertip_positions = read_link_positions_w(
                env,
                env_idx,
                safety_config.envelope.fingertip_link_names,
            )

        envelope_fields = None
        envelope_result = None  # H5: hoisted to prevent NameError
        dist_for_gating: float | None = None
        dist_min_held: float | None = None
        if envelope_evaluator is not None:
            envelope_result = envelope_evaluator.evaluate(
                state,
                arm_link_positions_w=arm_link_positions,
                fingertip_positions_w=fingertip_positions,
                held_object_active=held_object_active,
                held_part_pose=held_part_pose,
            )
            envelope_fields = envelope_result.to_log_dict()
            if safety_config.envelope.gating_enabled:
                dist_for_gating = float(envelope_result.dist_min_envelope)
            if envelope_result.dist_min_held is not None:
                dist_min_held = float(envelope_result.dist_min_held)

        # S7 Option C: pass closest envelope primitive position so TTC uses
        # envelope-relative approach direction (not EE-relative).
        closest_prim_pos = (
            envelope_result.closest_primitive_pos
            if envelope_result is not None
            else None
        )
        # G5a: functional risk info from policy state.
        _func_info: dict | None = None
        if pol is not None:
            _rewinds = getattr(pol, "_grasp_rewind_attempts", 0)
            _release_ok = True
            if hasattr(pol, "validate_placement_at_step") and hasattr(pol, "stage_name_at_step"):
                _step = task_time_step or 0
                _name = pol.stage_name_at_step(_step)
                if _name.startswith("open_gripper_to_release_"):
                    _release_ok = pol.validate_placement_at_step(state.ee_pos, _step)
            _func_info = {
                "rewind_attempts": int(_rewinds),
                "release_in_zone": _release_ok,
                "max_rewinds": 2,  # GRASP_MAX_REWIND_ATTEMPTS from pick_and_place_policy
            }
        # Skip TTC during vertical lift phases: pure up/down motion doesn't
        # benefit from TTC gating and only causes unnecessary slowdowns (§8.2).
        _skip_ttc_stage = pol.stage_name_at_step(task_time_step or 0) if pol is not None else ""
        _skip_ttc = _skip_ttc_stage.startswith((
            "lift_after_grasping_",
            "lift_after_releasing_",
            "grasp_slot_",
            "close_gripper_slot_",
        ))
        result = rule_engine.evaluate(
            state,
            dist_for_gating=dist_for_gating,
            dist_min_held=dist_min_held,
            held_object_active=held_object_active,
            closest_primitive_pos=closest_prim_pos,
            functional_risk_info=_func_info,
            skip_ttc=_skip_ttc,
            proposed_ee_pos=proposed_actions[env_idx][:3],
        )
        enrich_gate_metadata_from_envelope(result.metadata, envelope_fields)
        enrich_gate_metadata_from_perception_track(result.metadata, perception_fields)
        gate_result = result
        shadow_fields = None

        envelope_gating = safety_config.envelope.gating_enabled
        if envelope_gating and dist_for_gating is not None:
            g_gt, dist_gt = compute_ground_truth_v12_from_envelope(
                dist_for_gating,
                safety_config,
            )
        else:
            g_gt, dist_gt = compute_ground_truth_from_state(state, safety_config)

        if layer2_predictor is not None:
            dist_ee = result.metadata.get("dist_ee_human")
            ttc_rule = result.metadata.get("ttc")
            pred_row = row_for_predictor(
                state.to_log_dict(),
                dist_ee_human=dist_ee,
                ttc=ttc_rule,
                envelope_fields=envelope_fields,
            )
            g_ml = layer2_predictor.predict_row(pred_row)
            g_ml_confidence = layer2_predictor.predict_proba_for_label(pred_row, g_ml)
            fcfg = fusion_config or load_fusion_config()
            dist_min_meta = result.metadata.get("dist_min_envelope")
            fusion = compute_fusion(
                g_rule=int(result.g_t),
                g_ml=g_ml,
                g_ml_confidence=g_ml_confidence,
                g_ground_truth=g_gt,
                dist_ee_human=float(dist_ee) if dist_ee not in (None, "") else None,
                dist_min_envelope=(
                    float(dist_min_meta)
                    if dist_min_meta not in (None, "")
                    else None
                ),
                envelope_gating=envelope_gating,
                safe_dist_hard_stop=fcfg.safe_dist_hard_stop,
                safe_dist_warn=fcfg.safe_dist_warn,
                ml_override_theta=fcfg.ml_override_theta,
                trigger_rule=str(result.metadata.get("trigger_rule", "")),
            )
            shadow_fields = fusion.to_log_dict()
            if enable_layer2_fusion:
                gate_result = GateResult(
                    g_t=GateDecision(fusion.would_fuse),
                    reason=f"tier_fusion:{fusion.fusion_tier}",
                    metadata=result.metadata,
                )

        safe = safety_gate.apply(gate_result, proposed_actions[env_idx], prev_actions[env_idx])

        if held_object_active and pol is not None:
            ee_speed = float(np.linalg.norm(state.ee_vel[:3]))
            vel_threshold = safety_config.gripper_boost_vel_threshold
            dist_hold = result.metadata.get("dist_min_envelope")
            if dist_hold is None:
                dist_hold = result.metadata.get("dist_ee_human")
            dist_f = (
                float(dist_hold) if dist_hold not in (None, "") else None
            )
            warn_dist = safety_config.effective_warn
            traj = safety_config.human_trajectory
            hand_sweep_active = safety_config.human_enabled and (
                traj.is_approaching(state.step_index)
                or traj.is_retreating(state.step_index)
            )
            should_boost = False
            if gate_result.g_t != GateDecision.ALLOW and ee_speed >= vel_threshold:
                should_boost = True
            elif hand_sweep_active and ee_speed >= vel_threshold:
                # Part 1 carry (201–250) vs hand sweep (248–302): partial mitigation only; knock-off deferred (Phase 4+).
                should_boost = True
            elif dist_f is not None and dist_f < warn_dist:
                should_boost = True
            if should_boost:
                boosted = pol.gripper_closed - safety_config.gripper_boost_extra_closed
                if float(safe[7]) > boosted:
                    safe[7] = boosted

        if episode_had_collision is not None and g_gt == int(GateDecision.STOP):
            episode_had_collision[env_idx] = True

        branch_result = compute_gt_branches(
            state,
            safety_config,
            arm_link_positions_w=arm_link_positions,
            env=env,
            env_index=env_idx,
            dist_min_envelope=dist_for_gating,
        )

        gripper_hold_reason = "script"
        if pol is not None and hasattr(pol, "is_in_grasp_window"):
            # Only latch on an actual gate STOP (not GT-only tier0 envelope).
            replan_active = (
                replan_states is not None
                and replan_states[env_idx].allows_advance(task_time_step or 0)
            )
            if hasattr(pol, "should_latch_grasp_disturbance"):
                if pol.should_latch_grasp_disturbance(
                    eval_task_step,
                    replan_active=replan_active,
                ) and gate_result.g_t == GateDecision.STOP:
                    pol.note_grasp_disturbance()
            elif (
                not (
                    hasattr(pol, "is_grasp_hold_validated")
                    and pol.is_grasp_hold_validated()
                )
                and pol.is_in_grasp_window(eval_task_step)
                and gate_result.g_t == GateDecision.STOP
            ):
                pol.note_grasp_disturbance()

            # --- physics-based knock-off detection (works at ALL carry stages) ---
            # Uses envelope dist_min_held to detect hand→held-object contact.
            # Runs even after grasp validation — this is the ONLY mechanism that
            # can catch mid-transit knock-off before VLM confirmation (300 steps).
            if (
                gate_result.g_t == GateDecision.STOP
                and dist_min_held is not None
                and hasattr(pol, "note_carry_knock_if_hit")
                and pol.note_carry_knock_if_hit(
                    dist_min_held, eval_task_step,
                )
            ):
                print(
                    f"[WARN] Physics knock detected: dist_min_held={dist_min_held:.3f}m "
                    f"at task_step={task_time_step} — clearing grasp validation"
                )

        advance = _resolve_advance(
            gate_result=gate_result,
            replan_states=replan_states,
            env_idx=env_idx,
            task_time_step=task_time_step,
            transport_phase=transport_phase,
            result=result,
            safety_config=safety_config,
            pol=pol,
            state=state,
            env_policy=env_policy,
        )

        # ── End-of-detour check + part-abandonment ──────────────────
        # When the replan advance window closes (allows_advance True→False),
        # check whether the detour actually cleared the obstacle.  Two
        # independent triggers (budget exhaustion or repeated failures)
        # both gate on held_object_active: only abort if the part is
        # still in the gripper — a successfully placed part is left alone.
        if replan_states is not None and pol is not None:
            rs = replan_states[env_idx]
            is_in_detour = rs.allows_advance(task_time_step or 0)
            if rs._was_in_detour and not is_in_detour:
                # Detour window just closed.
                if gate_result.g_t in (GateDecision.STOP, GateDecision.SLOW_DOWN):
                    rs.replan_fail_count += 1
                else:
                    rs.replan_fail_count = 0  # success — reset
                # Trigger 1: lateral budget exhausted (spatial cap).
                if (rs._budget_exhausted
                        and held_object_active
                        and hasattr(pol, '_grasp_carry_aborted')):
                    pol._grasp_carry_aborted = True
                    print(f'[REPLAN] part abandoned: lateral budget exhausted '
                          f'@ task_step={task_time_step}')
                # Trigger 2: consecutive failed detours.
                elif (rs.replan_fail_count >= rs.MAX_REPLAN_FAILS
                      and held_object_active
                      and hasattr(pol, '_grasp_carry_aborted')):
                    pol._grasp_carry_aborted = True
                    print(f'[REPLAN] part abandoned: {rs.replan_fail_count} '
                          f'consecutive failed detours @ task_step={task_time_step}')
            rs._was_in_detour = is_in_detour

        grasp_rewound = False
        grasp_hold_validated = (
            pol is not None
            and hasattr(pol, "is_grasp_hold_validated")
            and pol.is_grasp_hold_validated()
        )
        if pol is not None and not grasp_hold_validated and (
            hasattr(pol, "maybe_rewind_for_failed_grasp")
            or hasattr(pol, "needs_grasp_validation")
        ):
            part_pose = None
            part_idx = pol.part_index_at_step(task_time_step or 0)
            if part_idx is not None:
                part_key = f"part_{part_idx}_pos"
                if part_key in env_policy:
                    part_pose = env_policy[part_key]
                elif hasattr(pol, "needs_grasp_validation") and pol.needs_grasp_validation(
                    task_time_step or 0
                ):
                    print(
                        f"[WARN] {part_key} missing from obs during grasp validation "
                        f"(task_step={task_time_step})"
                    )

            if hasattr(pol, "needs_grasp_validation") and pol.needs_grasp_validation(
                task_time_step or 0
            ):
                commit_carry = (
                    hasattr(pol, "_should_commit_grasp_carry")
                    and pol._should_commit_grasp_carry(
                        state.ee_pos, part_pose, task_time_step or 0
                    )
                )
                if commit_carry and hasattr(pol, "mark_grasp_hold_validated"):
                    pol.mark_grasp_hold_validated()
                    grasp_hold_validated = True
                elif part_pose is None or not pol.validate_grasp_hold(
                    state.ee_pos,
                    part_pose,
                    disturbance_pending=getattr(
                        pol, "_grasp_disturbance_pending", False
                    ),
                ):
                    advance = False
                elif hasattr(pol, "mark_grasp_hold_validated"):
                    pol.mark_grasp_hold_validated()
                    grasp_hold_validated = True

            # Only rewind when the gate allows movement; during STOP/SLOW_DOWN
            # the object may still be held — opening the gripper would drop it.
            if (
                gate_result.g_t == GateDecision.ALLOW
                and not grasp_hold_validated
                and hasattr(pol, "maybe_rewind_for_failed_grasp")
                and pol.maybe_rewind_for_failed_grasp(
                    state.ee_pos,
                    part_pose,
                    task_time_step or 0,
                )
            ):
                advance = False
                task_time_step = pol.time_step
                grasp_rewound = True

            if hasattr(pol, "consume_grasp_rewind_event"):
                grasp_event = pol.consume_grasp_rewind_event()
                if grasp_event:
                    result.metadata["grasp_rewind_event"] = grasp_event
                    print(
                        f"[WARN] grasp_rewind_event={grasp_event} "
                        f"(task_step={task_time_step})"
                    )

        if grasp_rewound and pol is not None:
            safe = safety_gate.apply(
                gate_result, pol.peek_action(), prev_actions[env_idx]
            )

        if pol is not None and hasattr(pol, "_gripper_for_proposed_action"):
            safe, gripper_hold_reason = _apply_policy_gripper_overrides(
                pol,
                safe,
                ee_pos=state.ee_pos,
                task_time_step=task_time_step,
                env_policy=env_policy,
                gate_decision=gate_result.g_t,
            )

        safe_actions.append(safe)
        new_prev_ee.append(state.ee_pos.copy())
        advance_mask.append(advance)
        g_rules.append(int(gate_result.g_t))
        gt_collisions.append(g_gt == int(GateDecision.STOP))

        replan_event = ""
        replan_trigger_rule = ""
        if replan_trigger is not None and replan_executor is not None and policy is not None:
            req = replan_trigger.update(
                state,
                result,
                task_time_step=task_time_step or 0,
                in_place_window=in_place_window,
                defer_late_approach=defer_late_approach,
                transport_phase=transport_phase,
                policy=pol,
                safety_config=safety_config,
                sim_step_index=step_counter,
            )
            if req is not None:
                replan_event = "trigger"
                replan_trigger_rule = req.trigger_rule
                if replan_states is not None:
                    replan_states[env_idx].last_trigger_rule = req.trigger_rule
                replan_event = _try_replan(
                    replan_executor, replan_trigger, replan_states,
                    pol, state, env_idx, req,
                    task_time_step_max=task_time_step_max,
                )
                if replan_event == "applied" and task_time_step_max is not None and pol.time_stamps is not None:
                    task_time_step_max = int(pol.time_stamps[-1])

        # --- Phase 4b: VLM Stage 5 replan trigger ---
        # 8.1 fix: require high confidence (>=0.85) AND dynamic risk type.
        _vlm_action = ""
        _vlm_conf = 0.0
        _vlm_risk = ""
        if vlm_fields is not None:
            _vlm_action = str(vlm_fields.get("vlm_suggested_action", "")).lower()
            _vlm_conf = float(vlm_fields.get("vlm_risk_confidence") or vlm_fields.get("vlm_confidence") or 0)
            _vlm_risk = str(vlm_fields.get("vlm_risk_type", "")).lower()
        _vlm_should_replan = (
            _vlm_action == "error"  # always replan on VLM error
            or (_vlm_action == "replan" and _vlm_conf >= 0.85 and _vlm_risk == "dynamic")
        )
        if (
            vlm_fields is not None
            and _vlm_should_replan
            and replan_executor is not None
            and replan_trigger is not None
            and policy is not None
            and transport_phase == "transit"
            and not replan_event  # don't clobber an existing trigger this step
            and not (replan_states is not None and replan_states[env_idx].allows_advance(task_time_step or 0))
        ):
            import uuid as _uuid2, time as _time2
            from GMRobot.safety.replan.types import ReplanHint, ReplanRequest
            _ee2 = tuple(float(x) for x in np.asarray(state.ee_pos, dtype=np.float64).reshape(-1)[:3])
            _hand2 = tuple(float(x) for x in np.asarray(state.human_hand_pos, dtype=np.float64).reshape(-1)[:3])
            _dist2 = float(result.metadata.get("dist_min_envelope", result.metadata.get("dist_ee_human", 0.3)))
            # Use VLM semantic context for dodge side hint if available.
            vlm_explanation = str(vlm_fields.get("vlm_explanation", ""))
            hint2 = ReplanHint(
                side="retreat",
                detour_strategy="retreat_then_arc",
                semantic_context=vlm_explanation[:200] if vlm_explanation else None,
                vlm_confidence=float(vlm_fields.get("vlm_confidence") or 0.5),
            )
            vlm_req = ReplanRequest(
                request_id=str(_uuid2.uuid4()),
                step_index=step_counter,
                task_time_step=task_time_step or 0,
                trigger_source="vlm_stage5_replan",
                trigger_rule="vlm_replan",
                dist_ee_human=_dist2,
                dist_min=_dist2,
                g_rule=int(gate_result.g_t),
                ee_pos=_ee2,
                human_hand_pos=_hand2,
                hint=hint2,
                created_at_s=_time2.monotonic(),
            )
            replan_event = "trigger"
            replan_trigger_rule = "vlm_replan"
            if replan_states is not None:
                replan_states[env_idx].last_trigger_rule = "vlm_replan"
            replan_event = _try_replan(
                replan_executor, replan_trigger, replan_states,
                pol, state, env_idx, vlm_req,
                task_time_step_max=task_time_step_max,
            )
            if replan_event == "applied" and task_time_step_max is not None and pol.time_stamps is not None:
                task_time_step_max = int(pol.time_stamps[-1])

        if replan_event:
            metrics.record_replan_event(replan_event)
        metrics.record_step(gate_result.g_t)

        # R5: TTR/Kalman prediction cadence — only compute expensive predictions
        # every 10 steps (5Hz) to keep the 50Hz control loop light.
        _ttr_step = step_counter % 10 == 0 and not _multi_env
        ttr_fields: dict[str, str] = {}

        # F6: Kalman + TTR shadow predictions extracted to helpers.
        kalman_fields: dict[str, str] = _run_kalman_shadow(
            hand_trajectory_filter, hand_pos, _multi_env, _ttr_step,
        )
        ttr_fields = _run_ttr_shadow(
            time_to_risk_predictor, time_to_risk_history,
            time_to_risk_threshold_steps,
            state, gate_result, hand_vel, task_time_step,
            _ttr_step, transport_phase,
        )

        # --- W13: Predictive replan trigger (online, from time-to-risk model) ---
        # Moved here (after TTR computation) so ttr_fields is populated.
        if (
            ttr_fields.get("predictive_replan_trigger") == "1"
            and not replan_event  # don't clobber an existing trigger this step
            and replan_executor is not None
            and replan_trigger is not None
            and policy is not None
            and not (replan_states is not None and replan_states[env_idx].allows_advance(task_time_step or 0))
        ):
            import uuid, time as _time
            from GMRobot.safety.replan.types import ReplanHint, ReplanRequest
            _ee = tuple(float(x) for x in np.asarray(state.ee_pos, dtype=np.float64).reshape(-1)[:3])
            _hand = tuple(float(x) for x in np.asarray(state.human_hand_pos, dtype=np.float64).reshape(-1)[:3])
            _dist = float(result.metadata.get("dist_min_envelope", result.metadata.get("dist_ee_human", 0.3)))
            _kalman_speed = 0.0
            if hand_trajectory_filter is not None and hand_trajectory_filter.state is not None:
                _ks = hand_trajectory_filter.state
                if len(_ks) >= 6:
                    _kalman_speed = float(np.linalg.norm(_ks[3:6]))
            hint = ReplanHint(
                side="retreat",
                detour_strategy="retreat_then_arc",
                lateral_offset_m=0.10 + min(_kalman_speed * 0.5, 0.10),
                raise_approach_m=0.05 + min(_kalman_speed * 0.3, 0.05),
            )
            pred_req = ReplanRequest(
                request_id=str(uuid.uuid4()),
                step_index=step_counter,
                task_time_step=task_time_step or 0,
                trigger_source="w13_predictive_ttr",
                trigger_rule="predictive_ttr",
                dist_ee_human=_dist,
                dist_min=_dist,
                g_rule=int(gate_result.g_t),
                ee_pos=_ee,
                human_hand_pos=_hand,
                hint=hint,
                created_at_s=_time.monotonic(),
                hand_speed_mps=float(_kalman_speed),
            )
            replan_event = "trigger"
            replan_trigger_rule = "predictive_ttr"
            if replan_states is not None:
                replan_states[env_idx].last_trigger_rule = "predictive_ttr"
            replan_event = _try_replan(
                replan_executor, replan_trigger, replan_states,
                pol, state, env_idx, pred_req,
                task_time_step_max=task_time_step_max,
            )
            if replan_event == "applied" and task_time_step_max is not None and pol.time_stamps is not None:
                task_time_step_max = int(pol.time_stamps[-1])
            metrics.record_replan_event(replan_event)

        replan_fields = _build_replan_log_fields(
            replan_states, env_idx, replan_event, replan_trigger_rule,
            transport_phase, stage_name, task_time_step,
        )

        # --- held part position logging & part tracker update ---
        held_part_fields: dict[str, str] | None = None
        if (
            held_object_active
            and held_part_pose is not None
            and len(np.asarray(held_part_pose, dtype=np.float64).reshape(-1)) >= 3
        ):
            hp = np.asarray(held_part_pose, dtype=np.float64).reshape(-1)[:3]
            held_part_fields = {
                "held_part_pos_x": f"{hp[0]:.6f}",
                "held_part_pos_y": f"{hp[1]:.6f}",
                "held_part_pos_z": f"{hp[2]:.6f}",
            }
        else:
            held_part_fields = None

        if part_tracker is not None and pol is not None:
            part_idx = pol.part_index_at_step(task_time_step or 0) if hasattr(pol, "part_index_at_step") else None
            changed = part_tracker.update(
                task_time_step=task_time_step or 0,
                part_idx=part_idx,
                is_carrying=held_object_active,
                held_part_pos=held_part_pose,
                stage_name=stage_name,
                grasp_hold_validated=grasp_hold_validated,
                grasp_rewound=grasp_rewound,
                vlm_retry_triggered=False,
            )
            if changed is not None:
                print(
                    f"[PART] part_{changed.part_index}: {changed.status.value}"
                    f" @ task_step={task_time_step}"
                )

        if logger is not None:
            # Merge Kalman + TTR shadow fields into envelope dict (no logger API change).
            if (kalman_fields or ttr_fields) and envelope_fields is not None:
                envelope_fields = dict(envelope_fields)
                if kalman_fields:
                    envelope_fields.update(kalman_fields)
                if ttr_fields:
                    envelope_fields.update(ttr_fields)
            # Force VLM refresh BEFORE logger.record so the next VLM cycle
            # is triggered immediately during placement — placement_verified will
            # read the fresh result on the next VLM interval (not after release).
            if pol is not None and getattr(pol, "_release_gripper_committed", False):
                run_vlm_inference._force_vlm_refresh = True
            logger.record(
                state,
                proposed_actions[env_idx],
                gate_result,
                safe,
                env_index=env_idx,
                g_ground_truth=g_gt,
                dist_ee_human_gt=dist_gt,
                gt_branch_fields=branch_result.to_log_dict(),
                envelope_fields=envelope_fields,
                task_time_step=task_time_step,
                task_time_step_max=task_time_step_max,
                shadow_fields=shadow_fields,
                vlm_fields=vlm_fields,
                perception_fields=perception_fields,
                replan_fields=replan_fields,
                gripper_fields={
                    "gripper_hold_reason": gripper_hold_reason,
                    "release_gripper_committed": (
                        "1"
                        if pol is not None
                        and getattr(pol, "_release_gripper_committed", False)
                        else "0"
                    ),
                    # 8.6: post-placement verification via VLM scene analysis.
                    "placement_verified": (
                        "1"
                        if pol is not None
                        and getattr(pol, "_release_gripper_committed", False)
                        and hasattr(run_vlm_inference, "_cached_result")
                        and run_vlm_inference._cached_result is not None
                        and str(run_vlm_inference._cached_result.get("vlm_suggested_action", "")).lower() == "continue"
                        else "0"
                    ),
                },
                grasp_supervisor_fields=grasp_supervisor_fields,
                held_part_fields=held_part_fields,
            )

    return np.stack(safe_actions, axis=0), new_prev_ee, advance_mask, g_rules, gt_collisions


def main():
    """Create the environment and run the scripted policy."""
    env_cfg = create_env_cfg()
    env = gym.make(args_cli.task, cfg=env_cfg)

    # Keep the policy aligned with the actual vectorized environment size.
    num_envs = env.unwrapped.num_envs
    policy = MultiEnvPickAndPlacePolicy(num_envs=num_envs)

    print(f"[INFO]: Gym observation space: {env.observation_space}")
    print(f"[INFO]: Gym action space: {env.action_space}")

    save_camera = args_cli.save_camera

    # --record_video auto-enables --save_camera
    if args_cli.record_video:
        if not args_cli.enable_cameras:
            raise RuntimeError("--record_video requires --enable_cameras.")
        save_camera = True

    if save_camera and not args_cli.enable_cameras:
        raise RuntimeError("--save_camera requires --enable_cameras.")

    record_video = args_cli.record_video
    if save_camera:
        output_dir = os.path.abspath(args_cli.camera_output_dir)
        if os.path.isdir(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        msg = (
            f"[INFO]: Saving camera frames every {args_cli.camera_save_interval} steps "
            f"to {output_dir}"
        )
        if record_video:
            msg += f" (video: {args_cli.record_fps} fps)"
        print(msg)

    obs, info = env.reset()
    policy.reset(obs)

    safety_config = None
    rule_engine = None
    safety_gate = None
    human_motion = None
    safety_logger = None
    safety_metrics = SafetyMetrics()
    part_tracker = PartTracker(num_parts=20)
    prev_actions = None
    prev_ee_positions: list[np.ndarray | None] = []
    layer2_predictor = None
    fusion_config = None
    replan_trigger = None
    replan_executor = None
    replan_states: list[ReplanRuntimeState] | None = None
    envelope_evaluator: EnvelopeEvaluator | None = None
    vlm_client: VLMClient | None = None
    perception_client: PerceptionClient | None = None
    grasp_supervisor: VLMGraspSupervisor | None = None
    hand_trajectory_filter: HandTrajectoryFilter | None = None

    if args_cli.enable_vlm and not args_cli.enable_cameras:
        raise RuntimeError("--enable_vlm requires --enable_cameras.")
    if args_cli.enable_vlm_grasp_supervisor and not args_cli.enable_vlm:
        raise RuntimeError("--enable_vlm_grasp_supervisor requires --enable_vlm.")
    if args_cli.enable_perception and not args_cli.enable_cameras:
        raise RuntimeError("--enable_perception requires --enable_cameras.")
    if args_cli.enable_perception_track and not args_cli.enable_perception:
        raise RuntimeError("--enable_perception_track requires --enable_perception.")

    if args_cli.enable_vlm:
        vlm_cfg_path = args_cli.vlm_config or "/root/GMRobot/configs/vlm_client.yaml"
        vlm_client = VLMClient.from_yaml(vlm_cfg_path)
        health = vlm_client.health_check()
        print(f"[INFO]: VLM client enabled (health={health})")

    if args_cli.enable_vlm_grasp_supervisor:
        grasp_supervisor = VLMGraspSupervisor(
            VLMGraspSupervisorConfig(
                enabled=True,
                interval=args_cli.vlm_grasp_interval,
                scene_interval=args_cli.vlm_scene_inventory_interval,
                confidence_threshold=args_cli.vlm_grasp_confidence_threshold,
            )
        )
        print(
            f"[INFO]: VLM grasp supervisor enabled "
            f"(interval={args_cli.vlm_grasp_interval}, "
            f"scene_interval={args_cli.vlm_scene_inventory_interval}, "
            f"confidence_threshold={args_cli.vlm_grasp_confidence_threshold})"
        )

    if args_cli.enable_perception:
        perc_cfg_path = (
            args_cli.perception_config or "/root/GMRobot/configs/perception_client.yaml"
        )
        perception_client = PerceptionClient.from_yaml(perc_cfg_path)
        perc_health = perception_client.health_check()
        track_note = " + /track shadow" if args_cli.enable_perception_track else ""
        print(f"[INFO]: Perception client enabled (shadow{track_note}, health={perc_health})")

    # W13: Time-to-risk regression predictor (shadow + optional predictive replan).
    time_to_risk_predictor: TimeToRiskPredictor | None = None
    time_to_risk_history: deque | None = None
    if args_cli.enable_time_to_risk:
        from collections import deque as _deque
        from pathlib import Path as _Path
        model_dir = _Path(args_cli.time_to_risk_model_dir)
        if (model_dir / "time_to_risk_model.joblib").is_file():
            time_to_risk_predictor = TimeToRiskPredictor.from_artifacts(model_dir)
            time_to_risk_history = _deque(maxlen=5)
            print(
                f"[INFO]: Time-to-risk predictor enabled (W13 shadow, "
                f"{time_to_risk_predictor.n_features} features, "
                f"threshold={args_cli.time_to_risk_threshold_steps} steps)"
            )
        else:
            print(
                f"[WARN]: --enable_time_to_risk but model not found at {model_dir}"
            )

    if args_cli.enable_replan:
        if not args_cli.enable_safety:
            raise RuntimeError("--enable_replan requires --enable_safety.")
        replan_states = [ReplanRuntimeState() for _ in range(num_envs)]
        replan_executor = GeometryReplanV0()
        print("[INFO]: Phase 4a geometry replan enabled (L1 warn trigger).")

    if args_cli.enable_layer2_fusion:
        if not args_cli.enable_safety:
            raise RuntimeError("--enable_layer2_fusion requires --enable_safety.")
        if not args_cli.layer2_model_dir:
            raise RuntimeError("--enable_layer2_fusion requires --layer2_model_dir.")
        args_cli.enable_layer2_shadow = True

    if args_cli.enable_layer2_shadow or args_cli.enable_layer2_fusion:
        if not args_cli.enable_safety:
            raise RuntimeError("--enable_layer2_shadow requires --enable_safety.")
        if not args_cli.layer2_model_dir:
            raise RuntimeError("--enable_layer2_shadow requires --layer2_model_dir.")
        from GMRobot.safety.layer2.predictor import SafetyPredictor

        layer2_predictor = SafetyPredictor.from_artifacts(args_cli.layer2_model_dir)
        fusion_config = load_fusion_config(args_cli.fusion_config)
        if args_cli.enable_layer2_fusion:
            print(
                f"[INFO]: Layer 2 tier fusion gate enabled (model={args_cli.layer2_model_dir}, "
                f"theta={fusion_config.ml_override_theta})."
            )
        else:
            print(
                f"[INFO]: Layer 2 shadow enabled (model={args_cli.layer2_model_dir}); "
                "gate uses g_rule only."
            )

    if args_cli.enable_safety:
        safety_config = load_safety_config(args_cli.safety_config)

        # S13 P2 / W9-P2: Kalman filter for hand trajectory prediction (shadow).
        # Created AFTER config load so control_dt from YAML is respected.
        hand_trajectory_filter = HandTrajectoryFilter(
            HandTrajectoryFilterConfig(dt=safety_config.control_dt)
        )
        print("[INFO]: Hand trajectory Kalman filter enabled (W9-P2 shadow)")

        rule_engine = RuleEngine(safety_config)
        safety_gate = SafetyGate(safety_config)
        human_motion = HumanMotionController(
            safety_config,
            num_envs=num_envs,
            device=env.unwrapped.device,
        )
        if safety_config.log_enabled:
            safety_logger = SafetyLogger(
                safety_config.log_dir,
                episode_id=0,
                enabled=True,
            )
        envelope_evaluator = EnvelopeEvaluator(safety_config)
        print(f"[INFO]: Layer 1 safety enabled (50 Hz, config={args_cli.safety_config or 'default'})")
        if args_cli.enable_replan:
            replan_trigger = L1WarnReplanTrigger(
                ReplanTriggerConfig(
                    safe_dist_hard_stop=safety_config.safe_dist_hard_stop,
                    safe_dist_warn=safety_config.safe_dist_warn,
                    lateral_offset_m=safety_config.replan_lateral_offset_m,
                    detour_stage_duration=safety_config.replan_detour_stage_duration,
                    replan_trigger_threshold=safety_config.replan_trigger_threshold,
                    ttc_replan_trigger_threshold=safety_config.ttc_replan_trigger_threshold,
                    ttc_replan_hand_speed_min=safety_config.ttc_replan_hand_speed_min,
                    ttc_forecast_replan_threshold=safety_config.ttc_forecast_replan_threshold,
                    use_perception_track_strategy=safety_config.use_perception_track_strategy,
                    held_critical_replan_enabled=safety_config.held_critical_replan_enabled,
                    proactive_route_replan_enabled=safety_config.proactive_route_replan_enabled,
                    proactive_route_horizon_steps=safety_config.proactive_route_horizon_steps,
                    proactive_route_warn_gap_m=safety_config.proactive_route_warn_gap_m,
                    proactive_route_hard_gap_m=safety_config.proactive_route_hard_gap_m,
                )
            )

    step_counter = 0
    last_g_rules: list[int] | None = None
    episode_had_collision = [False] * num_envs if args_cli.enable_safety else None
    perception_track_session: PerceptionTrackSession | None = (
        PerceptionTrackSession() if args_cli.enable_perception_track else None
    )
    last_ground_hand_box: list[float] | None = None

    def finalize_safety_log(*, policy_success: bool, timed_out: bool = False) -> None:
        if safety_logger is None or episode_had_collision is None:
            return
        had_collision = any(episode_had_collision)
        outcome = episode_outcome_from_ground_truth(
            had_collision=had_collision,
            policy_success=policy_success,
            timed_out=timed_out,
        )
        pol = policy.single_env_policies[0]
        expected = safety_config.expected_task_steps if safety_config else None
        if expected is None and pol.time_stamps is not None and len(pol.time_stamps) > 0:
            expected = int(pol.time_stamps[-1])
        if expected is not None and not policy_success and not had_collision:
            ratio = pol.time_step / max(expected, 1)
            outcome = f"{outcome}@{pol.time_step}/{expected}"
        safety_logger.set_outcome(outcome)
        path = safety_logger.flush()
        if path:
            print(f"[INFO]: Safety log written to {path} (outcome={outcome})")

    if save_camera:
        save_camera_frames(obs, args_cli.camera_output_dir, step_counter)

    while simulation_app.is_running():
        with torch.inference_mode():
            if human_motion is not None:
                human_motion.apply_to_env(env, step_counter)

            if args_cli.enable_safety and rule_engine is not None and safety_gate is not None:
                proposed_actions = policy.get_action(obs, advance=False)
                if prev_actions is None:
                    prev_actions = proposed_actions.copy()
                if not prev_ee_positions:
                    prev_ee_positions = [None] * num_envs

                vlm_fields = None
                perception_fields = None
                if (
                    vlm_client is not None
                    and args_cli.vlm_interval > 0
                    and step_counter % args_cli.vlm_interval == 0
                ):
                    vlm_fields = run_vlm_inference(
                        vlm_client,
                        obs,
                        step_counter=step_counter,
                        save_camera=save_camera,
                        camera_output_dir=args_cli.camera_output_dir,
                    )
                    if step_counter % max(args_cli.progress_interval, 1) == 0:
                        action = (vlm_fields or {}).get("vlm_suggested_action", "n/a")
                        print(f"[VLM] step={step_counter} result={action}")

                # --- VLM grasp supervisor: check object-in-gripper during carry ---
                grasp_supervisor_fields = None
                if grasp_supervisor is not None and policy is not None:
                    # Determine whether we are in a carry phase for *any* env.
                    any_carrying = False
                    for env_idx in range(num_envs):
                        pol = policy.single_env_policies[env_idx]
                        task_ts = int(pol.time_step) if pol is not None else 0
                        if pol is not None and hasattr(pol, "is_carrying_object"):
                            if pol.is_carrying_object(task_ts):
                                any_carrying = True
                                break

                    obs_np = to_numpy(obs)
                    if "camera" in obs_np and "scene_rgb" in obs_np["camera"]:
                        # Use env-0 RGB for the VLM check.
                        rgb_frame = obs_np["camera"]["scene_rgb"]
                        if rgb_frame.ndim == 4:
                            rgb_frame = rgb_frame[0]

                        check_result = grasp_supervisor.check(
                            vlm_client,
                            rgb_frame,
                            step=step_counter,
                            is_carrying=any_carrying,
                            meta={"step": step_counter},
                        )

                        if check_result is not None and not check_result.skipped:
                            status = "held" if check_result.object_held else "LOST"
                            if step_counter % max(args_cli.progress_interval, 1) == 0:
                                print(
                                    f"[VLM-GRASP] step={step_counter} "
                                    f"object_held={check_result.object_held} "
                                    f"confidence={check_result.confidence:.2f} "
                                    f"streak={grasp_supervisor._consecutive_lost} "
                                    f"({status})"
                                )

                            if grasp_supervisor.should_abort_carry():
                                print(
                                    f"[WARN] VLM grasp supervisor: object LOST "
                                    f"(confidence={check_result.confidence:.2f}, "
                                    f"streak={grasp_supervisor._consecutive_lost}) "
                                    f"— retrying current part"
                                )
                                for env_idx in range(num_envs):
                                    pol = policy.single_env_policies[env_idx]
                                    if pol is not None and hasattr(pol, "trigger_vlm_retry_current_part"):
                                        ok = pol.trigger_vlm_retry_current_part()
                                        if ok:
                                            # F11: feedback VLM retry to PartTracker so
                                            # vlm_retry_count increments and SKIPPED status
                                            # can fire after VLM_MAX_RETRIES exhaustions.
                                            if part_tracker is not None:
                                                _tts = getattr(pol, "time_step", 0)
                                                _pidx = pol.part_index_at_step(_tts) if hasattr(pol, "part_index_at_step") else None
                                                part_tracker.update(
                                                    task_time_step=_tts,
                                                    part_idx=_pidx,
                                                    is_carrying=False,
                                                    held_part_pos=None,
                                                    stage_name="",
                                                    vlm_retry_triggered=True,
                                                )
                                        else:
                                            # Rewind step not found — fall back to skip.
                                            print(
                                                f"[WARN] VLM retry failed for env={env_idx} "
                                                f"— skipping part"
                                            )
                                            if hasattr(pol, "_grasp_carry_aborted"):
                                                pol._grasp_carry_aborted = True
                                            if hasattr(pol, "_grasp_rewind_attempts"):
                                                pol._grasp_rewind_attempts = 999

                        # --- VLM scene inventory: periodic full-scene part count ---
                        inventory_result = grasp_supervisor.check_scene_inventory(
                            vlm_client,
                            rgb_frame,
                            step=step_counter,
                            meta={"step": step_counter},
                        )
                        if inventory_result is not None and not inventory_result.skipped:
                            if step_counter % max(args_cli.progress_interval, 1) == 0:
                                print(
                                    f"[VLM-SCENE] step={step_counter} "
                                    f"total={inventory_result.total_parts} "
                                    f"gripper={inventory_result.parts_in_gripper} "
                                    f"source={inventory_result.parts_in_source} "
                                    f"target={inventory_result.parts_in_target} "
                                    f"elsewhere={inventory_result.parts_elsewhere}"
                                )

                    # Merge grasp check + scene inventory fields so the logger
                    # receives both without an API change.
                    grasp_supervisor_fields = {
                        **grasp_supervisor_log_fields(grasp_supervisor),
                        **scene_inventory_log_fields(grasp_supervisor),
                    }

                ground_fields = None
                track_fields = None
                ground_result = None
                if (
                    perception_client is not None
                    and args_cli.perception_interval > 0
                    and step_counter % args_cli.perception_interval == 0
                ):
                    # G2: pass VLM keywords to GDINO for context-aware detection.
                    _kw = (vlm_fields or {}).get("vlm_keywords", "")
                    ground_fields, ground_result = run_perception_ground_shadow(
                        perception_client,
                        obs,
                        step_counter=step_counter,
                        save_camera=save_camera,
                        camera_output_dir=args_cli.camera_output_dir,
                        text_prompt=_kw if _kw else None,
                    )
                    if ground_result:
                        dets = ground_result.get("detections") or []
                        hand_dets = [
                            d
                            for d in dets
                            if "hand" in str(d.get("label", "")).lower()
                        ]
                        pool = hand_dets or dets
                        if pool:
                            best = max(
                                pool, key=lambda d: float(d.get("score", 0) or 0)
                            )
                            last_ground_hand_box = best.get("box_xyxy")

                if (
                    perception_client is not None
                    and perception_track_session is not None
                    and args_cli.perception_track_interval > 0
                    and step_counter % args_cli.perception_track_interval == 0
                ):
                    track_fields, perception_track_session = run_perception_track_shadow(
                        perception_client,
                        obs,
                        step_counter=step_counter,
                        track_session=perception_track_session,
                        seed_box_xyxy=last_ground_hand_box,
                    )

                perception_fields = merge_perception_log_fields(
                    ground_fields, track_fields
                )

                if perception_fields and step_counter % max(args_cli.progress_interval, 1) == 0:
                    if ground_fields:
                        n_det = ground_fields.get("perception_detection_count", "n/a")
                        latency = ground_fields.get("perception_latency_ms", "n/a")
                        print(
                            f"[PERCEPTION] step={step_counter} "
                            f"detections={n_det} latency_ms={latency}"
                        )
                    if track_fields:
                        speed = track_fields.get("perception_track_speed_px_s", "n/a")
                        direction = track_fields.get(
                            "perception_track_direction_deg", "n/a"
                        )
                        print(
                            f"[TRACK] step={step_counter} "
                            f"speed_px_s={speed} direction_deg={direction}"
                        )

                actions, prev_ee_positions, advance_mask, last_g_rules, _ = apply_safety_gate(
                    obs,
                    proposed_actions,
                    prev_actions,
                    prev_ee_positions,
                    step_counter=step_counter,
                    rule_engine=rule_engine,
                    safety_gate=safety_gate,
                    human_motion=human_motion,
                    safety_config=safety_config,
                    logger=safety_logger,
                    metrics=safety_metrics,
                    episode_had_collision=episode_had_collision,
                    env=env,
                    policy=policy,
                    layer2_predictor=layer2_predictor,
                    fusion_config=fusion_config,
                    enable_layer2_fusion=args_cli.enable_layer2_fusion,
                    replan_trigger=replan_trigger,
                    replan_executor=replan_executor,
                    replan_states=replan_states,
                    envelope_evaluator=envelope_evaluator,
                    vlm_fields=vlm_fields,
                    perception_fields=perception_fields,
                    grasp_supervisor_fields=grasp_supervisor_fields,
                    hand_trajectory_filter=hand_trajectory_filter,
                    time_to_risk_predictor=time_to_risk_predictor,
                    time_to_risk_history=time_to_risk_history,
                    time_to_risk_threshold_steps=args_cli.time_to_risk_threshold_steps,
                    part_tracker=part_tracker,
                )
                policy.advance_time_steps(advance_mask)
            else:
                actions = policy.get_action(obs, advance=True)
                if prev_actions is None:
                    prev_actions = actions.copy()

            actions = torch.from_numpy(actions).to(
                device=env.unwrapped.device,
                dtype=torch.float32,
            )

            obs, reward, terminated, truncated, info = env.step(actions)
            prev_actions = actions.detach().cpu().numpy()
            step_counter += 1

            if (
                args_cli.progress_interval > 0
                and step_counter % args_cli.progress_interval == 0
            ):
                time_step = policy.single_env_policies[0].time_step
                g_rule = last_g_rules[0] if last_g_rules else -1
                progress_msg = (
                    f"[PROGRESS] step_counter={step_counter} time_step={time_step} "
                    f"g_rule={g_rule}"
                )
                if args_cli.enable_safety:
                    progress_msg += (
                        f" intervention_rate={safety_metrics.intervention_rate:.3f}"
                        f" slow_down_rate={safety_metrics.slow_down_rate:.3f}"
                        f" max_stop={safety_metrics.max_consecutive_stop}"
                    )
                    if safety_metrics.replan_triggers > 0:
                        progress_msg += (
                            f" replan_ok={safety_metrics.replan_success_rate:.2f}"
                        )
                print(progress_msg, flush=True)

            if args_cli.max_steps is not None and step_counter >= args_cli.max_steps:
                time_step = policy.single_env_policies[0].time_step
                print(
                    f"[INFO]: Reached --max_steps={args_cli.max_steps} "
                    f"(time_step={time_step}); stopping."
                )
                if args_cli.enable_safety:
                    print(f"[INFO]: Safety metrics: {safety_metrics.summary()}")
                    if part_tracker is not None:
                        report = part_tracker.generate_report()
                        print("\n".join(report.summary_lines()))
                finalize_safety_log(policy_success=False, timed_out=True)
                break

            if save_camera and step_counter % args_cli.camera_save_interval == 0:
                save_camera_frames(obs, args_cli.camera_output_dir, step_counter)

            terminated = to_numpy(terminated)
            truncated = to_numpy(truncated)
            done_mask = terminated | truncated

            policy.reset(obs, done_mask)

            if all(policy.is_success()):
                finalize_safety_log(policy_success=True)
                safety_metrics.record_episode_success(True)
                summary = safety_metrics.summary()
                if args_cli.enable_safety:
                    print(f"[INFO]: Safety metrics: {summary}")
                    if part_tracker is not None:
                        report = part_tracker.generate_report()
                        print("\n".join(report.summary_lines()))
                print(
                    "[INFO]: Policy sequence completed successfully; exiting.",
                    flush=True,
                )
                break

    if safety_logger is not None:
        safety_logger.flush()

    env.close()

    if record_video:
        compile_video(args_cli.camera_output_dir, args_cli.record_fps)


# -----------------------------------------------------------------------------
# Video recording helper
# -----------------------------------------------------------------------------

def compile_video(frame_dir: str, fps: int) -> None:
    """Compile PNG frames into an MP4 video using ffmpeg."""
    import subprocess

    png_pattern = os.path.join(frame_dir, "frame_*_env0.png")
    import glob

    png_files = sorted(glob.glob(png_pattern))
    if not png_files:
        print("[WARN]: No video frames found; skipping video compilation.")
        return

    output_path = os.path.join(frame_dir, "output.mp4")
    print(f"[INFO]: Compiling {len(png_files)} frames into {output_path} …")

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate", str(fps),
            "-pattern_type", "glob",
            "-i", png_pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-loglevel", "error",
            output_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"[WARN]: ffmpeg failed: {result.stderr.strip()}")
    else:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[INFO]: Video saved: {output_path} ({size_mb:.1f} MB, {fps} fps)")


if __name__ == "__main__":
    main()
    simulation_app.close()
