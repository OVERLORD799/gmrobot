"""GMDisturb Phase 1: G1 + UR10e + pressure mat co-simulation environment config.

Registered task: ``G1-UR10e-Disturbance-v0``
Depends on: isaaclab 2.x (isaaclab.* imports)

This is THE central config file — it defines the scene layout, observation
groups, action space, events, commands, and terminations for the dual-robot
co-simulation.
"""

from __future__ import annotations

import os
import sys

import torch

import isaaclab.sim as sim_utils
import isaaclab.envs.mdp as mdp
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.controllers import DifferentialIKControllerCfg
from isaaclab.envs import ManagerBasedRLEnvCfg
from isaaclab.envs.mdp.actions.actions_cfg import DifferentialInverseKinematicsActionCfg
from isaaclab.envs.mdp.commands.commands_cfg import UniformVelocityCommandCfg
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.managers import TerminationTermCfg as DoneTerm
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import ContactSensorCfg
from isaaclab.sensors.camera import CameraCfg, TiledCameraCfg
from isaaclab.sensors.ray_caster import RayCasterCfg, patterns
from isaaclab.sim.schemas.schemas_cfg import RigidBodyPropertiesCfg
from isaaclab.utils import configclass
from isaaclab.utils.assets import ISAAC_NUCLEUS_DIR
from isaaclab.utils.math import combine_frame_transforms, matrix_from_quat, quat_from_euler_xyz
from isaaclab.utils.noise import AdditiveUniformNoiseCfg as Unoise

# =============================================================================
# Project-local imports (migrated and adapted for isaaclab 2.x)
# =============================================================================
# Add the project root so relative imports work when running via AppLauncher
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scene_camera_override import resolve_scene_camera_pose
from func_c_dual_reference_contract import (
    REFERENCE_CONTENT_SOURCE,
    resolve_part_locations,
    visual_opt_in_enabled,
)

_SCENE_CAMERA_POS, _SCENE_CAMERA_ROT = resolve_scene_camera_pose()

from mdp.tactile_obs import (
    tactile_force_multi_net,
    velocity_commands_deploy,
    walk_sin_phase,
    walk_cos_phase,
    last_action_padded_29,
)
from mdp import PHASE_PERIOD as _PHASE_PERIOD
from mdp.walk_action import WalkJointActionCfg
from mdp.terminations import root_out_of_mat_bounds
from vendored.robot_cfg import G1_927_WALK_CFG

# =============================================================================
# GMRobot imports — vendored copies for Python modules, live refs for USD assets.
# =============================================================================

from paths import GMROBOT_ASSETS as _GMROBOT_ASSETS, \
    PRESSURE_MAT_TACTILE as _PRESSURE_MAT_TACTILE

# GMRobot root for container/part USD assets (too large to vendored)

# UR10e config: DIRECT import from GMRobot (via vendored copy).
# GMRobot uses this EXACT ArticulationCfg — table at (0.6, 0, 0),
# containers at (0.75, +-0.25, 0), ground at z=-1.05.
from vendored.ur10e_cfg import UR10E_CFG

# GMRobot coordinate system: ground at z=-1.05, everything else at z=0.
_GMROBOT_Z_OFFSET = 0.0

from mdp.gm_safety_obs import (
    ee_lin_vel_w,
    arm_joint_pos,
    arm_joint_vel,
)

# Paths to container/part USD assets
_CONTAINER_USD = os.path.join(_GMROBOT_ASSETS, "container.usd")
_DIVIDER_USD = os.path.join(_GMROBOT_ASSETS, "container/GM_Container_Slim_Divider_Sim.usd")
_PART_USD = os.path.join(_GMROBOT_ASSETS, "part/part_5000.usd")

# UR10e joint names and gripper constants (from GMRobot)
ARM_JOINT_NAMES = [
    "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
    "wrist_1_joint", "wrist_2_joint", "wrist_3_joint",
]
GRIPPER_JOINT_NAMES = [
    "finger_joint", "right_outer_knuckle_joint", "right_inner_finger_joint",
    "right_inner_finger_knuckle_joint", "left_inner_finger_knuckle_joint",
    "left_inner_finger_joint",
]
GRIPPER_CLOSED = 0.7853981633974483   # pi/4
GRIPPER_OPEN = 0.4 * GRIPPER_CLOSED

# ——— Coordinate system ———
# GMRobot scene: ground at z=-1.05, everything (table/UR10e/containers) at z=0.
# GMDisturb replicates this exactly: ground/mat at z=-1.05, G1 at ground level,
# UR10e/table/containers at z=0 where IK works natively.
# (Duplicate assignment below is intentional — see line 74 for the value.)
CONTAINER_POSES = {"A": (0.75, -0.25, _GMROBOT_Z_OFFSET),
                   "B": (0.75, 0.25, _GMROBOT_Z_OFFSET)}
