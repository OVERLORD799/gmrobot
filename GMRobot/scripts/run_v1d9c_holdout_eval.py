#!/usr/bin/env python3
"""V1-D9C: held-out validation of rule v2.1 (depth path) on seed 48 (0 POSTs).

Seed 48 windows were captured alongside 46/47 but excluded from the D9A
feature screening. Honesty note: their translation/scale rates were visible
in the D9-batch printout; the aspect_change feature (the depth-path
discriminator) was never computed for seed 48 before this script.

Preregistered predictions (v2.1, enable_depth_path=True):
  dyn_sweep   -> trigger (translation path)
  approach    -> trigger (translation path; off-axis perspective translation)
  retreat     -> trigger (DEPTH path: scale 29.6 known, aspect unknown)
  static_idle -> no trigger
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

if "torch" not in sys.modules:
    _t = types.ModuleType("torch")
    _t.device = lambda *_a, **_k: "cpu"
    _t.tensor = lambda *a, **k: a
    _t.float32 = "float32"
    _t.no_grad = lambda: type("NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None})()
    sys.modules["torch"] = _t
    sys.modules["torch.nn"] = types.ModuleType("torch.nn")

from GMRobot.safety.evidence_gated_rule import (  # noqa: E402
    decide_dynamic_from_window_motion,
)
from GMRobot.vlm.window_motion import assess_window_motion  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
PREDICTIONS = {
    "dyn_sweep": ("trigger", "window_translation", True),
    "approach": ("trigger", "window_translation", True),
    "retreat": ("trigger", "window_depth_scale", True),
    "static_idle": ("no_trigger", "none", False),
}


def main() -> None:
    rep = json.loads((PD / "v1d9_batch_chain_eval_20260724/v1d9_report.json").read_text())
    rows = []
    all_ok = True
    for row in rep["rows"]:
        if row["seed"] != 48:
            continue
        name = row["window"]
        wm = assess_window_motion([(s, b) for s, b in row["step_boxes"]])
        d = decide_dynamic_from_window_motion(
            wm, track_score=0.9, canonical_entity="humanoid", enable_depth_path=True,
        )
        pred_trig, pred_bucket, gt_dyn = PREDICTIONS[name]
        confirmed = (d.dynamic_triggered == (pred_trig == "trigger")) and (
            not d.dynamic_triggered or d.motion_bucket == pred_bucket
        )
        correct = d.dynamic_triggered == gt_dyn
        all_ok = all_ok and confirmed and correct
        rows.append({
            "window": name, "gt_dynamic": gt_dyn,
            "translation_rate_px_s": wm["translation_rate_px_s"],
            "scale_rate_px_s": wm["scale_rate_px_s"],
            "aspect_change": wm["aspect_change"],
            "depth_motion_suspect": wm["depth_motion_suspect"],
            "triggered": d.dynamic_triggered,
            "motion_bucket": d.motion_bucket,
            "prediction": {"trigger": pred_trig, "bucket": pred_bucket},
            "prediction_confirmed": confirmed,
            "decision_correct": correct,
        })

    report = {
        "milestone": "V1-D9C",
        "date": time.strftime("%Y-%m-%d"),
        "rule": "evidence_gated_dynamic_rule_v2_1_depth",
        "holdout": "seed 48 (excluded from D9A screening; aspect_change never precomputed)",
        "rows": rows,
        "verdict": "D9C_HOLDOUT_PASS" if all_ok else "D9C_HOLDOUT_FAIL",
        "post_count": 0, "retry_count": 0,
    }
    out = PD / "v1d9c_holdout_eval_20260724"
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    out.mkdir(parents=True)
    (out / "v1d9c_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(rows, indent=1))
    print("verdict:", report["verdict"])


if __name__ == "__main__":
    main()
