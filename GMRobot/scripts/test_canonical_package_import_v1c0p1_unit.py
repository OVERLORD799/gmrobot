#!/usr/bin/env python3
"""V1-C0P1 canonical installed-package import / source-scan regression tests.

sys.path may only include GMRobot/source/GMRobot (editable install root).
Must NOT add GMRobot/source/GMRobot/GMRobot (that falsely creates top-level safety/).
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = ROOT / "source" / "GMRobot"
SRC_TREE = PKG_ROOT / "GMRobot"
AGENT = ROOT / "scripts" / "gm_state_machine_agent.py"

# Host lacks Isaac/torch; stub only for offline import of GMRobot.__init__ / safety.__init__.
# Docker gate uses real Isaac python without these stubs.


def _ensure_module(name: str, **attrs):
    if name in sys.modules:
        mod = sys.modules[name]
    else:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    for key, value in attrs.items():
        setattr(mod, key, value)
    if "." in name:
        parent_name, child = name.rsplit(".", 1)
        parent = _ensure_module(parent_name)
        setattr(parent, child, mod)
    return mod


def _install_host_stubs() -> None:
    _ensure_module("isaaclab_tasks")
    _ensure_module("isaaclab_tasks.utils", import_packages=lambda *_a, **_k: None)
    _ensure_module("omni")
    ext = _ensure_module("omni.ext")

    class _IExt:
        pass

    ext.IExt = _IExt
    ui = _ensure_module("omni.ui")
    ui.Window = type(
        "Window",
        (),
        {"__init__": lambda self, *a, **k: None, "frame": None},
    )
    ui.VStack = type(
        "VStack",
        (),
        {"__enter__": lambda self: self, "__exit__": lambda *a: None},
    )
    ui.Label = object
    ui.Button = object
    # Minimal torch surface for safety/__init__ import chain on host.
    torch = _ensure_module("torch")
    torch.device = lambda *_a, **_k: "cpu"
    torch.tensor = lambda *a, **k: a
    torch.float32 = "float32"
    torch.no_grad = lambda: type("NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None})()
    _ensure_module("torch.nn")
    _ensure_module("numpy", array=lambda *a, **k: a, ndarray=object)


def _configure_sys_path() -> None:
    # Drop any prior inner-package path that would create top-level `safety`.
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != SRC_TREE.resolve()]
    if str(PKG_ROOT) not in sys.path:
        sys.path.insert(0, str(PKG_ROOT))
    assert str(PKG_ROOT) in sys.path
    assert str(SRC_TREE) not in sys.path


def test_sys_path_canonical_only():
    _configure_sys_path()
    assert any(Path(p).resolve() == PKG_ROOT.resolve() for p in sys.path)
    assert not any(Path(p).resolve() == SRC_TREE.resolve() for p in sys.path)


def test_canonical_package_imports():
    _configure_sys_path()
    _install_host_stubs()
    # Fresh import namespace for this process: drop prior `safety` if any.
    for key in list(sys.modules):
        if key == "safety" or key.startswith("safety.") or key == "shadow" or key.startswith("shadow."):
            del sys.modules[key]

    import GMRobot  # noqa: F401
    import GMRobot.safety.semantic_supervisor as sem
    import GMRobot.safety.semantic_supervisor_logger as slog
    import GMRobot.shadow.semantic_bridge as bridge
    from GMRobot.shadow import SemanticShadowBridge

    assert sem.__name__.startswith("GMRobot.safety.")
    assert slog.__name__.startswith("GMRobot.safety.")
    assert bridge.__name__ == "GMRobot.shadow.semantic_bridge"
    assert SemanticShadowBridge is bridge.SemanticShadowBridge
    # Fix must not depend on top-level `safety`.
    assert "safety" not in sys.modules
    assert not any(k == "safety" or k.startswith("safety.") for k in sys.modules)


def test_source_tree_no_toplevel_safety_imports():
    pattern = re.compile(r"^\s*(from\s+safety(\s|\.|$)|import\s+safety(\s|$|,))")
    offenders: list[str] = []
    for path in sorted(SRC_TREE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if pattern.search(stripped):
                offenders.append(f"{path.relative_to(SRC_TREE)}:{i}:{line.strip()}")
    assert not offenders, "toplevel safety imports:\n" + "\n".join(offenders)


def test_gm_state_machine_agent_semantic_import_is_canonical():
    tree = ast.parse(AGENT.read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "GMRobot.shadow.semantic_bridge":
            names = {alias.name for alias in node.names}
            if "SemanticShadowBridge" in names:
                found = True
                break
    assert found, "gm_state_machine_agent must import SemanticShadowBridge from GMRobot.shadow.semantic_bridge"

    # Bootstrap: same import path the agent uses when semantic flag is enabled.
    _configure_sys_path()
    _install_host_stubs()
    for key in list(sys.modules):
        if key == "safety" or key.startswith("safety."):
            del sys.modules[key]
    mod = importlib.import_module("GMRobot.shadow.semantic_bridge")
    assert mod.__name__ == "GMRobot.shadow.semantic_bridge"
    assert "safety" not in sys.modules


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("OK", t.__name__)
    print(f"PASS {len(tests)}")
