#!/usr/bin/env python3
"""Offline tests for V1-M1F7 smoke context fixes."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))

from v1m1f7_smoke_context import load_runtime_scene_assertions_or_raise  # noqa: E402


def test_shell_has_no_pxr_import() -> None:
    shell = ROOT / "scripts" / "run_v1m1f7_func_c_empty_source_visual_smoke.sh"
    text = shell.read_text(encoding="utf-8")
    assert "from pxr import" not in text
    assert "import pxr" not in text


def test_runtime_assertions_missing_must_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td)
        (result_dir / "meta").mkdir(parents=True, exist_ok=True)
        try:
            load_runtime_scene_assertions_or_raise(result_dir)
        except SystemExit as exc:
            assert "missing" in str(exc)
        else:
            raise AssertionError("expected missing artifact failure")


def test_runtime_assertions_present_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td)
        meta = result_dir / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        payload = {
            "ok": True,
            "checks": {
                "task_execution_false": True,
                "visual_dataset_only_true": True,
                "spawn_task_parts_false": True,
                "part_count_cfg_zero": True,
                "containers_exist": True,
                "box_a_identity_container": True,
                "box_b_identity_full_visual": True,
            },
        }
        (meta / "runtime_scene_assertions.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        out = load_runtime_scene_assertions_or_raise(result_dir)
        assert out["ok"] is True


def main() -> None:
    test_shell_has_no_pxr_import()
    test_runtime_assertions_missing_must_fail()
    test_runtime_assertions_present_passes()
    print("PASS test_v1m1f7_smoke_context_unit")


if __name__ == "__main__":
    main()
