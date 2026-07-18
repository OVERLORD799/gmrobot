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
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

# Ensure project root is on sys.path before importing local modules.
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

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
from mat_event_detector import MatEventDetector
from g1_disturbance_controller import (
    G1DisturbanceController,
    DisturbanceMode,
    SCENARIOS,
)
from test_metrics import EpisodeMetrics, MetricsWriter
from per_part_state import PerPartTester, Phase
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


def main():
    from isaaclab_tasks.utils import parse_env_cfg

    task_id = "G1-UR10e-Disturbance-v0"
    env_cfg = parse_env_cfg(task_id, num_envs=1)
    env = gym.make(task_id, cfg=env_cfg)
    obs, info = env.reset()
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
        radius=args_cli.virtual_hand if args_cli.virtual_hand else cfg.virtual_hand.default_radius,
        speed=args_cli.virtual_hand_speed,
        height_mode=cfg.virtual_hand.height_mode,
        pursuit_mode=args_cli.replan,
        retreat_steps=max(0, args_cli.vhand_retreat),
    ) if args_cli.virtual_hand is not None else None
    # Warmup: let hand start blocking immediately — dynamic block point
    # (min(0.75, head_x + radius)) ensures hand only reaches as far as G1 allows.
    if virtual_hand is not None and args_cli.replan:
        virtual_hand._retreat_steps = 0

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
        # Read user_commands from the UR10e policy (lazy-init after reset).
        per_part = PerPartTester(ur10e._policy.user_commands)
        print(f"[phase3] Per-part protocol enabled: {per_part.parts_total} parts, "
              f"4-phase cycle (Pick→Transit→Place→Reset)")
        # Protocol: G1 body stays back, hand reaches containers.
        # G1 at x∈[-0.1,0.2] keeps body ≥0.65m from table edge (x=0.15).
        # Hand radius 0.45 from x=0.2 reaches x=0.65, surface at x=1.10
        # covers containers at x=0.75.
        _ws_x = (0.0, 0.15)   # G1 stays near table edge, hand can reach containers
        _ws_y = (-0.5, 0.5)
        _vx_b = 0.0
        _vy_b = 0.0
        # Increase hand radius — protocol controls it per-phase.
        if args_cli.virtual_hand <= 0.45:
            virtual_hand.radius = 0.45  # TRANSIT default; PICK/PLACE override to 0.12
            print(f"[phase3] Protocol: G1 workspace x∈[0.0,0.15], "
                  f"hand radius per-phase (TRANSIT=0.30, PICK/PLACE=0.08)")
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
        seed=42,
        control_dt=cfg.safety.control_dt,
        vy_scale=cfg.disturbance.vy_scale,  # F1 fix: lateral exploration
        vy_bias=_vy_b,
        vx_bias=_vx_b,
    )
    metrics = EpisodeMetrics(episode_id=0)
    writer = MetricsWriter(args_cli.output_csv)

    # ── Per-step tracking CSV (R7: for replan strategy comparison) ────────
    _track_path = args_cli.output_csv.replace(".csv", "_steps.csv")
    _track_fh = open(_track_path, "w")
    _track_fh.write("step,ee_x,ee_y,ee_z,hand_x,hand_y,hand_z,hand_dist_surface,"
                    "g1_body_dist,gate,gate_trigger,stage,parts_placed,replan_count,"
                    "replan_strategy,replan_raise_m,replan_lateral_m,"
                    "grasp_rewinds,carry_aborted,"
                    "min_part_z,parts_below_table,"
                    "deadlock_tier,vhand_retreated,vhand_block_active,"
                    "sphere_x,sphere_y,sphere_z,protocol_phase,protocol_part\n")

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
            # R7 aggressive thresholds: simulation has no real human — shrink
            # STOP zone so UR10e spends more time in SLOW_DOWN (replan) vs STOP (freeze).
            sc.safe_dist_hard_stop = 0.05    # was 0.13 — only STOP when nearly touching
            sc.safe_dist_warn = 0.25         # was 0.16 — 0.20m warn band for replan accumulation
            sc.ttc.ttc_threshold = 0.2       # was 0.5s — only STOP on very fast approaches
            sc.ttc.ttc_warn_threshold = 0.8  # was 1.5s — warn earlier for replan
            print(f"[phase3] Aggressive safety thresholds: "
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
                )
            )
            print("[phase3] Motion replan enabled (GMRobot L1WarnReplanTrigger + GeometryReplanV0)")
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
    last_vlm_decision: dict = {}          # H-group — most recent VLM output
    replan_last_success: bool = False     # F07
    replan_last_failure_reason: str = ""  # F08
    _vlm_replan_strategy: str = ""        # R7: VLM-coordinated replan hint
    _last_replan_strategy: str = ""       # R7: for tracking CSV
    _last_replan_raise: float = 0.0
    _last_replan_lateral: float = 0.0

    # ── Virtual-hand retreat/re-deploy ──────────────────────────────────
    vhand_retreated: bool = False              # hand currently pulled back
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
    for step in range(max_steps):
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
            # ── Per-part protocol: phase-driven attractor + radius ─────
            if per_part is not None:
                stage = ur10e.stage_name
                per_part.update(stage, ur10e_ee, head_pos, ur10e.is_grasping)
                attr = per_part.attractor_xy
                if attr is not None:
                    virtual_hand._attractor = attr.astype(np.float32)
                else:
                    # RESET phase — retreat hand to G1 head.
                    virtual_hand._attractor = head_pos[:2].copy()
                # Phase-dependent radius: small during PICK/PLACE (hand near
                # EE must not engulf it), medium during TRANSIT (block path).
                if per_part.phase == Phase.TRANSIT:
                    virtual_hand.radius = 0.30   # R7: from G1 at x∈[0,0.15], hand reaches x=0.30-0.45
                    # Attractor: fixed offset from G1 head toward containers.
                    # head_x+0.12 keeps hand surface in warn band (0.13-0.40m)
                    # regardless of G1's exact position.
                    virtual_hand._attractor = np.array(
                        [head_pos[0] + 0.12, virtual_hand._attractor[1]], dtype=np.float32)
                elif per_part.phase in (Phase.PICK, Phase.PLACE):
                    virtual_hand.radius = 0.08   # minimal — hand present but can't engulf EE
                # RESET: keep current radius (hand is retreated anyway)
                # G1 positioning: let the disturbance controller's boundary
                # steer handle workspace limits naturally.  The workspace
                # x∈[-0.1,0.2] already keeps G1 at a safe distance.
                # R7: hand velocity for TTC.  Zero during static phases
                # (approach/hold/retreat/home) so SLOW_DOWN accumulates for
                # replan without TTC jumping to STOP.  Inject real velocity
                # only during track_ee/strike for speed-aware rule testing.
                _zero_vel = True
                if scen_hand is not None:
                    _act = scen_hand._lookup(scen_hand._sim_time)[0]
                    _zero_vel = _act in ("approach", "hold", "retreat", "home")
                if hasattr(virtual_hand, '_prev_world_pos') and not _zero_vel:
                    adapter.human_hand_vel = (
                        (virtual_hand._world_pos - virtual_hand._prev_world_pos)
                        / cfg.safety.control_dt
                    ).astype(np.float32)
                else:
                    adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                virtual_hand._prev_world_pos = virtual_hand._world_pos.copy()
                # Log phase transitions.
                if step % ival == 0:
                    p = per_part
                    print(f"  [protocol] part={p.part_index+1}/{p.parts_total} "
                          f"phase={p.phase.value:7s} "
                          f"step_in_phase={p.state.step_in_phase} "
                          f"attr={attr}")
            # Attractor with optional lag.
            if args_cli.vhand_lag > 0:
                if vhand_smoothed is None:
                    vhand_smoothed = ur10e_ee[:2].copy()
                alpha = 1.0 - args_cli.vhand_lag
                vhand_smoothed = (alpha * ur10e_ee[:2] +
                                  (1.0 - alpha) * vhand_smoothed)
                virtual_hand._attractor = vhand_smoothed.copy()
            else:
                virtual_hand._attractor = ur10e_ee[:2].copy()
            # R7 deadlock hysteresis: during cooldown, pull attractor away from EE.
            if _dl_hysteresis_steps > 0:
                to_ee_xy = virtual_hand._attractor - ur10e_ee[:2]
                d_xy = float(np.linalg.norm(to_ee_xy))
                if d_xy < _DL_HYSTERESIS_DIST:
                    if d_xy > 1e-6:
                        virtual_hand._attractor = ur10e_ee[:2] + (to_ee_xy / d_xy) * _DL_HYSTERESIS_DIST
                    else:
                        virtual_hand._attractor = ur10e_ee[:2] + np.array([_DL_HYSTERESIS_DIST, 0.0])
            virtual_hand.step(cfg.safety.control_dt, head_pos, ee_z=ur10e_ee[2])

            # ── Retreat override (BEFORE safety gate) ──
            # When retreated, the safety gate must see a safe hand position
            # on the very next step — not one step later.  We override
            # BEFORE evaluate_safety so there is zero delay.
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
                # R6 C1 fix: project hand position to the sphere SURFACE so
                # the safety gate sees surface-to-surface distance, not
                # centre-to-centre.  A 0.45 m radius sphere has its surface
                # 0.45 m closer to the EE than its centre — without this
                # projection, SLOW_DOWN only fires after the EE has already
                # penetrated 0.23 m into the sphere.
                sphere_center = virtual_hand.position
                to_ee = ur10e_ee - sphere_center
                center_dist = float(np.linalg.norm(to_ee))
                if center_dist > 1e-6:
                    surface_point = sphere_center + (to_ee / center_dist) * virtual_hand.radius
                else:
                    surface_point = sphere_center
                adapter.human_hand_pos = surface_point
                adapter.human_hand_vel = np.zeros(3, dtype=np.float32)
                adapter.closest_body_distance = max(
                    0.0,
                    center_dist - virtual_hand.radius - adapter._ee_radius,
                )
                adapter.closest_body_name = "virtual_hand"

            # ── Protocol RESET: instant hand removal at safety-gate level ──
            # The virtual hand sphere still drifts toward G1's head, but the
            # safety gate sees the hand at a safe distance immediately.  This
            # breaks the STOP deadlock without waiting for the sphere to move.
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
        if virtual_hand is not None and gate_decision is not None:
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
                            - virtual_hand.radius - adapter._ee_radius)
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
                            - virtual_hand.radius - adapter._ee_radius)
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
                                - virtual_hand.radius - adapter._ee_radius)

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
                    # R7 H5 fix: pass dist_min_held to enable held-critical STOP
                    # and held-aware replan trigger paths in the RuleEngine.
                    # Uses EE-to-body surface distance as a conservative proxy
                    # (the held object extends beyond the EE, so the true
                    # held-object-to-body distance is ≥ this value).
                    # TODO: compute true held-part FK position for accurate
                    # knock-off detection during carry (needs part body index).
                    dist_min_held=(adapter.closest_body_distance
                                   if ur10e.is_grasping else None),
                )
                # Gate the UR10e EE action (dims 0-6)
                ur10e_gated_ee = adapter.apply_safety_gate(
                    gate_result,
                    ur10e_proposed[:7],
                    prev_ur10e_action,
                )
                ur10e_action = np.concatenate(
                    [ur10e_gated_ee, ur10e_proposed[7:8]]
                )

                # Track safety interventions
                gate_decision = gate_result.g_t
                if gate_decision.name == "STOP":
                    metrics.tier0_stop_count += 1
                    consecutive_gate_count += 1   # F09
                elif gate_decision.name == "SLOW_DOWN":
                    metrics.slowdown_count += 1
                    consecutive_gate_count += 1   # F09 — livelock includes sustained SLOW
                else:
                    consecutive_gate_count = max(0, consecutive_gate_count - 2)  # F09 decay

                # D-group: disturbance effect causal inference
                # Record when G1 first enters MODERATE/CAUTIOUS (disturbance starts).
                if disturb.mode in (DisturbanceMode.MODERATE, DisturbanceMode.CAUTIOUS):
                    if not disturbance_active:
                        disturbance_active = True
                        disturbance_start_step = step
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
                    # R7: inject VLM-coordinated strategy into replan hint.
                    if _vlm_replan_strategy:
                        req.hint.detour_strategy = _vlm_replan_strategy
                        _vlm_replan_strategy = ""  # consumed
                    if step % ival == 0 or metrics.replan_count == 0:
                        print(f"  [replan] trigger fired at step {step}, rule={req.trigger_rule}, "
                              f"strategy={req.hint.detour_strategy or 'auto'}, "
                              f"dist={getattr(req, 'dist_ee_human', '?')}")
                    replan_executor.submit(req)
                    done = replan_executor.poll()
                    if done is not None:
                        if replan_executor.apply(done, ur10e._policy, runtime_state=replan_state):
                            replan_trigger.on_replan_applied(step, done.resume_time_step)
                            # R7: capture replan params for tracking CSV.
                            _last_replan_strategy = req.hint.detour_strategy or "auto"
                            _last_replan_raise = getattr(replan_state, 'cumulative_raise_m', 0.0)
                            _last_replan_lateral = replan_state.cumulative_lateral_m if replan_state else 0.0
                            # apply_result() is called inside apply() now (cumulative tracking)
                            if hasattr(ur10e._policy, "on_replan_splice_applied"):
                                ur10e._policy.on_replan_splice_applied(done.resume_time_step)
                            metrics.replan_count += 1
                            replan_last_success = True
                            # Signal virtual hand to retreat — block-retreat-reblock cycle
                            if virtual_hand is not None:
                                virtual_hand.on_replan()
                            replan_last_failure_reason = ""
                            print(f"  [replan] detour APPLIED at step {step}, "
                                  f"resume_ts={done.resume_time_step} "
                                  f"cumul_lat={replan_state.cumulative_lateral_m:.3f}m")
                        else:
                            replan_last_success = False
                            replan_last_failure_reason = "executor.apply returned False"
                            print(f"  [replan] apply FAILED at step {step}")
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
        # Only advance the pick-and-place stage clock when the safety gate
        # allows motion.  During STOP the EE is held in place — advancing
        # the clock anyway would cause stage transitions (e.g. close_gripper)
        # to fire before the EE reaches the target pose.
        should_advance = (gate_decision is None)  # no safety → always advance
        if gate_decision is not None:
            if gate_decision.name == "ALLOW":
                should_advance = True
            elif (replan_state is not None
                  and replan_state.allows_advance(ur10e.time_step)
                  and ur10e.stage_name.startswith("replan_")):
                # Only force advance through actual detour waypoints.
                # Once the clock reaches the suffix (move_above_slot etc.),
                # normal gate rules resume — preventing the clock from
                # racing through close_gripper while the EE is still
                # mid-detour (rubber-band → empty grasp).
                should_advance = True
            # grasp rewind already modified time_step — don't double-advance
            if grasp_rewound:
                should_advance = False
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
                vhand_retreat_steps > 0
                and vhand_reploy_cooldown <= 0   # R7: don't retreat during cooldown
                and consecutive_gate_count >= vhand_retreat_steps
            )
            # --- Trigger B: repeated grasp rewind ---
            rewind_exhausted = (
                grasp_rewound
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
        )

        # ── 7. Apply arm motion (BEFORE env.step — WalkJointAction preserves non-leg joints) ──
        # Tilt check: if G1 is tipping, retract arms to avoid making it worse.
        arm_motion = disturb.arm_motion
        arm_t = disturb.step_in_phase * 0.02  # seconds into current phase → ramp-up
        g1_quat = g1.data.root_quat_w[0].cpu().numpy()
        g1_tilt = _quat_tilt_angle(g1_quat)
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

        # ── 9. Metrics ─────────────────────────────────────────────────
        g1_ur10e_dist = float(np.linalg.norm(g1_root[:2] - ur10e_ee[:2]))
        adapter_surface_dist = adapter.closest_body_distance if adapter is not None else float("inf")
        metrics.record_step(
            g1_root_z=float(g1_root[2]),
            g1_ur10e_distance=g1_ur10e_dist,
            surface_distance=adapter_surface_dist,
            mat_events=mat_events,
            gate_decision=gate_decision.name if gate_decision is not None else None,
            gate_trigger=getattr(gate_result, 'reason', '') if gate_decision is not None else '',
            gate_distance=adapter.closest_body_distance if adapter is not None else float("inf"),
            closest_body=adapter.closest_body_name if adapter is not None else '',
            # D-group / F-group / H-group (2026-07-11)
            disturbance_active=disturbance_active,
            consecutive_stop_count=consecutive_gate_count,  # R7 C3 fix: param name synced with test_metrics.py:88
            replan_success=replan_last_success if args_cli.replan else None,
            replan_failure_reason=replan_last_failure_reason,
            vlm_action=last_vlm_decision.get("action", ""),
            vlm_latency_ms=last_vlm_decision.get("latency_ms", 0.0),
            vlm_reason=last_vlm_decision.get("reason", ""),
        )
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
                f"{_proto_phase},{_proto_part}\n"
            )
            _track_fh.flush()

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
        metrics.parts_placed = ur10e.parts_placed

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
    metrics.parts_placed = ur10e.parts_placed
    writer.write(metrics)
    print(
        f"[phase3] Metrics written to {args_cli.output_csv}"
    )
    print(
        f"[phase3] time_step={ur10e.time_step}  success={ur10e.success}  "
        f"parts={ur10e.parts_placed}/{ur10e.total_parts}"
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
