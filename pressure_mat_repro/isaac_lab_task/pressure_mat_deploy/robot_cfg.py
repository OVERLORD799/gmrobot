# Self-contained G1 (29-DOF) walking robot config for the pressure-mat deploy task.
#
# This is the project's custom ``G1_927_WALK_CFG`` (originally appended to
# omni/isaac/lab_assets/unitree.py) vendored into the task package so the task
# imports cleanly on a STOCK IsaacLab 1.3.0 with no core/asset-lib edits.
# Uses only stock IsaacLab symbols (ArticulationCfg, IdealPDActuatorCfg,
# sim_utils.*). The robot USD ships alongside in ./data/.

from __future__ import annotations

import os

import omni.isaac.lab.sim as sim_utils
from omni.isaac.lab.actuators import IdealPDActuatorCfg
from omni.isaac.lab.assets import ArticulationCfg

# Robot USD lives next to this file (package-relative, so the package is
# relocatable — no dependence on the IsaacLab source tree layout).
_ROBOT_USD = os.path.join(os.path.dirname(__file__), "data", "g1_29dof_modified_new_91.usd")


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
            enabled_self_collisions=True, solver_position_iteration_count=8, solver_velocity_iteration_count=4
        ),
        #collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0., rest_offset=-0.),
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
            friction=0.,
        ),
    },
)
