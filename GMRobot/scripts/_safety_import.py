"""Import Layer 1 safety modules without loading Isaac Lab / GMRobot.tasks."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAFETY_DIR = _REPO_ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
_SAFETY_PKG = "GMRobot.safety"


def _ensure_packages() -> None:
    if "GMRobot" not in sys.modules:
        gm = types.ModuleType("GMRobot")
        gm.__path__ = [str(_SAFETY_DIR.parent)]
        sys.modules["GMRobot"] = gm

    if _SAFETY_PKG not in sys.modules:
        safety = types.ModuleType(_SAFETY_PKG)
        safety.__path__ = [str(_SAFETY_DIR)]
        sys.modules[_SAFETY_PKG] = safety


def load_safety_module(name: str):
    _ensure_packages()
    full = f"{_SAFETY_PKG}.{name}"
    if full in sys.modules:
        return sys.modules[full]

    path = _SAFETY_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _SAFETY_PKG
    assert spec.loader is not None
    sys.modules[full] = module
    spec.loader.exec_module(module)
    setattr(sys.modules[_SAFETY_PKG], name, module)
    return module


def bootstrap_safety():
    """Load safety stack in dependency order."""
    load_safety_module("types")
    load_safety_module("config")
    load_safety_module("ground_truth")
    load_safety_module("gt_branches")
    load_safety_module("envelope")
    return sys.modules[_SAFETY_PKG]
