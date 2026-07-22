#!/usr/bin/env python3
"""GMDisturb Phase 3: Disturbance-driven G1 walking + safety-gated UR10e.

Phase 3 wires three new capabilities:

1. **Disturbance velocity injection** — G1DisturbanceController output is
   written directly into the G1 walker observation pipeline (replacing the
   auto-resampling UniformVelocityCommandCfg from Phase 2).

2. **Distance-based behaviour modes** — CAUTIOUS (<15 cm: retreat/stop),
   MODERATE (15–30 cm: slow + steer away), AGGRESSIVE (>30 cm: full wander).

3. **Safety-layer integration** — G1EnvelopeAdapter output is fed into
   GMRobot's RuleEngine + SafetyGate, gating UR10e actions in real time.

Usage:
    python scripts/run_phase3.py --headless
    python scripts/run_phase3.py                   # with GUI
    python scripts/run_phase3.py --max_steps 5000 --mode AGGRESSIVE
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys

import numpy as np

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="GMDisturb Phase 3")
parser.add_argument("--max_steps", type=int, default=10000)
parser.add_argument("--progress_interval", type=int, default=200)
parser.add_argument("--output_csv", type=str, default="/tmp/gmdisturb_phase3.csv")
parser.add_argument(
    "--scenario",
    type=str,
    default=None,
    choices=[None, "arm_collision", "arm_wave", "constrained_wander", "vlm_explore"],
    help="Scripted disturbance scenario (default: random wander).",
)
parser.add_argument(
    "--mode",
    type=str,
    default="auto",
    choices=["auto", "AGGRESSIVE", "MODERATE", "CAUTIOUS"],
    help="Force disturbance mode (default: auto = distance-gated).",
)
parser.add_argument(
    "--safety-config",
    type=str,
    default=None,
    help="Path to GMRobot safety YAML config (default: SafetyConfig defaults).",
)
parser.add_argument(
    "--no-safety",
    action="store_true",
    help="Disable safety gating (UR10e actions pass through ungated).",
)
parser.add_argument(
    "--stress",
    action="store_true",
    help="Stress-test mode: project G1 hand positions to table height "
         "to force safety gate triggers despite vertical separation.",
)
parser.add_argument(
    "--virtual-hand",
    type=float,
    const=0.3,
    nargs="?",
    default=None,
    metavar="RADIUS",
    help="Virtual hand mode: a hand sphere of RADIUS (default 0.3m) centred "
         "on G1's head moves randomly at table height.  Replaces --stress.",
)
parser.add_argument(
    "--virtual-hand-speed",
    type=float,
    default=0.12,
    metavar="SPEED",
    help="Virtual hand drift speed in m/s (default 0.12). Lower = smoother.",
)
parser.add_argument(
    "--replan",
    action="store_true",
    help="Enable motion replan: after sustained SLOW_DOWN, inject detour waypoints.",
)
parser.add_argument(
    "--vlm",
    action="store_true",
    help="Enable VLM navigation: send head camera RGB to remote VLM every 4s, "
         "adjust G1 behaviour based on VLM risk assessment.",
)
parser.add_argument(
    "--vlm-scene",
    action="store_true",
    help="Enable VLM scene reasoning: send overhead camera RGB to VLM every ~16s "
         "for strategic approach-angle selection.  Requires --vlm.",
)
parser.add_argument(
    "--vlm-monitor",
    action="store_true",
    help="Enable VLM part monitoring: query overhead camera for slot occupancy, "
         "gripper state, and fallen-part detection.  Runs every ~16s.  "
         "Requires --vlm.  Compatible with --per-part-protocol.",
)
parser.add_argument(
    "--vlm-coordinate",
    action="store_true",
    help="Enable VLM coordinated guidance: overhead camera → VLM advises BOTH "
         "virtual hand (where to block) AND UR10e (which replan strategy).  "
         "Requires --vlm.  Overrides --per-part-protocol hand behavior.",
)
# ponytail (2026-07-13): --batch-radii and --batch-repeats removed — dead CLI
# flags that were parsed but never consumed in main().  batch_runner.py is the
# canonical batch interface (subprocess per episode).
parser.add_argument(
    "--g1-bias-y",
    type=float,
    default=0.0,
    help="Constant y-offset added to G1 velocity commands. "
         "Positive → steer toward right side (y>0), negative → left side (y<0).",
)
parser.add_argument(
    "--approach-side",
    type=str,
    default=None,
    choices=[None, "front", "back", "left", "right"],
    help="Preset: override workspace and velocity biases so G1 approaches the "
         "UR10e from a specific side of the table. "
         "'front' = default (x<0.6 side), 'back' = behind table (x>0.6 side), "
         "'left' = container A side (y<0), 'right' = container B side (y>0).",
)
parser.add_argument(
    "--vhand-lag",
    type=float,
    default=0.0,
    help="Virtual hand attractor lag factor (0-1). 0 = instant EE tracking, "
         "0.9 = heavy smoothing. Higher values make the hand trail behind UR10e movement.",
)
parser.add_argument(
    "--vhand-retreat",
    type=int,
    default=200,
    metavar="STEPS",
    help="Steps the virtual hand retreats after a replan or on consecutive "
         "STOP during grasp/place.  0 = never retreat.  "
         "Default: 200 steps (4 s at 50 Hz).",
)
parser.add_argument(
    "--per-part-protocol",
    action="store_true",
    help="Enable per-part structured testing: Pick→Transit→Place→Reset cycle "
         "per part.  Hand follows EE during Pick/Place, blocks transit path "
         "during Transit, retreats during Reset.  Requires --virtual-hand.",
)
parser.add_argument(
    "--num-parts",
    type=int,
    default=None,
    metavar="N",
    help="Truncate the pick-and-place command list to the first N parts "
         "(for mini B1 validation).  Default: use full policy command list.",
)
parser.add_argument(
    "--scenario-hand",
    type=str,
    default=None,
    choices=[None, "empty_box", "fast_approach", "transit_block", "knock_off"],
    help="Time-based hand scenario for GMRobot capability testing.  "
         "Requires --virtual-hand.  Overrides --per-part-protocol.",
)
parser.add_argument(
    "--vhand-remove-after",
    type=int,
    default=0,
    metavar="STEPS",
    help="Permanently remove the virtual hand after N simulation steps.  "
         "0 = never remove.  Useful for letting the UR10e finish its "
         "pick-and-place cycle undisturbed after sufficient replan testing.  "
         "Example: --vhand-remove-after 6000 removes the hand at step 6000.",
)
parser.add_argument(
    "--config",
    type=str,
    default=None,
    metavar="PATH",
    help="Path to YAML config (default: config/default.yaml).",
)
parser.add_argument(
    "--seed",
    type=int,
    default=None,
    help="Episode RNG seed for Python/NumPy/Torch, Isaac env_cfg.seed, "
         "G1DisturbanceController, and G1VirtualHand (default: 42). "
         "GPU PhysX may still be non-deterministic — see *_seeds.json sidecar.",
)
parser.add_argument(
    "--disturbance-scenario-label",
    type=str,
    default="",
    help="Canonical scenario name for CSV disturbance_scenario field (set by batch_runner).",
)
parser.add_argument(
    "--dynamic-sweep",
    action="store_true",
    help="Enable B2 world-coordinate lateral sweep proxy (from YAML dynamic_sweep).",
)
parser.add_argument(
    "--save_camera",
    action="store_true",
    help="Save scene RGB PNGs (capture-only; no VLM).",
)
parser.add_argument(
    "--camera_output_dir",
    type=str,
    default="",
    help="Directory for --save_camera PNGs (default: <output_csv>_camera/).",
)
parser.add_argument(
    "--camera_save_steps",
    type=str,
    default="",
    help="Comma-separated 0-based steps to dump scene RGB (e.g. 210,280). "
         "Empty = save every progress_interval when --save_camera.",
)
parser.add_argument(
    "--camera_pose_json",
    type=str,
    default="",
    help="Optional path to write resolved scene camera pose JSON.",
)
parser.add_argument(
    "--body_pose_jsonl",
    type=str,
    default="",
    help="Optional JSONL path for G1/UR10e body poses at camera save steps.",
)
parser.add_argument(
    "--motion_source_label",
    type=str,
    default="",
    help="Honest motion-source label written to capture sidecars "
         "(e.g. scripted_g1_locomotion_arm_wave). Does not change safety attribution.",
)
parser.add_argument(
    "--enforcement-mode",
    type=str,
    default=None,
    choices=[None, "active", "shadow", "off"],
    help="Safety enforcement: active (gate+replan), shadow (evaluate+log only), "
         "off (same as --no-safety when combined).  Default: active.",
)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

# Load config early for YAML-driven flags (before validation).
_PROJ_ROOT_EARLY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT_EARLY not in sys.path:
    sys.path.insert(0, _PROJ_ROOT_EARLY)
from config_loader import load_config as _load_config_early
_cfg_early = _load_config_early(args_cli.config)
if _cfg_early.per_part_protocol:
    args_cli.per_part_protocol = True
if _cfg_early.dynamic_sweep.enabled:
    args_cli.dynamic_sweep = True
if args_cli.enforcement_mode is None:
    args_cli.enforcement_mode = _cfg_early.safety.enforcement_mode
else:
    args_cli.enforcement_mode = str(args_cli.enforcement_mode).lower()
if args_cli.enforcement_mode == "off":
    args_cli.no_safety = True

# §5.2 enforcement: --per-part-protocol and --scenario-hand require --virtual-hand
if args_cli.per_part_protocol and args_cli.virtual_hand is None:
    parser.error("--per-part-protocol requires --virtual-hand RADIUS")
if args_cli.dynamic_sweep and args_cli.virtual_hand is None:
    parser.error("--dynamic-sweep requires --virtual-hand RADIUS")
if args_cli.scenario_hand is not None and args_cli.virtual_hand is None:
    parser.error("--scenario-hand requires --virtual-hand RADIUS")
# §5.2 enforcement: --replan requires an obstacle source (virtual hand, stress,
# scenario-hand, or per-part-protocol) and enabled safety.
if args_cli.replan:
    if args_cli.no_safety:
        parser.error("--replan requires safety to be enabled (cannot use with --no-safety)")
    _has_obstacle = (
        args_cli.virtual_hand is not None
        or args_cli.stress
        or args_cli.scenario_hand is not None
        or args_cli.per_part_protocol
        or args_cli.dynamic_sweep
    )
    if not _has_obstacle:
        parser.error("--replan requires an obstacle source: "
                     "--virtual-hand, --stress, --scenario-hand, or --per-part-protocol")

# Ensure project root is on sys.path before importing local modules.
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from dynamic_audit_csv import (
    DYNAMIC_AUDIT_HEADER,
    build_dynamic_audit_row,
    format_dynamic_audit_row,
)
from event_csv import EVENT_CSV_HEADER, build_event_row, format_event_row
from config_loader import load_config, Phase3Config

# Load config (CLI --config overrides the default YAML path)
cfg: Phase3Config = load_config(args_cli.config)

# C3 fix (2026-07-13): batch.* config values were loaded but never consumed —
# run_phase3.py always used argparse defaults.  Now cfg.batch.* is the source
# of truth; CLI args act as overrides when explicitly passed.
if args_cli.max_steps == parser.get_default("max_steps"):
    args_cli.max_steps = cfg.batch.max_steps
if args_cli.progress_interval == parser.get_default("progress_interval"):
    args_cli.progress_interval = cfg.batch.progress_interval
if args_cli.output_csv == parser.get_default("output_csv"):
    args_cli.output_csv = cfg.batch.output_csv
# R7 H4 fix: mode_default was omitted from the C3 config-wiring block.
if args_cli.mode == parser.get_default("mode"):
    args_cli.mode = cfg.batch.mode_default

# R6 L1 (reverted 2026-07-13): the scene config always includes a scene_camera
# (TiledCameraCfg in DualRobotSceneCfg).  Isaac Lab requires --enable_cameras
# to initialise ANY camera sensor, regardless of whether user code reads from
# it.  The conditional `args_cli.vlm or headless` broke the default (no-VLM,
# no-headless) case — the scene camera failed to init and crashed env.make().
# Always enable cameras; the GPU overhead of a single unread TiledCamera is
# negligible (~one render target texture).
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import torch
import gymnasium as gym

from dual_env_cfg import DualRobotDisturbanceEnvCfg

gym.register(
    id="G1-UR10e-Disturbance-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": DualRobotDisturbanceEnvCfg},
)

from g1_walk_controller import G1WalkController
from g1_arm_controller import G1ArmController, ARM_JOINT_INDICES
from g1_virtual_hand import G1VirtualHand
from g1_vlm_client import G1VLMClient, _ensure_tunnel, init_vlm_config
from ur10e_controller import UR10eController
from safety_adapter import G1EnvelopeAdapter
from seed_utils import apply_episode_seeds, seed_manifest, write_seed_sidecar
from spawn_utils import apply_g1_spawn_to_env_cfg, spawn_pose_error
from mat_event_detector import MatEventDetector
from g1_disturbance_controller import (
    G1DisturbanceController,
    DisturbanceMode,
    SCENARIOS,
)
from test_metrics import EpisodeMetrics, MetricsWriter
from per_part_state import PerPartTester, Phase
from protocol_vhand import (
    attempt_needs_canonical_redeploy,
    dynamic_sweep_redeploy_edge,
    find_open_attempt_id,
    is_b2_proactive_trigger_rule,
    policy_clock_should_advance,
    resolve_effective_gate_name,
    snapshot_parts_placed,
    protocol_retreat_transition,
    resolve_per_part_attractor,
    per_part_radius,
    ReplanAttribution,
)
from dynamic_sweep_proxy import (
    DynamicLateralSweepProxy,
    DynamicSweepSpec,
    PhaseProxyRadii,
    commanded_trajectory_row,
    sweep_geometry_precheck,
    time_to_risk_steps_from_ttc,
)
from scenarios import ScenarioHand, SCENARIOS as HAND_SCENARIOS

# GMRobot replan module — lazy-loaded via safety_adapter (same importlib pattern
# that avoids GMRobot's isaaclab-dependent __init__.py).  Resolved at init time
# when --replan is passed.
try:
    from safety_adapter import _get_replan_imports
    _HAS_REPLAN_LOADER = True
except ImportError:
    _HAS_REPLAN_LOADER = False


# =============================================================================
# Helpers
# =============================================================================

def _quat_tilt_angle(quat_xyzw: np.ndarray) -> float:
    """Return tilt angle (radians) from upright given a quaternion (w,x,y,z).

    Computes the angle between the robot's local Z axis and the world Z axis.
    0 = perfectly upright, π/2 = horizontal, π = upside-down.
    """
    w, x, y, z = float(quat_xyzw[0]), float(quat_xyzw[1]), float(quat_xyzw[2]), float(quat_xyzw[3])
    # Local Z in world frame: R * (0,0,1) where R is the rotation matrix from quaternion.
    # R[:,2] = [2xz + 2wy, 2yz - 2wx, 1 - 2xx - 2yy]
    zx = 2.0 * x * z + 2.0 * w * y
    zy = 2.0 * y * z - 2.0 * w * x
    zz = 1.0 - 2.0 * x * x - 2.0 * y * y
    # Dot with world Z (0,0,1) = zz
    zz_clamped = max(-1.0, min(1.0, zz))
    return float(np.arccos(zz_clamped))


def inject_disturbance_velocity(env, cmd: np.ndarray, device: str) -> None:
    """Write the disturbance controller's velocity into the G1 command buffer.

    This replaces the auto-generated UniformVelocityCommand with the
    disturbance controller's distance-gated output.  The next call to
    ``env.step()`` will use this velocity when computing walker observations.
    """
    vel_term = env.unwrapped.command_manager.get_term("g1_base_velocity")
    vel_term.vel_command_b[:] = torch.from_numpy(
        cmd.astype(np.float32)
    ).to(device).unsqueeze(0)


# =============================================================================
# Hand position visualisation
# =============================================================================

def _init_hand_sphere(stage) -> None:
    """Create a small yellow sphere at /World/envs/env_0/Debug/HandSphere."""
    from pxr import UsdGeom, Sdf, Gf
    path = Sdf.Path("/World/envs/env_0/Debug/HandSphere")
    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr().Set(0.04)
    sphere.CreateDisplayColorAttr().Set([(1.0, 1.0, 0.0)])  # yellow
    # Tag so we can find it later
    sphere.GetPrim().CreateAttribute("user:properties:debug_hand",
        Sdf.ValueTypeNames.Bool, False).Set(True)


def _init_arm_stick(stage) -> None:
    """Create a thin cylinder at /World/envs/env_0/Debug/ArmStick."""
    from pxr import UsdGeom, Sdf, Gf
    path = Sdf.Path("/World/envs/env_0/Debug/ArmStick")
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.CreateRadiusAttr().Set(0.025)
    cyl.CreateHeightAttr().Set(1.0)
    cyl.CreateDisplayColorAttr().Set([(0.8, 0.8, 0.8)])  # light grey


def _set_hand_sphere_position(stage, pos: np.ndarray, head_pos: np.ndarray = None,
                                color: tuple = (1.0, 1.0, 0.0)):
    """Move the debug hand sphere and arm stick."""
    from pxr import UsdGeom, Gf
    # --- Sphere ---
    prim_path = "/World/envs/env_0/Debug/HandSphere"
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        _init_hand_sphere(stage)
        prim = stage.GetPrimAtPath(prim_path)
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(float(pos[0]), float(pos[1]), float(pos[2])))
    UsdGeom.Sphere(prim).GetDisplayColorAttr().Set([color])

    # --- Arm stick (head → hand) ---
    if head_pos is not None:
        stick_path = "/World/envs/env_0/Debug/ArmStick"
        stick_prim = stage.GetPrimAtPath(stick_path)
        if not stick_prim.IsValid():
            _init_arm_stick(stage)
            stick_prim = stage.GetPrimAtPath(stick_path)
        mid = (np.array(pos[:3]) + np.array(head_pos[:3])) / 2.0
        direction = np.array(pos[:3]) - np.array(head_pos[:3])
        length = float(np.linalg.norm(direction))
        if length < 0.001:
            return
        direction /= length
        # Rotation: Z-axis → direction
        import math
        z_axis = np.array([0.0, 0.0, 1.0])
        axis = np.cross(z_axis, direction)
        axis_norm = float(np.linalg.norm(axis))
        if axis_norm < 1e-6:
            quat = Gf.Quatf(1, 0, 0, 0)
        else:
            axis /= axis_norm
            angle = math.acos(max(-1.0, min(1.0, np.dot(z_axis, direction))))
            half = angle / 2.0
            quat = Gf.Quatf(math.cos(half),
                            math.sin(half) * axis[0],
                            math.sin(half) * axis[1],
                            math.sin(half) * axis[2])
        cxform = UsdGeom.Xformable(stick_prim)
        cxform.ClearXformOpOrder()
        cxform.AddTranslateOp().Set(Gf.Vec3f(float(mid[0]), float(mid[1]), float(mid[2])))
        cxform.AddOrientOp().Set(quat)
        UsdGeom.Cylinder(stick_prim).GetHeightAttr().Set(length)
        UsdGeom.Cylinder(stick_prim).GetRadiusAttr().Set(0.015)


# =============================================================================
# Main
# =============================================================================

def _target_direction(name: str, ee_pos: np.ndarray) -> np.ndarray:
    """Return unit XY vector from EE toward the named target."""
    from scenarios import CONTAINER_A, CONTAINER_B, TRANSIT_MID
    targets = {
        "left":  CONTAINER_A,
        "right": CONTAINER_B,
        "path":  TRANSIT_MID,
        "front": np.array([0.0, ee_pos[1]], dtype=np.float32),
    }
    target = targets.get(name, CONTAINER_A)
    d = target - ee_pos[:2]
    n = float(np.linalg.norm(d))
    return (d / n).astype(np.float32) if n > 1e-6 else np.array([-1.0, 0.0], dtype=np.float32)


def _resolve_disturbance_source(cli_args, virtual_hand) -> str:
    """Return the canonical disturbance_source label per §6.1.

    Mapping:
      - virtual hand active            → scripted_virtual_hand
      - arm_collision / arm_wave       → g1_body (walking velocity patterns only)
      - stress mode (simulated arm)    → g1_attached_proxy
      - default wander                 → g1_body
    """
    if virtual_hand is not None:
        return "scripted_virtual_hand"
    if cli_args.stress:
        return "g1_attached_proxy"
    # arm_collision / arm_wave are scripted G1 velocity phases — no proxy hand.
    return "g1_body"


def _park_g1_at_workspace(env, workspace_x, workspace_y) -> None:
    """DEBUG ONLY — post-reset ``write_root_state_to_sim`` teleport.

    Do **not** call from paper B1 paths.  Prefer ``apply_g1_spawn_to_env_cfg``
    before ``gym.make`` so PhysX / obs history stay consistent.  Kept only for
    interactive debugging of workspace geometry.
    """
    raise RuntimeError(
        "_park_g1_at_workspace is deprecated for paper runs; "
        "set disturbance.g1_spawn_x/y/yaw before gym.make instead"
    )


def main():
    from isaaclab_tasks.utils import parse_env_cfg

    task_id = "G1-UR10e-Disturbance-v0"
    env_cfg = parse_env_cfg(task_id, num_envs=1)
    # Keep PhysX/Isaac episode horizon >= CLI max_steps.  Default
    # episode_length_s=200s truncates at 10000 steps @ 50 Hz and silently
    # ends B1 before 20 parts complete ("Episode ended at step 9999").
    _step_dt = float(env_cfg.decimation) * float(env_cfg.sim.dt)
    _needed_s = float(args_cli.max_steps) * _step_dt + _step_dt
    if float(getattr(env_cfg, "episode_length_s", 0.0) or 0.0) < _needed_s:
        env_cfg.episode_length_s = _needed_s
    print(
        f"[phase3] episode_length_s={env_cfg.episode_length_s:.1f}s "
        f"(max_steps={args_cli.max_steps}, step_dt={_step_dt:.4f}s)"
    )

    # P0: close the seed loop before env construction / controller init.
    _episode_seed = int(args_cli.seed if args_cli.seed is not None else 42)
    _seed_applied = apply_episode_seeds(_episode_seed, env_cfg=env_cfg)

    # P0: B1 spawn pose — mutate env_cfg *before* gym.make (not post-reset park).
    _spawn_record: dict = {}
    if cfg.disturbance.g1_spawn_x is not None:
        _spawn_record = apply_g1_spawn_to_env_cfg(
            env_cfg,
            spawn_x=float(cfg.disturbance.g1_spawn_x),
            spawn_y=float(cfg.disturbance.g1_spawn_y),
            spawn_yaw=float(cfg.disturbance.g1_spawn_yaw),
            spawn_jitter_xy=float(cfg.disturbance.g1_spawn_jitter_xy),
        )
        print(
            f"[phase3] G1 spawn (pre-make): "
            f"x={_spawn_record['g1_spawn_requested_x']:.3f} "
            f"y={_spawn_record['g1_spawn_requested_y']:.3f} "
            f"yaw={_spawn_record['g1_spawn_requested_yaw']:.3f} "
            f"jitter_xy={_spawn_record['g1_spawn_jitter_xy']:.3f} "
            f"pose_range={_spawn_record['reset_g1_pose_range']}"
        )
    else:
        print("[phase3] G1 spawn: using dual_env_cfg default init_state "
              "(no disturbance.g1_spawn_x)")

    env = gym.make(task_id, cfg=env_cfg)
    obs, info = env.reset(seed=_episode_seed)
    device = env.unwrapped.device

    # R7 H3 fix: ensure cleanup runs even on unhandled exception.
    atexit.register(lambda: _cleanup_sim(env, simulation_app))

    # ── Controllers ──────────────────────────────────────────────────────
    g1_walk = G1WalkController().to(device)
    ur10e = UR10eController()
    adapter = G1EnvelopeAdapter(
        safety_config_path=args_cli.safety_config,
        control_dt=cfg.safety.control_dt,
    )
    detector = MatEventDetector()
    arm_ctrl = G1ArmController()
    virtual_hand = G1VirtualHand(
        reach_radius=(
            float(args_cli.virtual_hand)
            if args_cli.virtual_hand is not None
            else float(cfg.virtual_hand.reach_radius)
        ),
        proxy_radius=float(cfg.virtual_hand.transit_proxy_radius),
        speed=args_cli.virtual_hand_speed,
        height_mode=cfg.virtual_hand.height_mode,
        seed=_episode_seed,
        pursuit_mode=bool(args_cli.replan and not args_cli.dynamic_sweep),
        retreat_steps=max(0, args_cli.vhand_retreat),
    ) if args_cli.virtual_hand is not None else None
    # Warmup: let hand start blocking immediately — dynamic block point
    # (min(0.75, head_x + reach_radius)) ensures centre only reaches as far as G1 allows.
    if virtual_hand is not None and args_cli.replan:
        virtual_hand._retreat_steps = 0

    _seed_record = seed_manifest(
        seed=_episode_seed,
        env_seed=getattr(env_cfg, "seed", _episode_seed),
        controller_seed=_episode_seed,
        virtual_hand_seed=(
            int(virtual_hand.seed) if virtual_hand is not None else None
        ),
        applied=_seed_applied,
    )
    if _spawn_record:
        _seed_record["g1_spawn"] = _spawn_record
    # Measured root pose after reset (validates spawn, not just requested).
    _g10 = env.unwrapped.scene["robot_g1"]
    _root0 = _g10.data.root_pos_w[0].detach().cpu().numpy()
    _quat0 = _g10.data.root_quat_w[0].detach().cpu().numpy()
    _seed_record["g1_root_initial"] = {
        "x": float(_root0[0]),
        "y": float(_root0[1]),
        "z": float(_root0[2]),
        "quat_wxyz": [float(v) for v in _quat0],
    }
    if _spawn_record:
        _err0 = spawn_pose_error(
            (_root0[0], _root0[1]),
            requested_x=_spawn_record["g1_spawn_requested_x"],
            requested_y=_spawn_record["g1_spawn_requested_y"],
        )
        _seed_record["spawn_pose_error"] = _err0
        print(
            f"[phase3] G1 root after reset: "
            f"({_root0[0]:.3f},{_root0[1]:.3f},{_root0[2]:.3f}) "
            f"spawn_pose_error={_err0:.4f}m"
        )
    _seed_path = write_seed_sidecar(args_cli.output_csv, _seed_record)
    print(
        f"[phase3] seeds: env={_seed_record['env_seed']} "
        f"controller={_seed_record['controller_seed']} "
        f"vhand={_seed_record['virtual_hand_seed']} "
        f"(sidecar={_seed_path})"
    )
    print(f"[phase3] {_seed_record['physx_note']}")

    # ── Optional scene-camera capture sidecars (0-POST; no VLM) ──────────
    _cam_out = ""
    _cam_steps: set[int] = set()
    _body_pose_fh = None
    if args_cli.save_camera:
        _cam_out = args_cli.camera_output_dir or (
            args_cli.output_csv.replace(".csv", "_camera")
        )
        os.makedirs(_cam_out, exist_ok=True)
        if args_cli.camera_save_steps.strip():
            _cam_steps = {
                int(x.strip())
                for x in args_cli.camera_save_steps.split(",")
                if x.strip() != ""
            }
        print(
            f"[phase3] save_camera=ON dir={_cam_out} "
            f"steps={sorted(_cam_steps) if _cam_steps else f'every progress_interval={args_cli.progress_interval}'}"
        )
    from scene_camera_override import (
        resolve_scene_camera_pose,
        scene_camera_override_enabled,
    )
    _cam_pos, _cam_rot = resolve_scene_camera_pose()
    _cam_pose_record = {
        "override_enabled": scene_camera_override_enabled(),
        "pos": list(_cam_pos),
        "rot": list(_cam_rot),
        "motion_source_label": args_cli.motion_source_label or "",
        "scenario": args_cli.scenario or "wander",
        "seed": int(_episode_seed),
        "virtual_hand": args_cli.virtual_hand is not None,
        "vlm": bool(args_cli.vlm),
        "save_camera": bool(args_cli.save_camera),
    }
    _pose_json = args_cli.camera_pose_json or (
        args_cli.output_csv.replace(".csv", "_camera_pose.json")
        if args_cli.save_camera
        else ""
    )
    if _pose_json:
        _pose_dir = os.path.dirname(_pose_json)
        if _pose_dir:
            os.makedirs(_pose_dir, exist_ok=True)
        with open(_pose_json, "w", encoding="utf-8") as _pf:
            json.dump(_cam_pose_record, _pf, indent=2)
            _pf.write("\n")
        print(f"[phase3] camera pose sidecar: {_pose_json}")
    if args_cli.body_pose_jsonl:
        _bp_dir = os.path.dirname(args_cli.body_pose_jsonl)
        if _bp_dir:
            os.makedirs(_bp_dir, exist_ok=True)
        _body_pose_fh = open(args_cli.body_pose_jsonl, "w", encoding="utf-8")
    elif args_cli.save_camera:
        _body_pose_fh = open(os.path.join(_cam_out, "body_poses.jsonl"), "w", encoding="utf-8")

    # ── Workspace + bias defaults (scenario/protocol may override) ──────
    _ws_x = cfg.disturbance.workspace_x
    _ws_y = cfg.disturbance.workspace_y
    _vx_b = 0.0
    _vy_b = args_cli.g1_bias_y

    # ── Scenario-based hand control (R7) ───────────────────────────────
    scen_hand: ScenarioHand | None = None
    if args_cli.scenario_hand and virtual_hand is not None:
        scen_hand = ScenarioHand(HAND_SCENARIOS[args_cli.scenario_hand]())
        print(f"[phase3] Scenario hand: {args_cli.scenario_hand}")
        # Keep G1 near table edge (x≈0) so hand at x=0.25 reaches warn zone.
        _ws_x = (0.0, 0.8)
        _ws_y = (-0.5, 0.5)

    # ── Per-part protocol (R7) ─────────────────────────────────────────
    per_part: PerPartTester | None = None
    if args_cli.per_part_protocol and virtual_hand is not None and scen_hand is None:
        # Truncate command list for mini B1 (--num-parts / batch episode.num_parts).
        if args_cli.num_parts is not None and args_cli.num_parts > 0:
            cmds = list(ur10e._policy.user_commands[: int(args_cli.num_parts)])
            ur10e._policy.user_commands = cmds
            print(f"[phase3] Truncated task to {len(cmds)} parts (--num-parts)")
        # Read user_commands from the UR10e policy (lazy-init after reset).
        per_part = PerPartTester(
            ur10e._policy.user_commands,
            prefer_replan=bool(args_cli.replan),
        )
        print(f"[phase3] Per-part protocol enabled: {per_part.parts_total} parts, "
              f"4-phase cycle (Pick→Transit→Place→Reset)"
              f"{' [prefer_replan]' if args_cli.replan else ''}")
        # Keep YAML disturbance.workspace_* — do not hardcode G1 pose here.
        # B1 corridor reachability is tuned via workspace + reach_radius using
        # measured g1_head_* telemetry, not comment-assumed head positions.
        _vx_b = 0.0
        _vy_b = 0.0
        virtual_hand.proxy_radius = float(cfg.virtual_hand.transit_proxy_radius)
        print(
            f"[phase3] Protocol: workspace from YAML "
            f"x∈[{_ws_x[0]:.2f},{_ws_x[1]:.2f}] y∈[{_ws_y[0]:.2f},{_ws_y[1]:.2f}]; "
            f"reach_radius={virtual_hand.reach_radius:.2f}; "
            f"proxy per-phase "
            f"(TRANSIT={cfg.virtual_hand.transit_proxy_radius:.2f}, "
            f"PICK/PLACE={cfg.virtual_hand.pick_place_proxy_radius:.2f}, "
            f"RESET={cfg.virtual_hand.reset_proxy_radius:.2f})"
        )
        if bool(getattr(cfg.disturbance, "park_g1_at_workspace", False)):
            print(
                "[phase3] WARNING: park_g1_at_workspace is deprecated and ignored; "
                "use disturbance.g1_spawn_x before gym.make"
            )
    _vh_phase_radii = {
        "transit_proxy_radius": float(cfg.virtual_hand.transit_proxy_radius),
        "pick_place_proxy_radius": float(cfg.virtual_hand.pick_place_proxy_radius),
        "reset_proxy_radius": float(cfg.virtual_hand.reset_proxy_radius),
        # Legacy kw aliases accepted by per_part_radius().
        "transit_radius": float(cfg.virtual_hand.transit_proxy_radius),
        "pick_place_radius": float(cfg.virtual_hand.pick_place_proxy_radius),
        "reset_radius": float(cfg.virtual_hand.reset_proxy_radius),
    }

    # ── B2 dynamic lateral sweep (world-coordinate scripted proxy) ───────
    dynamic_sweep: DynamicLateralSweepProxy | None = None
    _enforcement_mode = str(args_cli.enforcement_mode or "active").lower()
    if args_cli.dynamic_sweep and virtual_hand is not None and scen_hand is None:
        if per_part is None:
            print("[phase3] WARNING: --dynamic-sweep without per-part-protocol; "
                  "phase triggers may not fire")
        _ds = cfg.dynamic_sweep
        _sweep_spec = DynamicSweepSpec(
            start_xyz=tuple(float(x) for x in _ds.start_xyz),
            end_xyz=tuple(float(x) for x in _ds.end_xyz),
            duration_steps=int(_ds.duration_steps),
            retreat_duration_steps=int(_ds.retreat_duration_steps),
            trigger_phase=str(_ds.trigger_phase),
            proxy_radius=float(cfg.virtual_hand.transit_proxy_radius),
            ee_radius=0.08,
            seed=int(_episode_seed),
        )
        dynamic_sweep = DynamicLateralSweepProxy(
            spec=_sweep_spec,
            control_dt=float(cfg.safety.control_dt),
        )
        _phase_radii_obj = PhaseProxyRadii.from_mapping(_vh_phase_radii)
        _hard_stop_m = 0.25
        _warn_m = 0.28
        if not args_cli.no_safety:
            try:
                adapter._init_safety_layer()
                if adapter._safety_config is not None:
                    _hard_stop_m = float(adapter._safety_config.safe_dist_hard_stop)
                    _warn_m = float(adapter._safety_config.safe_dist_warn)
            except Exception as _geom_e:
                print(f"[phase3] WARNING: safety init for geometry precheck failed: {_geom_e}")
        print(
            f"[phase3] Dynamic sweep proxy: "
            f"start={_sweep_spec.start_xyz} end={_sweep_spec.end_xyz} "
            f"dur={_sweep_spec.duration_steps} "
            f"trajectory_id={dynamic_sweep.disturbance_trajectory_id[:16]}… "
            f"enforcement={_enforcement_mode}"
        )
        _geom_report = sweep_geometry_precheck(
            _sweep_spec,
            phase_radii=_phase_radii_obj,
            hard_stop_m=_hard_stop_m,
            warn_m=_warn_m,
        )
        for _line in _geom_report.summary_lines():
            print(f"[phase3] sweep_geometry: {_line}")
        _geom_errors = _geom_report.startup_errors()
        if _geom_errors:
            for _ge in _geom_errors:
                print(f"[phase3] FATAL sweep_geometry: {_ge}")
            env.close()
            simulation_app.close()
            raise SystemExit(1)

    scripted_phases = SCENARIOS.get(args_cli.scenario) if args_cli.scenario else None

    # ── Approach-side presets: only when no protocol/scenario active ─────
    if per_part is None and scen_hand is None and args_cli.approach_side == "front":
        _ws_x, _ws_y = (0.0, 0.8), (-0.5, 0.5)
    elif per_part is None and scen_hand is None and args_cli.approach_side == "back":
        _ws_x, _ws_y = (0.0, 0.8), (-0.5, 0.5)
        _vx_b = 0.25
    elif per_part is None and scen_hand is None and args_cli.approach_side == "left":
        _ws_x, _ws_y = (0.2, 0.8), (-0.7, -0.2)
        _vy_b = 0.10
    elif per_part is None and scen_hand is None and args_cli.approach_side == "right":
        _ws_x, _ws_y = (0.2, 0.8), (0.2, 0.7)
        _vy_b = -0.10

    print(f"[phase3] Approach side: {args_cli.approach_side or 'front (default)'}  "
          f"ws_x={_ws_x} ws_y={_ws_y} vx_bias={_vx_b} vy_bias={_vy_b}")

    disturb = G1DisturbanceController(
        scripted_phases=scripted_phases,
        workspace_x=_ws_x,
        workspace_y=_ws_y,
        cautious_threshold=cfg.disturbance.cautious_threshold,
        moderate_threshold=cfg.disturbance.moderate_threshold,
        speed_aggressive=cfg.disturbance.speed_aggressive,
        speed_moderate=cfg.disturbance.speed_moderate,
        speed_cautious=cfg.disturbance.speed_cautious,
        resample_interval=cfg.disturbance.resample_interval,
        seed=_episode_seed,
        control_dt=cfg.safety.control_dt,
        vy_scale=cfg.disturbance.vy_scale,  # F1 fix: lateral exploration
        vy_bias=_vy_b,
        vx_bias=_vx_b,
    )
    metrics = EpisodeMetrics(episode_id=0)
    metrics.safety_enforcement_mode = _enforcement_mode
    if dynamic_sweep is not None:
        metrics.disturbance_trajectory_id = dynamic_sweep.disturbance_trajectory_id
        metrics.disturbance_source = "scripted_virtual_hand"
    metrics.parts_total = ur10e.total_parts
    if _spawn_record:
        metrics.g1_spawn_requested_x = float(_spawn_record["g1_spawn_requested_x"])
        metrics.g1_spawn_requested_y = float(_spawn_record["g1_spawn_requested_y"])
        metrics.g1_spawn_requested_yaw = float(_spawn_record["g1_spawn_requested_yaw"])
        metrics.spawn_pose_error = float(_seed_record.get("spawn_pose_error", float("nan")))
    metrics.g1_root_initial_x = float(_root0[0])
    metrics.g1_root_initial_y = float(_root0[1])
    metrics.g1_root_initial_z = float(_root0[2])
    metrics.g1_root_x = float(_root0[0])
    metrics.g1_root_y = float(_root0[1])
    metrics.g1_root_z = float(_root0[2])
    writer = MetricsWriter(args_cli.output_csv)

    # ── Per-step tracking CSV (R7: for replan strategy comparison) ────────
    # §6.1: independent event CSV — written immediately on replan events, not on progress interval.
    _event_path = args_cli.output_csv.replace(".csv", "_events.csv")
    _event_fh = open(_event_path, "w")
    _event_fh.write(EVENT_CSV_HEADER)
    _trajectory_path = args_cli.output_csv.replace(".csv", "_trajectory.csv")
    _trajectory_fh = open(_trajectory_path, "w") if dynamic_sweep is not None else None
    _dynamic_audit_path = args_cli.output_csv.replace(".csv", "_dynamic_audit.csv")
    _dynamic_audit_fh = (
        open(_dynamic_audit_path, "w") if dynamic_sweep is not None else None
    )
    if _dynamic_audit_fh is not None:
        _dynamic_audit_fh.write(DYNAMIC_AUDIT_HEADER)
    if _trajectory_fh is not None:
        _trajectory_fh.write(
            "sim_step,disturbance_trajectory_id,sweep_attempt_id,sweep_progress,"
            "proxy_center_x,proxy_center_y,proxy_center_z,"
            "proxy_surface_x,proxy_surface_y,proxy_surface_z,"
            "sweep_velocity_x,sweep_velocity_y,sweep_velocity_z\n"
        )

    def _gate_distance_audit() -> dict[str, str]:
        """Distances / thresholds RuleEngine actually used (not proxy-only)."""
        empty = {
            "dist_m": "",
            "warn_threshold": "",
            "dist_min_for_gating": "",
            "dist_min_envelope": "",
            "dist_min_held": "",
            "safe_dist_hard_stop_active": "",
            "safe_dist_warn_active": "",
        }
        try:
            gr = gate_result  # set each safety step
        except NameError:
            gr = None
        meta = getattr(gr, "metadata", None) if gr is not None else None
        if not isinstance(meta, dict):
            meta = {}
        out = dict(empty)

        def _fmt(key: str, fallback=None) -> str:
            val = meta.get(key, fallback)
            if val is None or val == "":
                return ""
            try:
                return f"{float(val):.4f}"
            except (TypeError, ValueError):
                return ""

        out["dist_min_for_gating"] = _fmt("dist_min_for_gating")
        out["dist_min_envelope"] = _fmt("dist_min_envelope")
        out["dist_min_held"] = _fmt("dist_min_held")
        out["safe_dist_hard_stop_active"] = _fmt("safe_dist_hard_stop_active")
        out["safe_dist_warn_active"] = _fmt("safe_dist_warn_active")
        # Canonical event distance = gating distance; fall back to adapter surface.
        if out["dist_min_for_gating"]:
            out["dist_m"] = out["dist_min_for_gating"]
        else:
            try:
                if adapter is not None:
                    out["dist_m"] = f"{float(adapter.closest_body_distance):.4f}"
            except Exception:
                pass
        if out["safe_dist_warn_active"]:
            out["warn_threshold"] = out["safe_dist_warn_active"]
        else:
            try:
                if adapter is not None and adapter._safety_config is not None:
                    out["warn_threshold"] = (
                        f"{float(adapter._safety_config.safe_dist_warn):.4f}"
                    )
            except Exception:
                pass
        # Fill active thresholds from config if RuleEngine omitted them.
        if not out["safe_dist_hard_stop_active"]:
            try:
                if adapter is not None and adapter._safety_config is not None:
                    out["safe_dist_hard_stop_active"] = (
                        f"{float(adapter._safety_config.safe_dist_hard_stop):.4f}"
                    )
            except Exception:
                pass
        return out

    def _geom_snapshot() -> dict[str, str]:
        """Best-effort geometry fields for event / step CSV audit rows."""
        empty = {
            "ee_x": "", "ee_y": "", "ee_z": "",
            "proxy_center_x": "", "proxy_center_y": "", "proxy_center_z": "",
            "proxy_surface_x": "", "proxy_surface_y": "", "proxy_surface_z": "",
            "attractor_x": "", "attractor_y": "", "attractor_z": "",
            "g1_head_x": "", "g1_head_y": "", "g1_head_z": "",
            "reach_clamped": "",
            "reach_radius_active": "", "proxy_radius_active": "",
            "head_to_attractor_distance": "", "reach_margin": "",
        }
        try:
            ee = ur10e_ee  # set each loop iteration
        except NameError:
            return empty
        out = dict(empty)
        out["ee_x"] = f"{float(ee[0]):.4f}"
        out["ee_y"] = f"{float(ee[1]):.4f}"
        out["ee_z"] = f"{float(ee[2]):.4f}"
        try:
            if adapter is not None:
                surf = adapter.human_hand_pos
                out["proxy_surface_x"] = f"{float(surf[0]):.4f}"
                out["proxy_surface_y"] = f"{float(surf[1]):.4f}"
                out["proxy_surface_z"] = f"{float(surf[2]):.4f}"
        except Exception:
            pass
        if virtual_hand is not None:
            ctr = virtual_hand.position
            out["proxy_center_x"] = f"{float(ctr[0]):.4f}"
            out["proxy_center_y"] = f"{float(ctr[1]):.4f}"
            out["proxy_center_z"] = f"{float(ctr[2]):.4f}"
            if dynamic_sweep is None:
                attr = virtual_hand._attractor
                out["attractor_x"] = f"{float(attr[0]):.4f}"
                out["attractor_y"] = f"{float(attr[1]):.4f}"
                out["attractor_z"] = "0.0000"
                head = virtual_hand.head_position
                out["g1_head_x"] = f"{float(head[0]):.4f}"
                out["g1_head_y"] = f"{float(head[1]):.4f}"
                out["g1_head_z"] = f"{float(head[2]):.4f}"
                out["reach_clamped"] = "1" if virtual_hand.last_reach_clamped else "0"
                out["reach_radius_active"] = f"{float(virtual_hand.reach_radius):.4f}"
                out["proxy_radius_active"] = f"{float(virtual_hand.proxy_radius):.4f}"
                out["head_to_attractor_distance"] = (
                    f"{virtual_hand.head_to_attractor_distance():.4f}"
                )
                out["reach_margin"] = f"{virtual_hand.reach_margin():.4f}"
            else:
                if _sweep_out is not None:
                    out["proxy_radius_active"] = (
                        f"{float(_sweep_out.active_proxy_radius):.4f}"
                    )
                else:
                    out["proxy_radius_active"] = (
                        f"{float(virtual_hand.proxy_radius):.4f}"
                    )
        return out

    def _write_event(
        sim_step: int,
        event_type: str,
        attempt_id: int,
        event_id: str = "",
        trigger_rule: str = "",
        trigger_source: str = "",
        applied_step: str = "",
        slow_streak_length: int | str = "",
        *,
        sweep_attempt_id: str = "",
        sweep_progress: str = "",
        sweep_velocity_xyz: tuple[float, float, float] | list[float] | None = None,
        safety_enforcement_mode: str = "",
        shadow_gate_decision: str = "",
        shadow_replan_would_trigger: bool | None = None,
    ) -> None:
        _phase = (
            per_part.phase.value if per_part is not None else ""
        )
        _stage = ""
        try:
            _stage = ur10e.stage_name
        except Exception:
            _stage = ""
        d = _gate_distance_audit()
        g = _geom_snapshot()
        _streak = (
            "" if slow_streak_length == "" or slow_streak_length is None
            else str(int(slow_streak_length))
        )
        try:
            _gr = gate_result
            _gate_meta = getattr(_gr, "metadata", None) if _gr is not None else None
        except NameError:
            _gate_meta = None
        _mode = safety_enforcement_mode or _enforcement_mode
        _shadow_dec = shadow_gate_decision
        if not _shadow_dec:
            try:
                _shadow_dec = _shadow_gate_decision_this_step or ""
            except NameError:
                _shadow_dec = ""
        _shadow_would = shadow_replan_would_trigger
        if _shadow_would is None:
            try:
                _shadow_would = bool(_shadow_replan_would_this_step)
            except NameError:
                _shadow_would = False
        _sw_id = sweep_attempt_id
        _sw_prog = sweep_progress
        _sw_vel = sweep_velocity_xyz
        if not _sw_id and dynamic_sweep is not None:
            try:
                if _sweep_out is not None and _sweep_out.sweep_attempt_id > 0:
                    _sw_id = str(_sweep_out.sweep_attempt_id)
                    _sw_prog = f"{_sweep_out.sweep_progress:.6f}"
                    _sw_vel = tuple(float(x) for x in _sweep_out.surface_vel_xyz)
            except NameError:
                pass
        row = build_event_row(
            sim_step=sim_step,
            event_type=event_type,
            attempt_id=attempt_id,
            event_id=event_id,
            trigger_rule=trigger_rule,
            trigger_source=trigger_source,
            applied_step=applied_step,
            protocol_phase=_phase,
            stage_name=_stage,
            gate_audit=d,
            geom=g,
            slow_streak_length=_streak,
            gate_metadata=_gate_meta if isinstance(_gate_meta, dict) else None,
            control_dt=float(cfg.safety.control_dt),
            sweep_attempt_id=_sw_id,
            sweep_progress=_sw_prog,
            sweep_velocity_xyz=_sw_vel,
            safety_enforcement_mode=_mode,
            shadow_gate_decision=_shadow_dec,
            shadow_replan_would_trigger=bool(_shadow_would),
        )
        _event_fh.write(format_event_row(row))
        _event_fh.flush()

    def _write_dynamic_audit(sim_step: int) -> None:
        """Per-TRANSIT-step sweep audit using post-gate values."""
        if _dynamic_audit_fh is None or dynamic_sweep is None or _sweep_out is None:
            return
        if per_part is None or per_part.phase.value != "transit":
            return
        _meta = getattr(gate_result, "metadata", {}) if gate_result is not None else {}
        if not isinstance(_meta, dict):
            _meta = {}
        _gate_audit = _gate_distance_audit()
        _phase = per_part.phase.value
        _trigger_rule = str(_meta.get("trigger_rule", "") or "")
        _speed = float(np.linalg.norm(adapter.human_hand_vel)) if adapter is not None else 0.0
        row = build_dynamic_audit_row(
            sim_step=sim_step,
            policy_step=ur10e.time_step,
            protocol_phase=_phase,
            stage_name=ur10e.stage_name,
            disturbance_attempt_id=_disturbance_attempt_id,
            disturbance_trajectory_id=dynamic_sweep.disturbance_trajectory_id,
            gate_decision=gate_decision.name if gate_decision is not None else "NONE",
            trigger_rule=_trigger_rule,
            sweep_progress=_sweep_out.sweep_progress,
            ee_x=ur10e_ee[0],
            ee_y=ur10e_ee[1],
            ee_z=ur10e_ee[2],
            proxy_center_x=_sweep_out.center_xyz[0],
            proxy_center_y=_sweep_out.center_xyz[1],
            proxy_center_z=_sweep_out.center_xyz[2],
            proxy_surface_x=_sweep_out.surface_xyz[0],
            proxy_surface_y=_sweep_out.surface_xyz[1],
            proxy_surface_z=_sweep_out.surface_xyz[2],
            surface_velocity_x=_sweep_out.surface_vel_xyz[0],
            surface_velocity_y=_sweep_out.surface_vel_xyz[1],
            surface_velocity_z=_sweep_out.surface_vel_xyz[2],
            hand_speed=_speed,
            dist_min_proxy=adapter.closest_body_distance if adapter is not None else float("inf"),
            dist_min_for_gating=_gate_audit["dist_min_for_gating"],
            dist_min_envelope=_gate_audit["dist_min_envelope"],
            dist_min_held=_gate_audit["dist_min_held"],
            hard_stop_active=_gate_audit["safe_dist_hard_stop_active"],
            warn_active=_gate_audit["safe_dist_warn_active"],
            ttc_s=_meta.get("ttc"),
            ttc_forecast_s=_meta.get("ttc_forecast_s"),
            approach_rate=_meta.get("approach_rate"),
        )
        _dynamic_audit_fh.write(format_dynamic_audit_row(row))
        _dynamic_audit_fh.flush()

    _track_path = args_cli.output_csv.replace(".csv", "_steps.csv")
    _track_fh = open(_track_path, "w")
    _track_fh.write("step,ee_x,ee_y,ee_z,hand_x,hand_y,hand_z,hand_dist_surface,"
                    "g1_body_dist,gate,gate_trigger,stage,parts_placed,replan_count,"
                    "replan_strategy,replan_raise_m,replan_lateral_m,"
                    "grasp_rewinds,carry_aborted,"
                    "min_part_z,parts_below_table,"
                    "deadlock_tier,vhand_retreated,vhand_block_active,"
                    "sphere_x,sphere_y,sphere_z,protocol_phase,protocol_part,"
                    "disturbance_source,disturbance_scenario,disturbance_attempt_id,"
                    "gate_trigger_source,replan_trigger_source,"
                    "replan_trigger_step,replan_event_id,replan_applied_step,"
                    "closest_g1_body,dist_min_g1_body,dist_min_proxy,"
                    "warn_threshold_active,"
                    "dist_min_for_gating,dist_min_envelope,dist_min_held,"
                    "safe_dist_hard_stop_active,safe_dist_warn_active,"
                    "proxy_center_x,proxy_center_y,proxy_center_z,"
                    "proxy_surface_x,proxy_surface_y,proxy_surface_z,"
                    "attractor_x,attractor_y,attractor_z,"
                    "g1_head_x,g1_head_y,g1_head_z,"
                    "reach_clamped,slow_streak_length,"
                    "reach_radius_active,proxy_radius_active,"
                    "head_to_attractor_distance,reach_margin,"
                    "g1_root_x,g1_root_y,g1_root_z,g1_tilt_rad,"
                    "g1_spawn_requested_x,g1_spawn_requested_y,g1_spawn_requested_yaw,"
                    "spawn_pose_error\n")

    # ── VLM navigation (Phase 6) ──────────────────────────────────────────
    vlm_client: G1VLMClient | None = None
    vlm_last_action: str = "wait"
    VLM_INTERVAL: int = cfg.vlm.interval  # query VLM every N steps
    VLM_ACTION_CMD = cfg.vlm_action_cmd
    if args_cli.vlm:
        # C2 fix (2026-07-13): wire --config through to VLM client so that
        # custom config YAMLs actually affect VLM settings.
        init_vlm_config(args_cli.config)
        _ensure_tunnel()
        vlm_client = G1VLMClient()
        health = vlm_client.health()
        print(f"[phase3] VLM: {health.get('status','?')} model={health.get('model_id','?')}")

    # ── Initial state ────────────────────────────────────────────────────
    print(
        f"[phase3] UR10e base_z="
        f"{env.unwrapped.scene['robot_ur10e'].data.root_pos_w[0,2].item():.3f}  "
        f"G1 root_z="
        f"{env.unwrapped.scene['robot_g1'].data.root_pos_w[0,2].item():.3f}"
    )
    print(
        f"[phase3] Scenario: {args_cli.scenario or 'wander'}  "
        f"Mode: {args_cli.mode}  "
        f"Safety: {'OFF' if args_cli.no_safety else 'ON'}  "
        f"VLM: {'ON' if args_cli.vlm else 'OFF'}  "
        f"CAUTIOUS < {cfg.disturbance.cautious_threshold:.2f}m  "
        f"MODERATE < {cfg.disturbance.moderate_threshold:.2f}m  "
        f"AGGRESSIVE ≥ {cfg.disturbance.moderate_threshold:.2f}m"
    )

    ur10e.reset(obs["ur10e_policy"])
    disturb.reset()

    # Inject initial zero-velocity command so the first env.step() starts
    # with a known command (instead of UniformVelocityCommand's random init).
    inject_disturbance_velocity(env, disturb.command, device)

    scene = env.unwrapped.scene
    g1 = scene["robot_g1"]
    ur10e_robot = scene["robot_ur10e"]

    ival = args_cli.progress_interval
    max_steps = args_cli.max_steps

    # Previous UR10e action for safety gate hold interpolation
    prev_ur10e_action: np.ndarray = np.zeros(7, dtype=np.float32)

    # ── Replan state (GMRobot module — Phase 4a geometry replan) ──────────
    replan_trigger: object = None       # L1WarnReplanTrigger
    replan_executor: object = None      # GeometryReplanV0
    replan_state: object = None         # ReplanRuntimeState

    # ── Safety layer init + envelope gating ─────────────────────────────
    # R7 C2 fix: envelope gating must be enabled whenever a safety config is
    # in use, not only when --replan is passed.  Without this, the RuleEngine
    # silently ignores dist_for_gating (surface-corrected distance) and falls
    # back to centre-to-centre distance, overestimating clearance by up to
    # 0.20 m (head radius + EE radius).
    if not args_cli.no_safety:
        try:
            adapter._init_safety_layer()
            sc = adapter._safety_config
            sc.envelope.gating_enabled = True
            # Use YAML config values directly (no hidden overrides).
            # The --config YAML controls safety thresholds; paper scenarios
            # use explicit config_path to safety_fusion.yaml or safety_layer1.yaml.
            print(f"[phase3] Safety thresholds from config: "
                  f"hard_stop={sc.safe_dist_hard_stop:.2f}m "
                  f"warn={sc.safe_dist_warn:.2f}m "
                  f"TTC_stop={sc.ttc.ttc_threshold:.1f}s")
        except Exception as e:
            print(f"[phase3] WARNING: Safety layer init failed: {e}. "
                  "Surface-distance gating disabled.")
    if args_cli.replan and _HAS_REPLAN_LOADER:
        # C9 fix (2026-07-13): replan trigger threshold (5) is calibrated for
        # pursuit_mode virtual hand which produces sustained SLOW_DOWN.  Without
        # --virtual-hand, real G1 body kinematics rarely generate 5 consecutive
        # SLOW_DOWN steps — replan is effectively disabled.
        if args_cli.virtual_hand is None:
            print("[phase3] WARNING: --replan without --virtual-hand — "
                  "replan trigger threshold (5) is tuned for virtual-hand "
                  "pursuit mode.  Real G1 kinematics may never trigger replan.  "
                  "Add --virtual-hand RADIUS for reliable replan testing.")
        try:
            _replan = _get_replan_imports()
            # Safety layer already initialised above (R7 C2 fix); reuse.
            sc = adapter._safety_config
            # Auto-widen workspace z for detour headroom (detour raises EE ~0.1 m).
            if sc.workspace.z_max < 0.90:
                old_z = sc.workspace.z_max
                sc.workspace.z_max = 0.95
                print(f"[phase3] Workspace z_max widened: {old_z:.2f} → 0.95 (detour headroom)")
            # Auto-widen workspace XY for detour lateral offset.
            # Base lateral is 0.10 m, but adjust_lateral_for_held() can boost
            # it by HELD_CLOSEST_LATERAL_BOOST_M (0.05 m) when the held-part
            # envelope is closest to the hand.  Effective lateral up to 0.24 m
            # can push the EE outside the default x∈[0.1,1.1] y∈[-0.5,0.5].
            if sc.workspace.x_max < 1.20:
                sc.workspace.x_max = 1.25
                print(f"[phase3] Workspace x_max widened to 1.25 (detour lateral headroom)")
            if sc.workspace.x_min > 0.05:
                sc.workspace.x_min = 0.05
            if sc.workspace.y_max < 0.60:
                sc.workspace.y_max = 0.65
                print(f"[phase3] Workspace y_max widened to 0.65 (detour lateral headroom)")
            if sc.workspace.y_min > -0.60:
                sc.workspace.y_min = -0.65
                print(f"[phase3] Workspace y_min widened to -0.65 (detour lateral headroom)")
            # Envelope gating already enabled above (R7 C2 fix).
            # IW1 fix: widen warn band so RuleEngine issues SLOW_DOWN earlier for
            # the virtual hand (radius 0.45 m means centre is far from EE even when
            # surface is close).  Must write back to sc BEFORE RuleEngine reads it.
            # R7 deadlock fix: narrowed from 0.30→0.22 — wide enough for replan
            # trigger accumulation (5 steps at 50 Hz), narrow enough to avoid
            # sustained SLOW_DOWN during normal transit.
            # safe_dist_warn already set to 0.25 above (R7 aggressive thresholds)
            replan_state = _replan["ReplanRuntimeState"]()
            replan_executor = _replan["GeometryReplanV0"]()
            replan_trigger = _replan["L1WarnReplanTrigger"](
                _replan["ReplanTriggerConfig"](
                    safe_dist_hard_stop=sc.safe_dist_hard_stop,
                    safe_dist_warn=sc.safe_dist_warn,  # already widened above (R7: 0.22)
                    lateral_offset_m=cfg.safety.replan.detour_lateral_m,
                    detour_stage_duration=cfg.safety.replan.detour_duration,
                    replan_trigger_threshold=cfg.safety.replan.trigger_threshold,
                    ttc_replan_trigger_threshold=4,  # TTC replan triggers faster than static
                    ttc_forecast_replan_threshold=(
                        1.0 if cfg.dynamic_sweep.enabled else None
                    ),
                    held_critical_replan_enabled=bool(
                        cfg.safety.replan.held_critical_replan_enabled
                    ),
                )
            )
            print(
                "[phase3] Motion replan enabled (GMRobot L1WarnReplanTrigger + "
                f"GeometryReplanV0); held_critical_replan="
                f"{bool(cfg.safety.replan.held_critical_replan_enabled)}"
            )
        except Exception as e:
            print(f"[phase3] WARNING: --replan passed but replan init failed: {e}. "
                  "Replan disabled.")
    elif args_cli.replan:
        print("[phase3] WARNING: --replan passed but _get_replan_imports not available. "
              "Replan disabled. Check safety_adapter.py.")

    # ── F-group: safety response tracking ────────────────────────────────
    # H20 fix (2026-07-13): renamed from consecutive_gate_count — this counter
    # increments on BOTH STOP and SLOW_DOWN, not just STOP.  The old name
    # misled reviewers into checking tier0_stop_count==0 and concluding
    # "no livelock" when 116+ consecutive SLOW_DOWN events were active.
    consecutive_gate_count: int = 0        # F09 — consecutive non-ALLOW steps
    disturbance_active: bool = False       # D-group — G1 in CAUTIOUS/MODERATE
    disturbance_start_step: int = 0        # D-group — step when disturbance began
    _disturbance_attempt_id: int = 0       # §6.1 — incremented on each new disturbance activation
    last_vlm_decision: dict = {}          # H-group — most recent VLM output
    replan_last_success: bool = False     # F07
    replan_last_failure_reason: str = ""  # F08
    _replan_applied_this_step: bool = False  # §6.1 edge: True only on the step apply() succeeds
    _replan_event_id: int = 0            # §6.1: unique per replan correlation chain
    _pending_dynamic_retreat_event_id: int = 0  # B2: retreat next step shares trigger/applied id
    _replan_trigger_step: int = -1       # §6.1: sim step when trigger fired
    _replan_trigger_rule: str = ""       # §6.1: rule that triggered replan
    _replan_applied_step: int = -1       # §6.1: sim step when replan was applied
    _pending_replan_attr: object = None  # ReplanAttribution captured at trigger
    _applied_replan_attr: object = None  # attribution consumed on successful apply
    _vlm_replan_strategy: str = ""        # R7: VLM-coordinated replan hint
    _last_replan_strategy: str = ""       # R7: for tracking CSV
    _last_replan_raise: float = 0.0
    _last_replan_lateral: float = 0.0

    # ── Virtual-hand retreat/re-deploy ──────────────────────────────────
    vhand_retreated: bool = False              # hand currently pulled back
    retreat_event_this_step: bool = False
    redeploy_event_this_step: bool = False
    vhand_retreat_steps: int = max(0, args_cli.vhand_retreat)  # STOP timeout (0=never)
    vhand_last_stage_key: str = ""             # detect stage transitions
    # R7 deadlock fix: after re-deploy, block another retreat for N steps so
    # the UR10e has time to complete its approach→descend→grasp/lift cycle
    # before the hand can retreat again.  Without this, re-deploy→STOP→retreat
    # oscillates every few seconds and the UR10e never makes progress.
    _VHAND_REPLOY_COOLDOWN: int = 300  # steps (6 s @ 50 Hz) — one full pick/place cycle
    vhand_reploy_cooldown: int = 0       # decremented each step; retreat blocked while >0

    # ── Deadlock detection + 3-tier escape (R7) ─────────────────────────
    # Deadlock = positive feedback: hand close → STOP → EE frozen → hand
    # stays near EE → STOP persists.  Three conditions must hold:
    #   1. consecutive STOP > 50 steps (temporal)
    #   2. EE position variance < 0.001 m² over window (spatial freeze)
    #   3. hand-EE distance variance < 0.0001 m² over window (distance stable)
    # Escape tiers: L1 jitter (±0.05m) → L2 repel (push hand 0.5m away)
    # → L3 G1 retreat (force G1 backward).  Hysteresis prevents bounce-back.
    _DL_WINDOW: int = 50                        # steps for variance window
    _DL_EE_HISTORY: list = []                   # last N EE positions [(x,y,z),...]
    _DL_DIST_HISTORY: list = []                 # last N hand-EE surface distances
    _dl_escape_tier: int = 0                     # 0=normal 1=jitter 2=repel 3=g1_retreat
    _dl_hysteresis_steps: int = 0                # must stay >0.30m for N steps before re-approach
    _DL_HYSTERESIS_DIST: float = 0.30            # safe radius (m)
    _DL_HYSTERESIS_STEPS_REQ: int = 30           # steps required in safe zone
    # R7 H2 fix: vhand_retreat_steps=0 means "never retreat", but the retreat
    # timeout is the ONLY escape from STOP during PLACE stages (descend_to_box,
    # open_gripper).  With retreat disabled, UR10e freezes permanently if the
    # virtual hand blocks the corridor during a place operation.
    if vhand_retreat_steps == 0 and virtual_hand is not None:
        print("[phase3] WARNING: --vhand-retreat 0 disables retreat timeout.  "
              "If the virtual hand blocks the UR10e during a place stage "
              "(descend_to_box / open_gripper), the UR10e will deadlock "
              "permanently — there is no other escape path.")
    vhand_smoothed: np.ndarray | None = None   # R5 M3: lag-filtered attractor (was main._vhand_smoothed)
    tilt_warned: bool = False                  # R5 M3: tilt warning already emitted (was main._tilt_warned)
    _prev_protocol_phase: str = ""             # detect per-part phase transitions for retreat events
    _safety_sc: object = None                  # P1: cached safety config for step CSV warn threshold
    retreat_event_this_step: bool = False      # P0-2: one-shot edge for metrics (not long-lived latch)
    _in_transit_prev: bool = False             # TRANSIT SLOW-streak telemetry
    _shadow_gate_decision_this_step: str = ""
    _shadow_replan_would_this_step: bool = False
    _replan_dist_at_trigger: float = float("inf")
    _replan_hard_at_trigger: float = float("inf")
    _replan_gate_at_trigger: str = ""
    _replan_rule_at_trigger: str = ""
    _sweep_out = None
    _prev_sweep_retreating: bool = False  # P0-10: lifecycle RETREATING edge

    # ── Mode override ────────────────────────────────────────────────────
    mode_override: DisturbanceMode | None = None
    if args_cli.mode != "auto":
        mode_override = DisturbanceMode(args_cli.mode)

    # Resolve EE tracking body index once (configurable via ee_track).
    _ee_body_ids, _ = ur10e_robot.find_bodies(cfg.safety.ee_track.body)
    _ee_body_idx = _ee_body_ids[0]
    _ee_offset = np.array(cfg.safety.ee_track.offset, dtype=np.float32)

    # mid360_link = LiDAR body, mounted at the very top of G1's head.
    _head_body_idx = g1.find_bodies("mid360_link")[0][0]
    _HEAD_Z_OFFSET = 0.14  # above LiDAR body (visible clearance from head)
    # d435_link = camera body used for virtual-hand head tracking.
    # ponytail: cached at init — previously looked up every step (10000 calls).
    _d435_body_idx = g1.find_bodies("d435_link")[0][0]

    # ── Safety import failure cache (R6 H1 fix) ──────────────────────────
    # Re-attempting the import on every step when GMRobot modules are missing
    # wastes CPU and silently prints nothing after step 0.  Cache the failure
    # and, when --no-safety was NOT explicitly passed, refuse to start.
    _safety_import_failed: bool = False
    _safety_import_error: str = ""

    gate_decision = None  # initialised before first use (deadlock check)
    _g1_root_now = np.asarray(_root0, dtype=np.float64).copy()
    g1_tilt = 0.0
    for step in range(max_steps):
        # §6.1: unconditionally clear replan edge at start of each step.
        _replan_applied_this_step = False
        _replan_trigger_rule = ""
        _applied_replan_attr = None
        _shadow_gate_decision_this_step = ""
        _shadow_replan_would_this_step = False
        _sweep_out = None
        retreat_event_this_step = False
        redeploy_event_this_step = False
        # ── 1. Read robot state ───────────────────────────────────────
        g1_root = g1.data.root_pos_w[0].cpu().numpy()
        ur10e_ee = ur10e_robot.data.body_link_pos_w[0, _ee_body_idx].cpu().numpy() + _ee_offset

        # ── 2. G1 walking (reads obs with injected velocity) ──────────
        walker_obs = obs["g1_walker"][0].cpu().numpy().astype(np.float32)
        g1_leg_action = g1_walk.get_action(walker_obs)  # (12,)

        # ── 3. VLM navigation query ────────────────────────────────────
        if vlm_client is not None and step % VLM_INTERVAL == 0:
            head_rgb = obs.get("g1_head_camera", {}).get("head_rgb")
            if head_rgb is not None:
                img = head_rgb[0].cpu().numpy()
                decision = vlm_client.query(img, step)
                vlm_last_action = decision.get("action", "wait")
                last_vlm_decision = decision          # H-group
                if step % (VLM_INTERVAL * 5) == 0:  # log every 5th query
                    print(f"  [vlm] step {step}: action={vlm_last_action} "
                          f"reason={decision.get('reason','?')[:60]} "
                          f"latency={decision.get('latency_ms',0):.0f}ms")

        # ── 3b. Scene VLM strategic advisor (overhead camera, low freq) ──
        # R7: the scene camera gives a global overhead view.  The VLM acts as
        # a strategy advisor — it picks the best approach angle for G1 to test
        # safety boundaries, overriding the static --approach-side preset.
        # Runs at 1/4 the head-camera rate (~16 s vs ~4 s).
        _SCENE_VLM_INTERVAL: int = cfg.vlm.scene_interval
        _scene_strategy: str = "continue"  # default: keep current approach
        if args_cli.vlm_scene and vlm_client is not None and step % _SCENE_VLM_INTERVAL == 0:
            scene_rgb = obs.get("ur10e_camera", {}).get("scene_rgb")
            if scene_rgb is not None:
                scene_img = scene_rgb[0].cpu().numpy()
                scene_advice = vlm_client.query_scene(scene_img, step)
                _scene_strategy = scene_advice.get("strategy", "continue")
                if step % (_SCENE_VLM_INTERVAL * 2) == 0:
                    print(f"  [vlm-scene] step {step}: strategy={_scene_strategy} "
                          f"reason={scene_advice.get('reason','?')[:60]} "
                          f"latency={scene_advice.get('latency_ms',0):.0f}ms")

        # ── 3c/3d shared interval (defined once, used by monitor + coordinate) ──
        _MONITOR_INTERVAL: int = cfg.vlm.scene_interval

        # ── 3c. VLM part monitoring (overhead camera, low freq) ──────────
        # R7: periodically query the scene camera for part/gripper state.
        # Acts as visual ground-truth: confirms picks, detects knock-offs,
        # cross-validates the protocol's assumptions about part progress.
        if args_cli.vlm_monitor and vlm_client is not None and step % _MONITOR_INTERVAL == 0:
            monitor_rgb = obs.get("ur10e_camera", {}).get("scene_rgb")
            if monitor_rgb is not None:
                mimg = monitor_rgb[0].cpu().numpy()
                mstate = vlm_client.query_monitor(mimg, step)
                _monitor_A = mstate.get("container_A_slots", [])
                _monitor_B = mstate.get("container_B_slots", [])
                _monitor_fallen = mstate.get("fallen_parts", 0)
                _monitor_grip = mstate.get("gripper", "?")
                _monitor_arm = mstate.get("arm_status", "?")
                # Cross-validate against protocol state.
                _proto_part_idx = per_part.part_index + 1 if per_part is not None else 0
                _proto_phase = per_part.phase.value if per_part is not None else "none"
                print(f"  [vlm-monitor] step={step} gripper={_monitor_grip} "
                      f"arm={_monitor_arm} A_slots={_monitor_A} B_slots={_monitor_B} "
                      f"fallen={_monitor_fallen} "
                      f"proto_part={_proto_part_idx} proto_phase={_proto_phase} "
                      f"latency={mstate.get('latency_ms',0):.0f}ms")

        # ── 3d. VLM coordinated guidance (overhead → hand + UR10e) ────────
        # R7: VLM advises both sides simultaneously.  hand_action overrides
        # the protocol's phase behavior; ur10e_strategy feeds into replan hint.
        _coord_hand_action: str = ""
        _coord_ur10e_strategy: str = ""
        if args_cli.vlm_coordinate and vlm_client is not None and step % _MONITOR_INTERVAL == 0:
            coord_rgb = obs.get("ur10e_camera", {}).get("scene_rgb")
            if coord_rgb is not None:
                cimg = coord_rgb[0].cpu().numpy()
                coord = vlm_client.query_coordinate(cimg, step)
                _coord_hand_action = coord.get("hand_action", "")
                _coord_ur10e_strategy = coord.get("ur10e_strategy", "")
                _coord_target = coord.get("hand_target_xy")
                # Apply hand guidance immediately.
                if per_part is not None and _coord_hand_action:
                    if _coord_hand_action == "retreat":
                        per_part.state.attractor_xy = None
                    elif _coord_target is not None:
                        per_part.state.attractor_xy = np.array(_coord_target, dtype=np.float32)
                # Store for injection on next replan trigger.
                if _coord_ur10e_strategy and _coord_ur10e_strategy != "continue":
                    _vlm_replan_strategy = _coord_ur10e_strategy
                print(f"  [vlm-coord] step={step} hand={_coord_hand_action} "
                      f"ur10e={_coord_ur10e_strategy} "
                      f"target={_coord_target} "
                      f"reason={coord.get('reason','?')[:60]} "
                      f"latency={coord.get('latency_ms',0):.0f}ms")

        # Apply scene VLM strategy every step — overrides static approach preset.
        if args_cli.vlm_scene and vlm_client is not None and _scene_strategy != "continue":
            if _scene_strategy == "left":
                disturb._vy_bias = 0.10
                disturb._vx_bias = 0.0
            elif _scene_strategy == "right":
                disturb._vy_bias = -0.10
                disturb._vx_bias = 0.0
            elif _scene_strategy == "front":
                disturb._vy_bias = 0.0
                disturb._vx_bias = 0.25
            elif _scene_strategy == "back":
                disturb._vy_bias = 0.0
                disturb._vx_bias = -0.25

        # ── 4. Disturbance controller → inject velocity ───────────────
        force_retreat = mode_override == DisturbanceMode.CAUTIOUS if mode_override else False

        # VLM-guided velocity override (maps action → (vx, vy, wz))
        vlm_cmd: np.ndarray | None = None
        if vlm_client is not None and vlm_last_action in VLM_ACTION_CMD:
            vlm_cmd = VLM_ACTION_CMD[vlm_last_action]
        # Read G1 body contact forces for force-based stuck retreat (Phase 4).
        contact_forces = None
        try:
            cf_sensor = scene.sensors.get("g1_contact_forces")
            if cf_sensor is not None and cf_sensor.data.net_forces_w is not None:
                contact_forces = cf_sensor.data.net_forces_w[0].cpu().numpy()  # (37, 3)
        except Exception:
            pass
        disturb_cmd = disturb.update(
            g1_root, ur10e_ee,
            force_retreat=force_retreat,
            force_mode=mode_override,  # R7 C1 fix: pass override BEFORE velocity computation
            contact_forces=contact_forces,
            # H2 fix (2026-07-13): pass the safety-adapter surface distance so
            # the disturbance controller's mode selection matches what the
            # safety gate actually sees (virtual hand surface, not G1 root).
            surface_distance=adapter.closest_body_distance if adapter is not None else None,
        )

        # VLM velocity override with hybrid drive (D) + boundary spring (B)
        if vlm_cmd is not None:
            # D: blend VLM intent with corridor attractor
            to_corridor = ur10e_ee[:2] - g1_root[:2]
            corridor_dist = float(np.linalg.norm(to_corridor))
            if corridor_dist > cfg.vlm.corridor_activate_dist:
                attractor = to_corridor / corridor_dist * cfg.vlm.corridor_pull_gain
                vlm_cmd[:2] = (cfg.vlm.blend_vlm_weight * vlm_cmd[:2]
                               + cfg.vlm.blend_corridor_weight * attractor)
            disturb_cmd = vlm_cmd

            # B: boundary spring — if G1 strays too far, override with retreat
            g1_ee_dist = float(np.linalg.norm(g1_root[:2] - ur10e_ee[:2]))
            if g1_ee_dist > cfg.vlm.boundary_max_dist:
                to_ee = ur10e_ee[:2] - g1_root[:2]
                disturb_cmd = np.array([to_ee[0], to_ee[1], 0.0], dtype=np.float32)
                disturb_cmd[:2] = (cfg.vlm.boundary_spring_gain
                                   * disturb_cmd[:2] / (np.linalg.norm(disturb_cmd[:2]) + 1e-9))
                if step % 200 == 0:
                    print(f"  [vlm] boundary spring: G1 too far (d={g1_ee_dist:.1f}m), pulling back")

        # Inject into command manager for the NEXT env.step() observation
        inject_disturbance_velocity(env, disturb_cmd, device)

        # ── 4. UR10e pick-and-place (proposed action, no auto-advance) ──
        # Clock must only advance when gate allows it; STOP/SLOW_DOWN
        # freeze the stage sequence so the EE has time to reach the target
        # pose before the next stage fires (e.g. close_gripper before EE
        # reaches the part during a STOPped descent).
        ur10e_proposed = ur10e.get_action(obs["ur10e_policy"], advance=False)  # (8,)

        # ── 5. Safety adapter + GMRobot safety layer ──────────────────
        adapter.update(g1, ur10e_ee)

        # Stress mode / approach-side: simulated arm reaching toward UR10e.
        if args_cli.stress or args_cli.approach_side is not None:
            body_xy = adapter.human_hand_pos[:2].copy()
            ee_xy = ur10e_ee[:2]
            # Pull hand XY toward EE.
            adapter.human_hand_pos[:2] = 0.6 * body_xy + 0.4 * ee_xy
            adapter.human_hand_pos[2] = ur10e_ee[2]
            adapter.human_hand_vel[2] = 0.0
            # Fixed arm length: clamp hand to exactly arm_length from G1 head.
            if cfg.arm.length_fixed:
                head_pos = g1.data.body_link_pos_w[0, _head_body_idx].cpu().numpy()
                head_pos[2] += _HEAD_Z_OFFSET  # neck joint → visual head top
                to_hand = adapter.human_hand_pos - head_pos
                dist = float(np.linalg.norm(to_hand))
                if dist > 0.001:
                    adapter.human_hand_pos = head_pos + (to_hand / dist) * cfg.arm.length
            adapter.closest_body_distance = float(
                np.linalg.norm(adapter.human_hand_pos - ur10e_ee)
            )
            # R7 C3 fix: apply surface-distance correction (same as virtual-hand
            # path at lines 695-698).  Without body-radius + EE-radius subtraction,
            # the safety gate sees centre-to-centre distance and triggers STOP
            # later than intended (up to 0.13 m too late for a wrist-sized body).
            _stress_hand_radius = 0.05  # human wrist radius (matches SAFETY_BODIES)
            adapter.closest_body_distance = max(
                0.0,
                adapter.closest_body_distance - _stress_hand_radius - adapter._ee_radius,
            )
            adapter.closest_body_name = "stress_projection"

        # ── Virtual hand: override adapter hand position with moving sphere ──
        # R6 H5 fix: cache the real G1 body distance BEFORE the virtual hand
        # overrides adapter state.  The grasp-rewind check (5c) needs the actual
        # body-EE distance, not the virtual-hand distance which may be far away
        # during retreat.  Without this, grasp disturbance detection is
        # silently disabled in virtual-hand mode.
        # Caveat: in scenario-hand mode the scenario hand IS the obstacle that
        # matters — update after the scenario handler writes closest_body_distance.
        _body_distance_for_grasp = adapter.closest_body_distance
        # §6.1: cache the real G1 body name BEFORE virtual hand overrides it.
        _g1_closest_body_name = adapter.closest_body_name
        _g1_closest_body_dist = adapter.closest_body_distance

        # R7: permanent virtual-hand removal after N steps.
        # Lets the UR10e finish its pick-and-place cycle undisturbed.
        if (virtual_hand is not None
                and args_cli.vhand_remove_after > 0
                and step >= args_cli.vhand_remove_after):
            print(f"\n[phase3] Virtual hand REMOVED at step {step} "
                  f"(vhand_remove_after={args_cli.vhand_remove_after})")
            virtual_hand = None

        # ── Scenario: direction + length hand (polar coordinates) ─────────
        # Hand is defined in spherical coordinates centred on G1's head:
        #   direction = blend of base_dir (head→table, the "where to aim")
        #               and ee_dir (head→EE, an EE-driven fine-tuning bias)
        #   length    = α × distance(head, EE), clamped to [min, max]
        # During transit α=1.0 → arm extends, hand nears EE → SLOW_DOWN.
        # During pick/place α=0.3 → arm retracts, hand stays near head.
        # No position switching — only α changes, direction is continuous.
        # Base direction points toward table centre XY, but Z tracks the
        # EE's current operating height so the arm aims at the right level
        # (grasp height during pick, transit height during carry, etc.).
        _BASE_Z = float(np.clip(ur10e_ee[2], 0.25, 0.90))
        _TABLE_XYZ = np.array([0.60, 0.0, _BASE_Z], dtype=np.float32)
        _HAND_BODY_RADIUS = 0.05    # wrist radius (SAFETY_BODIES)
        _EE_RADIUS = 0.08           # UR10e EE sphere radius
        _BASE_DIR_BLEND = 0.7       # base_dir weight vs ee_dir
        _calc_surf = lambda hp, ee: float(max(0.0,
            np.linalg.norm(hp - ee) - _HAND_BODY_RADIUS - _EE_RADIUS))

        if scen_hand is not None:
            _head_pos = g1.data.body_link_pos_w[0, _head_body_idx].cpu().numpy()
            _head_pos[2] += _HEAD_Z_OFFSET  # neck joint → visual head top
            sc = scen_hand.update(_head_pos, ur10e_ee)
            # ── Direction: blend base_dir (toward workspace) + ee_dir ──
            _to_table = _TABLE_XYZ - _head_pos
            _base_dir = _to_table / (float(np.linalg.norm(_to_table)) + 1e-8)
            _to_ee = ur10e_ee - _head_pos
            _ee_dir = _to_ee / (float(np.linalg.norm(_to_ee)) + 1e-8)
            _ee_blend = _BASE_DIR_BLEND if sc["action"] != "track_ee" else 0.3
            _dir_blend = _ee_blend * _base_dir + (1.0 - _ee_blend) * _ee_dir
            _dir_blend /= (float(np.linalg.norm(_dir_blend)) + 1e-8)
            # ── Length: α × EE distance, clamped ────────────────────────
            _ee_dist = float(np.linalg.norm(_to_ee))
            _is_pick = any(kw in (ur10e.stage_name or "") for kw in (
                "move_above_slot", "descend_to_slot",
                "close_gripper", "grasp_", "lift_slot"))
            _is_place = any(kw in (ur10e.stage_name or "") for kw in (
                "descend_to_box", "open_gripper_to_release"))
            if sc["action"] == "block":
                _alpha = 0.3 if (_is_pick or _is_place) else 1.0
            elif sc["action"] in ("home", "retreat"):
                _alpha = 0.3    # retracted
            else:  # track_ee
                _alpha = 1.0
            _raw_len = _alpha * _ee_dist
            _length = float(np.clip(_raw_len, cfg.arm.length_min, cfg.arm.length_max))
            # ── Hand position ───────────────────────────────────────────
            adapter.human_hand_pos = (_head_pos + _dir_blend * _length).astype(np.float32)
            adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
            adapter.closest_body_distance = _calc_surf(
                adapter.human_hand_pos, ur10e_ee)
            adapter.closest_body_name = (
                f"scenario_{sc['action']}_{sc['direction']}"
                if sc["action"] == "block" else f"scenario_{sc['action']}")
            if step % ival == 0:
                print(f"  [scenario] t={scen_hand._sim_time:.1f}s "
                      f"action={sc['action']} dir={sc['direction']} "
                      f"α={_alpha:.1f} len={_length:.2f}m "
                      f"surf={adapter.closest_body_distance:.2f}m")

        if virtual_hand is not None and scen_hand is None:
            head_pos = g1.data.body_link_pos_w[0, _d435_body_idx].cpu().numpy()
            if dynamic_sweep is not None:
                # ── B2: world-coordinate scripted lateral sweep ─────────
                _cur_phase = "reset"
                if per_part is not None:
                    stage = ur10e.stage_name
                    per_part.update(stage, ur10e_ee, head_pos, ur10e.is_grasping)
                    _cur_phase = per_part.phase.value
                    _was_retreated = vhand_retreated
                    _attempt_has_retreat = (
                        _disturbance_attempt_id > 0
                        and _disturbance_attempt_id in metrics._attempt_recoveries
                        and metrics._attempt_recoveries[_disturbance_attempt_id].retreat_step >= 0
                    )
                    vhand_retreated, _proto_retreat_edge = protocol_retreat_transition(
                        _prev_protocol_phase, _cur_phase, vhand_retreated,
                        prefer_replan=True,
                        timed_out=bool(per_part.phase_entered_via_timeout),
                        attempt_already_retreated=_attempt_has_retreat,
                    )
                    if _proto_retreat_edge and _enforcement_mode == "active":
                        retreat_event_this_step = True
                        _write_event(
                            step, "retreat", _disturbance_attempt_id,
                            trigger_rule="protocol",
                            trigger_source="scripted_virtual_hand",
                        )
                    elif (
                        _was_retreated
                        and not vhand_retreated
                        and _enforcement_mode == "active"
                        and attempt_needs_canonical_redeploy(
                            metrics._attempt_recoveries, _disturbance_attempt_id
                        )
                    ):
                        # Protocol latch clear only if this attempt has no
                        # canonical redeploy yet (RETREATING→IDLE is preferred).
                        redeploy_event_this_step = True
                        _write_event(
                            step, "redeploy", _disturbance_attempt_id,
                            trigger_rule="protocol",
                            trigger_source="scripted_virtual_hand",
                        )
                    _prev_protocol_phase = _cur_phase
                _sweep_out = dynamic_sweep.step(
                    protocol_phase=_cur_phase,
                    ee_pos=ur10e_ee,
                    enforcement_mode=_enforcement_mode,
                    replan_applied_this_step=bool(
                        _replan_applied_this_step and _enforcement_mode == "active"
                    ),
                    phase_radii=_phase_radii_obj,
                )
                if _sweep_out.attempt_started:
                    _disturbance_attempt_id = max(
                        _disturbance_attempt_id, _sweep_out.sweep_attempt_id
                    )
                from dynamic_sweep_proxy import SweepLifecycle
                # Canonical recovery redeploy: lifecycle RETREATING→IDLE only.
                # Do not key off the protocol latch — PLACE→RESET may re-assert
                # retreated when attempt_already_retreated (would double-count).
                _sweep_retreating = (
                    _sweep_out.lifecycle == SweepLifecycle.RETREATING
                )
                if (
                    dynamic_sweep_redeploy_edge(
                        _prev_sweep_retreating,
                        _sweep_retreating,
                        already_emitted=redeploy_event_this_step,
                    )
                    and _enforcement_mode == "active"
                ):
                    _open_aid = find_open_attempt_id(metrics._attempt_recoveries)
                    _redeploy_aid = (
                        _open_aid if _open_aid > 0 else _disturbance_attempt_id
                    )
                    if attempt_needs_canonical_redeploy(
                        metrics._attempt_recoveries, _redeploy_aid
                    ):
                        redeploy_event_this_step = True
                        _write_event(
                            step, "redeploy", _redeploy_aid,
                            trigger_rule="protocol",
                            trigger_source="scripted_virtual_hand",
                        )
                _prev_sweep_retreating = _sweep_retreating
                vhand_retreated = _sweep_retreating
                if _sweep_out.retreat_started and _enforcement_mode == "active":
                    retreat_event_this_step = True
                    metrics.note_transit_replan()
                    metrics.note_retreat(
                        attempt_id=_disturbance_attempt_id,
                        sim_step=step,
                        policy_step=ur10e.time_step,
                        parts_placed=ur10e.parts_placed,
                    )
                    _write_event(
                        step, "retreat", _disturbance_attempt_id,
                        event_id=(
                            str(_pending_dynamic_retreat_event_id)
                            if _pending_dynamic_retreat_event_id > 0
                            else ""
                        ),
                        trigger_rule="replan",
                        trigger_source="scripted_virtual_hand",
                        applied_step=str(step),
                    )
                    _pending_dynamic_retreat_event_id = 0
                virtual_hand._world_pos = _sweep_out.center_xyz.copy()
                virtual_hand.proxy_radius = float(_sweep_out.active_proxy_radius)
                adapter.human_hand_pos = _sweep_out.surface_xyz.astype(np.float32)
                adapter.human_hand_vel = _sweep_out.surface_vel_xyz.astype(np.float32)
                adapter.closest_body_distance = float(_sweep_out.surface_distance)
                adapter.closest_body_name = "scripted_virtual_hand"
                if per_part is not None and per_part.phase == Phase.RESET:
                    adapter.human_hand_pos = np.array([0.0, 0.0, 2.0], dtype=np.float32)
                    adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                    adapter.closest_body_distance = 999.0
                    adapter.closest_body_name = "protocol_reset"
                if _trajectory_fh is not None and _sweep_out.sweep_attempt_id > 0:
                    _log_traj = (
                        dynamic_sweep.first_intervention_step is None
                        or step <= dynamic_sweep.first_intervention_step
                    )
                    if _log_traj:
                        row = commanded_trajectory_row(
                            sim_step=step,
                            output=_sweep_out,
                            disturbance_trajectory_id=dynamic_sweep.disturbance_trajectory_id,
                        )
                        _trajectory_fh.write(
                            ",".join(row[c] for c in (
                                "sim_step", "disturbance_trajectory_id", "sweep_attempt_id",
                                "sweep_progress", "proxy_center_x", "proxy_center_y",
                                "proxy_center_z", "proxy_surface_x", "proxy_surface_y",
                                "proxy_surface_z", "sweep_velocity_x", "sweep_velocity_y",
                                "sweep_velocity_z",
                            )) + "\n"
                        )
                        _trajectory_fh.flush()
            else:
                # ── Per-part protocol: phase-driven attractor + radius ─────
                if per_part is not None:
                    stage = ur10e.stage_name
                    per_part.update(stage, ur10e_ee, head_pos, ur10e.is_grasping)
                    _cur_phase = per_part.phase.value
                    virtual_hand._attractor = resolve_per_part_attractor(
                        phase=_cur_phase,
                        protocol_attractor_xy=per_part.attractor_xy,
                        head_xy=head_pos[:2],
                        ee_xy=ur10e_ee[:2],
                    )
                    virtual_hand.proxy_radius = per_part_radius(_cur_phase, **_vh_phase_radii)
                    adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                    virtual_hand._prev_world_pos = virtual_hand._world_pos.copy()
                    _was_retreated = vhand_retreated
                    _attempt_has_retreat = (
                        _disturbance_attempt_id > 0
                        and _disturbance_attempt_id in metrics._attempt_recoveries
                        and metrics._attempt_recoveries[_disturbance_attempt_id].retreat_step >= 0
                    )
                    vhand_retreated, _proto_retreat_edge = protocol_retreat_transition(
                        _prev_protocol_phase, _cur_phase, vhand_retreated,
                        prefer_replan=bool(args_cli.replan),
                        timed_out=bool(per_part.phase_entered_via_timeout),
                        attempt_already_retreated=_attempt_has_retreat,
                    )
                    if _proto_retreat_edge:
                        retreat_event_this_step = True
                        _write_event(
                            step, "retreat", _disturbance_attempt_id,
                            trigger_rule="protocol",
                            trigger_source=_resolve_disturbance_source(args_cli, virtual_hand),
                        )
                        if step % ival == 0:
                            print(f"  [protocol] RETREAT: {_prev_protocol_phase}→{_cur_phase} "
                                  f"at step {step}, policy_step={ur10e.time_step}")
                    elif _was_retreated and not vhand_retreated:
                        redeploy_event_this_step = True
                        _write_event(
                            step, "redeploy", _disturbance_attempt_id,
                            trigger_rule="protocol",
                            trigger_source=_resolve_disturbance_source(args_cli, virtual_hand),
                        )
                        if step % ival == 0:
                            print(f"  [protocol] RE-DEPLOY: {_prev_protocol_phase}→{_cur_phase} "
                                  f"at step {step}")
                    _prev_protocol_phase = _cur_phase
                    if step % ival == 0:
                        p = per_part
                        print(f"  [protocol] part={p.part_index+1}/{p.parts_total} "
                              f"phase={p.phase.value:7s} "
                              f"step_in_phase={p.state.step_in_phase} "
                              f"attr={virtual_hand._attractor} "
                              f"retreated={vhand_retreated}")
                if per_part is None:
                    if args_cli.vhand_lag > 0:
                        if vhand_smoothed is None:
                            vhand_smoothed = ur10e_ee[:2].copy()
                        alpha = 1.0 - args_cli.vhand_lag
                        vhand_smoothed = (alpha * ur10e_ee[:2] +
                                          (1.0 - alpha) * vhand_smoothed)
                        virtual_hand._attractor = vhand_smoothed.copy()
                    else:
                        virtual_hand._attractor = ur10e_ee[:2].copy()
                    if _dl_hysteresis_steps > 0:
                        to_ee_xy = virtual_hand._attractor - ur10e_ee[:2]
                        d_xy = float(np.linalg.norm(to_ee_xy))
                        if d_xy < _DL_HYSTERESIS_DIST:
                            if d_xy > 1e-6:
                                virtual_hand._attractor = (
                                    ur10e_ee[:2] + (to_ee_xy / d_xy) * _DL_HYSTERESIS_DIST
                                )
                            else:
                                virtual_hand._attractor = (
                                    ur10e_ee[:2] + np.array([_DL_HYSTERESIS_DIST, 0.0])
                                )
                virtual_hand.step(cfg.safety.control_dt, head_pos, ee_z=ur10e_ee[2])

                if vhand_retreated:
                    head_pos_safe = head_pos.copy()
                    head_pos_safe[2] += _HEAD_Z_OFFSET
                    adapter.human_hand_pos = head_pos_safe
                    adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                    adapter.closest_body_distance = float(
                        np.linalg.norm(head_pos_safe - ur10e_ee)
                    )
                    adapter.closest_body_name = "virtual_hand_retreated"
                else:
                    sphere_center = virtual_hand.position
                    _proxy_r = float(virtual_hand.proxy_radius)
                    to_ee = ur10e_ee - sphere_center
                    center_dist = float(np.linalg.norm(to_ee))
                    if center_dist > 1e-6:
                        surface_point = sphere_center + (to_ee / center_dist) * _proxy_r
                    else:
                        surface_point = sphere_center
                    adapter.human_hand_pos = surface_point
                    adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                    adapter.closest_body_distance = max(
                        0.0,
                        center_dist - _proxy_r - adapter._ee_radius,
                    )
                    adapter.closest_body_name = "virtual_hand"

                if per_part is not None and per_part.phase == Phase.RESET:
                    adapter.human_hand_pos = np.array([0.0, 0.0, 2.0], dtype=np.float32)
                    adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                    adapter.human_torso_pos = np.array([0.0, 0.0, 2.0], dtype=np.float32)
                    adapter.human_torso_vel = np.zeros(3, dtype=np.float32)
                    adapter.closest_body_distance = 999.0
                    adapter.closest_body_name = "protocol_reset"

        # ── Visual debug: sphere + stick at the hand position ──
        if step % 5 == 0:
            from isaaclab.sim import SimulationContext
            stage = SimulationContext.instance().stage
            color = (1.0, 0.3, 0.3) if (args_cli.stress or virtual_hand) else (1.0, 1.0, 0.0)
            # Stick from visual top of G1's head to the hand.
            head_vis = g1.data.body_link_pos_w[0, _head_body_idx].cpu().numpy()
            head_vis[2] += _HEAD_Z_OFFSET  # neck joint → visual head top
            _set_hand_sphere_position(stage, adapter.human_hand_pos, head_pos=head_vis, color=color)

        # ── Deadlock detection + 3-tier escape (R7) ──────────────────────
        # Detects the positive-feedback deadlock: hand close → STOP → EE
        # frozen → hand stays near EE → STOP persists.  Three conditions
        # must ALL hold.  Escalation: jitter → repel → G1 retreat.
        # Shadow mode must not mutate proxy / protocol from evaluated STOP.
        if (
            virtual_hand is not None
            and gate_decision is not None
            and _enforcement_mode != "shadow"
        ):
            # Update sliding windows.
            _DL_EE_HISTORY.append(ur10e_ee.copy())
            _DL_DIST_HISTORY.append(adapter.closest_body_distance)
            if len(_DL_EE_HISTORY) > _DL_WINDOW:
                _DL_EE_HISTORY.pop(0)
                _DL_DIST_HISTORY.pop(0)

            if len(_DL_EE_HISTORY) >= _DL_WINDOW:
                ee_arr = np.array(_DL_EE_HISTORY)
                dist_arr = np.array(_DL_DIST_HISTORY)
                ee_var = float(np.var(ee_arr[:, 0]) + np.var(ee_arr[:, 1]) + np.var(ee_arr[:, 2]))
                dist_var = float(np.var(dist_arr))
                is_deadlocked = (
                    consecutive_gate_count > 50            # condition 1: time
                    and ee_var < 0.001                     # condition 2: EE frozen
                    and dist_var < 0.0001                  # condition 3: distance stable
                )

                # R7: also force RESET on sustained close-proximity STOP —
                # catches the case where hand radius is too large and surface
                # distance stays at 0 despite jitter.
                _dl_force_reset = (
                    per_part is not None
                    and consecutive_gate_count > 30
                    and adapter.closest_body_distance < 0.10
                )
                if _dl_force_reset:
                    per_part.state.phase = Phase.RESET
                    per_part.state.step_in_phase = 0
                    per_part.state.timed_out = False
                    per_part.state.attractor_xy = None
                    _dl_escape_tier = 0
                    _DL_EE_HISTORY.clear()
                    _DL_DIST_HISTORY.clear()
                    if step % ival == 0:
                        print(f"  [deadlock] FORCE RESET: STOP>30 + hand_dist<0.10, "
                              f"retreating hand to let UR10e proceed")

                if is_deadlocked:
                    _dl_escape_tier = min(_dl_escape_tier + 1, 3)
                    if _dl_escape_tier == 1:
                        # L1 — jitter: random ±0.05m to hand position.
                        jitter = np.random.uniform(-0.05, 0.05, 3)
                        jitter[2] *= 0.2  # less Z jitter
                        adapter.human_hand_pos = adapter.human_hand_pos + jitter
                        adapter.closest_body_distance = max(0.0,
                            float(np.linalg.norm(adapter.human_hand_pos - ur10e_ee))
                            - virtual_hand.proxy_radius - adapter._ee_radius)
                        if step % ival == 0:
                            print(f"  [deadlock] L1 JITTER tier={_dl_escape_tier} "
                                  f"ee_var={ee_var:.6f} dist_var={dist_var:.6f}")
                    elif _dl_escape_tier == 2:
                        # L2 — repel: push hand 0.5m away from EE.
                        to_ee = ur10e_ee - adapter.human_hand_pos
                        d = float(np.linalg.norm(to_ee))
                        if d > 1e-6:
                            adapter.human_hand_pos = adapter.human_hand_pos - (to_ee / d) * 0.5
                        adapter.closest_body_distance = max(0.0,
                            float(np.linalg.norm(adapter.human_hand_pos - ur10e_ee))
                            - virtual_hand.proxy_radius - adapter._ee_radius)
                        _dl_hysteresis_steps = _DL_HYSTERESIS_STEPS_REQ
                        if step % ival == 0:
                            print(f"  [deadlock] L2 REPEL tier={_dl_escape_tier} pushed hand 0.5m away")
                    else:
                        # L3 — G1 retreat: force G1 backward + reset hand.
                        retreat_cmd = np.array([-0.50, 0.0, 0.0], dtype=np.float32)
                        inject_disturbance_velocity(env, retreat_cmd, device)
                        virtual_hand._attractor = np.array([0.5, 0.0], dtype=np.float32)
                        virtual_hand._local_xy = np.zeros(2, dtype=np.float32)
                        _dl_escape_tier = 0  # reset after full retreat
                        _dl_hysteresis_steps = _DL_HYSTERESIS_STEPS_REQ
                        _DL_EE_HISTORY.clear()
                        _DL_DIST_HISTORY.clear()
                        if step % ival == 0:
                            print(f"  [deadlock] L3 G1_RETREAT forcing G1 backward, hand reset")
                else:
                    # Not deadlocked — decay escape tier slowly.
                    if _dl_escape_tier > 0:
                        _dl_escape_tier = max(0, _dl_escape_tier - 0.05)

                # ── Hysteresis: after L2/L3 escape, hand must stay >0.30m
                # for 30 steps before re-approaching.  Prevents bounce-back.
                if _dl_hysteresis_steps > 0:
                    if adapter.closest_body_distance > _DL_HYSTERESIS_DIST:
                        _dl_hysteresis_steps -= 1
                    else:
                        _dl_hysteresis_steps = _DL_HYSTERESIS_STEPS_REQ  # reset
                    # During hysteresis, force hand away if it drifts too close.
                    if _dl_hysteresis_steps > 0 and adapter.closest_body_distance < _DL_HYSTERESIS_DIST:
                        to_ee = ur10e_ee - adapter.human_hand_pos
                        d = float(np.linalg.norm(to_ee))
                        if d > 1e-6:
                            push = (to_ee / d) * (_DL_HYSTERESIS_DIST - adapter.closest_body_distance + 0.05)
                            adapter.human_hand_pos = adapter.human_hand_pos - push
                            adapter.closest_body_distance = max(0.0,
                                float(np.linalg.norm(adapter.human_hand_pos - ur10e_ee))
                                - virtual_hand.proxy_radius - adapter._ee_radius)

        # ── Arm length range clamp ──────────────────────────────────────
        # Clamp hand-to-head distance to [length_min, length_max] when
        # length_fixed is False.  This prevents the hand from drifting
        # unrealistically close to the head or extending beyond the G1's
        # physical reach, while still allowing variable length for obstacle
        # sphere tracking during avoidance.
        if not cfg.arm.length_fixed and (cfg.arm.length_min > 0 or cfg.arm.length_max > 0):
            _head_pos = g1.data.body_link_pos_w[0, _head_body_idx].cpu().numpy()
            _head_pos[2] += _HEAD_Z_OFFSET
            _to_hand = adapter.human_hand_pos - _head_pos
            _dist = float(np.linalg.norm(_to_hand))
            if _dist > 0.001:
                if cfg.arm.length_min > 0 and _dist < cfg.arm.length_min:
                    adapter.human_hand_pos = _head_pos + (_to_hand / _dist) * cfg.arm.length_min
                elif cfg.arm.length_max > 0 and _dist > cfg.arm.length_max:
                    adapter.human_hand_pos = _head_pos + (_to_hand / _dist) * cfg.arm.length_max

        if not args_cli.no_safety:
            # Build safety observations from UR10e obs
            safety_obs_dict = {}
            for key in ["ee_vel", "joint_pos", "joint_vel"]:
                val = obs.get("safety", {}).get(key)
                if val is not None:
                    safety_obs_dict[key] = val[0].cpu().numpy()

            policy_obs_dict = {"ee_pos": obs["ur10e_policy"]["ee_pos"][0].cpu().numpy()}

            sim_time = step * cfg.safety.control_dt

            try:
                safety_state = adapter.build_safety_state(
                    policy_obs_dict,
                    safety_obs_dict,
                    step_index=step,
                    sim_time=sim_time,
                )
                # ── Dynamic SLOW_DOWN warn band ────────────────────────
                # Phase base + speed boost + approach-direction gating.
                _ee_vel = safety_obs_dict.get("ee_vel")
                _safety_sc = adapter._safety_config  # not 'sc' — overwritten at L958
                if _ee_vel is not None and ur10e is not None and _safety_sc is not None:
                    _to_hand = adapter.human_hand_pos - ur10e_ee
                    _d = float(np.linalg.norm(_to_hand))
                    if _d > 1e-8:
                        _unit = _to_hand / _d
                        _approach = max(0.0, float(np.dot(_ee_vel, _unit)))
                        _phase = ur10e.transport_phase or "transit"
                        _warn_base = {"transit": 0.20, "approach": 0.15, "place": 0.30}.get(_phase, 0.10)
                        _dyn_warn = (_warn_base + _approach * 0.8) if _approach > 1e-6 else 0.10
                        _dyn_warn = float(np.clip(
                            _dyn_warn,
                            max(0.08, _safety_sc.safe_dist_hard_stop),
                            0.50))
                        _safety_sc.safe_dist_warn = _dyn_warn
                        if replan_trigger is not None:
                            replan_trigger.config.safe_dist_warn = _dyn_warn
                gate_result = adapter.evaluate_safety(
                    safety_state,
                    held_object_active=ur10e.is_grasping,
                    dist_for_gating=adapter.closest_body_distance,
                    proposed_ee_pos=ur10e_proposed[:3],
                    dist_min_held=(adapter.closest_body_distance
                                   if ur10e.is_grasping else None),
                )
                if _enforcement_mode == "shadow":
                    _shadow_gate_decision_this_step = gate_result.g_t.name
                    ur10e_action = ur10e_proposed
                else:
                    ur10e_gated_ee = adapter.apply_safety_gate(
                        gate_result,
                        ur10e_proposed[:7],
                        prev_ur10e_action,
                    )
                    ur10e_action = np.concatenate(
                        [ur10e_gated_ee, ur10e_proposed[7:8]]
                    )

                # Track safety interventions (evaluation always runs).
                gate_decision = gate_result.g_t
                if _enforcement_mode != "shadow":
                    if gate_decision.name == "STOP":
                        metrics.tier0_stop_count += 1
                        consecutive_gate_count += 1   # F09
                    elif gate_decision.name == "SLOW_DOWN":
                        metrics.slowdown_count += 1
                        consecutive_gate_count += 1   # F09 — livelock includes sustained SLOW
                    else:
                        consecutive_gate_count = max(0, consecutive_gate_count - 2)  # F09 decay

                # D-group: disturbance effect causal inference (§6.1).
                # Attempt windows are created when:
                #   a) G1 body enters MODERATE/CAUTIOUS zone, OR
                #   b) Per-part protocol TRANSIT phase begins (B1 deterministic), OR
                #   c) Virtual hand enters warn zone (fallback when no protocol).
                _g1_active = disturb.mode in (DisturbanceMode.MODERATE, DisturbanceMode.CAUTIOUS)
                from dynamic_sweep_proxy import SweepLifecycle as _SweepLifecycle
                _sweep_disturbing = (
                    dynamic_sweep is not None
                    and _sweep_out is not None
                    and _sweep_out.lifecycle == _SweepLifecycle.SWEEPING
                )
                _protocol_transit = (
                    per_part is not None
                    and per_part.phase.value == "transit"
                    and virtual_hand is not None
                    and not vhand_retreated
                    and (dynamic_sweep is None or _sweep_disturbing)
                )
                _vhand_warn_threshold = (
                    adapter._safety_config.safe_dist_warn
                    if adapter is not None and adapter._safety_config is not None
                    else 0.16
                )
                _vhand_active = (
                    virtual_hand is not None
                    and not vhand_retreated
                    and not _protocol_transit  # don't double-count
                    and adapter.closest_body_distance < _vhand_warn_threshold
                )
                _currently_disturbing = _g1_active or _protocol_transit or _vhand_active
                if dynamic_sweep is not None and _sweep_out is not None:
                    if _sweep_out.lifecycle == _SweepLifecycle.SWEEPING:
                        disturbance_active = True
                        if _sweep_out.sweep_attempt_id > 0:
                            _disturbance_attempt_id = _sweep_out.sweep_attempt_id
                    elif not _g1_active and not _vhand_active:
                        disturbance_active = False
                elif _currently_disturbing:
                    if not disturbance_active:
                        disturbance_active = True
                        disturbance_start_step = step
                        _disturbance_attempt_id += 1  # §6.1: new disturbance attempt
                else:
                    disturbance_active = False
            except ImportError as e:
                # GMRobot safety modules not available — fall back to ungated.
                # This is expected when isaaclab is not on sys.path (e.g. dry-run).
                # R6 H1 fix: cache the failure — don't re-attempt import on every
                # step.  If --no-safety was NOT explicitly passed, this is a
                # misconfiguration; refuse to start rather than silently running
                # 10000 steps with zero safety gating.
                if not _safety_import_failed:
                    _safety_import_failed = True
                    _safety_import_error = str(e)
                    if not args_cli.no_safety:
                        print(f"\n[phase3] FATAL: Safety layer import failed but "
                              f"--no-safety was not passed.")
                        print(f"[phase3]        Import error: {e}")
                        print(f"[phase3]        GMRobot safety modules are required "
                              f"for gated operation.")
                        print(f"[phase3]        Pass --no-safety explicitly to run "
                              f"without the safety gate.")
                        env.close()
                        simulation_app.close()
                        raise SystemExit(1) from e
                    print(f"[phase3] WARNING: Safety layer import failed: {e}")
                    print(f"[phase3]          Running without safety gating "
                          f"(--no-safety explicit).")
                ur10e_action = ur10e_proposed
                gate_decision = None
            except Exception as e:
                # Any runtime error in the safety pipeline is a critical fault.
                # Default to HOLD (fail-safe), not ungated pass-through (fail-open).
                import traceback as _tb
                print(f"[phase3] CRITICAL: Safety pipeline crashed at step {step}: {e}")
                _tb.print_exc()
                # Hold previous EE position; keep gripper command from proposed.
                ur10e_action = np.concatenate(
                    [prev_ur10e_action, ur10e_proposed[7:8]]
                )
                from types import SimpleNamespace
                gate_decision = SimpleNamespace(name="ERROR")
                # R5 C2 fix: bind gate_result so metrics/replan paths that
                # reference it after the try block don't NameError.
                gate_result = SimpleNamespace(
                    g_t=gate_decision,
                    reason="safety_pipeline_crash",
                    metadata={},
                )
                safety_state = SimpleNamespace(
                    step_index=step, sim_time=sim_time,
                    ee_pos=ur10e_ee, human_hand_pos=adapter.human_hand_pos,
                    human_hand_vel=np.zeros(3, dtype=np.float32),
                )
        else:
            ur10e_action = ur10e_proposed
            gate_decision = None

        prev_ur10e_action = ur10e_action[:7].copy()

        # ── 5b. Replan check (GMRobot L1WarnReplanTrigger + GeometryReplanV0) ──
        if replan_trigger is not None and replan_executor is not None and gate_decision is not None:
            try:
                transport_phase = ur10e.transport_phase
                req = replan_trigger.update(
                    safety_state, gate_result,
                    task_time_step=ur10e.time_step,
                    transport_phase=transport_phase,
                    policy=ur10e._policy,
                    safety_config=adapter._safety_config,
                    sim_step_index=step,
                )
                if req is not None:
                    # B1 prefer_replan: only accept replan while the proxy still
                    # occupies the corridor (TRANSIT).  Suppress stale TTC after
                    # PLACE/RESET or after the hand has already retreated.
                    if args_cli.replan and per_part is not None:
                        _phase_now = per_part.phase.value
                        _dist_now = float(adapter.closest_body_distance)
                        _warn_now = (
                            float(adapter._safety_config.safe_dist_warn)
                            if adapter._safety_config is not None
                            else 0.25
                        )
                        if (
                            vhand_retreated
                            or _phase_now != "transit"
                            or _dist_now > max(1.0, _warn_now * 4.0)
                        ):
                            if step % ival == 0:
                                print(
                                    f"  [replan] suppressed at step {step}: "
                                    f"phase={_phase_now} retreated={vhand_retreated} "
                                    f"dist={_dist_now:.3f}"
                                )
                            req = None
                if req is not None:
                    if _vlm_replan_strategy:
                        req.hint.detour_strategy = _vlm_replan_strategy
                        _vlm_replan_strategy = ""
                    if step % ival == 0 or metrics.replan_count == 0:
                        print(
                            f"  [replan] trigger fired at step {step}, "
                            f"rule={req.trigger_rule}, "
                            f"strategy={req.hint.detour_strategy or 'auto'}, "
                            f"dist_min={getattr(req, 'dist_min', getattr(req, 'dist_ee_human', '?'))}, "
                            f"dist_held={getattr(req, 'dist_min_held', None)}"
                        )
                    _replan_trigger_rule = req.trigger_rule
                    _replan_trigger_step = step
                    _replan_applied_this_step = False
                    _src = "scripted_virtual_hand" if dynamic_sweep is not None else _resolve_disturbance_source(args_cli, virtual_hand)
                    if _disturbance_attempt_id <= 0:
                        _disturbance_attempt_id = 1
                    _pending_replan_attr = ReplanAttribution.from_trigger(
                        attempt_id=_disturbance_attempt_id,
                        trigger_rule=req.trigger_rule,
                        trigger_source=_src,
                        trigger_step=step,
                    )
                    _meta_trig = getattr(gate_result, "metadata", {}) or {}
                    try:
                        _replan_dist_at_trigger = float(
                            _meta_trig.get("dist_min_for_gating", req.dist_min)
                        )
                    except (TypeError, ValueError):
                        _replan_dist_at_trigger = float(adapter.closest_body_distance)
                    _replan_hard_at_trigger = float(
                        adapter._safety_config.safe_dist_hard_stop
                    )
                    _replan_gate_at_trigger = gate_decision.name if gate_decision else ""
                    _replan_rule_at_trigger = str(req.trigger_rule or "")
                    if dynamic_sweep is not None and is_b2_proactive_trigger_rule(req.trigger_rule):
                        dynamic_sweep.note_first_intervention(step)
                    if _enforcement_mode == "shadow":
                        _write_event(
                            step,
                            "shadow_trigger",
                            _disturbance_attempt_id,
                            trigger_rule=req.trigger_rule,
                            trigger_source=_src,
                        )
                        _shadow_replan_would_this_step = True
                    else:
                        _replan_event_id += 1
                        _correlation_event_id = str(_replan_event_id)
                        _write_event(
                            step,
                            "trigger",
                            _disturbance_attempt_id,
                            event_id=_correlation_event_id,
                            trigger_rule=req.trigger_rule,
                            trigger_source=_src,
                        )
                        replan_executor.submit(req)
                        done = replan_executor.poll()
                        if done is not None:
                            if replan_executor.apply(done, ur10e._policy, runtime_state=replan_state):
                                replan_trigger.on_replan_applied(step, done.resume_time_step)
                                _last_replan_strategy = req.hint.detour_strategy or "auto"
                                _last_replan_raise = getattr(replan_state, 'cumulative_raise_m', 0.0)
                                _last_replan_lateral = replan_state.cumulative_lateral_m if replan_state else 0.0
                                if hasattr(ur10e._policy, "on_replan_splice_applied"):
                                    ur10e._policy.on_replan_splice_applied(done.resume_time_step)
                                metrics.replan_count += 1
                                replan_last_success = True
                                _replan_applied_this_step = True
                                _replan_applied_step = step
                                _applied_replan_attr = _pending_replan_attr
                                _pending_replan_attr = None
                                _write_event(
                                    step, "applied", _disturbance_attempt_id,
                                    event_id=_correlation_event_id,
                                    trigger_rule=_replan_trigger_rule,
                                    trigger_source=_src,
                                    applied_step=str(step),
                                )
                                if dynamic_sweep is not None:
                                    dynamic_sweep.on_replan_applied_active()
                                    _pending_dynamic_retreat_event_id = int(_correlation_event_id)
                                elif virtual_hand is not None:
                                    virtual_hand.on_replan()
                                    if _src in (
                                        "scripted_virtual_hand",
                                        "g1_attached_proxy",
                                    ) or per_part is not None:
                                        _already = (
                                            _disturbance_attempt_id in metrics._attempt_recoveries
                                            and metrics._attempt_recoveries[
                                                _disturbance_attempt_id
                                            ].retreat_step >= 0
                                        ) or vhand_retreated
                                        vhand_retreated = True
                                        if not _already and not retreat_event_this_step:
                                            retreat_event_this_step = True
                                            _write_event(
                                                step, "retreat", _disturbance_attempt_id,
                                                event_id=_correlation_event_id,
                                                trigger_rule="replan",
                                                trigger_source=_src,
                                                applied_step=str(step),
                                            )
                                            print(
                                                f"  [protocol] RETREAT: replan-applied "
                                                f"at step {step}, attempt={_disturbance_attempt_id}"
                                            )
                                        if per_part is not None and per_part.phase.value == "transit":
                                            metrics.note_transit_replan()
                                replan_last_failure_reason = ""
                                print(f"  [replan] detour APPLIED at step {step}, "
                                      f"resume_ts={done.resume_time_step} "
                                      f"cumul_lat={replan_state.cumulative_lateral_m:.3f}m "
                                      f"event_id={_correlation_event_id}")
                            else:
                                replan_last_success = False
                                _replan_applied_this_step = False
                                replan_last_failure_reason = "executor.apply returned False"
                                _write_event(
                                    step, "apply_failed", _disturbance_attempt_id,
                                    event_id=_correlation_event_id,
                                    trigger_rule=_replan_trigger_rule,
                                    trigger_source=_src,
                                    applied_step=str(step),
                                )
                                print(f"  [replan] apply FAILED at step {step}")
                        else:
                            replan_last_success = False
                            _replan_applied_this_step = False
                            replan_last_failure_reason = "executor.poll returned None"
                            _write_event(
                                step, "apply_cancelled", _disturbance_attempt_id,
                                event_id=_correlation_event_id,
                                trigger_rule=_replan_trigger_rule,
                                trigger_source=_src,
                            )
                            print(f"  [replan] apply CANCELLED (no result) at step {step}")
                else:
                    _replan_applied_this_step = False
            except Exception as e:
                import traceback
                print(f"[phase3] WARNING: replan trigger/apply failed at step {step}: {e}")
                traceback.print_exc()

        # ── 5c. Grasp-rewind check ────────────────────────────────────
        # Detect empty-grasp (夹空): when the UR10e closes its gripper on
        # an empty slot, rewind to re-pick the same part instead of
        # skipping to the next.  The GMRobot agent triggers this on STOP
        # during the grasp window, but in GMDisturb the part may be
        # knocked off *before* the UR10e arrives — no STOP occurs.
        # We always latch a grasp disturbance at the close_gripper stage,
        # then let maybe_rewind_for_failed_grasp check whether the part
        # is actually aligned with the EE.
        grasp_rewound = False
        stage = ur10e.stage_name
        # R7: protocol keeps G1 body back; 0.20m threshold avoids false triggers.
        # Without protocol, G1 wanders close — keep 0.50m for safety.
        _grasp_disturb_threshold = 0.20 if per_part is not None else 0.50
        # In scenario-hand mode the hand is a controlled test obstacle — its
        # proximity during close_gripper does NOT indicate a real grasp
        # disturbance.  Without this guard the scenario hand (always within
        # ~0.45 m of the EE even when retracted) triggers note_grasp_disturbance
        # on every pick, leading to rewind→exhaustion→carry_aborted→empty lift.
        if (scen_hand is None
                and stage.startswith("close_gripper_")
                and _body_distance_for_grasp < _grasp_disturb_threshold):
            ur10e._policy.note_grasp_disturbance()

        if hasattr(ur10e._policy, "maybe_rewind_for_failed_grasp"):
            part_pose = None
            part_idx = ur10e._policy.part_index_at_step(ur10e.time_step)
            if part_idx is not None:
                part_key = f"part_{part_idx + 1}_pos"
                part_pose = obs.get("ur10e_policy", {}).get(part_key)
                if part_pose is not None and hasattr(part_pose, "cpu"):
                    part_pose = part_pose.cpu().numpy()
            if ur10e._policy.maybe_rewind_for_failed_grasp(
                ur10e_ee, part_pose, ur10e.time_step,
            ):
                grasp_rewound = True
                if step % ival == 0:
                    print(f"  [grasp] EMPTY GRASP detected — rewinding to re-pick "
                          f"part {part_idx + 1 if part_idx is not None else '?'} "
                          f"(attempt {ur10e._policy._grasp_rewind_attempts})")
            # Consume any rewind event for logging.
            if hasattr(ur10e._policy, "consume_grasp_rewind_event"):
                event = ur10e._policy.consume_grasp_rewind_event()
                if event and step % ival == 0:
                    print(f"  [grasp] rewind_event={event}")

        # ── UR10e clock advance ────────────────────────────────────────
        # Only advance the pick-and-place stage clock when the *effective*
        # safety gate allows motion.  Under shadow, evaluated STOP/SLOW is
        # logged but effective is forced to ALLOW so the policy clock is
        # not frozen (B4 control-isolation).
        _evaluated_gate_name = (
            gate_decision.name if gate_decision is not None else None
        )
        _effective_gate_name = resolve_effective_gate_name(
            _evaluated_gate_name, _enforcement_mode
        )
        _replan_force_advance = bool(
            replan_state is not None
            and replan_state.allows_advance(ur10e.time_step)
            and ur10e.stage_name.startswith("replan_")
        )
        should_advance = policy_clock_should_advance(
            effective_gate_name=_effective_gate_name,
            grasp_rewound=grasp_rewound,
            replan_force_advance=_replan_force_advance,
        )
        if _enforcement_mode == "shadow":
            if _evaluated_gate_name in ("STOP", "SLOW_DOWN"):
                metrics.shadow_nonallow_evaluated_steps += 1
            if not np.allclose(
                ur10e_action.astype(np.float64),
                ur10e_proposed.astype(np.float64),
                rtol=0.0,
                atol=0.0,
                equal_nan=True,
            ):
                metrics.shadow_action_modified_steps += 1
            # Leakage: clock blocked by safety (not grasp rewind).
            if not should_advance and not grasp_rewound:
                metrics.shadow_clock_blocked_steps += 1
        if should_advance:
            ur10e.advance()

        # ── Virtual-hand retreat / re-deploy ────────────────────────────
        # Two independent triggers (either one causes retreat):
        #   A) Consecutive STOP timeout (vhand_retreat_steps) — catches deadlock
        #   B) Grasp rewind count (GRASP_MAX_REWIND_ATTEMPTS) — catches
        #      repeated re-grasp loops where STOP never fires
        #
        # Re-deploys to the container corridor centre after the UR10e
        # completes the current operation, testing replan on each transit
        # without blocking grasp/place indefinitely.
        if virtual_hand is not None and per_part is None:  # protocol manages retreat
            stage = ur10e.stage_name
            in_grasp = any(kw in stage for kw in ("close_gripper", "grasp_slot", "descend_to_slot"))
            in_place = any(kw in stage for kw in ("descend_to_box", "open_gripper"))
            # C10 fix (2026-07-13): lift_slot_ removed — the EE is still at container
            # height when lift begins, so re-deploying the virtual hand to the corridor
            # centre immediately triggers STOP (hand surface at distance 0).  Re-deploy
            # now waits until the EE has actually moved to a safe altitude above the
            # containers (move_above_box / move_above_slot).
            is_safe  = any(kw in stage for kw in ("lift_after_releasing",
                           "move_above_box_with_", "move_above_slot_"))

            # Stage transition → re-deploy.
            _key = stage[:35]
            if _key != vhand_last_stage_key:
                if vhand_retreated and is_safe:
                    vhand_retreated = False
                    virtual_hand._attractor = np.array([0.75, 0.0], dtype=np.float32)
                    virtual_hand._local_xy = (virtual_hand._attractor
                                              - virtual_hand._head_pos[:2])
                    d = float(np.linalg.norm(virtual_hand._local_xy))
                    if d > virtual_hand.radius:
                        virtual_hand._local_xy *= virtual_hand.radius / d
                    virtual_hand._vel = np.zeros(2, dtype=np.float32)
                    # R5 H8 fix: reset retreat counter so the hand stays at the
                    # block point instead of immediately re-entering the retreat
                    # branch on the next step() call (which checks _retreat_steps>0).
                    virtual_hand._retreat_steps = 0
                    # Recompute world position so the hand sphere is at the
                    # corridor block point immediately — no 1-step stale position.
                    virtual_hand._world_pos[:2] = (virtual_hand._head_pos[:2]
                                                   + virtual_hand._local_xy)
                    # R7 deadlock fix: prevent immediate re-retreat after re-deploy.
                    # Give the UR10e time (~6s) to complete its pick/place cycle.
                    vhand_reploy_cooldown = _VHAND_REPLOY_COOLDOWN
                    if step % ival == 0:
                        print(f"  [vhand] re-deployed to corridor after {stage} "
                              f"(cooldown={_VHAND_REPLOY_COOLDOWN} steps)")
                vhand_last_stage_key = _key

            # Decrement re-deploy cooldown each step.
            if vhand_reploy_cooldown > 0:
                vhand_reploy_cooldown -= 1

            # --- Trigger A: consecutive STOP timeout ---
            timeout_trigger = (
                _enforcement_mode != "shadow"
                and vhand_retreat_steps > 0
                and vhand_reploy_cooldown <= 0   # R7: don't retreat during cooldown
                and consecutive_gate_count >= vhand_retreat_steps
            )
            # --- Trigger B: repeated grasp rewind ---
            rewind_exhausted = (
                _enforcement_mode != "shadow"
                and grasp_rewound
                and hasattr(ur10e._policy, '_grasp_rewind_attempts')
                and ur10e._policy._grasp_rewind_attempts >= 2  # GRASP_MAX_REWIND_ATTEMPTS
            )

            if (not vhand_retreated
                    and (in_grasp or in_place)
                    and (timeout_trigger or rewind_exhausted)):
                vhand_retreated = True
                reason = f"timeout={consecutive_gate_count}steps" if timeout_trigger else "rewind_exhausted"
                if step % ival == 0:
                    print(f"  [vhand] RETREATED ({reason}) in {stage[:40]}")

        # ── 6. Mat event detection ────────────────────────────────────
        tactile_img = (
            obs["tactile"]["tactile"][0].cpu().numpy()
            if isinstance(obs["tactile"], dict)
            else obs["tactile"][0].cpu().numpy()
        )
        left_foot_pos = g1.data.body_link_pos_w[
            0, g1.find_bodies("left_ankle_roll_link")[0][0]
        ].cpu().numpy()
        right_foot_pos = g1.data.body_link_pos_w[
            0, g1.find_bodies("right_ankle_roll_link")[0][0]
        ].cpu().numpy()
        # Build part_positions dict for nearest-neighbor drop matching (M2 fix).
        part_positions: dict[str, np.ndarray] = {}
        for key, val in obs.get("ur10e_policy", {}).items():
            if key.startswith("part_") and key.endswith("_pos"):
                part_positions[key] = val[0].cpu().numpy() if hasattr(val, "cpu") else val
        mat_events = detector.detect(
            tactile_img, left_foot_pos, right_foot_pos,
            part_positions=part_positions if part_positions else None,
            ee_pos=ur10e_ee,
        )

        # ── 7. Apply arm motion (BEFORE env.step — WalkJointAction preserves non-leg joints) ──
        # Tilt check: if G1 is tipping, retract arms to avoid making it worse.
        arm_motion = disturb.arm_motion
        arm_t = disturb.step_in_phase * 0.02  # seconds into current phase → ramp-up
        g1_quat = g1.data.root_quat_w[0].cpu().numpy()
        g1_tilt = _quat_tilt_angle(g1_quat)
        _g1_root_now = g1.data.root_pos_w[0].cpu().numpy()
        metrics.g1_root_x = float(_g1_root_now[0])
        metrics.g1_root_y = float(_g1_root_now[1])
        metrics.g1_root_z = float(_g1_root_now[2])
        metrics.g1_tilt_rad = float(g1_tilt)
        if g1_tilt > metrics.g1_tilt_rad_max:
            metrics.g1_tilt_rad_max = float(g1_tilt)
        if g1_tilt > cfg.safety.tilt_threshold_rad:
            if not tilt_warned:
                print(f"\n[phase3] G1 tilting ({g1_tilt:.2f} rad) — retracting arms for stability")
                tilt_warned = True
            arm_motion = "none"
            arm_t = 0.0
        else:
            tilt_warned = False

        arm_offsets = arm_ctrl.get_action(arm_t, arm_motion)
        arm_ctrl.apply(g1, arm_offsets)

        # ── 8. Build combined action ──────────────────────────────────
        action = torch.zeros(1, 20, device=device)
        action[0, :12] = torch.from_numpy(g1_leg_action).to(device)
        action[0, 12:19] = torch.from_numpy(
            ur10e_action[:7].astype(np.float32)
        ).to(device)
        action[0, 19] = torch.tensor(
            ur10e_action[7], dtype=torch.float32, device=device
        )

        # ── 9. Step simulation ────────────────────────────────────────
        obs, reward, terminated, truncated, info = env.step(action)

        # ── 9a. Optional scene RGB + body-pose capture (0-POST) ────────
        _do_cam = False
        if args_cli.save_camera:
            if _cam_steps:
                _do_cam = step in _cam_steps
            else:
                _do_cam = (step % ival == 0)
        if _do_cam:
            scene_rgb = obs.get("ur10e_camera", {}).get("scene_rgb")
            if scene_rgb is not None:
                from PIL import Image as _PILImage

                _arr = scene_rgb[0].detach().cpu().numpy()
                if _arr.dtype != np.uint8:
                    _arr = np.clip(_arr, 0, 255).astype(np.uint8)
                if _arr.shape[-1] > 3:
                    _arr = _arr[..., :3]
                _frame_path = os.path.join(_cam_out, f"frame_{step:06d}_env0.png")
                _PILImage.fromarray(_arr).save(_frame_path)
                print(f"  [camera] saved {_frame_path}")
            if _body_pose_fh is not None:
                from safety_adapter import TRACKED_BODIES as _TRACKED

                _bodies = {}
                for _bn in _TRACKED:
                    try:
                        _bi = g1.find_bodies(_bn)[0][0]
                        _bp = g1.data.body_link_pos_w[0, _bi].cpu().numpy()
                        _bodies[_bn] = [float(v) for v in _bp]
                    except Exception:
                        continue
                _root_now = g1.data.root_pos_w[0].cpu().numpy()
                _ee_now = ur10e_robot.data.body_link_pos_w[0, _ee_body_idx].cpu().numpy() + _ee_offset
                _rec = {
                    "step": int(step),
                    "phase": str(disturb.scenario_name),
                    "g1_root": [float(v) for v in _root_now],
                    "ur10e_ee": [float(v) for v in _ee_now],
                    "g1_bodies": _bodies,
                    "camera_pos": list(_cam_pos),
                    "motion_source_label": args_cli.motion_source_label or "",
                    "gate": gate_decision.name if gate_decision is not None else "NONE",
                }
                # Prefer live closest-body dist from adapter when available.
                if adapter is not None:
                    _rec["dist_min_g1_body"] = float(adapter.closest_body_distance)
                    _rec["closest_g1_body"] = str(adapter.closest_body_name or "")
                _body_pose_fh.write(json.dumps(_rec) + "\n")
                _body_pose_fh.flush()

        # ── 9. Metrics ─────────────────────────────────────────────────
        g1_ur10e_dist = float(np.linalg.norm(g1_root[:2] - ur10e_ee[:2]))
        adapter_surface_dist = adapter.closest_body_distance if adapter is not None else float("inf")
        # Gate attribution: only attribute when trigger is distance/geometry-related.
        _gate_reason = getattr(gate_result, 'reason', '') if gate_decision is not None else ''
        _gate_is_distance_related = (
            gate_decision is not None
            and gate_decision.name in ("STOP", "SLOW_DOWN")
            and any(kw in _gate_reason for kw in ("tier0", "warn", "ttc", "static", "dynamic"))
        )
        # TRANSIT telemetry + SLOW streak events (observation only).
        _in_transit_now = (
            per_part is not None and per_part.phase.value == "transit"
        )
        if _in_transit_now:
            _is_slow = (
                gate_decision is not None and gate_decision.name == "SLOW_DOWN"
            )
            _proxy_d = float(
                adapter.closest_body_distance
                if adapter is not None else float("inf")
            )
            _streak_before = metrics._transit_slow_streak
            _ended = metrics.note_transit_observation(
                proxy_distance=_proxy_d, is_slow=_is_slow,
            )
            if _is_slow and _streak_before == 0:
                _write_event(
                    step, "slow_streak_start", _disturbance_attempt_id,
                    trigger_rule="slow",
                    trigger_source=_resolve_disturbance_source(args_cli, virtual_hand),
                    slow_streak_length=metrics._transit_slow_streak,
                )
            if _ended > 0:
                _write_event(
                    step, "slow_streak_end", _disturbance_attempt_id,
                    trigger_rule="slow",
                    trigger_source=_resolve_disturbance_source(args_cli, virtual_hand),
                    slow_streak_length=_ended,
                )
        elif _in_transit_prev:
            _ended = metrics.end_transit_slow_streak()
            if _ended > 0:
                _write_event(
                    step, "slow_streak_end", _disturbance_attempt_id,
                    trigger_rule="slow",
                    trigger_source=_resolve_disturbance_source(args_cli, virtual_hand),
                    slow_streak_length=_ended,
                )
        _in_transit_prev = _in_transit_now

        if _enforcement_mode == "shadow":
            if _replan_applied_this_step:
                metrics.shadow_replan_applied_count += 1
            if retreat_event_this_step:
                metrics.shadow_retreat_count += 1

        metrics.record_step(
            g1_root_z=float(g1_root[2]),
            g1_ur10e_distance=g1_ur10e_dist,
            surface_distance=adapter_surface_dist,
            mat_events=mat_events,
            gate_decision=gate_decision.name if gate_decision is not None else None,
            gate_trigger=_gate_reason,
            gate_distance=adapter.closest_body_distance if adapter is not None else float("inf"),
            closest_body=adapter.closest_body_name if adapter is not None else '',
            disturbance_active=disturbance_active,
            consecutive_stop_count=consecutive_gate_count,
            replan_success=True if (args_cli.replan and _replan_applied_this_step) else (None if not args_cli.replan else False),
            replan_failure_reason=replan_last_failure_reason,
            replan_event_id=_replan_event_id if _replan_applied_this_step else 0,
            replan_attribution=_applied_replan_attr if _replan_applied_this_step else None,
            vlm_action=last_vlm_decision.get("action", ""),
            vlm_latency_ms=last_vlm_decision.get("latency_ms", 0.0),
            vlm_reason=last_vlm_decision.get("reason", ""),
            disturbance_source=(
                "scripted_virtual_hand" if dynamic_sweep is not None
                else _resolve_disturbance_source(args_cli, virtual_hand)
            ),
            disturbance_scenario=args_cli.disturbance_scenario_label or args_cli.scenario or "wander",
            disturbance_attempt_id=_disturbance_attempt_id,
            gate_trigger_source=(
                ("scripted_virtual_hand" if dynamic_sweep is not None else _resolve_disturbance_source(args_cli, virtual_hand))
                if (_gate_is_distance_related and disturbance_active and _enforcement_mode != "shadow")
                else ""
            ),
            replan_trigger_source=(
                getattr(_applied_replan_attr, "trigger_source", "")
                if _replan_applied_this_step and _applied_replan_attr is not None
                else ""
            ),
            closest_g1_body_name=_g1_closest_body_name,
            dist_min_g1_body=_g1_closest_body_dist,
            dist_min_proxy=adapter_surface_dist if virtual_hand is not None else float("inf"),
            vhand_retreated=vhand_retreated,
            retreat_event_this_step=retreat_event_this_step,
            redeploy_event_this_step=redeploy_event_this_step,
            policy_step=ur10e.time_step,
            parts_placed_now=ur10e.parts_placed,
            enforcement_mode=_enforcement_mode,
            shadow_gate_decision=_shadow_gate_decision_this_step or None,
            shadow_replan_would_trigger=_shadow_replan_would_this_step,
            replan_trigger_rule=_replan_rule_at_trigger,
            dist_min_at_replan_trigger=_replan_dist_at_trigger,
            safe_dist_hard_stop_at_trigger=_replan_hard_at_trigger,
            gate_decision_at_trigger=_replan_gate_at_trigger,
        )
        _write_dynamic_audit(step)
        metrics.stuck_count = disturb.stuck_count

        # ── 10. Progress ───────────────────────────────────────────────
        if step % ival == 0:
            # Per-step tracking CSV — EE pos, hand pos, gate state, parts.
            _hand = adapter.human_hand_pos
            _gate_name = gate_decision.name if gate_decision is not None else "NONE"
            _gate_reason = getattr(gate_result, 'reason', '') if gate_decision is not None else ''
            _sphere = virtual_hand.position if virtual_hand is not None else np.zeros(3)
            _proto_phase = per_part.phase.value if per_part is not None else "none"
            _proto_part = per_part.part_index + 1 if per_part is not None else 0
            # Part Z tracking: min Z across all parts, count below table.
            _min_part_z = 99.0
            _parts_below = 0
            for _pk, _pv in obs.get("ur10e_policy", {}).items():
                if _pk.startswith("part_") and _pk.endswith("_pos"):
                    _pz = float(_pv[0, 2].cpu().numpy()) if hasattr(_pv, "cpu") else float(_pv[2])
                    _min_part_z = min(_min_part_z, _pz)
                    if _pz < -0.5:
                        _parts_below += 1
            if _min_part_z == 99.0:
                _min_part_z = 0.0
            # Grasp state.
            _rewind_count = getattr(ur10e._policy, '_grasp_rewind_attempts', 0)
            _carry_aborted = int(getattr(ur10e._policy, '_grasp_carry_aborted', False))
            _attr = (
                virtual_hand._attractor if virtual_hand is not None
                else np.zeros(2, dtype=np.float32)
            )
            _head_telem = (
                virtual_hand.head_position if virtual_hand is not None
                else np.zeros(3, dtype=np.float32)
            )
            _reach_clamped = (
                int(virtual_hand.last_reach_clamped) if virtual_hand is not None else 0
            )
            _slow_streak_len = (
                int(metrics._transit_slow_streak) if _in_transit_now else 0
            )
            _gate_audit = _gate_distance_audit()
            _track_fh.write(
                f"{step},{ur10e_ee[0]:.4f},{ur10e_ee[1]:.4f},{ur10e_ee[2]:.4f},"
                f"{_hand[0]:.4f},{_hand[1]:.4f},{_hand[2]:.4f},"
                f"{adapter.closest_body_distance:.4f},"
                f"{_body_distance_for_grasp:.4f},"
                f"{_gate_name},{_gate_reason},"
                f"{ur10e.stage_name},{ur10e.parts_placed},{metrics.replan_count},"
                f"{_last_replan_strategy},{_last_replan_raise:.4f},{_last_replan_lateral:.4f},"
                f"{_rewind_count},{_carry_aborted},"
                f"{_min_part_z:.4f},{_parts_below},"
                f"{int(_dl_escape_tier)},{int(vhand_retreated) if virtual_hand is not None else 0},"
                f"{int(not vhand_retreated and virtual_hand is not None)},"
                f"{_sphere[0]:.4f},{_sphere[1]:.4f},{_sphere[2]:.4f},"
                f"{_proto_phase},{_proto_part},"
                f"{_resolve_disturbance_source(args_cli, virtual_hand)},"
                f"{args_cli.disturbance_scenario_label or args_cli.scenario or 'wander'},{_disturbance_attempt_id},"
                f"{_resolve_disturbance_source(args_cli, virtual_hand) if _gate_name in ('STOP','SLOW_DOWN') and _gate_is_distance_related and disturbance_active else ''},"
                f"{_replan_trigger_rule if step == _replan_trigger_step else ''},"
                f"{_replan_trigger_step if step == _replan_trigger_step else ''},"
                f"{_replan_event_id if step == _replan_applied_step else ''},"
                f"{_replan_applied_step if step == _replan_applied_step else ''},"
                f"{_g1_closest_body_name},"
                f"{_g1_closest_body_dist:.4f},"
                f"{adapter_surface_dist if virtual_hand is not None else float('inf'):.4f},"
                f"{_safety_sc.safe_dist_warn if _safety_sc is not None else 0.0:.4f},"
                f"{_gate_audit['dist_min_for_gating']},"
                f"{_gate_audit['dist_min_envelope']},"
                f"{_gate_audit['dist_min_held']},"
                f"{_gate_audit['safe_dist_hard_stop_active']},"
                f"{_gate_audit['safe_dist_warn_active']},"
                f"{_sphere[0]:.4f},{_sphere[1]:.4f},{_sphere[2]:.4f},"
                f"{_hand[0]:.4f},{_hand[1]:.4f},{_hand[2]:.4f},"
                f"{_attr[0]:.4f},{_attr[1]:.4f},0.0000,"
                f"{_head_telem[0]:.4f},{_head_telem[1]:.4f},{_head_telem[2]:.4f},"
                f"{_reach_clamped},{_slow_streak_len},"
                f"{float(virtual_hand.reach_radius) if virtual_hand is not None else 0.0:.4f},"
                f"{float(virtual_hand.proxy_radius) if virtual_hand is not None else 0.0:.4f},"
                f"{virtual_hand.head_to_attractor_distance() if virtual_hand is not None else 0.0:.4f},"
                f"{virtual_hand.reach_margin() if virtual_hand is not None else 0.0:.4f},"
                f"{float(_g1_root_now[0]):.4f},{float(_g1_root_now[1]):.4f},{float(_g1_root_now[2]):.4f},"
                f"{float(g1_tilt):.4f},"
                f"{'' if metrics.g1_spawn_requested_x != metrics.g1_spawn_requested_x else f'{metrics.g1_spawn_requested_x:.4f}'},"
                f"{'' if metrics.g1_spawn_requested_y != metrics.g1_spawn_requested_y else f'{metrics.g1_spawn_requested_y:.4f}'},"
                f"{'' if metrics.g1_spawn_requested_yaw != metrics.g1_spawn_requested_yaw else f'{metrics.g1_spawn_requested_yaw:.4f}'},"
                f"{'' if metrics.spawn_pose_error != metrics.spawn_pose_error else f'{metrics.spawn_pose_error:.4f}'}\n"
            )
            _track_fh.flush()
            # §6.1: replan trigger_step is one-shot — reset after progress write.
            if step == _replan_trigger_step:
                _replan_trigger_step = -1

            mode_str = disturb.mode.value.upper() if disturb.mode else "?"
            gate_str = gate_decision.name if gate_decision is not None else "N/A"
            stuck_flag = " STUCK!" if disturb.is_stuck else ""
            adapter_dist = adapter.closest_body_distance
            hand = adapter.human_hand_pos
            head_pos_log = g1.data.body_link_pos_w[0, _head_body_idx].cpu().numpy()
            head_pos_log[2] += _HEAD_Z_OFFSET
            print(
                f"  step {step:5d}  t={ur10e.time_step:5d}  "
                f"{disturb.scenario_name:8s}  "
                f"mode={mode_str:10s}{stuck_flag}  "
                f"d_root={g1_ur10e_dist:.2f}  d_adp={adapter_dist:.2f}  "
                f"head=({head_pos_log[0]:.2f},{head_pos_log[1]:.2f},{head_pos_log[2]:.2f})  "
                f"hand=({hand[0]:.2f},{hand[1]:.2f},{hand[2]:.2f})  "
                f"v=({disturb_cmd[0]:+.2f},{disturb_cmd[1]:+.2f})  "
                f"gate={gate_str:9s}  "
                f"{' VLM=' + vlm_last_action if vlm_client else ''}  "
                f"{ur10e.stage_name:40s}"
            )

        # ── 11. Termination ────────────────────────────────────────────
        metrics.policy_steps = ur10e.time_step

        if ur10e.success:
            print(f"\n[phase3] ALL PARTS PLACED at step {step}")
            break
        if terminated or truncated:
            print(f"\n[phase3] Episode ended at step {step}")
            break
        if g1_root[2] < cfg.safety.collapse_z:
            print(f"\n[phase3] G1 collapsed at step {step}")
            metrics.g1_fell = True
            break
    else:
        print(f"\n[phase3] Max steps ({max_steps})")

    # ── Finalise ───────────────────────────────────────────────────────
    metrics.policy_steps = ur10e.time_step
    # P0-1: single snapshot helper — controller success may report index 19
    # while success=True (20/20).  Same logic must be used everywhere.
    metrics.parts_placed = snapshot_parts_placed(
        success=ur10e.success,
        parts_placed=ur10e.parts_placed,
        total_parts=ur10e.total_parts,
    )
    writer.write(metrics)
    print(
        f"[phase3] Metrics written to {args_cli.output_csv}"
    )
    print(
        f"[phase3] time_step={ur10e.time_step}  success={ur10e.success}  "
        f"parts={metrics.parts_placed}/{ur10e.total_parts}  "
        f"task_completed={metrics.parts_placed >= ur10e.total_parts}"
    )
    print(
        f"[phase3] Safety: STOP={metrics.tier0_stop_count}  "
        f"SLOW={metrics.slowdown_count}  REPLAN={metrics.replan_count}  "
        f"STUCK={metrics.stuck_count}"
    )
    print(
        f"[phase3] Proximity: min={metrics.min_g1_ur10e_distance_m:.3f}m  "
        f"mean={metrics.mean_g1_ur10e_distance_m:.3f}m"
    )

    _track_fh.close()
    _event_fh.close()
    if _body_pose_fh is not None:
        _body_pose_fh.close()
    if _dynamic_audit_fh is not None:
        _dynamic_audit_fh.close()
    if _trajectory_fh is not None:
        _trajectory_fh.close()
    _cleanup_sim(env, simulation_app)


# R7 H3 fix: register atexit handler so env.close() + simulation_app.close()
# always run even if the main loop crashes.  Without this, GPU VRAM, PhysX
# contexts, and Omniverse Kit child processes leak on any unhandled exception.
_SIM_CLEANUP_DONE: bool = False

def _cleanup_sim(env, simulation_app) -> None:
    """Idempotent simulation cleanup — safe to call multiple times."""
    global _SIM_CLEANUP_DONE
    if _SIM_CLEANUP_DONE:
        return
    _SIM_CLEANUP_DONE = True
    try:
        env.close()
    except Exception:
        pass
    try:
        simulation_app.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
