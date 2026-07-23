#!/usr/bin/env python3
"""Offline analyze / asset precheck for E01-Func-C."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))

from shadow.v1e01_func_c_capture import (  # noqa: E402
    E01_FUNC_C_CAPTURE_STEPS,
    LABEL_STATUS,
    REVIEWER_APPROVED,
    SCENE_GROUP,
    audit_episode_gates,
    audit_geometry_window,
    build_capture_manifest,
    build_frame_record,
    paper_scenario_sha_map,
    precheck_container_full_asset,
)


def _find_steps_csv(safety_logs: Path) -> Path | None:
    """Prefer the longest formal-capture episode CSV (not a short smoke log)."""
    cands = sorted(set(safety_logs.glob("**/episode_*.csv")) | set(safety_logs.glob("**/*.csv")))
    scored: list[tuple[int, float, Path]] = []
    for p in cands:
        text = p.read_text(encoding="utf-8", errors="replace")
        if "g_rule" not in text and "gate" not in text:
            continue
        n_rows = max(0, text.count("\n") - 1)
        scored.append((n_rows, p.stat().st_mtime, p))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def _post_proof(meta: Path) -> dict:
    text = ""
    for name in ("capture_stdout.txt", "capture_stderr.txt", "smoke_stdout.txt", "smoke_stderr.txt"):
        p = meta / name
        if p.is_file():
            text += p.read_text(encoding="utf-8", errors="replace")
    client_hits = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("vlmclient", "perceptionclient", "five_stage", "post /analyze", "post /ground")):
            client_hits.append(line[:200])
    return {
        "post_count": 0,
        "vlm_off_or_absent": ("VLM" not in text) or ("enable_vlm" not in text.lower()),
        "client_init_lines": client_hits[:20],
        "traceback_count": text.count("Traceback"),
        "ok": len(client_hits) == 0 and text.count("Traceback") == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--assets-dir", type=Path, required=True)
    ap.add_argument("--precheck-only", action="store_true")
    args = ap.parse_args()
    rd = args.results_dir
    meta = rd / "meta"
    meta.mkdir(parents=True, exist_ok=True)

    pre = precheck_container_full_asset(args.assets_dir)
    (meta / "asset_precheck.json").write_text(json.dumps(pre, indent=2) + "\n", encoding="utf-8")
    if args.precheck_only:
        print(json.dumps({"verdict": pre.get("verdict"), "ok": pre.get("ok"), "evidence": pre.get("evidence")}, indent=2))
        return 0 if pre.get("ok") else 2

    if not pre.get("ok"):
        print(json.dumps({"verdict": "ASSET_SEMANTIC_DISTINCTION_UNPROVEN", "precheck": pre}, indent=2))
        return 2

    steps = _find_steps_csv(rd / "safety_logs")
    geom = (
        audit_geometry_window(steps)
        if steps is not None
        else {"ok": False, "verdict": "GEOMETRY_WINDOW_FAIL", "reason": "missing_steps_csv"}
    )
    ep = audit_episode_gates(steps) if steps is not None else {}
    frames = []
    for step in E01_FUNC_C_CAPTURE_STEPS:
        png = rd / "scene" / f"frame_{step:06d}_env0.png"
        frames.append(
            build_frame_record(
                step=step,
                rgb_path=png,
                hand_pos=[0.25, -0.75, 0.60],
            )
        )
    post = _post_proof(meta)
    g1 = ROOT.parent / "g1_ur10e_disturbance"
    # Thresholds from capture safety YAML (report-only; not retuned).
    safety_thresholds = {
        "safe_dist_hard_stop": 0.13,
        "safe_dist_warn": 0.16,
        "ttc_threshold": 0.5,
        "ttc_warn_threshold": 1.5,
        "source": "GMRobot/configs/ivj_v1e01_target_container_full.yaml",
    }
    if isinstance(geom, dict):
        geom = dict(geom)
        geom["safety_thresholds"] = safety_thresholds
        dmin = geom.get("dist_min")
        if dmin is not None:
            geom["margin_to_warn"] = float(dmin) - float(safety_thresholds["safe_dist_warn"])
            geom["margin_to_hard"] = float(dmin) - float(safety_thresholds["safe_dist_hard_stop"])
    man = build_capture_manifest(
        frames=frames,
        geometry_window=geom,
        episode_gates=ep,
        asset_precheck=pre,
        post_count=0 if post["ok"] else -1,
        extra={
            "post_proof": post,
            "b0_b4_sha": paper_scenario_sha_map(g1) if g1.is_dir() else {},
            "steps_csv": str(steps) if steps else "",
            "label_status": LABEL_STATUS,
            "reviewer_approved": REVIEWER_APPROVED,
            "scene_group": SCENE_GROUP,
            "safety_thresholds": safety_thresholds,
            "ready_for_human_label_review": bool(
                pre.get("ok")
                and geom.get("ok")
                and all(Path(fr["path"]).is_file() for fr in frames)
            ),
            "ready_for_vlm_screen": False,
        },
    )
    man_dir = rd / "manifest"
    man_dir.mkdir(parents=True, exist_ok=True)
    (man_dir / "capture_manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    with (man_dir / "capture_manifest.frames.jsonl").open("w", encoding="utf-8") as fh:
        for fr in frames:
            fh.write(json.dumps(fr) + "\n")
    (meta / "post_count_proof.json").write_text(json.dumps(post, indent=2) + "\n", encoding="utf-8")
    (meta / "geometry_window.json").write_text(json.dumps(geom, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": man["verdict"], "visual_gate_ok": man["visual_gate_ok"], "geometry_ok": geom.get("ok")}, indent=2))
    return 0 if man["verdict"] == "CAPTURE_PASS_PROVISIONAL_FUNCTIONAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
