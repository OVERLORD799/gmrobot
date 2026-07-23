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


def test_validate_manifest_dynamic_label_boundaries() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        dyn = manifest["candidates"][1]
        dyn["semantic_identity"] = "scripted_g1_locomotion"
        dyn["human_motion"] = False
        dyn["human_hand"] = False
        dyn["PPE"] = False
        dyn["motion_attribution"] = "SCRIPTED_G1_MOTION_SUPPORTED"
        manifest["global_flags"]["technical_review_status"] = "technical_temporal_pass_pending_user"
        dyn["technical_review_status"] = "technical_temporal_pass_pending_user"
        assert validate_manifest(manifest, repo_root) == []

        bad = copy.deepcopy(manifest)
        bad["candidates"][1]["semantic_identity"] = "wrong_identity"
        bad["candidates"][1]["motion_attribution"] = "MAYBE"
        errors = validate_manifest(bad, repo_root)
        assert any("semantic_identity" in e for e in errors)
        assert any("motion_attribution" in e for e in errors)


def test_validate_manifest_accepts_func_c_semantic_clarity_pending_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        manifest["global_flags"]["technical_review_status"] = "artifact_removed_semantic_clarity_pending_user"
        func = manifest["candidates"][0]
        func["technical_review_status"] = "artifact_removed_semantic_clarity_pending_user"
        func["formal_recapture_allowed"] = False
        func["semantic_clarity"] = "user_confirmation_required"
        assert validate_manifest(manifest, repo_root) == []


def test_validate_manifest_rejects_old_or_illegal_semantic_clarity_combos() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        func = manifest["candidates"][0]

        # Old status with semantic_clarity field must fail.
        old_status = copy.deepcopy(manifest)
        old_func = old_status["candidates"][0]
        old_func["semantic_clarity"] = "user_confirmation_required"
        errors = validate_manifest(old_status, repo_root)
        assert any("semantic_clarity only allowed" in e for e in errors)

        # New status with illegal approval combination must fail.
        bad_approval = copy.deepcopy(manifest)
        bad_approval["global_flags"]["technical_review_status"] = "artifact_removed_semantic_clarity_pending_user"
        bad_func = bad_approval["candidates"][0]
        bad_func["technical_review_status"] = "artifact_removed_semantic_clarity_pending_user"
        bad_func["formal_recapture_allowed"] = True
        bad_func["reviewer_approved"] = True
        bad_func["semantic_clarity"] = "user_confirmation_required"
        errors = validate_manifest(bad_approval, repo_root)
        assert any("formal_recapture_allowed must be false" in e for e in errors)
        assert any("reviewer_approved must be false" in e for e in errors)

        # New status with arbitrary semantic_clarity string must fail.
        bad_semantic = copy.deepcopy(manifest)
        bad_semantic["global_flags"]["technical_review_status"] = "artifact_removed_semantic_clarity_pending_user"
        bad_sem_func = bad_semantic["candidates"][0]
        bad_sem_func["technical_review_status"] = "artifact_removed_semantic_clarity_pending_user"
        bad_sem_func["formal_recapture_allowed"] = False
        bad_sem_func["semantic_clarity"] = "any_string_should_not_pass"
        errors = validate_manifest(bad_semantic, repo_root)
        assert any("semantic_clarity must be user_confirmation_required" in e for e in errors)


def test_validate_manifest_accepts_reference_locked_rework_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        func = manifest["candidates"][0]
        func["technical_review_status"] = "visual_rework_in_progress_reference_locked"
        func["formal_recapture_allowed"] = False
        func["reviewer_approved"] = False
        func["reference_locked"] = {
            "reference_frame_sha256": "a" * 64,
            "rejected_frame_sha256": "b" * 64,
        }
        assert validate_manifest(manifest, repo_root) == []


def test_validate_manifest_accepts_occlusion_fix_pending_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        func = manifest["candidates"][0]
        func["technical_review_status"] = "visual_rework_parts_occlusion_fix_pending"
        func["formal_recapture_allowed"] = False
        func["reviewer_approved"] = False
        func["semantic_clarity"] = "user_confirmation_required"
        func["reference_locked"] = {
            "reference_frame_sha256": "a" * 64,
            "rejected_frame_sha256": "b" * 64,
        }
        assert validate_manifest(manifest, repo_root) == []


