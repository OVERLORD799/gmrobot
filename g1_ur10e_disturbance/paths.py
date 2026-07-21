"""Centralised path constants for GMDisturb.

Reads from environment variables with workspace-relative fallbacks.
Import from this module instead of calling ``os.environ.get()`` with a
hardcoded ``/root/...`` default scattered across the codebase.

Usage::

    from paths import GMDISTURB_ROOT, GMROBOT_ROOT, PHASE3_SCRIPT
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Workspace layout: GMrobot/{g1_ur10e_disturbance, GMRobot, pressure_mat_repro}
_GMDISTURB_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _GMDISTURB_DIR.parent

# ---------------------------------------------------------------------------
# Primary roots (env var → workspace-relative fallback)
# ---------------------------------------------------------------------------

GMDISTURB_ROOT = os.environ.get("GMDISTURB_ROOT", str(_GMDISTURB_DIR))
GMROBOT_ROOT = os.environ.get("GMROBOT_ROOT", str(_WORKSPACE_ROOT / "GMRobot"))
ISAACLAB_ROOT = os.environ.get("ISAACLAB_ROOT", str(Path.home() / "IsaacLab"))
CONDA_PREFIX = os.environ.get(
    "CONDA_PREFIX", str(Path.home() / "anaconda3" / "envs" / "env_isaaclab")
)
PRESSURE_MAT_ROOT = os.environ.get(
    "PRESSURE_MAT_ROOT", str(_WORKSPACE_ROOT / "pressure_mat_repro")
)

# ---------------------------------------------------------------------------
# Derived paths
# ---------------------------------------------------------------------------

# Executables
# Prefer ISAAC_PYTHON (Docker / Isaac Kit) over bare-metal conda fallback.
# Do not invent CONDA_PREFIX inside containers — set ISAAC_PYTHON instead.
ISAAC_PYTHON = os.environ.get("ISAAC_PYTHON", "")
CONDA_PYTHON = os.path.join(CONDA_PREFIX, "bin", "python3")


def resolve_python() -> str:
    """Return the interpreter that should launch Isaac / phase3 subprocesses."""
    if ISAAC_PYTHON and os.path.exists(ISAAC_PYTHON):
        return ISAAC_PYTHON
    if os.path.exists(CONDA_PYTHON):
        return CONDA_PYTHON
    return sys.executable


# Back-compat alias used by batch runners
PYTHON = resolve_python()

# GMDisturb project
PHASE3_SCRIPT = os.path.join(GMDISTURB_ROOT, "scripts", "run_phase3.py")
DEFAULT_CONFIG_PATH = os.path.join(GMDISTURB_ROOT, "config", "default.yaml")

# GMRobot source tree
GMROBOT_ASSETS = os.path.join(
    GMROBOT_ROOT, "source", "GMRobot", "GMRobot", "assets"
)
GMROBOT_SAFETY = os.path.join(GMROBOT_ROOT, "source", "GMRobot", "GMRobot", "safety")
GMROBOT_MDP = os.path.join(
    GMROBOT_ROOT,
    "source",
    "GMRobot",
    "GMRobot",
    "tasks",
    "manager_based",
    "gmrobot",
    "mdp",
)

# UR10e
UR10E_USD_PATH = os.path.join(GMROBOT_ASSETS, "ur10e_2f", "ur10e_gripper.usd")

# Pressure mat assets
PRESSURE_MAT_USD = os.path.join(
    PRESSURE_MAT_ROOT,
    "isaac_lab_task",
    "pressure_mat_deploy",
    "data",
    "g1_29dof_modified_new_91.usd",
)
PRESSURE_MAT_TACTILE = os.path.join(
    PRESSURE_MAT_ROOT,
    "isaac_lab_task",
    "pressure_mat_deploy",
    "data",
    "tactile_mat_32x32_4m.usd",
)
PRESSURE_MAT_POLICY = os.path.join(PRESSURE_MAT_ROOT, "policy", "0121_walk.pt")
