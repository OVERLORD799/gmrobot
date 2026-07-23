#!/usr/bin/env python3
"""Generate offline V1-M1Y camera framing design artifacts (no capture)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from e01_dyn_b_m1y_camera_framing import run_search, write_json


def _write_audit_csv(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "gate_all",
        "cam_x",
        "cam_y",
        "cam_z",
        "links220",
        "links330",
        "clip220",
        "clip330",
        "roi220",
        "roi330",
        "sep220_330",
        "anchor_pass",
        "camera_delta_m",
        "score",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, c in enumerate(payload.get("ranked_candidates", []), start=1):
            w.writerow(
                {
                    "rank": i,
                    "gate_all": int(bool(c["gate_all"])),
                    "cam_x": c["cam_pos"][0],
                    "cam_y": c["cam_pos"][1],
                    "cam_z": c["cam_pos"][2],
                    "links220": c["step_220"]["links_visible_margin"],
                    "links330": c["step_330"]["links_visible_margin"],
                    "clip220": c["step_220"]["clipping_ratio"],
                    "clip330": c["step_330"]["clipping_ratio"],
                    "roi220": c["step_220"]["roi_area_fraction"],
                    "roi330": c["step_330"]["roi_area_fraction"],
                    "sep220_330": c["centroid_separation_px_220_330"],
                    "anchor_pass": int(bool(c["anchors"]["pass"])),
                    "camera_delta_m": c["camera_delta_from_prior_m"],
                    "score": c["ranking_score"],
                }
            )


def _write_markdown(path: Path, payload: dict) -> None:
    top = payload["ranked_candidates"][0] if payload.get("ranked_candidates") else None
    verdict = payload.get("verdict", "NO_GO")
    lines = [
        "# V1-M1Y Dyn-B camera framing design (offline, 2026-07-23)",
        "",
        f"- verdict: **{verdict}**",
        f"- candidate_count: `{payload.get('candidate_count', 0)}`",
        f"- runtime_override_can_express_selected_pose: `{payload.get('runtime_override_can_express_selected_pose')}`",
    ]
    if top is not None:
        lines.extend(
            [
                f"- top_candidate_pos: `{top['cam_pos']}`",
                f"- top_candidate_gate_all: `{top['gate_all']}`",
                f"- top_links_220_330: `{top['step_220']['links_visible_margin']}/{top['step_330']['links_visible_margin']}`",
                f"- top_clipping_220_330: `{top['step_220']['clipping_ratio']:.4f}/{top['step_330']['clipping_ratio']:.4f}`",
                f"- top_roi_frac_220_330: `{top['step_220']['roi_area_fraction']:.4f}/{top['step_330']['roi_area_fraction']:.4f}`",
                f"- top_centroid_sep_px: `{top['centroid_separation_px_220_330']}`",
                f"- top_anchor_pass: `{top['anchors']['pass']}`",
                f"- top_camera_delta_m: `{top['camera_delta_from_prior_m']:.4f}`",
            ]
        )
    sel = payload.get("recommended_pose")
    if sel is None:
        lines.append("- recommended_pose: `NO_GO (no candidate passed all hard gates)`")
    else:
        lines.append(f"- recommended_pose: `{sel['cam_pos']}` rot `{sel['cam_rot']}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline V1-M1Y camera framing designer.")
    ap.add_argument("--body-pose-jsonl", required=True, type=str)
    ap.add_argument("--out-json", required=True, type=str)
    ap.add_argument("--out-md", required=True, type=str)
    ap.add_argument("--out-candidate-csv", required=True, type=str)
    args = ap.parse_args()

    payload = run_search(body_pose_jsonl=args.body_pose_jsonl)
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_csv = Path(args.out_candidate_csv)
    write_json(out_json, payload)
    _write_markdown(out_md, payload)
    _write_audit_csv(out_csv, payload)
    print(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "candidate_count": payload["candidate_count"],
                "recommended_pose": payload["recommended_pose"]["cam_pos"] if payload.get("recommended_pose") else None,
                "out_json": str(out_json),
                "out_md": str(out_md),
                "out_candidate_csv": str(out_csv),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
