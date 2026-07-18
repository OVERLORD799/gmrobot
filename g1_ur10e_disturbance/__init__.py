"""GMDisturb — G1 humanoid + UR10e arm co-simulation for disturbance testing.

Registered tasks:
    ``G1-UR10e-Disturbance-v0`` — 32×32 pressure mat, full scene

Import this package to register the task with gymnasium:
    >>> import g1_ur10e_disturbance
    >>> env = gym.make("G1-UR10e-Disturbance-v0")
"""

import gymnasium as gym

from dual_env_cfg import DualRobotDisturbanceEnvCfg

gym.register(
    id="G1-UR10e-Disturbance-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": DualRobotDisturbanceEnvCfg},
)