CONTAINER_YAWS = {"A": 0.0, "B": 0.0}
CONTAINER_SCALE = (0.01, 0.01, 0.01)
CONTAINER_X_SLOTS = 5
CONTAINER_Y_SLOTS = 4
CONTAINER_X_GAP = 0.11042
CONTAINER_Y_GAP = 0.07
CONTAINER_ROT = (0.5, 0.5, 0.5, 0.5)
GRID_ROT = (0.7071068, -0.7071068, 0.0, 0.0)
GRID_OFFSET = (-0.27305, -0.16637, 0.10)
PART_HEIGHT = 0.17
PART_DEFAULT_ROT = (0.7071068, 0.0, -0.7071068, 0.0)
PART_SLOT_COUNT = CONTAINER_X_SLOTS * CONTAINER_Y_SLOTS  # 20
# Default: all 20 parts start in Container A (Dual baseline).
# Opt-in GMDISTURB_V1E01_FUNC_C_VISUAL=1: deterministic B@1..B@20 for
# Func-C capture-only reference framing, while preserving Dual defaults.
PART_LOCATIONS = resolve_part_locations()
if visual_opt_in_enabled() and REFERENCE_CONTENT_SOURCE != "part_assets_20_slots":
    raise RuntimeError(
        "Func-C Dual reference scene BLOCKED: reference content source is not part-assets slots."
    )

# =============================================================================
# Container/Part builder functions (inlined from GMRobot gmrobot_env_cfg.py)
# =============================================================================

def _yaw_quat(yaw: float) -> "torch.Tensor":
    """Return quaternion (w, x, y, z) for a pure yaw rotation."""
    zero = torch.zeros(1, dtype=torch.float32)
    yaw_t = torch.tensor([yaw], dtype=torch.float32)
    return quat_from_euler_xyz(zero, zero, yaw_t)

def _compose_pose(base_pos, base_yaw, local_pos=(0.,0.,0.), local_rot=(1.,0.,0.,0.)):
    """Compose a local pose inside a yaw-rotated parent frame."""
    t01 = torch.tensor([base_pos], dtype=torch.float32)
    q01 = _yaw_quat(base_yaw)
    t12 = torch.tensor([local_pos], dtype=torch.float32)
    q12 = torch.tensor([local_rot], dtype=torch.float32)
    pos, quat = combine_frame_transforms(t01, q01, t12, q12)
    return tuple(pos[0].tolist()), tuple(quat[0].tolist())

def _slot_local_offset(slot_idx_zero: int) -> tuple[float, float, float]:
    """Return slot center in container-local frame."""
    x_idx = slot_idx_zero // CONTAINER_Y_SLOTS
    y_idx = slot_idx_zero % CONTAINER_Y_SLOTS
    x_center = 0.5 * (CONTAINER_X_SLOTS - 1) * CONTAINER_X_GAP
    y_center = 0.5 * (CONTAINER_Y_SLOTS - 1) * CONTAINER_Y_GAP
    return (x_idx * CONTAINER_X_GAP - x_center, y_idx * CONTAINER_Y_GAP - y_center, PART_HEIGHT)

def build_container_grid_assets() -> dict:
    """Build AssetBaseCfg dict for container A with dividers."""
    assets = {}
    for cname, cpos in CONTAINER_POSES.items():
        cyaw = CONTAINER_YAWS[cname]
        box_pos, box_rot = _compose_pose(cpos, cyaw, local_rot=CONTAINER_ROT)
        grid_pos, grid_rot = _compose_pose(cpos, cyaw, local_pos=GRID_OFFSET, local_rot=GRID_ROT)
        assets[f"box_{cname}"] = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Container{cname}",
            init_state=AssetBaseCfg.InitialStateCfg(pos=box_pos, rot=box_rot),
            spawn=sim_utils.UsdFileCfg(usd_path=_CONTAINER_USD, scale=CONTAINER_SCALE),
        )
        assets[f"grid_{cname}"] = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Grid{cname}",
            init_state=AssetBaseCfg.InitialStateCfg(pos=grid_pos, rot=grid_rot),
            spawn=sim_utils.UsdFileCfg(usd_path=_DIVIDER_USD),
        )
    return assets

def build_part_assets() -> dict:
    """Build RigidObjectCfg dict for 20 parts (IDENTICAL to GMRobot)."""
    assets = {}
    for idx, location in enumerate(PART_LOCATIONS, start=1):
        container_id, slot_id_str = location.split("@")
        slot_id = int(slot_id_str) - 1

        part_pos, part_rot = _compose_pose(
            CONTAINER_POSES[container_id], CONTAINER_YAWS[container_id],
            local_pos=_slot_local_offset(slot_id), local_rot=PART_DEFAULT_ROT,
        )
        assets[f"part_{idx}"] = RigidObjectCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Part_{idx}",
            init_state=RigidObjectCfg.InitialStateCfg(pos=part_pos, rot=part_rot),
            spawn=sim_utils.UsdFileCfg(
                usd_path=_PART_USD, scale=(1.0, 1.0, 1.0),
                rigid_props=RigidBodyPropertiesCfg(
                    solver_position_iteration_count=32,
                    solver_velocity_iteration_count=4,
                    max_angular_velocity=1000.0,
                    max_linear_velocity=1000.0,
                    max_depenetration_velocity=5.0,
                    disable_gravity=False,
                ),
                mass_props=sim_utils.MassPropertiesCfg(mass=0.2),
            ),
        )
    return assets

# Observation helpers for UR10e policy obs (inlined from GMRobot)
def _get_static_box_pos(env, box_name: str) -> "torch.Tensor":
    """Return a fixed container 4x4 transform repeated across envs."""
    pos = torch.tensor(CONTAINER_POSES[box_name], device=env.device, dtype=torch.float32)
    yaw = CONTAINER_YAWS[box_name]
    rot = _yaw_quat(yaw)
    T = torch.eye(4, device=env.device, dtype=torch.float32)
    T[:3, :3] = matrix_from_quat(rot)
    T[:3, 3] = pos
    return T.unsqueeze(0).repeat(env.num_envs, 1, 1)

