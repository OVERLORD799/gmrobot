#!/usr/bin/env python3
"""V1-D7B: offline eval of window-aggregate motion (evidence layer v2 candidate).

Replays SIX archived tracking windows (zero new POSTs) and compares the v2
window-translation verdict against the v1 stack (last-frame instantaneous
speed + D4A size-band drift gate) and ground truth.

Datasets: D6A front lateral (dyn), D7A b1 reverse sweep (dyn), b2 retreat
depth (dyn, preregistered fail-closed limitation), b3 static idle (static),
b4 outer trajectory (dyn), D3C top-down leak window (scene dynamic).
"""

from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

from GMRobot.vlm.window_motion import assess_window_motion  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"


def boxes_d6a() -> list[tuple[int, list[float] | None]]:
    r = json.loads((PD / "v1d6a_front_camera_eval_20260724/v1d6a_report.json").read_text())
    return [(f["step"], f["box"]) for f in r["phase_t_production_chain"]["per_frame"]]


def boxes_d7a(name: str) -> tuple[list[tuple[int, list[float] | None]], dict[str, Any]]:
    r = json.loads((PD / "v1d7a_batch_chain_eval_20260724/v1d7a_report.json").read_text())
    c = r["captures"][name]
    return [(f["step"], f["box"]) for f in c["per_frame"]], c


def boxes_d3c() -> list[tuple[int, list[float] | None]]:
    out: list[tuple[int, list[float] | None]] = []
    for p in sorted(glob.glob(str(PD / "v1d3c_dense_replay_eval_20260724/raw/*track*.json"))):
        d = json.loads(Path(p).read_text())
        step = int("".join(ch for ch in Path(p).stem if ch.isdigit()))
        box = None
        for t in d.get("tracks") or []:
            for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
                if t.get(k) is not None:
                    box = [float(x) for x in t[k]]
                    break
            break
        out.append((step, box))
    return out


def main() -> None:
    cases: list[dict[str, Any]] = []

    d6a = boxes_d6a()
    cases.append({"name": "d6a_front_lateral", "gt_dynamic": True, "boxes": d6a,
                  "v1_outcome": "true_positive (rule triggered)"})
    for name, gt in (("b1_reverse_sweep", True), ("b2_retreat_depth", True),
                     ("b3_static_idle", False), ("b4_outer_traj", True)):
        bx, c = boxes_d7a(name)
        cases.append({"name": name, "gt_dynamic": gt, "boxes": bx,
                      "v1_outcome": c["outcome"]})
    cases.append({"name": "d3c_topdown_leak_window", "gt_dynamic": True, "boxes": boxes_d3c(),
                  "v1_outcome": "drift-rejected (evidence invalid)"})

    rows: list[dict[str, Any]] = []
    for c in cases:
        m = assess_window_motion(c["boxes"])
        v2_dyn = bool(m["dynamic_by_translation"])
        gt = bool(c["gt_dynamic"])
        if gt and v2_dyn:
            v2_outcome = "true_positive"
        elif gt and not v2_dyn:
            v2_outcome = "miss_fail_closed"
        elif not gt and not v2_dyn:
            v2_outcome = "true_negative"
        else:
            v2_outcome = "false_positive"
        rows.append({
            "case": c["name"], "gt_dynamic": gt,
            "translation_rate_px_s": m["translation_rate_px_s"],
            "scale_rate_px_s": m["scale_rate_px_s"],
            "x_edge_asymmetry": m["x_edge_asymmetry"],
            "v2_dynamic_by_translation": v2_dyn,
            "v2_outcome": v2_outcome,
            "v1_outcome": c["v1_outcome"],
            "window_metrics": m,
        })

    n_correct_v2 = sum(1 for r in rows if r["v2_outcome"] in ("true_positive", "true_negative"))
    report = {
        "milestone": "V1-D7B",
        "date": time.strftime("%Y-%m-%d"),
        "method": "window-aggregate box decomposition (translation vs scale), offline replay only",
        "threshold_px_s": 25.0,
        "rows": rows,
        "v2_correct": f"{n_correct_v2}/{len(rows)}",
        "known_limitation": "camera-axis depth motion (b2) stays fail-closed: "
                            "scale growth is ambiguous with mask leak under current calibration",
        "post_count": 0,
        "retry_count": 0,
    }
    out = PD / "v1d7b_window_motion_offline_eval_20260724"
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    out.mkdir(parents=True)
    (out / "v1d7b_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps([{k: r[k] for k in
                       ("case", "gt_dynamic", "translation_rate_px_s",
                        "v2_outcome", "v1_outcome")} for r in rows], indent=1))
    print("v2_correct:", report["v2_correct"])


if __name__ == "__main__":
    main()
