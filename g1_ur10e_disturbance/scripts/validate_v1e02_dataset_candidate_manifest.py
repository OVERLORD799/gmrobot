#!/usr/bin/env python3
"""Offline validator for V1-E0.2 dataset candidate manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict[str, Any], repo_root: Path) -> list[str]:
    errors: list[str] = []
    flags = manifest.get("global_flags", {})
    for key in ("human_hand", "glove", "PPE", "learned_whole_body_control", "VLM_output", "reviewer_approved"):
        if flags.get(key) is not False:
            errors.append(f"global_flags.{key} must be false")
    if flags.get("technical_review_status") not in {"pending_user_review", "technical_temporal_pass_pending_user", "fail"}:
        errors.append("global_flags.technical_review_status invalid")

    candidates = manifest.get("candidates", [])
    if len(candidates) < 2:
        errors.append("at least two candidates required")
        return errors

    seen_risk_types: set[str] = set()
    for c in candidates:
        rid = c.get("id", "<missing>")
        risk_type = c.get("risk_type")
        if risk_type in seen_risk_types:
            errors.append(f"{rid}: duplicated risk_type {risk_type}")
        seen_risk_types.add(risk_type)
        if c.get("category") != "provisional":
            errors.append(f"{rid}: category must be provisional")
        if c.get("reviewer_approved") is not False:
            errors.append(f"{rid}: reviewer_approved must be false")
        if c.get("technical_review_status") not in {"pending_user_review", "technical_temporal_pass_pending_user", "fail"}:
            errors.append(f"{rid}: technical_review_status invalid")

        hv = c.get("historical_verdict_ref", {})
        if "verdict" not in hv:
            errors.append(f"{rid}: missing historical verdict reference")
        doc = hv.get("doc")
        if not doc:
            errors.append(f"{rid}: missing historical verdict doc path")
        else:
            p = repo_root / doc
            if not p.exists():
                errors.append(f"{rid}: historical verdict doc not found: {p}")

        for frame in c.get("frames", []):
            p = Path(frame["path"])
            if not p.exists():
                errors.append(f"{rid}: frame missing {p}")
                continue
            sha = _sha256(p)
            if sha != frame.get("sha256"):
                errors.append(f"{rid}: sha mismatch for {p.name}")
            if int(frame.get("width", 0)) <= 0 or int(frame.get("height", 0)) <= 0:
                errors.append(f"{rid}: invalid resolution for {p.name}")

        if c.get("risk_type") == "dynamic":
            if c.get("semantic_identity") not in {None, "scripted_g1_locomotion"}:
                errors.append(f"{rid}: semantic_identity must be scripted_g1_locomotion when set")
            if c.get("human_motion") not in {None, False}:
                errors.append(f"{rid}: human_motion must be false when set")
            if c.get("human_hand") not in {None, False}:
                errors.append(f"{rid}: human_hand must be false when set")
            if c.get("PPE") not in {None, False}:
                errors.append(f"{rid}: PPE must be false when set")
            if c.get("motion_attribution") not in {None, "SCRIPTED_G1_MOTION_SUPPORTED", "INSUFFICIENT"}:
                errors.append(f"{rid}: invalid motion_attribution")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate V1-E0.2 dataset candidate manifest")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--repo-root", default="/home/czz/GMrobot")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    repo_root = Path(args.repo_root).resolve()
    manifest = _load_json(manifest_path)
    errors = validate_manifest(manifest, repo_root)
    out = {"ok": not errors, "error_count": len(errors), "errors": errors}
    print(json.dumps(out, ensure_ascii=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