def _get_static_slot_transform(env, container_id: str, slot_id: int) -> "torch.Tensor":
    """Return slot transform as flattened 4x4, shape (N, 4, 4)."""
    slot_pos, slot_rot = _compose_pose(
        CONTAINER_POSES[container_id], CONTAINER_YAWS[container_id],
        local_pos=_slot_local_offset(slot_id - 1),
    )
    pos = torch.tensor(slot_pos, device=env.device, dtype=torch.float32).unsqueeze(0)
    quat = torch.tensor(slot_rot, device=env.device, dtype=torch.float32).unsqueeze(0)
    rot = matrix_from_quat(quat)
    T = torch.eye(4, device=env.device, dtype=torch.float32)
    T[:3, :3] = rot
    T[:3, 3] = pos
    return T.unsqueeze(0).repeat(env.num_envs, 1, 1)

# Pre-built observation term dicts (match GMRobot's OBS_BOXES, OBS_PARTS, OBS_SLOTS)
_OBS_BOXES = {
    f"box_{bn}_pos": ObsTerm(func=_get_static_box_pos, params={"box_name": bn})
    for bn in CONTAINER_POSES
}
_OBS_PARTS = {
    f"part_{idx}_pos": ObsTerm(
        func=mdp.body_pose_w,
        params={"asset_cfg": SceneEntityCfg(f"part_{idx}")},
    )
    for idx in range(1, PART_SLOT_COUNT + 1)
}
_OBS_SLOTS = {}
for cid in CONTAINER_POSES:
    for sid in range(1, PART_SLOT_COUNT + 1):
        _OBS_SLOTS[f"slot_{cid}_{sid}_T"] = ObsTerm(
            func=_get_static_slot_transform,
            params={"container_id": cid, "slot_id": sid},
        )


# =============================================================================
# Constants
# =============================================================================

# Pressure mat
ROWS = 32
COLS = 32
MAT_SIZE_X = 4.0  # meters
MAT_SIZE_Y = 4.0  # meters
COUPLING_LENGTH = 0.01  # Pasternak shear (meters)

# Paths — local assets first, env var / original repo as fallback
_LOCAL_ASSETS = os.path.join(_PROJECT_ROOT, "assets")
_LOCAL_MAT = os.path.join(_LOCAL_ASSETS, "tactile_mat_32x32_4m.usd")
if os.path.exists(_LOCAL_MAT):
    _MAT_USD = _LOCAL_MAT
else:
    _MAT_USD = _PRESSURE_MAT_TACTILE
TABLE_USD = f"{ISAAC_NUCLEUS_DIR}/Props/Mounts/SeattleLabTable/table_instanceable.usd"

# Taxel filter paths (1024 paths for 32×32 mat)
_TAXEL_FILTER_PATHS = [
    f"{{ENV_REGEX_NS}}/Mat/sensor_{r:02d}_{c:02d}"
    for r in range(1, ROWS + 1)
    for c in range(1, COLS + 1)
]

# Robot initial states
# G1 root at 0.8 m above the floor (z=0)
G1_INIT_POS = (-1.5, 0.0, -0.25)  # G1 stays back — virtual hand does all the reaching
G1_INIT_QUAT = (1.0, 0.0, 0.0, 0.0)  # Facing +x

# Workspace bounds for G1 disturbance
WORKSPACE_X_RANGE = (0.0, 0.8)
WORKSPACE_Y_RANGE = (-0.5, 0.5)


# =============================================================================
# Helper functions
# =============================================================================

def _mat_asset_cfg(usd_path: str) -> AssetBaseCfg:
    """Pressure mat as a static asset (kinematic) on the floor (z=0)."""
    return AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Mat",
        spawn=sim_utils.UsdFileCfg(usd_path=usd_path),
    )


def _foot_contact_sensor(prim_path: str) -> ContactSensorCfg:
    """ContactSensor on one G1 foot, filtering against all taxels."""
    return ContactSensorCfg(
        prim_path=prim_path,
        filter_prim_paths_expr=list(_TAXEL_FILTER_PATHS),
        update_period=0.005,
        history_length=3,
        track_air_time=True,
    )


def _g1_body_contact_sensor() -> ContactSensorCfg:
    """Whole-body ContactSensor for G1 — reports per-body net contact force."""
    return ContactSensorCfg(
        prim_path="{ENV_REGEX_NS}/Robot_G1/.*",
        history_length=3,
        track_air_time=True,
    )


# =============================================================================
# Scene
# =============================================================================

