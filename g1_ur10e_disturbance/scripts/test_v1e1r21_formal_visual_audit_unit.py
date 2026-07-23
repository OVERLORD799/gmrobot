#!/usr/bin/env python3
"""Unit tests for V1-E1R2.1 formal visual audit validator."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_v1e1r21_formal_visual_audit import validate  # noqa: E402


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _base_docs(tmp: Path) -> tuple[dict, dict]:
    result_dir = tmp / "results"
    (result_dir / "scene").mkdir(parents=True)
    (result_dir / "meta").mkdir(parents=True)

    f100 = result_dir / "scene" / "frame_000100_env0.png"
    f200 = result_dir / "scene" / "frame_000200_env0.png"
    f100.write_bytes(b"frame100")
    f200.write_bytes(b"frame200")
    (result_dir / "meta" / "capture_stderr.txt").write_text(
        "Rigid Body of (...)\\nCCD enabled are not supported\\n",
        encoding="utf-8",
    )
    m1 = tmp / "m1f13_runtime_scene_assertions.json"
    m1.write_text('{"ok": true}\\n', encoding="utf-8")

    audit_doc = {
        "result_dir": str(result_dir),
        "fixed_facts": {
            "frame_sha256": {
                "frame_000100_env0.png": _sha(f100),
                "frame_000200_env0.png": _sha(f200),
            }
        },
        "verdicts": {
            "raw_automation_verdict": "FAIL_FINAL",
            "audited_visual_dataset_verdict": "FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE",
        },
        "composite_assertion_evidence": {
            "is_native_runtime_assertion_for_this_run": False,
            "e1r2_runtime_assertions_present": False,
            "m1f13_runtime_assertions_path": str(m1),
            "m1f13_runtime_assertions_ok": True,
        },
        "physics_limitations": {
            "geometry_evidence": False,
            "control_evidence": False,
            "physics_clean": False,
        },
    }
    source_doc = {
        "verdict": "FAIL_FINAL",
        "raw_automation_verdict": "FAIL_FINAL",
        "audited_visual_dataset_verdict": "FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE",
    }
    return audit_doc, source_doc


def test_validate_ok() -> None:
    with tempfile.TemporaryDirectory() as td:
        audit_doc, source_doc = _base_docs(Path(td))
        assert validate(audit_doc, source_doc, Path(td)) == []


def test_validate_detects_failures() -> None:
    with tempfile.TemporaryDirectory() as td:
        audit_doc, source_doc = _base_docs(Path(td))
        bad = copy.deepcopy(audit_doc)
        bad["fixed_facts"]["frame_sha256"]["frame_000100_env0.png"] = "deadbeef"
        bad["verdicts"]["raw_automation_verdict"] = "PASS"
        bad["composite_assertion_evidence"]["is_native_runtime_assertion_for_this_run"] = True
        bad["physics_limitations"]["physics_clean"] = True
        src_bad = copy.deepcopy(source_doc)
        src_bad["verdict"] = "PASS"
        errors = validate(bad, src_bad, Path(td))
        assert any("sha mismatch" in e for e in errors)
        assert any("raw_automation_verdict must be FAIL_FINAL" in e for e in errors)
        assert any("source_doc.verdict must remain FAIL_FINAL" in e for e in errors)
        assert any("non-native runtime assertion provenance" in e for e in errors)
        assert any("physics_clean must be false" in e for e in errors)


if __name__ == "__main__":
    test_validate_ok()
    test_validate_detects_failures()
    print(json.dumps({"ok": True}))
