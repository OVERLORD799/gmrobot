#!/usr/bin/env python3
"""V1-D11: prospective validation of rule v2.2 (depth translation floor) on
an unseen outer-family capture (seed 52).

The v2.2 floor (8 px/s) was calibrated post-hoc including the S3 seed-51
mask-breathing false positive; this run closes that honesty gap with
predictions registered BEFORE any tracking.

Preregistered gates (must all confirm for PASS):
  sweep    (165-245): trigger, GT dynamic.
  retreat  (345-415): trigger, GT dynamic.
  static_idle (430-475): NO trigger, GT static (F12 regression test).
Observational (known sensitivity gap, not a gate):
  approach (55-135): may miss; recorded either way.

Budget: 59 track POSTs, no GT seeding, no VLM. Single run, no retry.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import types
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

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

from GMRobot.perception.client import PerceptionClient, PerceptionClientConfig  # noqa: E402
from GMRobot.safety.evidence_gated_rule import (  # noqa: E402
    decide_dynamic_from_window_motion,
)
from GMRobot.vlm.window_motion import assess_window_motion  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
RUN = "v1d11_seed52_prospective_20260724"
SEED_PROMPT = "humanoid robot . robotic arm"
WINDOWS = {
    "approach": {"steps": list(range(55, 136, 5)), "gt_dynamic": True, "gate": False,
                 "prediction": "observational_may_miss"},
    "sweep": {"steps": list(range(165, 246, 5)), "gt_dynamic": True, "gate": True,
              "prediction": "trigger"},
    "retreat": {"steps": list(range(345, 416, 5)), "gt_dynamic": True, "gate": True,
                "prediction": "trigger"},
    "static_idle": {"steps": list(range(430, 476, 5)), "gt_dynamic": False, "gate": True,
                    "prediction": "no_trigger"},
}


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D11 prospective eval")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    raw = out / "raw"
    raw.mkdir(parents=True)

    pclient = PerceptionClient(PerceptionClientConfig(
        base_url=args.perception_base_url, timeout_s=300.0, track_target_label="robot",
    ))

    rows: list[dict[str, Any]] = []
    post = 0
    gates_ok = True
    for name, cfg in WINDOWS.items():
        steps: list[int] = cfg["steps"]
        frames = {
            s: np.array(Image.open(PD / RUN / f"scene/frame_{s:06d}_env0.png").convert("RGB"),
                        dtype=np.uint8)
            for s in steps
        }
        session = None
        step_boxes: list[tuple[int, list[float] | None]] = []
        for s in steps:
            res, session = pclient.track_frame(
                frames[s], session, text_prompt=SEED_PROMPT if s == steps[0] else None,
            )
            post += 1
            (raw / f"{name}_track_{s:06d}.json").write_text(json.dumps(res, indent=2) + "\n")
            t = (pclient.pick_primary_track(res, target_label="robot")
                 if res.get("tracks") else None)
            step_boxes.append((s, _det_box(t) if t else None))

        wm = assess_window_motion(step_boxes)
        d = decide_dynamic_from_window_motion(
            wm, track_score=0.9, canonical_entity="humanoid", enable_depth_path=True,
        )
        gt = bool(cfg["gt_dynamic"])
        if cfg["gate"]:
            confirmed = d.dynamic_triggered == (cfg["prediction"] == "trigger")
            gates_ok = gates_ok and confirmed
        else:
            confirmed = None
        rows.append({
            "window": name, "gt_dynamic": gt, "gate": cfg["gate"],
            "prediction": cfg["prediction"],
            "n_boxes": sum(1 for _, b in step_boxes if b), "n_steps": len(steps),
            "window_metrics": wm,
            "triggered": d.dynamic_triggered, "motion_bucket": d.motion_bucket,
            "rejection_reason": d.rejection_reason,
            "prediction_confirmed": confirmed,
            "decision_correct": d.dynamic_triggered == gt,
        })

    report = {
        "milestone": "V1-D11",
        "date": time.strftime("%Y-%m-%d"),
        "capture_run": RUN, "seed": 52,
        "rule": "evidence_gated_dynamic_rule_v2_1_depth + v2.2 floor",
        "rows": rows,
        "verdict": "D11_PROSPECTIVE_PASS" if gates_ok else "D11_PROSPECTIVE_FAIL",
        "post_count": post, "retry_count": 0,
    }
    (out / "v1d11_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps([{
        "window": r["window"], "gt": r["gt_dynamic"],
        "on_target": f"{r['n_boxes']}/{r['n_steps']}",
        "trans": round(r["window_metrics"].get("translation_rate_px_s") or -1, 1),
        "scale": round(r["window_metrics"].get("scale_rate_px_s") or -1, 1),
        "aspect": round(r["window_metrics"].get("aspect_change") or -1, 3),
        "trig": r["triggered"], "bucket": r["motion_bucket"],
        "pred_ok": r["prediction_confirmed"], "correct": r["decision_correct"],
    } for r in rows], indent=1))
    print("verdict:", report["verdict"], "post:", post)


if __name__ == "__main__":
    main()