@configclass
class DualRobotSceneCfg(InteractiveSceneCfg):
    """Scene: G1 + UR10e + pressure mat + table + containers + 20 parts."""

    # Ground & Light
    ground = AssetBaseCfg(
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.0, 0.0, -1.05)),
        prim_path="/World/GroundPlane",
        spawn=sim_utils.GroundPlaneCfg(),
    )
    dome_light = AssetBaseCfg(
        prim_path="/World/DomeLight",
        spawn=sim_utils.DomeLightCfg(intensity=2000.0),
    )

    # Pressure Mat (on the floor at z=0)
    mat = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Mat",
        spawn=sim_utils.UsdFileCfg(usd_path=_MAT_USD),
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.0, 0.0, -1.05)),
    )

    # === Robots ===
    robot_g1: ArticulationCfg = G1_927_WALK_CFG.replace(
        prim_path="{ENV_REGEX_NS}/Robot_G1",
        init_state=ArticulationCfg.InitialStateCfg(
            pos=G1_INIT_POS,
            rot=G1_INIT_QUAT,
            joint_pos=G1_927_WALK_CFG.init_state.joint_pos,
            joint_vel=G1_927_WALK_CFG.init_state.joint_vel,
        ),
    )

    # UR10e desk-mounted — built inline, NO .replace().  The G1 robot above
    # uses G1_927_WALK_CFG.replace(...) which works because G1_927_WALK_CFG
    # is a module-level constant.  UR10e's .replace() does NOT merge init_state
    # correctly across vendored config files, so we construct it from scratch.
    robot_ur10e: ArticulationCfg = UR10E_CFG.replace(
        prim_path="{ENV_REGEX_NS}/Robot_UR10e",
    )

    # === G1 Contact Sensors ===
    left_foot_sensor = _foot_contact_sensor(
        "{ENV_REGEX_NS}/Robot_G1/left_ankle_roll_link"
    )
    right_foot_sensor = _foot_contact_sensor(
        "{ENV_REGEX_NS}/Robot_G1/right_ankle_roll_link"
    )
    g1_contact_forces = _g1_body_contact_sensor()

    # === UR10e Workspace ===
    # Table at (0.6, 0, 0) — GMRobot original position
    # Table at (0, 0, z) directly under UR10e base — UR10e is table-mounted
    table = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Table",
        spawn=sim_utils.UsdFileCfg(usd_path=TABLE_USD),
        init_state=AssetBaseCfg.InitialStateCfg(
            pos=(0.6, 0.0, _GMROBOT_Z_OFFSET),
            rot=(0.70711, 0.0, 0.0, 0.70711),
        ),
    )

    # Containers + Parts (from GMRobot)
    locals().update(build_container_grid_assets())
    locals().update(build_part_assets())

    # === Scene Camera (overhead) ===
    # Default pose (1.0, 0.0, 3.0). Opt-in override via env (see scene_camera_override.py):
    #   GMDISTURB_SCENE_CAMERA_OVERRIDE=1
    #   GMDISTURB_SCENE_CAMERA_POS=...
    #   GMDISTURB_SCENE_CAMERA_ROT=...
    # When override is off, POS/ROT env vars are ignored and Dual defaults are unchanged.
    scene_camera: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/SceneCamera",
        update_period=0.1,
        height=480,
        width=640,
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=18.0,
            focus_distance=400.0,
            horizontal_aperture=20.955,
            clipping_range=(0.1, 1.0e5),
        ),
        offset=TiledCameraCfg.OffsetCfg(
            pos=_SCENE_CAMERA_POS,
            rot=_SCENE_CAMERA_ROT,
            convention="world",
        ),
    )

    # === G1 Head Camera (D435, Phase 6: navigation) ===
    g1_head_camera: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot_G1/d435_link/HeadCamera",
        update_period=0.1,
        height=240,
        width=320,
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=12.0,
            focus_distance=10.0,
            horizontal_aperture=20.955,
            clipping_range=(0.05, 20.0),
        ),
        offset=TiledCameraCfg.OffsetCfg(
            pos=(0.05, 0.0, 0.0),   # forward-facing, on the D435 body
            rot=(0.5, 0.5, 0.5, 0.5),  # looking forward
            convention="world",
        ),
    )

    # === G1 Head LiDAR (MID-360) ===
    # Deferred: RayCasterCfg requires the prim to pre-exist in USD stage
    # (unlike TiledCamera which creates it).  Mounting LiDAR on articulated
    # bodies needs programmatic prim creation at init time.  Tracked as Phase 6.1.


# =============================================================================
# Observations
# =============================================================================

@configclass
class _TactileObsCfg(ObsGroup):
    """Per-taxel Newton image (ROWS × COLS), feet net-force calibrated."""
    tactile = ObsTerm(
        func=tactile_force_multi_net,
        params={
            "sensor_names": ["left_foot_sensor", "right_foot_sensor"],
            "rows": ROWS,
            "cols": COLS,
            "coupling_length": COUPLING_LENGTH,
            "mat_size_x": MAT_SIZE_X,
            "mat_size_y": MAT_SIZE_Y,
            "physics_calibrate": True,
        },
    )
    def __post_init__(self):
        self.enable_corruption = False
        self.concatenate_terms = False


@configclass
class _G1WalkerObsCfg(ObsGroup):
    """588-dim walker observation (8 terms × 6-step history).

    Matches the input spec of the Unitree deploy_walk torchscript policy.
    """
    base_ang_vel = ObsTerm(
        func=mdp.base_ang_vel,
        scale=1.0,
        noise=Unoise(n_min=-0.2, n_max=0.2),
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
    )
    projected_gravity = ObsTerm(
        func=mdp.projected_gravity,
        noise=Unoise(n_min=-0.05, n_max=0.05),
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
    )
    velocity_commands = ObsTerm(
        func=velocity_commands_deploy,
        params={
            "command_name": "g1_base_velocity",
            "lin_scale": 2.0,
            "ang_scale": 0.25,
        },
    )
    joint_pos = ObsTerm(
        func=mdp.joint_pos_rel,
        scale=1.0,
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
        noise=Unoise(n_min=-0.01, n_max=0.01),
    )
    joint_vel = ObsTerm(
        func=mdp.joint_vel_rel,
        scale=1.0,
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
        noise=Unoise(n_min=-1.5, n_max=1.5),
    )
    actions = ObsTerm(
        func=last_action_padded_29,
        params={"action_name": "g1_joint_pos"},
    )
    sin_phase = ObsTerm(
        func=walk_sin_phase,
        params={"command_name": "g1_base_velocity", "period": _PHASE_PERIOD},
    )
    cos_phase = ObsTerm(
        func=walk_cos_phase,
        params={"command_name": "g1_base_velocity", "period": _PHASE_PERIOD},
    )
    def __post_init__(self):
        self.history_length = 6
        self.enable_corruption = False
        self.concatenate_terms = True


