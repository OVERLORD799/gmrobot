from __future__ import annotations

import math
import os

import torch

import isaaclab.envs.mdp as mdp
import isaaclab.sim as sim_utils
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.controllers import DifferentialIKControllerCfg
from isaaclab.envs import ManagerBasedRLEnvCfg
from isaaclab.envs.mdp.actions.actions_cfg import DifferentialInverseKinematicsActionCfg
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import RewardTermCfg as RewTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors.camera.camera_cfg import CameraCfg
from isaaclab.sensors.camera.tiled_camera_cfg import TiledCameraCfg
from isaaclab.sim.schemas.schemas_cfg import RigidBodyPropertiesCfg
from isaaclab.utils import configclass
from isaaclab.utils.assets import ISAAC_NUCLEUS_DIR
from isaaclab.utils.math import combine_frame_transforms, quat_from_euler_xyz, matrix_from_quat

from ....assets.ur10e_cfg import UR10E_CFG
from .mdp import safety_obs


# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, "../../../assets"))

CONTAINER_USD = os.path.join(_ASSETS_DIR, "container.usd")
DIVIDER_USD = os.path.join(_ASSETS_DIR, "container/GM_Container_Slim_Divider_Sim.usd")
PART_USD = os.path.join(_ASSETS_DIR, "part/part_5000.usd")


# --------------------------------------------------------------------------------------
# Scene constants
# --------------------------------------------------------------------------------------

CONTAINER_ROT = (0.5, 0.5, 0.5, 0.5)
GRID_ROT = (0.7071068, -0.7071068, 0.0, 0.0)
GRID_OFFSET = (-0.27305, -0.16637, 0.10)

CONTAINER_POSES = {
    "A": (0.75, -0.25, 0.0),
    "B": (0.75, 0.25, 0.0),
}

CONTAINER_YAWS = {
    "A": 0.0,
    "B": 0.0,
}

CONTAINER_SCALE = (0.01, 0.01, 0.01)

CONTAINER_X_SLOTS = 5
CONTAINER_Y_SLOTS = 4
CONTAINER_X_GAP = 0.11042
CONTAINER_Y_GAP = 0.07

PART_HEIGHT = 0.17
PART_DEFAULT_ROT = (0.7071068, 0.0, -0.7071068, 0.0)
PART_SLOT_COUNT = CONTAINER_X_SLOTS * CONTAINER_Y_SLOTS
PART_LOCATIONS = [f"A@{i}" for i in range(1, PART_SLOT_COUNT + 1)]

ARM_JOINT_NAMES = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
]

GRIPPER_JOINT_NAMES = [
    "finger_joint",
    "right_outer_knuckle_joint",
    "right_inner_finger_joint",
    "right_inner_finger_knuckle_joint",
    "left_inner_finger_knuckle_joint",
    "left_inner_finger_joint",
]

GRIPPER_CLOSED = math.pi / 4.0
GRIPPER_OPEN = 0.4 * GRIPPER_CLOSED


# --------------------------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------------------------

def _yaw_quat(yaw: float) -> torch.Tensor:
    """Return quaternion (w, x, y, z) for a pure yaw rotation."""
    zero = torch.zeros(1, dtype=torch.float32)
    yaw_tensor = torch.tensor([yaw], dtype=torch.float32)
    return quat_from_euler_xyz(zero, zero, yaw_tensor)


