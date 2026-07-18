# source/<YourProjectName>/<YourProjectName>/assets/ur10e_cfg.py

import os

import isaaclab.sim as sim_utils
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets.articulation import ArticulationCfg

from paths import GMROBOT_ASSETS as _ASSETS_DIR, UR10E_USD_PATH as UR10E_USD

"""
Configuration for UR10e robot asset.

Link names:
    'base_link',
    'shoulder_link',
    'upper_arm_link',
    'forearm_link',
    'wrist_1_link',
    'wrist_2_link',
    'wrist_3_link',
    
    'base_link_0',
    'left_outer_knuckle',
    'right_outer_knuckle',
    'left_outer_finger',
    'right_outer_finger',
    'left_inner_finger',
    'right_inner_finger',
    'left_inner_knuckle',
    'right_inner_knuckle'

Joint names:
    'shoulder_pan_joint',
    'shoulder_lift_joint',
    'elbow_joint',
    'wrist_1_joint',
    'wrist_2_joint',
    'wrist_3_joint',
    
    'finger_joint',
    'right_outer_knuckle_joint',
    'left_inner_finger_joint',
    'right_inner_finger_joint',
    'left_inner_finger_knuckle_joint',
    'right_inner_finger_knuckle_joint'
"""

# Desk-mounted variant — same robot, base raised to table height.
# Used by GMDisturb because the Isaac Sim reference grid cannot be moved.
_DESK_Z = float(os.environ.get("UR10E_DESK_Z", "1.05"))

UR10E_DESK_CFG = ArticulationCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=UR10E_USD,
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            disable_gravity=True,
            max_depenetration_velocity=5.0,
        ),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            enabled_self_collisions=False, solver_position_iteration_count=16, solver_velocity_iteration_count=1
        ),
        activate_contact_sensors=False,
    ),
    init_state=ArticulationCfg.InitialStateCfg(
        joint_pos={
            "shoulder_pan_joint": 0,
            "shoulder_lift_joint": -1.5707963267948966,
            "elbow_joint": 1.5707963267948966,
            "wrist_1_joint": -1.5707963267948966,
            "wrist_2_joint": -1.5707963267948966,
            "wrist_3_joint": 0.0,
        },
        pos=(0.0, 0.0, _DESK_Z),
        rot=(1.0, 0.0, 0.0, 0.0),
    ),
    actuators={
        "shoulder": ImplicitActuatorCfg(
            joint_names_expr=["shoulder_.*"],
            stiffness=1320.0, damping=72.6636085, friction=0.0, armature=0.0,
        ),
        "elbow": ImplicitActuatorCfg(
            joint_names_expr=["elbow_joint"],
            stiffness=600.0, damping=34.64101615, friction=0.0, armature=0.0,
        ),
        "wrist": ImplicitActuatorCfg(
            joint_names_expr=["wrist_.*"],
            stiffness=216.0, damping=29.39387691, friction=0.0, armature=0.0,
        ),
        "gripper": ImplicitActuatorCfg(
            joint_names_expr=[
                'finger_joint', 'right_outer_knuckle_joint',
                'left_inner_finger_joint', 'right_inner_finger_joint',
                'left_inner_finger_knuckle_joint', 'right_inner_finger_knuckle_joint',
            ],
            stiffness=800, damping=4.0, friction=0.0, armature=0.0,
        ),
    },
)

# Original floor-standing UR10e (kept for GMRobot compatibility).
UR10E_CFG = ArticulationCfg(
    spawn=sim_utils.UsdFileCfg(
        usd_path=UR10E_USD,
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            disable_gravity=True,
            max_depenetration_velocity=5.0,
        ),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            enabled_self_collisions=False, solver_position_iteration_count=16, solver_velocity_iteration_count=1
        ),
        activate_contact_sensors=False,
    ),
    init_state=ArticulationCfg.InitialStateCfg(
        joint_pos={
            "shoulder_pan_joint": 0,
            "shoulder_lift_joint": -1.5707963267948966,
            "elbow_joint": 1.5707963267948966,
            "wrist_1_joint": -1.5707963267948966,
            "wrist_2_joint": -1.5707963267948966,
            "wrist_3_joint": 0.0,
        },
        pos=(0.0, 0.0, 0.0),
        rot=(1.0, 0.0, 0.0, 0.0),
    ),
    actuators={
        # 'shoulder_pan_joint', 'shoulder_lift_joint', 'elbow_joint', 'wrist_1_joint', 'wrist_2_joint', 'wrist_3_joint'
        "shoulder": ImplicitActuatorCfg(
            joint_names_expr=["shoulder_.*"],
            stiffness=1320.0,
            damping=72.6636085,
            friction=0.0,
            armature=0.0,
        ),
        "elbow": ImplicitActuatorCfg(
            joint_names_expr=["elbow_joint"],
            stiffness=600.0,
            damping=34.64101615,
            friction=0.0,
            armature=0.0,
        ),
        "wrist": ImplicitActuatorCfg(
            joint_names_expr=["wrist_.*"],
            stiffness=216.0,
            damping=29.39387691,
            friction=0.0,
            armature=0.0,
        ),
        "gripper": ImplicitActuatorCfg(
            joint_names_expr=[
                'finger_joint',
                'right_outer_knuckle_joint',
                'left_inner_finger_joint',
                'right_inner_finger_joint',
                'left_inner_finger_knuckle_joint',
                'right_inner_finger_knuckle_joint'
            ],
            stiffness=800,
            damping=4.0,
            friction=0.0,
            armature=0.0,
        ),
    },
)