@configclass
class _UR10ePolicyObsCfg(ObsGroup):
    """UR10e policy observations: EE pose + 20 part poses + 2 box poses + 40 slot transforms."""
    ee_pos = ObsTerm(
        func=mdp.body_pose_w,
        params={"asset_cfg": SceneEntityCfg("robot_ur10e", body_names="wrist_3_link")},
    )
    locals().update(_OBS_BOXES)
    locals().update(_OBS_PARTS)
    locals().update(_OBS_SLOTS)
    def __post_init__(self):
        self.concatenate_terms = False


@configclass
class _UR10eCameraObsCfg(ObsGroup):
    """Scene camera RGB for VLM / perception."""
    scene_rgb = ObsTerm(
        func=mdp.image,
        params={
            "sensor_cfg": SceneEntityCfg("scene_camera"),
            "data_type": "rgb",
            "normalize": False,
        },
    )
    def __post_init__(self):
        self.concatenate_terms = False


@configclass
class _UR10eSafetyObsCfg(ObsGroup):
    """UR10e safety observations: EE velocity, joint states.

    NOTE: Human hand/torso positions are provided at runtime by
    G1EnvelopeAdapter, NOT from fixed sensor prims. The safety_obs
    terms for human_hand_pos/vel are kept as placeholders.
    """
    ee_vel = ObsTerm(
        func=ee_lin_vel_w,
        params={"asset_cfg": SceneEntityCfg("robot_ur10e", body_names="wrist_3_link")},
    )
    joint_pos = ObsTerm(
        func=arm_joint_pos,
        params={"asset_cfg": SceneEntityCfg("robot_ur10e", joint_names=ARM_JOINT_NAMES)},
    )
    joint_vel = ObsTerm(
        func=arm_joint_vel,
        params={"asset_cfg": SceneEntityCfg("robot_ur10e", joint_names=ARM_JOINT_NAMES)},
    )
    def __post_init__(self):
        self.concatenate_terms = False


@configclass
class _G1BodyObsCfg(ObsGroup):
    """G1 body tracking for safety adapter — per-body world positions."""
    g1_root_pos = ObsTerm(
        func=mdp.root_pos_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
    )
    g1_root_vel = ObsTerm(
        func=mdp.root_lin_vel_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
    )
    g1_root_ang_vel = ObsTerm(
        func=mdp.root_ang_vel_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1")},
    )
    g1_left_hand_pos = ObsTerm(
        func=mdp.body_pose_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1", body_names=["left_wrist_pitch_link"])},
    )
    g1_right_hand_pos = ObsTerm(
        func=mdp.body_pose_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1", body_names=["right_wrist_pitch_link"])},
    )
    g1_left_foot_pos = ObsTerm(
        func=mdp.body_pose_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1", body_names=["left_ankle_roll_link"])},
    )
    g1_right_foot_pos = ObsTerm(
        func=mdp.body_pose_w,
        params={"asset_cfg": SceneEntityCfg("robot_g1", body_names=["right_ankle_roll_link"])},
    )
    def __post_init__(self):
        self.concatenate_terms = False


@configclass
class _G1HeadCameraObsCfg(ObsGroup):
    """G1 first-person RGB from the D435 head camera."""
    head_rgb = ObsTerm(
        func=mdp.image,
        params={
            "sensor_cfg": SceneEntityCfg("g1_head_camera"),
            "data_type": "rgb",
            "normalize": False,
        },
    )
    def __post_init__(self):
        self.concatenate_terms = False


@configclass
class DualRobotObservationsCfg:
    """All observation groups for the combined environment."""
    g1_walker: ObsGroup = _G1WalkerObsCfg()
    tactile: ObsGroup = _TactileObsCfg()
    ur10e_policy: ObsGroup = _UR10ePolicyObsCfg()
    ur10e_camera: ObsGroup = _UR10eCameraObsCfg()
    safety: ObsGroup = _UR10eSafetyObsCfg()
    g1_body: ObsGroup = _G1BodyObsCfg()
    g1_head_camera: ObsGroup = _G1HeadCameraObsCfg()
    # LiDAR: sensor prim is active (g1_lidar), data read directly at runtime
    # via env.unwrapped.scene.sensors["g1_lidar"].data.pos_w / ray_hits_w
    def __post_init__(self):
        self.policy = self.g1_walker


# =============================================================================
# Actions
# =============================================================================

