#!/usr/bin/env bash
# Quick activation for Isaac Sim 5.1 + GMrobot workspace
source "${HOME}/anaconda3/etc/profile.d/conda.sh"
conda activate env_isaaclab
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
export ISAACLAB_ROOT="${ISAACLAB_ROOT:-${HOME}/IsaacLab}"
export OMNI_KIT_ACCEPT_EULA=YES
export PATH="${CONDA_PREFIX}/bin:${PATH}"
echo "Isaac Sim 5.1.0 + Isaac Lab v2.3.2"
echo "  CONDA_PREFIX=${CONDA_PREFIX}"
echo "  ISAACLAB_ROOT=${ISAACLAB_ROOT}"
echo "  GMROBOT_ROOT=${GMROBOT_ROOT}"
echo "  GMDISTURB_ROOT=${GMDISTURB_ROOT}"
