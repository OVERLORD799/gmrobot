# Copyright (c) 2022-2024, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""HiRes (64x64 / 4 m) variant of the pressure-mat deploy env.

Task id: ``PressureMat-Walk-G1-Deploy-HiRes-v0``. Same physics / policy / obs
layout as the 32x32 base env, but a finer 64x64 mat (6.3 cm pitch). Used to
validate the ``..._hires_...`` velocity checkpoint. Self-contained.
"""

from __future__ import annotations

import os

from omni.isaac.lab.utils import configclass

from . import mdp
from .deploy_env_cfg import (
    MAT_SIZE_X,
    MAT_SIZE_Y,
    PressureMatWalkG1DeployEnvCfg,
    _DATA_DIR,
    _mat_asset_cfg,
)

_HIRES_ROWS = 64
_HIRES_COLS = 64
_HIRES_MAT_USD = os.path.join(_DATA_DIR, "tactile_mat_64x64_4m.usd")
_HIRES_FILTER_PATHS = [
    f"{{ENV_REGEX_NS}}/Mat/sensor_{r:02d}_{c:02d}"
    for r in range(1, _HIRES_ROWS + 1)
    for c in range(1, _HIRES_COLS + 1)
]


@configclass
class PressureMatWalkG1DeployHiResEnvCfg(PressureMatWalkG1DeployEnvCfg):
    def __post_init__(self):
        super().__post_init__()
        # Swap to the 64x64 mat + matching foot-sensor filters + tactile dims.
        self.scene.mat = _mat_asset_cfg(_HIRES_MAT_USD)
        self.scene.left_foot_sensor.filter_prim_paths_expr = list(_HIRES_FILTER_PATHS)
        self.scene.right_foot_sensor.filter_prim_paths_expr = list(_HIRES_FILTER_PATHS)
        self.scene.left_foot_sensor.update_period = self.sim.dt
        self.scene.right_foot_sensor.update_period = self.sim.dt
        self.observations.policy.tactile.params["rows"] = _HIRES_ROWS
        self.observations.policy.tactile.params["cols"] = _HIRES_COLS