@configclass
class DualRobotActionsCfg:
    """20D combined action: G1 legs (12D) + UR10e EE (8D)."""

    g1_joint_pos = WalkJointActionCfg(
        asset_name="robot_g1",
        joint_names=[".*hip.*", ".*ankle.*", ".*knee.*"],
        scale=0.25,
        use_default_offset=True,
        clip={".*": (-100.0, 100.0)},
    )

    ur10e_ee = DifferentialInverseKinematicsActionCfg(
        asset_name="robot_ur10e",
        body_name="wrist_3_link",
        joint_names=ARM_JOINT_NAMES,
        controller=DifferentialIKControllerCfg(
            command_type="pose",
            use_relative_mode=False,
            ik_method="dls",
            # Note: nullspace_joint_pos is NOT available in Isaac Lab 0.54.x
            # DifferentialIKControllerCfg. DLS method uses lambda_val damping
            # (default 0.01) for singularity-robust IK.
        ),
        body_offset=DifferentialInverseKinematicsActionCfg.OffsetCfg(
            pos=[0.0, 0.0, 0.15]
        ),
    )

    ur10e_gripper = mdp.BinaryJointPositionActionCfg(
        asset_name="robot_ur10e",
        joint_names=GRIPPER_JOINT_NAMES,
        open_command_expr={
            "finger_joint": GRIPPER_OPEN,
            "right_outer_knuckle_joint": GRIPPER_OPEN,
            "right_inner_finger_joint": GRIPPER_OPEN,
            "right_inner_finger_knuckle_joint": -GRIPPER_OPEN,
            "left_inner_finger_knuckle_joint": -GRIPPER_OPEN,
            "left_inner_finger_joint": -GRIPPER_OPEN,
        },
        close_command_expr={
            "finger_joint": GRIPPER_CLOSED,
            "right_outer_knuckle_joint": GRIPPER_CLOSED,
            "right_inner_finger_joint": GRIPPER_CLOSED,
            "right_inner_finger_knuckle_joint": -GRIPPER_CLOSED,
            "left_inner_finger_knuckle_joint": -GRIPPER_CLOSED,
            "left_inner_finger_joint": -GRIPPER_CLOSED,
        },
    )


# =============================================================================
# Commands
# =============================================================================

@configclass
class DualRobotCommandsCfg:
    """G1 velocity command — driven by G1DisturbanceController (Phase 3).

    ``UniformVelocityCommandCfg`` is retained as a shell: its
    ``vel_command_b`` buffer is overwritten every step by the
    disturbance controller via ``command_manager.get_term("g1_base_velocity")``.

    Key settings:
    - ``resampling_time_range`` = huge (1e6 s) → never auto-resamples.
    - ``rel_standing_envs`` = 0.0 → never zeroes the command.
    """

    g1_base_velocity = UniformVelocityCommandCfg(
        asset_name="robot_g1",
        resampling_time_range=(1e6, 1e6),  # never auto-resample (Phase 3)
        rel_standing_envs=0.0,              # never stand still
        rel_heading_envs=1.0,
        heading_command=False,
        debug_vis=False,
        ranges=UniformVelocityCommandCfg.Ranges(
            lin_vel_x=(-0.8, 0.8),
            lin_vel_y=(-0.5, 0.5),
            ang_vel_z=(-1.57, 1.57),
        ),
    )


# =============================================================================
# Runtime UR10e position fix — ArticulationCfg.init_state.pos is NOT honoured
# for this USD (likely due to ImplicitActuatorCfg / USD internal transforms).
# We move the robot to desk height on first reset directly through the PhysX API.
# =============================================================================

_UR10E_DESK_Z = 0.0  # must match _GMROBOT_Z_OFFSET

# Identity quaternion (w=1, x=y=z=0) — matches GMRobot UR10E_CFG rot.
_IDENTITY_QUAT = (1.0, 0.0, 0.0, 0.0)

def _fix_ur10e_position(env: "ManagerBasedRLEnv", env_ids: "torch.Tensor"):
    """One-shot per env: teleport UR10e root to (0,0,0).

    The UR10e USD has a built-in root offset (~-1.08, 2.35, 0) that
    ImplicitActuatorCfg does NOT override.  GMRobot uses reset_scene_to_default
    to fix this; we use write_root_state_to_sim because reset_scene_to_default
    would also reset G1.

    M7 fix: the _done flag is stored on the env instance (not the function),
    so if the env is destroyed and recreated (batch mode), the fix runs again.
    """
    # Per-instance flag — survives episode resets, does NOT survive env recreate.
    if getattr(env, "_gmdisturb_ur10e_position_fixed", False):
        return
    robot = env.scene["robot_ur10e"]
    before = robot.data.root_pos_w[0].cpu().numpy()
    root_state = robot.data.root_state_w.clone()
    root_state[:, :3] = torch.tensor([0.0, 0.0, 0.0], device=root_state.device)
    robot.write_root_state_to_sim(root_state)
    after = robot.data.root_pos_w[0].cpu().numpy()
    print(f"[GMDisturb] UR10e teleported: ({before[0]:.2f},{before[1]:.2f},{before[2]:.2f}) -> ({after[0]:.2f},{after[1]:.2f},{after[2]:.2f})")
    env._gmdisturb_ur10e_position_fixed = True


# =============================================================================
# Runtime collision filter: G1 ↔ UR10e
# =============================================================================
# Per-pair collision filtering cannot be expressed through the Isaac Lab config
# layer (CollisionPropertiesCfg is per-body, not per-pair).  We run a one-shot
# event on first reset that uses the Omniverse PhysX scripting API to add the
# two articulation root prims to PhysX's collision filter list.
#
# Why not config-time: the USD stage is only available after the simulation
# context has been initialized (which happens during env.__init__, after the
# config __post_init__ has returned).