def _compose_pose(
    base_pos: tuple[float, float, float],
    base_yaw: float,
    local_pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    local_rot: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """Compose a local pose inside a yaw-rotated parent frame."""
    t01 = torch.tensor([base_pos], dtype=torch.float32)
    q01 = _yaw_quat(base_yaw)
    t12 = torch.tensor([local_pos], dtype=torch.float32)
    q12 = torch.tensor([local_rot], dtype=torch.float32)

    pos, quat = combine_frame_transforms(t01, q01, t12, q12)
    return tuple(pos[0].tolist()), tuple(quat[0].tolist())


def _slot_local_offset(slot_idx_zero_based: int) -> tuple[float, float, float]:
    """Return slot center position in the container-local frame."""
    x_idx = slot_idx_zero_based // CONTAINER_Y_SLOTS
    y_idx = slot_idx_zero_based % CONTAINER_Y_SLOTS

    x_center = 0.5 * (CONTAINER_X_SLOTS - 1) * CONTAINER_X_GAP
    y_center = 0.5 * (CONTAINER_Y_SLOTS - 1) * CONTAINER_Y_GAP

    x = x_idx * CONTAINER_X_GAP - x_center
    y = y_idx * CONTAINER_Y_GAP - y_center
    z = PART_HEIGHT
    return (x, y, z)


def build_container_grid_assets() -> dict[str, AssetBaseCfg]:
    assets: dict[str, AssetBaseCfg] = {}

    for container_name, container_pos in CONTAINER_POSES.items():
        container_yaw = CONTAINER_YAWS[container_name]

        box_pos, box_rot = _compose_pose(
            base_pos=container_pos,
            base_yaw=container_yaw,
            local_rot=CONTAINER_ROT,
        )
        grid_pos, grid_rot = _compose_pose(
            base_pos=container_pos,
            base_yaw=container_yaw,
            local_pos=GRID_OFFSET,
            local_rot=GRID_ROT,
        )

        assets[f"box_{container_name}"] = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Container{container_name}",
            init_state=AssetBaseCfg.InitialStateCfg(pos=box_pos, rot=box_rot),
            spawn=sim_utils.UsdFileCfg(
                usd_path=CONTAINER_USD,
                scale=CONTAINER_SCALE,
            ),
        )

        assets[f"grid_{container_name}"] = AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Grid{container_name}",
            init_state=AssetBaseCfg.InitialStateCfg(pos=grid_pos, rot=grid_rot),
            spawn=sim_utils.UsdFileCfg(usd_path=DIVIDER_USD),
        )

    return assets


def build_part_assets() -> dict[str, RigidObjectCfg]:
    assets: dict[str, RigidObjectCfg] = {}

    for idx, location in enumerate(PART_LOCATIONS, start=1):
        container_id, slot_id_str = location.split("@")
        slot_id = int(slot_id_str) - 1

        part_pos, part_rot = _compose_pose(
            base_pos=CONTAINER_POSES[container_id],
            base_yaw=CONTAINER_YAWS[container_id],
            local_pos=_slot_local_offset(slot_id),
            local_rot=PART_DEFAULT_ROT,
        )

        assets[f"part_{idx}"] = RigidObjectCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Part_{idx}",
            init_state=RigidObjectCfg.InitialStateCfg(
                pos=part_pos,
                rot=part_rot,
            ),
            spawn=sim_utils.UsdFileCfg(
                usd_path=PART_USD,
                scale=(1.0, 1.0, 1.0),
                rigid_props=RigidBodyPropertiesCfg(
                    solver_position_iteration_count=32,
                    solver_velocity_iteration_count=4,
                    max_angular_velocity=1000.0,
                    max_linear_velocity=1000.0,
                    max_depenetration_velocity=5.0,
                    disable_gravity=False,
                ),
                semantic_tags=[("class", f"part_{idx}")],
                mass_props=sim_utils.MassPropertiesCfg(mass=0.2),
            ),
        )

    return assets


CONTAINER_ASSETS = build_container_grid_assets()
PART_ASSETS = build_part_assets()


# --------------------------------------------------------------------------------------
# Custom observations
# --------------------------------------------------------------------------------------

def ee_pos_w(
    env,
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot", body_names="wrist_3_link"),
) -> torch.Tensor:
    """Return end-effector body link position in world frame."""
    robot = env.scene[asset_cfg.name]
    return robot.data.body_link_pos_w[:, asset_cfg.body_ids].reshape(env.num_envs, -1)


