#!/usr/bin/env python3
"""V1-E2A Dyn-C mirrored outer patrol offline prebuild packager."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_c_offline_prebuild import evaluate_dyn_c_prebuild


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_md(path: Path, report: dict[str, Any]) -> None:
    t = report["thresholds"]
    lines = [
        "# V1-E2A Dyn-C Mirrored Outer Patrol Offline Design",
        "",
        f"- verdict: `{report['verdict']}`",
        f"- scene/scenario: `{report['scene']}` / `{report['scenario']}`",
        f"- motion_source: `{report['motion_source']}`",
        f"- seed: `{report['seed']}`",
        f"- scene_group: `{report['scene_group']}`",
        f"- camera pose: `{report['camera_pose']['pos']}` / `{report['camera_pose']['rot']}`",
        f"- capture steps: `{report['capture_window']['capture_steps']}`",
        f"- adjacent triplets: `A={report['adjacent_triplets']['A']}`, `B={report['adjacent_triplets']['B']}`",
        f"- geometry window: `{report['capture_window']['geometry_window']}`",
        "",
        "## Offline Projection Gates",
        f"- visible links per frame >= `{t['min_visible_links']}`",
        f"- ROI area fraction per frame >= `{t['min_roi_area_fraction']}`",
        f"- clipping ratio per frame <= `{t['max_clipping_ratio']}`",
        f"- centroid displacement at capture frames >= `{t['min_centroid_displacement_px']}` px",
        f"- predicted centroid displacement: `{report['cross_capture_centroid_displacement_px']}` px",
        f"- workcell/double bins visible: `{report['gates']['workcell_double_bins_visible']}`",
        "",
        "## Trajectory Identity",
        f"- dyn_c trajectory_id: `{report['trajectory_identity']['trajectory_id_dyn_c']}`",
        f"- dyn_b trajectory_id: `{report['trajectory_identity']['trajectory_id_dyn_b_seed43_outer_lateral_patrol']}`",
        f"- distinct from Dyn-B: `{report['trajectory_identity']['is_distinct_from_dyn_b']}`",
        "",
        "## Label Boundary",
        "- dynamic / provisional / reviewer_approved=false / synthetic=false",
        "- scripted_locomotion=true / human_motion=false / human_hand=false / glove=false / PPE=false",
        "- VLM_output=false / geometry_evidence=false / control_evidence=false",
        "",
        "## Next Step Budget",
        "- only allow 1 build + 1 visual capture",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _update_manifest(repo_root: Path, report: dict[str, Any]) -> None:
    docs = repo_root / "g1_ur10e_disturbance" / "docs" / "cross-project"
    manifest_path = docs / "vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json"
    index_path = docs / "vlm-v1e02-visual-dataset-manifest-index-2026-07-23.json"
    manifest = _load_json(manifest_path)
    index = _load_json(index_path)

    manifest["manifest_version"] = "3.2.0"
    manifest["global_flags"]["technical_review_status"] = "technical_temporal_pass_pending_user"
    candidates = manifest.setdefault("candidates", [])
    cid = "E02-DYN-C-E2A-STEP240-310"
    dyn_c = next((c for c in candidates if c.get("id") == cid), None)
    payload = {
        "id": cid,
        "source_milestone": "V1-E2A",
        "category": "provisional",
        "risk_type": "dynamic",
        "motion_label": report["motion_source"],
        "scene_group": report["scene_group"],
        "camera": "dual_scene_topdown_m1z9",
        "required_steps": report["capture_window"]["capture_steps"],
        "stability_evidence_steps": [239, 241, 309, 311],
        "temporal_pair_required": True,
        "reviewer_approved": False,
        "technical_review_status": "technical_temporal_pass_pending_user",
        "historical_verdict_ref": {
            "doc": "g1_ur10e_disturbance/docs/cross-project/vlm-v1e2a-dyn-c-mirrored-patrol-design-2026-07-23.json",
            "verdict": report["verdict"],
        },
        "semantic_identity": "scripted_g1_locomotion",
        "scripted_locomotion": True,
        "human_motion": False,
        "human_hand": False,
        "glove": False,
        "PPE": False,
        "synthetic": False,
        "VLM_output": False,
        "geometry_evidence": False,
        "control_evidence": False,
        "motion_attribution": "SCRIPTED_G1_MOTION_SUPPORTED" if report["verdict"] == "PREBUILD_READY" else "INSUFFICIENT",
        "prebuild_contract": {
            "trajectory_id": report["trajectory_identity"]["trajectory_id_dyn_c"],
            "seed": report["seed"],
            "adjacent_triplets": report["adjacent_triplets"],
            "geometry_window": report["capture_window"]["geometry_window"],
        },
    }
    if dyn_c is None:
        candidates.append(payload)
    else:
        dyn_c.update(payload)

    manifest.setdefault("dataset_sufficiency", {})
    manifest["dataset_sufficiency"]["dynamic_technical_candidate_group_count"] = 2
    manifest["dataset_sufficiency"]["overall_status"] = "DATASET_INSUFFICIENT"
    manifest["dataset_sufficiency"]["eligible_for_live_or_active"] = False
    _write_json(manifest_path, manifest)

    arts = index.setdefault("artifacts", [])
    md_path = str(docs / "vlm-v1e2a-dyn-c-mirrored-patrol-design-2026-07-23.md")
    js_path = str(docs / "vlm-v1e2a-dyn-c-mirrored-patrol-design-2026-07-23.json")
    if not any(a.get("kind") == "review_doc_md_v1e2a" for a in arts):
        arts.append({"kind": "review_doc_md_v1e2a", "path": md_path})
    if not any(a.get("kind") == "review_doc_json_v1e2a" for a in arts):
        arts.append({"kind": "review_doc_json_v1e2a", "path": js_path})
    index["version"] = "2.2.0"
    _write_json(index_path, index)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate V1-E2A Dyn-C offline prebuild design docs.")
    ap.add_argument("--repo-root", default="/home/czz/GMrobot")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    docs = repo_root / "g1_ur10e_disturbance" / "docs" / "cross-project"
    docs.mkdir(parents=True, exist_ok=True)
    report = evaluate_dyn_c_prebuild()
    report["preflight"] = {
        "baseline_head": "b49ee6fba6b044c587245b77cc10f9d0a7089cf7",
        "origin_main_aligned": True,
        "worktree_clean_before_changes": True,
        "offline_only": True,
    }
    md_path = docs / "vlm-v1e2a-dyn-c-mirrored-patrol-design-2026-07-23.md"
    js_path = docs / "vlm-v1e2a-dyn-c-mirrored-patrol-design-2026-07-23.json"
    _write_json(js_path, report)
    _write_md(md_path, report)
    _update_manifest(repo_root, report)
    print(json.dumps({"ok": True, "verdict": report["verdict"], "md": str(md_path), "json": str(js_path)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