def _setup_g1_ur10e_collision_filter(
    env: "ManagerBasedRLEnv",
    env_ids: "torch.Tensor",
    g1_prim_regex: str = "{ENV_REGEX_NS}/Robot_G1",
    ur10e_prim_regex: str = "{ENV_REGEX_NS}/Robot_UR10e",
):
    """Disable PhysX collision response between G1 and UR10e articulation roots.

    This is a one-shot event — after the first call, subsequent invocations
    are no-ops.  The filter persists across episode resets because it operates
    on the USD stage, not per-episode state.

    Safety: the safety gate relies on FK-based (kinematic) distance detection,
    not on PhysX contact reports.  Disabling collision response between the
    two robots prevents simulation instability when their articulation chains
    overlap, without affecting safety behaviour.

    R2 fix: the previous implementation silently caught all exceptions and
    was a complete no-op.  This version uses the PhysX filtering API to
    actually disable collision response between the two articulation roots,
    with a graceful fallback if the API is unavailable.
    """
    # M7 fix: per-instance flag instead of function attribute — survives
    # episode resets, does NOT survive env destroy+recreate (batch mode).
    if getattr(env, "_gmdisturb_collision_filter_done", False):
        return

    # Resolve the regex prim paths to concrete env-0 paths.
    env0_g1 = g1_prim_regex.replace("{ENV_REGEX_NS}", "/World/envs/env_0")
    env0_ur10e = ur10e_prim_regex.replace("{ENV_REGEX_NS}", "/World/envs/env_0")

    applied = False
    api_error = None
    try:
        from pxr import UsdPhysics
        from isaaclab.sim import SimulationContext

        stage = SimulationContext.instance().stage
        g1_prim = stage.GetPrimAtPath(env0_g1)
        ur10e_prim = stage.GetPrimAtPath(env0_ur10e)

        if g1_prim.IsValid() and ur10e_prim.IsValid():
            filtering_api = UsdPhysics.FilteredPairsAPI.Apply(g1_prim)
            rel = filtering_api.CreateFilteredPairsRel()
            rel.AddTarget(env0_ur10e)
            applied = True
    except ImportError as e:
        api_error = f"UsdPhysics unavailable: {e}"
    except Exception as e:
        api_error = str(e)

    if applied:
        print("[GMDisturb] G1↔UR10e collision filter APPLIED (FK safety gate active).")
    else:
        msg = (
            "[GMDisturb] G1↔UR10e collision filter NOT APPLIED. "
        )
        if api_error:
            msg += f"Reason: {api_error}. "
        msg += (
            "Contact buffer set to 2**24 for dual-articulation support. "
            "AGGRESSIVE mode may cause simulation instability. "
            "MODERATE/CAUTIOUS modes are safe."
        )
        print(msg)
        # H3 fix: if the user explicitly asked for AGGRESSIVE mode and we
        # can't filter collisions, warn prominently — the run may crash.
        if os.environ.get("GMDISTURB_MODE", "").upper() == "AGGRESSIVE":
            print(
                "[GMDisturb] WARNING: AGGRESSIVE mode active without collision filter — "
                "risk of PhysX instability with two-articulation contact."
            )

    env._gmdisturb_collision_filter_done = True


def _reset_parts_to_default(env: "ManagerBasedRLEnv", env_ids: "torch.Tensor"):
    """Reset all 20 RigidObject parts to their initial container-A positions.

    R2 M6 fix: DualRobotEventsCfg removed ``reset_scene_to_default`` (which
    would also reset G1), but no replacement was added for parts.  This
    function writes the default root state for every part asset, ensuring
    multi-episode runs start with parts in container A.
    """
    scene = env.unwrapped.scene
    for part_name in scene.rigid_objects:
        part = scene[part_name]
        default_root = part.data.default_root_state[env_ids].clone()
        part.write_root_state_to_sim(default_root, env_ids=env_ids)


# =============================================================================
# Events
# =============================================================================

@configclass
class DualRobotEventsCfg:
    """Reset + domain randomization for both robots and parts."""

    # --- Move UR10e to desk height (one-shot; config init_state is ignored) ---
    fix_ur10e_position = EventTerm(
        func=_fix_ur10e_position,
        mode="reset",
    )

    # --- Scene-wide collision filter (one-shot, first reset only) ---
    disable_g1_ur10e_collision = EventTerm(
        func=_setup_g1_ur10e_collision_filter,
        mode="reset",
    )

    # --- G1 ---
    reset_g1_base = EventTerm(
        func=mdp.reset_root_state_uniform,
        mode="reset",
        params={
            "asset_cfg": SceneEntityCfg("robot_g1"),
            "pose_range": {"x": (-0.1, 0.1), "y": (-0.1, 0.1), "yaw": (-0.1, 0.1)},
            "velocity_range": {},
        },
    )
    reset_g1_joints = EventTerm(
        func=mdp.reset_joints_by_scale,
        mode="reset",
        params={
            "asset_cfg": SceneEntityCfg("robot_g1"),
            "position_range": (1.0, 1.0),
            "velocity_range": (0.0, 0.0),
        },
    )
    g1_foot_friction = EventTerm(
        func=mdp.randomize_rigid_body_material,
        mode="reset",
        params={
            "asset_cfg": SceneEntityCfg("robot_g1", body_names=".*"),
            "static_friction_range": (0.8, 0.8),
            "dynamic_friction_range": (0.6, 0.6),
            "restitution_range": (0.0, 0.0),
            "num_buckets": 64,
        },
    )

    # --- Parts (20 RigidObjects) ---
    # R2 M6 fix: reset_scene_to_default was removed (it resets G1 too), but
    # no replacement was added for the 20 parts.  Without explicit reset,
    # multi-episode runs would start with parts at their previous positions.
    reset_parts = EventTerm(
        func=_reset_parts_to_default,
        mode="reset",
    )

    # --- UR10e ---
    reset_ur10e_joints = EventTerm(
        func=mdp.reset_joints_by_offset,
        mode="reset",
        params={
            "position_range": (0.0, 0.0),
            "velocity_range": (0.0, 0.0),
            "asset_cfg": SceneEntityCfg("robot_ur10e"),
        },
    )


