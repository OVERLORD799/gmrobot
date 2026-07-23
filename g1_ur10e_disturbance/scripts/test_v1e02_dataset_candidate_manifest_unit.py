#!/usr/bin/env python3
"""Unit tests for V1-E0.2 dataset candidate manifest validator."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_v1e02_dataset_candidate_manifest import validate_manifest  # noqa: E402


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _base_manifest(tmpdir: Path, repo_root: Path) -> dict:
    img = tmpdir / "frame.png"
    img.write_bytes(b"png-bytes")
    hist = repo_root / "g1_ur10e_disturbance" / "docs" / "cross-project" / "hist.json"
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text('{"verdict":"KEEP"}\n', encoding="utf-8")
    frame = {
        "path": str(img),
        "sha256": _sha(img),
        "width": 640,
        "height": 480,
    }
    return {
        "global_flags": {
            "human_hand": False,
            "glove": False,
            "PPE": False,
            "learned_whole_body_control": False,
            "VLM_output": False,
            "reviewer_approved": False,
            "technical_review_status": "pending_user_review",
        },
        "candidates": [
            {
                "id": "func",
                "risk_type": "functional",
                "category": "provisional",
                "reviewer_approved": False,
                "technical_review_status": "pending_user_review",
                "historical_verdict_ref": {"doc": "g1_ur10e_disturbance/docs/cross-project/hist.json", "verdict": "KEEP"},
                "frames": [frame],
            },
            {
                "id": "dyn",
                "risk_type": "dynamic",
                "category": "provisional",
                "reviewer_approved": False,
                "technical_review_status": "pending_user_review",
                "historical_verdict_ref": {"doc": "g1_ur10e_disturbance/docs/cross-project/hist.json", "verdict": "KEEP"},
                "frames": [frame],
            },
        ],
    }


def test_validate_manifest_ok() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        assert validate_manifest(manifest, repo_root) == []


def test_validate_manifest_detects_errors() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        bad = copy.deepcopy(manifest)
        bad["global_flags"]["human_hand"] = True
        bad["candidates"][1]["risk_type"] = "functional"
        bad["candidates"][0]["frames"][0]["sha256"] = "deadbeef"
        errors = validate_manifest(bad, repo_root)
        assert any("global_flags.human_hand" in e for e in errors)
        assert any("duplicated risk_type functional" in e for e in errors)
        assert any("sha mismatch" in e for e in errors)


if __name__ == "__main__":
    test_validate_manifest_ok()
    test_validate_manifest_detects_errors()
    print(json.dumps({"ok": True}))
