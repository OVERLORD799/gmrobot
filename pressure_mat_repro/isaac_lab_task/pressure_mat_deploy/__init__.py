# Copyright (c) 2022-2024, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Self-contained pressure-mat walking task for the unitree deploy_walk policy.

Drop this ``pressure_mat_deploy`` folder under
``.../omni/isaac/lab_tasks/manager_based/`` of a STOCK IsaacLab 1.3.0 install.
On ``import omni.isaac.lab_tasks`` it auto-registers two gym tasks:

  * ``PressureMat-Walk-G1-Deploy-v0``        — 32x32 / 4 m mat (the demo task)
  * ``PressureMat-Walk-G1-Deploy-HiRes-v0``  — 64x64 / 4 m mat (ablation)

No edits to IsaacLab core or asset libraries are required.
"""

import gymnasium as gym

from . import deploy_env_cfg, deploy_hires_env_cfg

gym.register(
    id="PressureMat-Walk-G1-Deploy-v0",
    entry_point="omni.isaac.lab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": deploy_env_cfg.PressureMatWalkG1DeployEnvCfg},
)

gym.register(
    id="PressureMat-Walk-G1-Deploy-HiRes-v0",
    entry_point="omni.isaac.lab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": deploy_hires_env_cfg.PressureMatWalkG1DeployHiResEnvCfg},
)