def test_validate_manifest_accepts_reference_visual_pending_user_confirmation_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        manifest["global_flags"]["technical_review_status"] = "reference_visual_pass_pending_user_confirmation"
        func = manifest["candidates"][0]
        func["technical_review_status"] = "reference_visual_pass_pending_user_confirmation"
        func["reviewer_approved"] = False
        func["formal_recapture_allowed"] = False
        func["artifact_removal_technical_pass"] = True
        func["reference_bin_visual_contract_pass"] = True
        func["semantic_clarity"] = "user_confirmation_required"
        assert validate_manifest(manifest, repo_root) == []


def test_validate_manifest_rejects_reference_visual_pending_user_confirmation_bad_flags() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        manifest["global_flags"]["technical_review_status"] = "reference_visual_pass_pending_user_confirmation"
        func = manifest["candidates"][0]
        func["technical_review_status"] = "reference_visual_pass_pending_user_confirmation"
        func["reviewer_approved"] = True
        func["formal_recapture_allowed"] = True
        func["artifact_removal_technical_pass"] = False
        func["reference_bin_visual_contract_pass"] = False
        func["semantic_clarity"] = "user_confirmation_required"
        errors = validate_manifest(manifest, repo_root)
        assert any("reviewer_approved must be false under reference visual pending user confirmation status" in e for e in errors)
        assert any("formal_recapture_allowed must be false under reference visual pending user confirmation status" in e for e in errors)
        assert any("artifact_removal_technical_pass must be true under reference visual pending user confirmation status" in e for e in errors)
        assert any("reference_bin_visual_contract_pass must be true under reference visual pending user confirmation status" in e for e in errors)


def test_validate_manifest_accepts_func_c_formal_visual_capture_pass_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        manifest["dataset_sufficiency"] = {
            "functional_formal_visual_group_count": 1,
            "dynamic_technical_candidate_group_count": 1,
            "overall_status": "DATASET_INSUFFICIENT",
            "eligible_for_live_or_active": False,
        }
        func = manifest["candidates"][0]
        func["technical_review_status"] = "func_c_formal_visual_capture_pass"
        func["reviewer_approved"] = True
        func["formal_recapture_allowed"] = False
        func["consumed"] = True
        func["group_count"] = 1
        func["frames_split_into_independent_samples"] = False
        func["audited_visual_dataset_verdict"] = "FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE"
        func["raw_automation_verdict"] = "FAIL_FINAL"
        func["composite_assertion_evidence"] = {"is_native_runtime_assertion_for_this_run": False}
        assert validate_manifest(manifest, repo_root) == []


def test_validate_manifest_rejects_func_c_formal_visual_capture_pass_bad_flags() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        repo_root = tmpdir / "repo"
        repo_root.mkdir()
        manifest = _base_manifest(tmpdir, repo_root)
        manifest["dataset_sufficiency"] = {
            "functional_formal_visual_group_count": 0,
            "dynamic_technical_candidate_group_count": 0,
            "overall_status": "READY",
            "eligible_for_live_or_active": True,
        }
        func = manifest["candidates"][0]
        func["technical_review_status"] = "func_c_formal_visual_capture_pass"
        func["reviewer_approved"] = False
        func["formal_recapture_allowed"] = True
        func["consumed"] = False
        func["group_count"] = 2
        func["frames_split_into_independent_samples"] = True
        func["audited_visual_dataset_verdict"] = "OTHER"
        func["raw_automation_verdict"] = "PASS"
        func["composite_assertion_evidence"] = {"is_native_runtime_assertion_for_this_run": True}
        errors = validate_manifest(manifest, repo_root)
        assert any("reviewer_approved must be true under formal visual capture pass status" in e for e in errors)
        assert any("formal_recapture_allowed must be false under formal visual capture pass status" in e for e in errors)
        assert any("dataset_sufficiency.overall_status must remain DATASET_INSUFFICIENT" in e for e in errors)


if __name__ == "__main__":
    test_validate_manifest_ok()
    test_validate_manifest_detects_errors()
    test_validate_manifest_dynamic_label_boundaries()
    test_validate_manifest_accepts_func_c_semantic_clarity_pending_state()
    test_validate_manifest_rejects_old_or_illegal_semantic_clarity_combos()
    test_validate_manifest_accepts_reference_locked_rework_state()
    test_validate_manifest_accepts_occlusion_fix_pending_state()
    test_validate_manifest_accepts_reference_visual_pending_user_confirmation_state()
    test_validate_manifest_rejects_reference_visual_pending_user_confirmation_bad_flags()
    test_validate_manifest_accepts_func_c_formal_visual_capture_pass_state()
    test_validate_manifest_rejects_func_c_formal_visual_capture_pass_bad_flags()
    print(json.dumps({"ok": True}))
