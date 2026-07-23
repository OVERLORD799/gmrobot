#!/usr/bin/env python3
"""Offline validator for V1-E1R2.1 formal visual audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(audit_doc: dict[str, Any], source_doc: dict[str, Any], repo_root: Path) -> list[str]:
    errors: list[str] = []
    fixed = audit_doc.get("fixed_facts", {})
    result_dir = Path(audit_doc.get("result_dir", ""))
    if not result_dir.exists():
        errors.append(f"result_dir missing: {result_dir}")
        return errors

    expected = fixed.get("frame_sha256", {})
    for frame in ("frame_000100_env0.png", "frame_000200_env0.png"):
        p = result_dir / "scene" / frame
        if not p.exists():
            errors.append(f"frame missing: {p}")
            continue
        if expected.get(frame) and _sha256(p) != expected.get(frame):
            errors.append(f"sha mismatch: {frame}")

    verdicts = audit_doc.get("verdicts", {})
    if verdicts.get("raw_automation_verdict") != "FAIL_FINAL":
        errors.append("raw_automation_verdict must be FAIL_FINAL")
    if verdicts.get("audited_visual_dataset_verdict") != "FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE":
        errors.append("audited_visual_dataset_verdict invalid")

    if source_doc.get("verdict") != "FAIL_FINAL":
        errors.append("source_doc.verdict must remain FAIL_FINAL")
    if source_doc.get("raw_automation_verdict") != "FAIL_FINAL":
        errors.append("source_doc.raw_automation_verdict must remain FAIL_FINAL")
    if source_doc.get("audited_visual_dataset_verdict") != "FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE":
        errors.append("source_doc.audited_visual_dataset_verdict invalid")

    comp = audit_doc.get("composite_assertion_evidence", {})
    if comp.get("is_native_runtime_assertion_for_this_run") is not False:
        errors.append("composite evidence must declare non-native runtime assertion provenance")
    if comp.get("e1r2_runtime_assertions_present") is not False:
        errors.append("e1r2_runtime_assertions_present must be false")
    m1_path = Path(comp.get("m1f13_runtime_assertions_path", ""))
    if not m1_path.exists():
        errors.append(f"m1f13 runtime assertions missing: {m1_path}")
    if comp.get("m1f13_runtime_assertions_ok") is not True:
        errors.append("m1f13_runtime_assertions_ok must be true")

    physics = audit_doc.get("physics_limitations", {})
    if physics.get("geometry_evidence") is not False:
        errors.append("geometry_evidence must be false")
    if physics.get("control_evidence") is not False:
        errors.append("control_evidence must be false")
    if physics.get("physics_clean") is not False:
        errors.append("physics_clean must be false")

    stderr_path = result_dir / "meta" / "capture_stderr.txt"
    if not stderr_path.exists():
        errors.append(f"capture_stderr missing: {stderr_path}")
    else:
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="ignore")
        if "Rigid Body of" not in stderr_text:
            errors.append("missing RigidBody hierarchy error evidence in stderr")
        if "CCD enabled are not supported" not in stderr_text:
            errors.append("missing CCD error evidence in stderr")

    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate V1-E1R2.1 formal visual audit")
    ap.add_argument("--audit-doc", required=True)
    ap.add_argument("--source-doc", required=True)
    ap.add_argument("--repo-root", default="/home/czz/GMrobot")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    audit_doc = _load_json(Path(args.audit_doc).resolve())
    source_doc = _load_json(Path(args.source_doc).resolve())
    errors = validate(audit_doc, source_doc, repo_root)
    out = {"ok": not errors, "error_count": len(errors), "errors": errors}
    print(json.dumps(out, ensure_ascii=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
