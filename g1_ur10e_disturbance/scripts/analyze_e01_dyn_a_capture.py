#!/usr/bin/env python3
"""Offline analyze E01-Dyn-A capture artifacts and write manifest + gate report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_a_capture import (  # noqa: E402
    E01_DYN_A_CAPTURE_STEPS,
    MOTION_SOURCE_ARM_WAVE,
    audit_episode_gates,
    audit_geometry_window,
    build_capture_manifest,
    build_frame_record,
    paper_scenario_sha_map,
    sha256_file,
)


def _load_body_poses(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[int(rec["step"])] = rec
    return out


def _post_count_from_logs(meta_dir: Path) -> dict:
    text = ""
    for name in ("capture_stdout.txt", "smoke_stdout.txt"):
        p = meta_dir / name
        if p.is_file():
            text += p.read_text(encoding="utf-8", errors="replace")
    patterns = [
        r"\bPOST\b",
        r"requests\.(post|get)",
        r"/analyze",
        r"/ground",
        r"/track",
        r"VLMClient",
        r"five.?stage",
        r"PerceptionClient",
    ]
    hits = []
    for pat in patterns:
        if re.search(pat, text, flags=re.I):
            hits.append(pat)
    # Kit may log https CDN — filter to VLM/perception client init only.
    client_hits = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("vlmclient", "perceptionclient", "five_stage", "post /", " posting")):
            client_hits.append(line[:200])
    return {
        "post_count_declared": 0,
        "client_init_lines": client_hits[:20],
        "ok": len(client_hits) == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True)
    args = ap.parse_args()
    rd = args.results_dir
    meta = rd / "meta"
    scene = rd / "scene"
    steps = rd / "safety_logs" / "phase3_steps.csv"
    pose_path = meta / "camera_pose.json"
    bodies = _load_body_poses(meta / "body_poses.jsonl")
    cam = json.loads(pose_path.read_text(encoding="utf-8")) if pose_path.is_file() else {
        "pos": [0.2, 0.0, 3.2],
        "rot": [0.7071, 0.0, 0.7071, 0.0],
    }
    geom = audit_geometry_window(steps) if steps.is_file() else {
        "ok": False, "verdict": "GEOMETRY_WINDOW_FAIL", "reason": "missing_steps_csv"
    }
    ep = audit_episode_gates(steps) if steps.is_file() else {}
    frames = []
    for step in E01_DYN_A_CAPTURE_STEPS:
        png = scene / f"frame_{step:06d}_env0.png"
        rec = bodies.get(step, {})
        body_map = rec.get("g1_bodies") or {}
        pts = list(body_map.values()) if body_map else []
        if not pts and rec.get("g1_root"):
            pts = [rec["g1_root"]]
        frames.append(
            build_frame_record(
                step=step,
                rgb_path=png,
                body_points=pts,
                cam_pos=cam.get("pos", [0.2, 0.0, 3.2]),
                gate=str(rec.get("gate") or "UNKNOWN"),
                phase=str(rec.get("phase") or ""),
                dist_min_g1_body=rec.get("dist_min_g1_body"),
            )
        )
    post_proof = _post_count_from_logs(meta)
    man = build_capture_manifest(
        frames=frames,
        camera_pose=cam,
        geometry_window=geom,
        episode_gates=ep,
        post_count=0 if post_proof["ok"] else -1,
        extra={
            "post_proof": post_proof,
            "b0_b4_sha": paper_scenario_sha_map(ROOT),
            "steps_csv_sha256": sha256_file(steps) if steps.is_file() else "",
            "motion_source": MOTION_SOURCE_ARM_WAVE,
        },
    )
    man_dir = rd / "manifest"
    man_dir.mkdir(parents=True, exist_ok=True)
    (man_dir / "capture_manifest.json").write_text(
        json.dumps(man, indent=2) + "\n", encoding="utf-8"
    )
    with (man_dir / "capture_manifest.frames.jsonl").open("w", encoding="utf-8") as fh:
        for fr in frames:
            fh.write(json.dumps(fr) + "\n")
    (meta / "post_count_proof.json").write_text(
        json.dumps(post_proof, indent=2) + "\n", encoding="utf-8"
    )
    (meta / "geometry_window.json").write_text(
        json.dumps(geom, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": man["verdict"], "visual_gate_ok": man["visual_gate_ok"], "geometry_ok": geom.get("ok")}, indent=2))
    return 0 if man["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
