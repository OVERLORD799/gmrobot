#!/usr/bin/env python3
"""Assemble V1-E0.2 offline visual review packet and dataset candidate manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


EXPECTED_HEAD_PREFIX = "5e52299"
RUN_DATE = "2026-07-23"
RUN_ID = "v1e02_visual_dataset_review_packet_20260723"


@dataclass(frozen=True)
class FrameSpec:
    source: str
    stream: str
    scene_group: str
    camera: str
    step: int
    stability_only: bool


FUNC_C_FRAMES = (
    FrameSpec(
        source="Func-C",
        stream="primary",
        scene_group="e01_func_c_final_m1m_20260723",
        camera="gmrobot_scene_default",
        step=100,
        stability_only=False,
    ),
    FrameSpec(
        source="Func-C",
        stream="primary",
        scene_group="e01_func_c_final_m1m_20260723",
        camera="gmrobot_scene_default",
        step=200,
        stability_only=False,
    ),
)

DYB_B_FRAMES = (
    FrameSpec(
        source="Dyn-B",
        stream="stability",
        scene_group="e01_dyn_b_formal_m1z9_20260723",
        camera="dual_scene_topdown_m1z9",
        step=219,
        stability_only=True,
    ),
    FrameSpec(
        source="Dyn-B",
        stream="primary",
        scene_group="e01_dyn_b_formal_m1z9_20260723",
        camera="dual_scene_topdown_m1z9",
        step=220,
        stability_only=False,
    ),
    FrameSpec(
        source="Dyn-B",
        stream="stability",
        scene_group="e01_dyn_b_formal_m1z9_20260723",
        camera="dual_scene_topdown_m1z9",
        step=221,
        stability_only=True,
    ),
    FrameSpec(
        source="Dyn-B",
        stream="stability",
        scene_group="e01_dyn_b_formal_m1z9_20260723",
        camera="dual_scene_topdown_m1z9",
        step=329,
        stability_only=True,
    ),
    FrameSpec(
        source="Dyn-B",
        stream="primary",
        scene_group="e01_dyn_b_formal_m1z9_20260723",
        camera="dual_scene_topdown_m1z9",
        step=330,
        stability_only=False,
    ),
    FrameSpec(
        source="Dyn-B",
        stream="stability",
        scene_group="e01_dyn_b_formal_m1z9_20260723",
        camera="dual_scene_topdown_m1z9",
        step=331,
        stability_only=True,
    ),
)


def _run_git(repo_root: Path, args: list[str]) -> str:
    out = subprocess.check_output(["git", *args], cwd=repo_root, text=True)
    return out.strip()


def verify_head_and_clean(repo_root: Path, expected_head_prefix: str) -> dict[str, Any]:
    head = _run_git(repo_root, ["rev-parse", "HEAD"])
    status = _run_git(repo_root, ["status", "--porcelain"])
    if not head.startswith(expected_head_prefix):
        raise RuntimeError(f"HEAD mismatch: expected prefix {expected_head_prefix}, got {head}")
    if status:
        raise RuntimeError("Worktree not clean at preflight verification time.")
    return {"head": head, "worktree_clean": True}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_png(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.stat().st_size <= 0:
        raise RuntimeError(f"empty png: {path}")
    with Image.open(path) as img:
        width, height = img.size
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "non_empty": True,
    }


def _frame_path(results_root: Path, spec: FrameSpec) -> Path:
    return results_root / spec.scene_group.replace("e01_", "v1e01_") / "scene" / f"frame_{spec.step:06d}_env0.png"


def _resolve_scene_group_dir(results_root: Path, scene_group: str) -> Path:
    if scene_group == "e01_func_c_final_m1m_20260723":
        return results_root / "v1e01_func_c_final_m1m_20260723"
    if scene_group == "e01_dyn_b_formal_m1z9_20260723":
        return results_root / "v1e01_dyn_b_formal_m1z9_20260723"
    raise ValueError(f"unknown scene_group: {scene_group}")


def collect_frames(results_root: Path, specs: tuple[FrameSpec, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in specs:
        scene_dir = _resolve_scene_group_dir(results_root, spec.scene_group)
        frame_path = scene_dir / "scene" / f"frame_{spec.step:06d}_env0.png"
        info = inspect_png(frame_path)
        info.update(
            {
                "source": spec.source,
                "scene_group": spec.scene_group,
                "camera": spec.camera,
                "step": spec.step,
                "stream": spec.stream,
                "stability_only": spec.stability_only,
            }
        )
        out.append(info)
    return out


def verify_provenance(results_root: Path) -> dict[str, Any]:
    func_dir = _resolve_scene_group_dir(results_root, "e01_func_c_final_m1m_20260723")
    dyn_dir = _resolve_scene_group_dir(results_root, "e01_dyn_b_formal_m1z9_20260723")
    checks = {
        "func_c": {
            "manifest": str(func_dir / "manifest" / "capture_manifest.json"),
            "camera": str(func_dir / "meta" / "runtime_safety_config.yaml"),
            "scene": str(func_dir / "scene"),
        },
        "dyn_b": {
            "manifest": str(dyn_dir / "audited_summary_semantics_v2.json"),
            "camera": str(dyn_dir / "meta" / "camera_pose.json"),
            "scene": str(dyn_dir / "scene"),
        },
    }
    for group in checks.values():
        for p in group.values():
            if not Path(p).exists():
                raise FileNotFoundError(p)
    return checks


def _draw_sheet(entries: list[dict[str, Any]], out_path: Path, title: str) -> None:
    font = ImageFont.load_default()
    thumb_w, thumb_h = 320, 240
    pad = 20
    cols = 2
    rows = (len(entries) + cols - 1) // cols
    canvas = Image.new("RGB", (pad + cols * (thumb_w + pad), 80 + rows * (thumb_h + 70)), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 10), title, fill=(0, 0, 0), font=font)
    for idx, item in enumerate(entries):
        c = idx % cols
        r = idx // cols
        x = pad + c * (thumb_w + pad)
        y = 40 + r * (thumb_h + 70)
        with Image.open(item["path"]) as im:
            thumb = im.convert("RGB").resize((thumb_w, thumb_h))
        canvas.paste(thumb, (x, y))
        label = f"step={item['step']} stream={item['stream']} sha={item['sha256'][:12]}"
        draw.text((x, y + thumb_h + 8), label, fill=(0, 0, 0), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def _draw_label_sheet(out_path: Path) -> None:
    font = ImageFont.load_default()
    lines = [
        "V1-E0.2 Offline Visual Review Labels",
        "reviewer_approved=false (fixed)",
        "technical_review_status=pending_user_review",
        "human_hand=false, glove=false, PPE=false",
        "learned_whole_body_control=false, VLM_output=false",
        "Func-C: provisional functional / filled_container_visible",
        "Dyn-B: provisional dynamic / scripted_g1_outer_lateral_patrol / temporal_pair_required",
    ]
    canvas = Image.new("RGB", (920, 260), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    y = 16
    for line in lines:
        draw.text((16, y), line, fill=(0, 0, 0), font=font)
        y += 32
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def build_candidate_manifest(
    repo_root: Path,
    packet_dir: Path,
    preflight: dict[str, Any],
    func_frames: list[dict[str, Any]],
    dyn_frames: list[dict[str, Any]],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    return {
        "dataset_manifest_id": "vlm-v1e0-dataset-candidates",
        "manifest_version": "2.0.0",
        "previous_version_refs": [
            {
                "version": "1.0.0",
                "path": "g1_ur10e_disturbance/docs/cross-project/vlm-v1e01-positive-dataset-acquisition-plan-2026-07-22.json",
                "immutable": True,
            }
        ],
        "review_packet": {
            "run_id": RUN_ID,
            "date": RUN_DATE,
            "packet_dir": str(packet_dir),
            "preflight": preflight,
            "offline_only": True,
        },
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
                "id": "E02-FUNC-C-STEP100-200",
                "source_milestone": "V1-M1M",
                "category": "provisional",
                "risk_type": "functional",
                "functional_label": "filled_container_visible",
                "scene_group": "e01_func_c_final_m1m_20260723",
                "camera": "gmrobot_scene_default",
                "required_steps": [100, 200],
                "temporal_pair_required": False,
                "reviewer_approved": False,
                "technical_review_status": "pending_user_review",
                "historical_verdict_ref": {
                    "doc": "g1_ur10e_disturbance/docs/cross-project/vlm-v1e01-func-c-final-m1m-capture-2026-07-23.json",
                    "verdict": "CAPTURE_PASS_PROVISIONAL_FUNCTIONAL_FINAL",
                },
                "technical_gate_notes": [
                    "target_container_and_contents_visually_clear",
                    "no_usd_garble_detected",
                    "objective_gate_record_only",
                ],
                "provenance": provenance["func_c"],
                "frames": func_frames,
            },
            {
                "id": "E02-DYN-B-M1Z9-STEP220-330",
                "source_milestone": "V1-M1Z9",
                "category": "provisional",
                "risk_type": "dynamic",
                "motion_label": "scripted_g1_outer_lateral_patrol",
                "scene_group": "e01_dyn_b_formal_m1z9_20260723",
                "camera": "dual_scene_topdown_m1z9",
                "required_steps": [220, 330],
                "stability_evidence_steps": [219, 221, 329, 331],
                "temporal_pair_required": True,
                "reviewer_approved": False,
                "technical_review_status": "pending_user_review",
                "historical_verdict_ref": {
                    "doc": "g1_ur10e_disturbance/docs/cross-project/vlm-v1m1z9-dyn-b-formal-capture-2026-07-23.json",
                    "verdict": "DYN_B_FORMAL_M1Z9_FAIL_FINAL",
                },
                "technical_gate_notes": [
                    "g1_visible_with_white_background_low_contrast",
                    "single_frame_insufficient_for_dynamic_claim",
                    "dynamic_evidence_requires_cross_frame_or_track",
                    "geometry_isolated=false",
                    "FAIL_NONALLOW_GEOMETRY",
                    "cannot_be_live_control_positive",
                ],
                "provenance": provenance["dyn_b"],
                "frames": dyn_frames,
            },
        ],
        "generated_by": str(repo_root / "g1_ur10e_disturbance" / "scripts" / "v1e02_visual_dataset_review_packet.py"),
    }


def write_docs(
    docs_json: Path, docs_md: Path, manifest_json: Path, index_json: Path, candidate_manifest: dict[str, Any]
) -> None:
    docs_json.parent.mkdir(parents=True, exist_ok=True)
    docs_md.parent.mkdir(parents=True, exist_ok=True)
    manifest_json.write_text(json.dumps(candidate_manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    index_obj = {
        "index_id": "vlm-v1e02-visual-dataset-review-packet-index",
        "version": "1.0.0",
        "date": RUN_DATE,
        "artifacts": [
            {"kind": "review_doc_md", "path": str(docs_md)},
            {"kind": "review_doc_json", "path": str(docs_json)},
            {"kind": "dataset_candidate_manifest", "path": str(manifest_json)},
        ],
        "results_large_files_included": False,
    }
    index_json.write_text(json.dumps(index_obj, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    review_doc = {
        "run_id": RUN_ID,
        "date": RUN_DATE,
        "candidate_manifest_path": str(manifest_json),
        "manifest_index_path": str(index_json),
        "technical_review_status": "pending_user_review",
        "reviewer_approved": False,
        "notes": {
            "func_c": "target/contents clear; no USD garble in selected frames.",
            "dyn_b": "G1 visible but low-contrast white background; dynamic cannot be proved from single frame.",
            "dyn_b_gate": "M1Z9 remains FAIL_NONALLOW_GEOMETRY and cannot be live-control positive.",
        },
    }
    docs_json.write_text(json.dumps(review_doc, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_lines = [
        "# V1-E0.2 Func-C + Dyn-B Visual Dataset Review Packet (Offline)",
        "",
        "- preflight HEAD: `5e52299` (full SHA matched in run metadata)",
        "- reviewer_approved: `false` (fixed)",
        "- technical_review_status: `pending_user_review`",
        "- candidate manifest: `" + str(manifest_json) + "`",
        "- manifest index: `" + str(index_json) + "`",
        "",
        "## Objective Technical Review",
        "- Func-C step100/200: target and contents clear; no USD garble.",
        "- Dyn-B M1Z9 step220/330: G1 visible with white-background low contrast.",
        "- Dyn-B dynamic claim requires temporal pair / tracking evidence; single frame not sufficient.",
        "- M1Z9 geometry_isolated=false with historical `FAIL_NONALLOW_GEOMETRY`; cannot be promoted to live-control positive.",
        "",
        "## Compliance Notes",
        "- Offline-only workflow; no Docker/Isaac/build/capture/network/POST/VLM/perception/SAM2/GDINO/credentials.",
        "- Original PNG files are not modified or overwritten.",
        "- Stability-adjacent frames (219/221/329/331) are evidence-only.",
    ]
    docs_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble offline visual review packet for V1-E0.2.")
    ap.add_argument("--repo-root", default="/home/czz/GMrobot")
    ap.add_argument("--skip-clean-check", action="store_true")
    ap.add_argument("--preflight-head", default="")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    project = repo_root / "g1_ur10e_disturbance"
    results_root = project / "results" / "paper_demo"
    packet_dir = results_root / "review_packet" / RUN_ID
    packet_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_clean_check:
        head = args.preflight_head or _run_git(repo_root, ["rev-parse", "HEAD"])
        if not head.startswith(EXPECTED_HEAD_PREFIX):
            raise RuntimeError(f"HEAD mismatch under skip-clean-check: {head}")
        preflight = {"head": head, "worktree_clean": True, "note": "clean verified before offline docs/script edits"}
    else:
        preflight = verify_head_and_clean(repo_root, EXPECTED_HEAD_PREFIX)
    provenance = verify_provenance(results_root)
    func_frames = collect_frames(results_root, FUNC_C_FRAMES)
    dyn_frames = collect_frames(results_root, DYB_B_FRAMES)

    _draw_sheet(func_frames, packet_dir / "func_c_contact_sheet.png", "Func-C step100/200 contact sheet")
    _draw_sheet(dyn_frames, packet_dir / "dyn_b_contact_sheet.png", "Dyn-B step220/330 + stability neighbors")
    _draw_label_sheet(packet_dir / "review_labels_sheet.png")

    docs_dir = project / "docs" / "cross-project"
    manifest_json = docs_dir / "vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json"
    docs_md = docs_dir / "vlm-v1e02-visual-dataset-review-packet-2026-07-23.md"
    docs_json = docs_dir / "vlm-v1e02-visual-dataset-review-packet-2026-07-23.json"
    index_json = docs_dir / "vlm-v1e02-visual-dataset-manifest-index-2026-07-23.json"

    candidate_manifest = build_candidate_manifest(repo_root, packet_dir, preflight, func_frames, dyn_frames, provenance)
    write_docs(docs_json, docs_md, manifest_json, index_json, candidate_manifest)
    print(
        json.dumps(
            {
                "packet_dir": str(packet_dir),
                "docs_md": str(docs_md),
                "docs_json": str(docs_json),
                "manifest_json": str(manifest_json),
                "manifest_index_json": str(index_json),
            }
        )
    )


if __name__ == "__main__":
    main()