def get_static_box_pos(env, box_name: str) -> torch.Tensor:
    """Return a fixed container position repeated across environments."""
    pos = torch.tensor(CONTAINER_POSES[box_name], device=env.device, dtype=torch.float32)
    yaw = CONTAINER_YAWS[box_name]
    rot = _yaw_quat(yaw)
    T = torch.eye(4, device=env.device, dtype=torch.float32)
    T[:3, :3] = matrix_from_quat(rot)
    T[:3, 3] = pos
    return T.unsqueeze(0).repeat(env.num_envs, 1, 1)


def get_static_slot_transform(env, container_id: str, slot_id: int) -> torch.Tensor:
    """Return slot transform T as a flattened 4x4 matrix, shape (num_envs, 4, 4)."""
    slot_pos, slot_rot = _compose_pose(
        base_pos=CONTAINER_POSES[container_id],
        base_yaw=CONTAINER_YAWS[container_id],
        local_pos=_slot_local_offset(slot_id - 1),  # slot_id is 1-based externally
    )

    pos = torch.tensor(slot_pos, device=env.device, dtype=torch.float32).unsqueeze(0)   # (1, 3)
    quat = torch.tensor(slot_rot, device=env.device, dtype=torch.float32).unsqueeze(0)  # (1, 4)

    rot = matrix_from_quat(quat)  # (1, 3, 3)

    T = torch.eye(4, device=env.device, dtype=torch.float32)
    T[:3, :3] = rot
    T[:3, 3] = pos

    return T.unsqueeze(0).repeat(env.num_envs, 1, 1)


def build_box_observations() -> dict[str, ObsTerm]:
    return {
        f"box_{box_name}_pos": ObsTerm(
            func=get_static_box_pos,
            params={"box_name": box_name},
        )
        for box_name in CONTAINER_POSES
    }


def build_part_observations() -> dict[str, ObsTerm]:
    return {
        f"part_{idx}_pos": ObsTerm(
            func=mdp.body_pose_w,
            params={"asset_cfg": SceneEntityCfg(f"part_{idx}")},
        )
        for idx in range(1, len(PART_LOCATIONS) + 1)
    }


def build_slot_observations() -> dict[str, ObsTerm]:
    obs = {}
    for container_id in CONTAINER_POSES:
        for slot_id in range(1, CONTAINER_X_SLOTS * CONTAINER_Y_SLOTS + 1):
            obs[f"slot_{container_id}_{slot_id}_T"] = ObsTerm(
                func=get_static_slot_transform,
                params={
                    "container_id": container_id,
                    "slot_id": slot_id,
                },
            )
    return obs


OBS_BOXES = build_box_observations()
OBS_PARTS = build_part_observations()
OBS_SLOTS = build_slot_observations()

# --------------------------------------------------------------------------------------
# Scene configuration
# --------------------------------------------------------------------------------------