# =============================================================================
# Rewards (empty — no RL)
# =============================================================================

@configclass
class DualRobotRewardsCfg:
    """No RL training; scripted testing only."""
    pass


# =============================================================================
# Terminations
# =============================================================================

@configclass
class DualRobotTerminationsCfg:
    """Terminations for G1 + UR10e co-simulation."""

    time_out = DoneTerm(func=mdp.time_out, time_out=True)
    # S3 fix: minimum_height changed from -1.0 to -0.7.
    # G1 root at standing height is z≈-0.25 (ground -1.05 + 0.80).
    # A fallen G1 root drops to ~-0.75 (ground -1.05 + 0.30 knee height).
    # The previous threshold (-1.0) required root to pass through the floor
    # before triggering termination, silently corrupting episode metrics.
    g1_fall = DoneTerm(
        func=mdp.root_height_below_minimum,
        params={"asset_cfg": SceneEntityCfg("robot_g1"), "minimum_height": -0.7},
    )
    g1_out_of_mat = DoneTerm(
        func=root_out_of_mat_bounds,
        params={
            "asset_cfg": SceneEntityCfg("robot_g1"),
            "bounds_x": (-1.85, 1.85),
            "bounds_y": (-1.85, 1.85),
        },
    )


# =============================================================================
# Full Environment Config
# =============================================================================

@configclass
class DualRobotDisturbanceEnvCfg(ManagerBasedRLEnvCfg):
    """G1 + UR10e co-simulation for disturbance testing.

    Registered as: ``G1-UR10e-Disturbance-v0``
    """

    scene: DualRobotSceneCfg = DualRobotSceneCfg(num_envs=1, env_spacing=5.0)
    observations: DualRobotObservationsCfg = DualRobotObservationsCfg()
    actions: DualRobotActionsCfg = DualRobotActionsCfg()
    commands: DualRobotCommandsCfg = DualRobotCommandsCfg()
    events: DualRobotEventsCfg = DualRobotEventsCfg()
    rewards: DualRobotRewardsCfg = DualRobotRewardsCfg()
    terminations: DualRobotTerminationsCfg = DualRobotTerminationsCfg()

    def __post_init__(self):
        self.decimation = 4
        # Configurable via env var EPISODE_LENGTH_S; default 300s = 15000 steps
        # at 50 Hz.  B1 (20 parts + replan overhead) needs >10000 steps.
        # run_phase3.py further raises this to cover --max_steps when needed.
        self.episode_length_s = float(os.environ.get("EPISODE_LENGTH_S", "300.0"))
        self.sim.dt = 0.005  # 200 Hz physics
        self.sim.render_interval = self.decimation

        # Ensure G1 contact sensors are active
        self.scene.robot_g1.spawn.activate_contact_sensors = True

        # ——— G1 ↔ UR10e collision handling ———
        #
        # Two-articulation co-simulation requires BOTH measures below:
        #
        # (a) GPU contact buffer size — must be large enough for all rigid
        #     body pairs from two complex articulations. Without this, PhysX
        #     silently drops contacts under heavy load (e.g. G1 walking +
        #     UR10e picking), causing missed foot/floor contacts.
        #
        # (b) Runtime collision-pair filter — disables PhysX collision
        #     RESPONSE between G1 and UR10e articulation root prims. The
        #     safety gate uses FK distance detection (not physics contacts),
        #     so PhysX collision response offers no safety benefit and causes
        #     simulation instability when two heavy articulation chains
        #     intersect.
        #
        #     Filter setup is deferred to the first env reset (event
        #     _setup_g1_ur10e_collision_filter) because the USD stage is
        #     only available after the simulation has started.
        #
        # NOTE: G1 still collides with table/containers/parts; UR10e still
        # collides with parts (gripper grasping).
        if hasattr(self.sim, "physics"):
            self.sim.physics.gpu_max_rigid_contact_count = 2**24

        # Sensor update at physics rate
        self.scene.g1_contact_forces.update_period = self.sim.dt
        self.scene.left_foot_sensor.update_period = self.sim.dt
        self.scene.right_foot_sensor.update_period = self.sim.dt

        # Camera settings (from GMRobot)
        self.wait_for_textures = False
        self.num_rerenders_on_reset = 0

        # Viewer: third-person follow G1, looking at scene centre
        self.viewer.eye = (-4.0, 4.0, 3.0)
        self.viewer.lookat = (0.0, 0.0, 0.5)
        self.viewer.origin_type = "world"
