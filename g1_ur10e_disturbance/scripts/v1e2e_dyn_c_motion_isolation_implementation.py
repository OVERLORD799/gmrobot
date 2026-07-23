#!/usr/bin/env python3
"""Generate V1-E2E Dyn-C motion-isolation implementation docs + manifest update."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_c_motion_preflight import evaluate_motion_isolation_implementation, write_json  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_md(path: Path, report: dict[str, Any]) -> None:
    audits = report["audits"]
    gates = report["motion_preflight_contract"]["gates"]
    lines = [
        "# V1-E2E Dyn-C Motion Isolation Implementation",
        "",
        f"- status: `{report['status']}`",
        "- verdict policy: offline implementation only, no Isaac displacement claim",
        f"- freeze switch: `--freeze-ur10e` wired (default off)",
        f"- mirrored locomotion wiring: `{audits['mirrored_locomotion_wiring']['mirrored_scripted_phases_registered']}`",
        "",
        "## Root-Cause Audit",
        f"- task_execution=false vs UR10 freeze: `{audits['run_phase3_action_pipeline']['task_execution_false_not_freeze']}`",
        "- UR10 freeze path: effective action overridden to hold action before env write",
        "- UR10 telemetry: initial_joint_pose + hold_hash + per-step action_norm/joint_delta",
        "",
        "## Motion Preflight Contract",
        f"- seed/camera fixed: `44` / `{report['motion_preflight_contract']['camera_pose']}`",
        f"- gate: projected displacement >= `{gates['projected_displacement_px_min']}` px",
        f"- gate: ROI area >= `{gates['roi_area_fraction_min'] * 100:.2f}%`",
        f"- gate: UR10 action_norm <= `{gates['ur10_action_norm_max']}`",
        f"- gate: UR10 joint_delta_max_abs <= `{gates['ur10_joint_delta_max_abs']}`",
        "- gate: no fall + command/actual direction consistent",
        "",
        "## Next Step Budget",
        "- only 1 source-only build + 1 short motion preflight (not formal capture)",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _update_manifest(repo_root: Path) -> None:
    manifest_path = (
        repo_root
        / "g1_ur10e_disturbance"
        / "docs"
        / "cross-project"
        / "vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json"
    )
    manifest = _load_json(manifest_path)
    for cand in manifest.get("candidates", []):
        if cand.get("id") == "E02-DYN-C-E2A-STEP240-310":
            cand["status"] = "motion_isolation_implementation_pending"
            cand["count_as_dynamic_positive_group"] = False
            cand["technical_review_status"] = "implementation_ready_pending_short_preflight"
            break
    write_json(manifest_path, manifest)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate V1-E2E motion-isolation implementation docs.")
    ap.add_argument("--repo-root", default="/home/czz/GMrobot")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    docs = repo_root / "g1_ur10e_disturbance" / "docs" / "cross-project"
    docs.mkdir(parents=True, exist_ok=True)
    report = evaluate_motion_isolation_implementation(repo_root)
    report["next_step_only"] = "1 source-only build + 1 short motion preflight (no formal capture)"

    md = docs / "vlm-v1e2e-dyn-c-motion-isolation-implementation-2026-07-23.md"
    js = docs / "vlm-v1e2e-dyn-c-motion-isolation-implementation-2026-07-23.json"
    write_json(js, report)
    _write_md(md, report)
    _update_manifest(repo_root)
    print(json.dumps({"ok": True, "md": str(md), "json": str(js), "status": report["status"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
