#!/usr/bin/env bash
# GMrobot workspace environment — source from scripts:
#   source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/env.sh"
GMROBOT_WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export GMDISTURB_ROOT="${GMDISTURB_ROOT:-${GMROBOT_WORKSPACE}/g1_ur10e_disturbance}"
export GMROBOT_ROOT="${GMROBOT_ROOT:-${GMROBOT_WORKSPACE}/GMRobot}"
export PRESSURE_MAT_ROOT="${PRESSURE_MAT_ROOT:-${GMROBOT_WORKSPACE}/pressure_mat_repro}"

# External deps (override via env if installed elsewhere)
export ISAACLAB_ROOT="${ISAACLAB_ROOT:-${HOME}/IsaacLab}"
export ISAAC_SIM_VERSION="${ISAAC_SIM_VERSION:-5.1.0}"
export ISAACLAB_TAG="${ISAACLAB_TAG:-v2.3.2}"
export CONDA_PREFIX="${CONDA_PREFIX:-${HOME}/anaconda3/envs/env_isaaclab}"
export OMNI_KIT_ACCEPT_EULA="${OMNI_KIT_ACCEPT_EULA:-YES}"