@configclass
class UR10eGMSceneCfg(InteractiveSceneCfg):
    """Scene: UR10e mounted on a table with containers, dividers, parts, and a camera."""

    ground = AssetBaseCfg(
        prim_path="/World/defaultGroundPlane",
        spawn=sim_utils.GroundPlaneCfg(),
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.0, 0.0, -1.05)),
    )

    dome_light = AssetBaseCfg(
        prim_path="/World/Light",
        spawn=sim_utils.DomeLightCfg(intensity=3000.0, color=(0.75, 0.75, 0.75)),
    )

    table = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Table",
        spawn=sim_utils.UsdFileCfg(
            usd_path=f"{ISAAC_NUCLEUS_DIR}/Props/Mounts/SeattleLabTable/table_instanceable.usd",
        ),
        init_state=AssetBaseCfg.InitialStateCfg(
            pos=(0.6, 0.0, 0.0),
            rot=(0.70711, 0.0, 0.0, 0.70711),
        ),
    )

    robot: ArticulationCfg = UR10E_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")

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
        offset=CameraCfg.OffsetCfg(
            pos=(0.35, 0.0, 2.5),
            rot=(0.7071, 0.0, 0.7071, 0.0),
            convention="world",
        ),
    )

    locals().update(CONTAINER_ASSETS)
    locals().update(PART_ASSETS)

    human_hand: RigidObjectCfg = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/HumanHand",
        init_state=RigidObjectCfg.InitialStateCfg(
            pos=(0.45, -0.35, 0.18),
            rot=(1.0, 0.0, 0.0, 0.0),
        ),
        spawn=sim_utils.SphereCfg(
            radius=0.05,
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.9, 0.3, 0.2)),
            physics_material=sim_utils.RigidBodyMaterialCfg(static_friction=0.5),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                kinematic_enabled=True,
                disable_gravity=True,
                max_depenetration_velocity=1.0,
            ),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
        ),
    )

    # Optional human torso: larger kinematic sphere below the hand (W17/R2).
    # Enabled when human_torso_radius > 0 in safety YAML config.
    human_torso: RigidObjectCfg = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/HumanTorso",
        init_state=RigidObjectCfg.InitialStateCfg(
            pos=(0.45, -0.35, -0.12),  # 30cm below hand centre
            rot=(1.0, 0.0, 0.0, 0.0),
        ),
        spawn=sim_utils.SphereCfg(
            radius=0.15,  # ~30cm torso sphere
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.3, 0.5, 0.9)),
            physics_material=sim_utils.RigidBodyMaterialCfg(static_friction=0.5),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                kinematic_enabled=True,
                disable_gravity=True,
                max_depenetration_velocity=1.0,
            ),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=1.0),
        ),
    )


# --------------------------------------------------------------------------------------
# MDP: Actions
# --------------------------------------------------------------------------------------

