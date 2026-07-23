#!/usr/bin/env python3
"""Fail-fast import preflight for Isaac/NumPy ABI compatibility."""

from __future__ import annotations

import importlib
import json
import argparse
import traceback
from pathlib import Path


def _record_ok(name: str, module) -> dict[str, str]:
    return {
        "module": name,
        "status": "ok",
        "file": str(getattr(module, "__file__", "")),
        "version": str(getattr(module, "__version__", "")),
    }


def _record_fail(name: str, exc: Exception) -> dict[str, str]:
    return {
        "module": name,
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--json-out", type=str, default="")
    cli_args = cli.parse_args()
    checks: list[dict[str, str]] = []
    early_modules = [
        "numpy",
        "numpy.random",
        "gymnasium",
        "torch",
        "isaaclab.app",
    ]
    failed = False
    for name in early_modules:
        try:
            mod = importlib.import_module(name)
            checks.append(_record_ok(name, mod))
        except Exception as exc:
            failed = True
            checks.append(_record_fail(name, exc))
            checks.append({"module": name, "traceback": traceback.format_exc()})
            break
    if not failed:
        try:
            from isaaclab.app import AppLauncher  # noqa: F401

            checks.append({"module": "isaaclab.app.AppLauncher", "status": "ok"})
        except Exception as exc:
            failed = True
            checks.append(_record_fail("isaaclab.app.AppLauncher", exc))
            checks.append(
                {"module": "isaaclab.app.AppLauncher", "traceback": traceback.format_exc()}
            )
    payload = {"checks": checks}
    if cli_args.json_out:
        Path(cli_args.json_out).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"ok": (not failed), "check_count": len(checks)}, ensure_ascii=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
