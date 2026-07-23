#!/usr/bin/env python3
"""NumPy ABI guard helpers for Isaac AppLauncher workflows."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any


def _normalize_numpy_package_root(file_path: str) -> str:
    p = str(Path(file_path).resolve())
    marker = "/numpy/"
    idx = p.find(marker)
    if idx >= 0:
        return p[:idx]
    if p.endswith("/numpy"):
        return p[: -len("/numpy")]
    if p.endswith("/numpy/__init__.py"):
        return p[: -len("/numpy/__init__.py")]
    return str(Path(p).parent)


def inspect_numpy_conflicting_paths() -> list[str]:
    """Report known pip_prebundle archive paths currently present in sys.path."""
    found: list[str] = []
    for entry in list(sys.path):
        low = entry.lower()
        if "pip_prebundle" in low or "omni.kit.pip_archive" in low:
            found.append(entry)
    return found


def _collect_loaded_numpy_module_origins() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name, mod in sorted(sys.modules.items()):
        if not (name == "numpy" or name.startswith("numpy.")):
            continue
        file_path = str(getattr(mod, "__file__", ""))
        if not file_path:
            continue
        rows.append(
            {
                "module": name,
                "file": file_path,
                "root": _normalize_numpy_package_root(file_path),
            }
        )
    return rows


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def verify_numpy_single_root(
    *,
    stage: str,
    eager: bool,
    json_out: str | None = None,
    expected_root: str | None = None,
) -> dict[str, Any]:
    """Validate that loaded NumPy modules come from a single package root."""
    conflicting_paths = inspect_numpy_conflicting_paths()
    np_mod = importlib.import_module("numpy")
    eager_modules = ["numpy.random", "numpy.lib.recfunctions", "numpy.ma", "numpy.testing"]
    eager_errors: list[dict[str, str]] = []
    if eager:
        for name in eager_modules:
            try:
                importlib.import_module(name)
            except Exception as exc:  # pragma: no cover - captured in payload
                eager_errors.append({"module": name, "error": f"{type(exc).__name__}: {exc}"})
    loaded = _collect_loaded_numpy_module_origins()
    roots = sorted({item["root"] for item in loaded if item.get("root")})
    numpy_file = str(getattr(np_mod, "__file__", ""))
    numpy_root = _normalize_numpy_package_root(numpy_file) if numpy_file else ""
    npr = importlib.import_module("numpy.random")
    numpy_random_file = str(getattr(npr, "__file__", ""))
    numpy_random_root = _normalize_numpy_package_root(numpy_random_file) if numpy_random_file else ""
    ok = (
        len(roots) == 1
        and bool(numpy_root)
        and numpy_root == numpy_random_root
        and (expected_root is None or numpy_root == expected_root)
        and not eager_errors
    )
    payload: dict[str, Any] = {
        "stage": stage,
        "ok": ok,
        "numpy_version": str(getattr(np_mod, "__version__", "")),
        "numpy_file": numpy_file,
        "numpy_random_file": numpy_random_file,
        "numpy_root": numpy_root,
        "numpy_random_root": numpy_random_root,
        "normalized_roots": roots,
        "expected_root": expected_root or "",
        "conflicting_sys_path": conflicting_paths,
        "loaded_numpy_modules": loaded,
        "eager_errors": eager_errors,
    }
    _write_json(json_out, payload)
    if not ok:
        msg = json.dumps(payload, ensure_ascii=True)
        raise RuntimeError(f"NUMPY_ABI_GUARD_FAIL {msg}")
    return payload
