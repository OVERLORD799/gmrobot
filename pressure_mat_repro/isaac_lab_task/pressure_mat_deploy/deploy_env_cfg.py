# Copyright (c) 2022-2024, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Self-contained pressure-mat walking env for the unitree deploy_walk policy.

Task id: ``PressureMat-Walk-G1-Deploy-v0``.

A G1-29dof humanoid walks on a 32x32 / 4 m x 4 m tactile pressure mat. The
walker observation group (588-dim: 8 terms x 6-step history) is laid out to
match the ``0121_walk.pt`` torchscript policy; the policy is run externally by
the play / collect / validate scripts. The ``policy`` observation group is the
per-taxel Newton image (tactile_force_multi_net, Pasternak-smeared, calibrated
against the feet net contact force).

This module is FULLY SELF-CONTAINED — it depends only on stock IsaacLab 1.3.0
plus the sibling files in this package (robot_cfg, mdp). No edits to IsaacLab
core or asset libraries are required to run it. Drop the ``pressure_mat_deploy``
folder under ``.../lab_tasks/manager_based/`` and it auto-registers.
"""

from __future__ import annotations

import os

import omni.isaac.lab.sim as sim_utils
from omni.isaac.lab.assets import ArticulationCfg, AssetBaseCfg
from omni.isaac.lab.envs import ManagerBasedRLEnvCfg
from omni.isaac.lab.managers import EventTermCfg as EventTerm
from omni.isaac.lab.managers import ObservationGroupCfg as ObsGroup
from omni.isaac.lab.managers import ObservationTermCfg as ObsTerm
from omni.isaac.lab.managers import SceneEntityCfg
from omni.isaac.lab.managers import TerminationTermCfg as DoneTerm
from omni.isaac.lab.scene import InteractiveSceneCfg
from omni.isaac.lab.sensors import ContactSensorCfg
from omni.isaac.lab.utils import configclass
from omni.isaac.lab.utils.noise import AdditiveUniformNoiseCfg as Unoise

from . import mdp
from .robot_cfg import G1_927_WALK_CFG

# ---------------------------------------------------------------------------
# Mat geometry — 32x32 taxels over 4 m x 4 m  (pitch ~12.9 cm).
# ---------------------------------------------------------------------------
ROWS = 32
COLS = 32
MAT_SIZE_X = 4.0
MAT_SIZE_Y = 4.0
COUPLING_LENGTH = 0.01  # 1 cm Pasternak shear smearing

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_MAT_USD = os.path.join(_DATA_DIR, "tactile_mat_32x32_4m.usd")

# Taxels in the mat USD are named sensor_RR_CC (1-indexed, 2-digit).
_TAXEL_FILTER_PATHS = [
    f"{{ENV_REGEX_NS}}/Mat/sensor_{r:02d}_{c:02d}"
    for r in range(1, ROWS + 1)
    for c in range(1, COLS + 1)
]


def _mat_asset_cfg(usd_path: str) -> AssetBaseCfg:
    """Whole-mat USD (all taxels in one file) spawned as a static asset."""
    return AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Mat",
        spawn=sim_utils.UsdFileCfg(usd_path=usd_path),
    )


def _foot_contact_sensor(prim_path: str) -> ContactSensorCfg:
    """ContactSensor on one foot, filtering against every taxel."""
    return ContactSensorCfg(
        prim_path=prim_path,
        filter_prim_paths_expr=list(_TAXEL_FILTER_PATHS),
        update_period=0.005,
        history_length=3,
        track_air_time=True,
    )


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
@configclass
class SceneCfg(InteractiveSceneCfg):
    ground = AssetBaseCfg(prim_path="/World/GroundPlane", spawn=sim_utils.GroundPlaneCfg())
    mat = _mat_asset_cfg(_MAT_USD)
    robot: ArticulationCfg = G1_927_WALK_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
    left_foot_sensor = _foot_contact_sensor("{ENV_REGEX_NS}/Robot/left_ankle_roll_link")
    right_foot_sensor = _foot_contact_sensor("{ENV_REGEX_NS}/Robot/right_ankle_roll_link")
    contact_forces = ContactSensorCfg(
        prim_path="{ENV_REGEX_NS}/Robot/.*", history_length=3, track_air_time=True
    )
    dome_light = AssetBaseCfg(
        prim_path="/World/DomeLight", spawn=sim_utils.DomeLightCfg(intensity=2000.0)
    )


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------
@configclass
class _TactileObsCfg(ObsGroup):
    """Per-taxel Newton image (rows x cols), feet net-force calibrated."""

    tactile = ObsTerm(
        func=mdp.tactile_force_multi_net,
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
class _DeployWalkerObsCfg(ObsGroup):
    """588-dim walker obs (8 terms x 6 history) matching deploy_walk."""

    base_ang_vel = ObsTerm(func=mdp.base_ang_vel, scale=1.0, noise=Unoise(n_min=-0.2, n_max=0.2))
    projected_gravity = ObsTerm(func=mdp.projected_gravity, noise=Unoise(n_min=-0.05, n_max=0.05))
    velocity_commands = ObsTerm(
        func=mdp.velocity_commands_deploy,
        params={"command_name": "base_velocity", "lin_scale": 2.0, "ang_scale": 0.25},
    )
    joint_pos = ObsTerm(
        func=mdp.joint_pos_rel, scale=1.0,
        params={"asset_cfg": SceneEntityCfg("robot")}, noise=Unoise(n_min=-0.01, n_max=0.01),
    )
    joint_vel = ObsTerm(
        func=mdp.joint_vel_rel, scale=1.0,
        params={"asset_cfg": SceneEntityCfg("robot")}, noise=Unoise(n_min=-1.5, n_max=1.5),
    )
    actions = ObsTerm(func=mdp.last_action_padded_29, params={"action_name": "joint_pos"})
    sin_phase = ObsTerm(func=mdp.walk_sin_phase,
                        params={"command_name": "base_velocity", "period": mdp._PHASE_PERIOD})
    cos_phase = ObsTerm(func=mdp.walk_cos_phase,
                        params={"command_name": "base_velocity", "period": mdp._PHASE_PERIOD})

    def __post_init__(self):
        self.history_length = 6
        self.enable_corruption = False
        self.concatenate_terms = True


@configclass
class ObservationsCfg:
    policy: _TactileObsCfg = _TactileObsCfg()
    walker: _DeployWalkerObsCfg = _DeployWalkerObsCfg()


# ---------------------------------------------------------------------------
# Actions / Commands / Events / Rewards / Terminations
# ---------------------------------------------------------------------------
@configclass
class ActionsCfg:
    joint_pos = mdp.WalkJointActionCfg(
        asset_name="robot",
        joint_names=[".*hip.*", ".*ankle.*", ".*knee.*"],
        scale=0.25,
        use_default_offset=True,
        clip={".*_joint": (-100.0, 100.0)},
    )


@configclass
class CommandsCfg:
    base_velocity = mdp.UniformVelocityCommandCfg(
        asset_name="robot",
        resampling_time_range=(4.0, 4.0),
        rel_standing_envs=0.02,
        rel_heading_envs=1.0,
        heading_command=False,
        debug_vis=False,
        ranges=mdp.UniformVelocityCommandCfg.Ranges(
            lin_vel_x=(-0.8, 0.8), lin_vel_y=(-0.5, 0.5), ang_vel_z=(-1.57, 1.57)
        ),
    )


@configclass
class EventsCfg:
    reset_base = EventTerm(
        func=mdp.reset_root_state_uniform, mode="reset",
        params={"asset_cfg": SceneEntityCfg("robot"),
                "pose_range": {"x": (-0.1, 0.1), "y": (-0.1, 0.1), "yaw": (-0.1, 0.1)},
                "velocity_range": {}},
    )
    reset_robot_joints = EventTerm(
        func=mdp.reset_joints_by_scale, mode="reset",
        params={"asset_cfg": SceneEntityCfg("robot"),
                "position_range": (1.0, 1.0), "velocity_range": (0.0, 0.0)},
    )
    # Foot friction matched to the ground plane (0.8/0.6) — what the deploy
    # policy was trained against; keeps the gait stable on the mat.
    robot_friction = EventTerm(
        func=mdp.randomize_rigid_body_material, mode="reset",
        params={"asset_cfg": SceneEntityCfg("robot", body_names=".*"),
                "static_friction_range": (0.8, 0.8), "dynamic_friction_range": (0.6, 0.6),
                "restitution_range": (0.0, 0.0), "num_buckets": 64},
    )


@configclass
class RewardsCfg:
    """No rewards — the walking policy is a fixed external torchscript; this env
    is used only for inference / data collection."""
    pass


@configclass
class TerminationsCfg:
    time_out = DoneTerm(func=mdp.time_out, time_out=True)
    base_height = DoneTerm(
        func=mdp.root_height_below_minimum,
        params={"asset_cfg": SceneEntityCfg("robot"), "minimum_height": 0.2},
    )
    out_of_mat = DoneTerm(
        func=mdp.root_out_of_mat_bounds,
        params={"asset_cfg": SceneEntityCfg("robot"),
                "bounds_x": (-1.85, 1.85), "bounds_y": (-1.85, 1.85)},
    )


# ---------------------------------------------------------------------------
# Env config
# ---------------------------------------------------------------------------
@configclass
class PressureMatWalkG1DeployEnvCfg(ManagerBasedRLEnvCfg):
    scene: SceneCfg = SceneCfg(num_envs=1, env_spacing=4.0)
    observations: ObservationsCfg = ObservationsCfg()
    actions: ActionsCfg = ActionsCfg()
    commands: CommandsCfg = CommandsCfg()
    events: EventsCfg = EventsCfg()
    rewards: RewardsCfg = RewardsCfg()
    terminations: TerminationsCfg = TerminationsCfg()

    def __post_init__(self):
        self.decimation = 4
        self.episode_length_s = 6.0
        self.sim.dt = 0.005  # 200 Hz physics; control at 50 Hz (decimation 4)
        self.sim.render_interval = self.decimation
        # Ensure the robot's foot bodies report contacts for the foot sensors.
        self.scene.robot.spawn.activate_contact_sensors = True
        # Sensor update at physics rate.
        self.scene.contact_forces.update_period = self.sim.dt
        self.scene.left_foot_sensor.update_period = self.sim.dt
        self.scene.right_foot_sensor.update_period = self.sim.dt
        # Third-person follow camera so the robot stays in frame while walking.
        self.viewer.eye = (-4.0, 4.0, 3.0)
        self.viewer.lookat = (0.0, 0.0, 0.5)
        self.viewer.origin_type = "asset_root"
        self.viewer.asset_name = "robot"
