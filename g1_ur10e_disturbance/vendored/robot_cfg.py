# G1 (29-DOF) walking robot config — migrated from pressure_mat_repro for Isaac Lab 2.x.
#
# Originally at: pressure_mat_repro/isaac_lab_task/pressure_mat_deploy/robot_cfg.py
# Import paths rewired: omni.isaac.lab.* → isaaclab.*
# Config values (joint names, stiffness, damping, init_state, USD path) are UNCHANGED.

from __future__ import annotations

import os

import isaaclab.sim as sim_utils
from isaaclab.actuators import IdealPDActuatorCfg
from isaaclab.assets import ArticulationCfg

from paths import PRESSURE_MAT_USD

# Robot USD — local asset first, fall back to pressure_mat_repro via env var.
_LOCAL_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
if os.path.exists(os.path.join(_LOCAL_ASSETS, "g1_29dof_modified_new_91.usd")):
    _ROBOT_USD = os.path.join(_LOCAL_ASSETS, "g1_29dof_modified_new_91.usd")
else:
    _ROBOT_USD = PRESSURE_MAT_USD


G1_927_WALK_CFG = ArticulationCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=_ROBOT_USD,
        activate_contact_sensors=True,
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            disable_gravity=False,
            retain_accelerations=False,
            linear_damping=0.0,
            angular_damping=0.0,
            max_linear_velocity=1000.0,
            max_angular_velocity=1000.0,
            max_depenetration_velocity=1.0,
        ),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            enabled_self_collisions=True,
            solver_position_iteration_count=8,
            solver_velocity_iteration_count=4,
        ),
    ),
    init_state=ArticulationCfg.InitialStateCfg(
        pos=(0.0, 0.0, 0.8),
        joint_pos={
            ".*_hip_pitch_joint": -0.1,
            ".*_knee_joint": 0.3,
            ".*_ankle_pitch_joint": -0.2,
        },
        joint_vel={".*": 0.0},
    ),
    soft_joint_pos_limit_factor=0.9,
    actuators={
        "legs": IdealPDActuatorCfg(
            joint_names_expr=[
                ".*_hip_yaw_joint",
                ".*_hip_roll_joint",
                ".*_hip_pitch_joint",
                ".*_knee_joint",
                "waist_roll_joint",
                "waist_yaw_joint",
                "waist_pitch_joint",
            ],
            effort_limit={
                ".*_hip_yaw_joint": 88,
                ".*_hip_roll_joint": 88,
                ".*_hip_pitch_joint": 88,
                ".*_knee_joint": 139,
                "waist_roll_joint": 50,
                "waist_yaw_joint": 88,
                "waist_pitch_joint": 50,
            },
            velocity_limit={
                ".*_hip_yaw_joint": 32.0,
                ".*_hip_roll_joint": 32.0,
                ".*_hip_pitch_joint": 32.0,
                ".*_knee_joint": 20.0,
                "waist_roll_joint": 37.0,
                "waist_yaw_joint": 32.0,
                "waist_pitch_joint": 37.0,
            },
            stiffness={
                ".*_hip_yaw_joint": 100.0,
                ".*_hip_roll_joint": 100.0,
                ".*_hip_pitch_joint": 100.0,
                ".*_knee_joint": 150.0,
                "waist_roll_joint": 100.0,
                "waist_yaw_joint": 100.0,
                "waist_pitch_joint": 100.0,
            },
            damping={
                ".*_hip_yaw_joint": 4.0,
                ".*_hip_roll_joint": 4.0,
                ".*_hip_pitch_joint": 4.0,
                ".*_knee_joint": 5.0,
                "waist_roll_joint": 4,
                "waist_yaw_joint": 4.0,
                "waist_pitch_joint": 4.0,
            },
            armature=0.01,
            friction=0.0,
        ),
        "feet": IdealPDActuatorCfg(
            effort_limit=50,
            velocity_limit=37,
            joint_names_expr=[".*_ankle_pitch_joint", ".*_ankle_roll_joint"],
            stiffness=40.0,
            damping={
                ".*_ankle_pitch_joint": 2,
                ".*_ankle_roll_joint": 2,
            },
            armature=0.01,
            friction=0.0,
        ),
        "arms": IdealPDActuatorCfg(
            joint_names_expr=[
                ".*_shoulder_pitch_joint",
                ".*_shoulder_roll_joint",
                ".*_shoulder_yaw_joint",
                ".*_elbow_joint",
                ".*_wrist_roll_joint",
                ".*_wrist_pitch_joint",
                ".*_wrist_yaw_joint",
            ],
            effort_limit={
                ".*_shoulder_pitch_joint": 25,
                ".*_shoulder_roll_joint": 25,
                ".*_shoulder_yaw_joint": 25,
                ".*_elbow_joint": 25,
                ".*_wrist_roll_joint": 25,
                ".*_wrist_pitch_joint": 5,
                ".*_wrist_yaw_joint": 5,
            },
            velocity_limit={
                ".*_shoulder_pitch_joint": 37,
                ".*_shoulder_roll_joint": 37,
                ".*_shoulder_yaw_joint": 37,
                ".*_elbow_joint": 37,
                ".*_wrist_roll_joint": 37,
                ".*_wrist_pitch_joint": 22,
                ".*_wrist_yaw_joint": 22,
            },
            stiffness={
                ".*_shoulder_pitch_joint": 100,
                ".*_shoulder_roll_joint": 100,
                ".*_shoulder_yaw_joint": 50,
                ".*_elbow_joint": 50,
                ".*_wrist_roll_joint": 100,
                ".*_wrist_pitch_joint": 100,
                ".*_wrist_yaw_joint": 100,
            },
            damping={
                ".*_shoulder_pitch_joint": 4,
                ".*_shoulder_roll_joint": 4,
                ".*_shoulder_yaw_joint": 2.5,
                ".*_elbow_joint": 2.5,
                ".*_wrist_roll_joint": 4.0,
                ".*_wrist_pitch_joint": 4.0,
                ".*_wrist_yaw_joint": 4.0,
            },
            armature=0.01,
            friction=0.0,
        ),
    },
)
