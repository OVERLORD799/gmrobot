#!/usr/bin/env python3
"""Offline unit tests for NumPy ABI guard helpers."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from numpy_abi_guard import (  # noqa: E402
    _normalize_numpy_package_root,
    inspect_numpy_conflicting_paths,
    verify_numpy_single_root,
    verify_typing_extensions_paramspec,
)


def test_normalize_numpy_package_root_from_init():
    root = _normalize_numpy_package_root(
        "/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/__init__.py"
    )
    assert root.endswith("/isaac-sim/kit/python/lib/python3.11/site-packages")


def test_inspect_conflicting_paths_reports_pip_prebundle_without_mutation():
    original = list(sys.path)
    try:
        sys.path.insert(0, "/tmp/omni.kit.pip_archive-foo/pip_prebundle")
        found = inspect_numpy_conflicting_paths()
        assert any("pip_prebundle" in p for p in found)
        assert any("pip_prebundle" in p for p in sys.path)
    finally:
        sys.path[:] = original


def test_verify_numpy_single_root_emits_json_and_respects_expected_root():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "numpy_origin.json"
        pre = verify_numpy_single_root(stage="unit_pre", eager=True, json_out=str(out))
        assert pre["ok"] is True
        assert out.is_file()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["numpy_file"]
        assert payload["numpy_random_file"]
        assert payload["numpy_root"] == payload["numpy_random_root"]
        post = verify_numpy_single_root(
            stage="unit_post",
            eager=False,
            expected_root=payload["numpy_root"],
            json_out=None,
        )
        assert post["ok"] is True


def test_verify_typing_extensions_paramspec_emits_json():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "te.json"
        payload = verify_typing_extensions_paramspec(stage="unit", json_out=str(out))
        assert payload["ok"] is True
        assert payload["ParamSpec_available"] is True
        assert out.is_file()


def main() -> None:
    test_normalize_numpy_package_root_from_init()
    test_inspect_conflicting_paths_reports_pip_prebundle_without_mutation()
    test_verify_numpy_single_root_emits_json_and_respects_expected_root()
    test_verify_typing_extensions_paramspec_emits_json()
    print("PASS test_numpy_abi_guard_unit")


if __name__ == "__main__":
    main()
