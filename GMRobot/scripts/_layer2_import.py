"""Import Layer 2 modules without loading Isaac Lab / GMRobot.tasks."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAYER2_DIR = _REPO_ROOT / "source" / "GMRobot" / "GMRobot" / "safety" / "layer2"
_SAFETY_DIR = _REPO_ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
_LAYER2_PKG = "GMRobot.safety.layer2"
_SAFETY_PKG = "GMRobot.safety"
_TYPES_MOD = f"{_SAFETY_PKG}.types"


def _ensure_packages() -> None:
    if "GMRobot" not in sys.modules:
        gm = types.ModuleType("GMRobot")
        gm.__path__ = [str(_SAFETY_DIR.parent)]
        sys.modules["GMRobot"] = gm

    if _SAFETY_PKG not in sys.modules:
        safety = types.ModuleType(_SAFETY_PKG)
        safety.__path__ = [str(_SAFETY_DIR)]
        sys.modules[_SAFETY_PKG] = safety

    if _LAYER2_PKG not in sys.modules:
        layer2 = types.ModuleType(_LAYER2_PKG)
        layer2.__path__ = [str(_LAYER2_DIR)]
        sys.modules[_LAYER2_PKG] = layer2

    if _TYPES_MOD not in sys.modules:
        spec = importlib.util.spec_from_file_location(_TYPES_MOD, _SAFETY_DIR / "types.py")
        module = importlib.util.module_from_spec(spec)
        module.__package__ = _SAFETY_PKG
        assert spec.loader is not None
        sys.modules[_TYPES_MOD] = module
        spec.loader.exec_module(module)
        setattr(sys.modules[_SAFETY_PKG], "types", module)


def load_layer2_module(name: str):
    _ensure_packages()
    full = f"{_LAYER2_PKG}.{name}"
    path = _LAYER2_DIR / f"{name}.py"

    if full in sys.modules:
        return sys.modules[full]

    spec = importlib.util.spec_from_file_location(full, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _LAYER2_PKG
    assert spec.loader is not None
    sys.modules[full] = module
    spec.loader.exec_module(module)
    setattr(sys.modules[_LAYER2_PKG], name, module)
    return module