@configclass
class ActionsCfg:
    """Action specs: end-effector Cartesian control using differential IK."""

    ee_cartesian = DifferentialInverseKinematicsActionCfg(
        asset_name="robot",
        body_name="wrist_3_link",
        joint_names=ARM_JOINT_NAMES,
        controller=DifferentialIKControllerCfg(
            command_type="pose",
            use_relative_mode=False,
            ik_method="dls",
        ),
        body_offset=DifferentialInverseKinematicsActionCfg.OffsetCfg(pos=[0.0, 0.0, 0.15]),
    )

    gripper_actions = mdp.BinaryJointPositionActionCfg(
        asset_name="robot",
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


# --------------------------------------------------------------------------------------
# MDP: Observations
# --------------------------------------------------------------------------------------

@configclass
class ObservationsGMCfg:
    """Observation specs for the MDP."""

    @configclass
    class PolicyCfg(ObsGroup):
        """Observations for the policy."""

        ee_pos = ObsTerm(
            func=mdp.body_pose_w,
            params={"asset_cfg": SceneEntityCfg("robot", body_names="wrist_3_link")},
        )

        locals().update(OBS_BOXES)
        locals().update(OBS_PARTS)
        locals().update(OBS_SLOTS)

        def __post_init__(self):
            self.concatenate_terms = False

    @configclass
    class FlatPolicyCfg(ObsGroup):
        """PPO-only: 1D vector terms only (no 4×4 matrices).

        Drops boxes and slots—only EE pose and part positions.
        All terms are (7,) so torch.stack works for multi-env PPO.
        """

        ee_pos = ObsTerm(
            func=mdp.body_pose_w,
            params={"asset_cfg": SceneEntityCfg("robot", body_names="wrist_3_link")},
        )
        locals().update(OBS_PARTS)  # 20 × (7,) — same shape, stackable

        def __post_init__(self):
            self.concatenate_terms = True  # PPO: all terms (7,) → single flat Box

    policy: PolicyCfg = PolicyCfg()
    flat_policy: FlatPolicyCfg = FlatPolicyCfg()

    @configclass
    class CameraCfg(ObsGroup):
        """Camera observations. Reserved for downstream vision modules."""

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

    camera: CameraCfg = CameraCfg()

    @configclass
    class SafetyCfg(ObsGroup):
        """Privileged safety observations for Layer 1 (does not modify policy/camera groups)."""

        ee_vel = ObsTerm(
            func=safety_obs.ee_lin_vel_w,
            params={"asset_cfg": SceneEntityCfg("robot", body_names="wrist_3_link")},
        )
        human_hand_pos = ObsTerm(
            func=safety_obs.human_hand_pos_w,
            params={"asset_cfg": SceneEntityCfg("human_hand")},
        )
        human_hand_vel = ObsTerm(
            func=safety_obs.human_hand_vel_w,
            params={"asset_cfg": SceneEntityCfg("human_hand")},
        )
        human_torso_pos = ObsTerm(
            func=safety_obs.human_torso_pos_w,
            params={"asset_cfg": SceneEntityCfg("human_torso")},
        )
        human_torso_vel = ObsTerm(
            func=safety_obs.human_torso_vel_w,
            params={"asset_cfg": SceneEntityCfg("human_torso")},
        )
        joint_pos = ObsTerm(
            func=safety_obs.arm_joint_pos,
            params={"asset_cfg": SceneEntityCfg("robot", joint_names=ARM_JOINT_NAMES)},
        )
        joint_vel = ObsTerm(
            func=safety_obs.arm_joint_vel,
            params={"asset_cfg": SceneEntityCfg("robot", joint_names=ARM_JOINT_NAMES)},
        )

        def __post_init__(self):
            self.concatenate_terms = False

    safety: SafetyCfg = SafetyCfg()


# --------------------------------------------------------------------------------------
# MDP: Rewards
# --------------------------------------------------------------------------------------

@configclass
class RewardsCfg:
    """Reward terms for the MDP."""

    is_alive = RewTerm(
        func=mdp.is_alive,
        weight=1.0,
    )


# --------------------------------------------------------------------------------------
# MDP: Terminations & Events
# --------------------------------------------------------------------------------------

@configclass
class TerminationsCfg:
    """Termination conditions."""
    pass


@configclass
class EventGMCfg:
    """Events (resets, randomization, etc.)."""

    reset_scene_to_default = EventTerm(
        func=mdp.reset_scene_to_default,
        mode="reset",
    )

    reset_joints = EventTerm(
        func=mdp.reset_joints_by_offset,
        mode="reset",
        params={
            "position_range": (0.0, 0.0),
            "velocity_range": (0.0, 0.0),
            "asset_cfg": SceneEntityCfg("robot"),
        },
    )


# --------------------------------------------------------------------------------------
# Env config
# --------------------------------------------------------------------------------------

@configclass
class UR10eGMEnvCfg(ManagerBasedRLEnvCfg):
    """Manager-based RL env: UR10e on a table reaching/manipulating around fixed containers."""

    scene: UR10eGMSceneCfg = UR10eGMSceneCfg(
        num_envs=1,
        env_spacing=2.0,
    )

    observations: ObservationsGMCfg = ObservationsGMCfg()
    actions: ActionsCfg = ActionsCfg()
    rewards: RewardsCfg = RewardsCfg()
    terminations: TerminationsCfg = TerminationsCfg()
    events: EventGMCfg = EventGMCfg()

    def __post_init__(self):
        self.sim.dt = 1.0 / 200.0
        self.decimation = 4
        self.episode_length_s = 40.0
        # Headless + TiledCamera (RTX): reset() can hang forever in
        # `while SimulationManager.assets_loading(): sim.render()` when wait_for_textures=True.
        self.wait_for_textures = False
        self.num_rerenders_on_reset = 0
        self.sim.render_interval = self.decimation