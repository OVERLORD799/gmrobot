#!/usr/bin/env python3
"""V1-D10 S3: cross-trajectory-family chain eval (outer patrol, seeds 49/50/51).

The v2.1 depth channel was calibrated ONLY on the mirrored family (D9A);
the outer-family approach/retreat windows here are an out-of-family test.

Preregistered v2.1 predictions (enable_depth_path=True):
  approach (55-135):  trigger (translation or depth channel), GT dynamic.
  sweep    (165-245): trigger (translation), GT dynamic.
  retreat  (345-415): trigger (translation or depth channel), GT dynamic.
  idle     (430-475): no trigger, GT static.

Budget: 59 x 3 = 177 track POSTs. No GT seeding, no VLM. Single run, no retry.
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
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    build_temporal_evidence_from_track_result,
    validate_temporal_evidence,
)
from GMRobot.vlm.track_drift import assess_box_drift  # noqa: E402
from GMRobot.vlm.window_motion import assess_window_motion  # noqa: E402

PD = REPO / "g1_ur10e_disturbance/results/paper_demo"
SEED_PROMPT = "humanoid robot . robotic arm"
SEEDS = (49, 50, 51)
WINDOWS = {
    "approach": {"steps": list(range(55, 136, 5)), "gt_dynamic": True},
    "sweep": {"steps": list(range(165, 246, 5)), "gt_dynamic": True},
    "retreat": {"steps": list(range(345, 416, 5)), "gt_dynamic": True},
    "static_idle": {"steps": list(range(430, 476, 5)), "gt_dynamic": False},
}


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D10 S3 chain eval")
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
    post_total = 0
    for seed in SEEDS:
        run = f"v1d10_s3_seed{seed}_20260724"
        for name, cfg in WINDOWS.items():
            steps: list[int] = cfg["steps"]
            frames = {
                s: np.array(Image.open(PD / run / f"scene/frame_{s:06d}_env0.png").convert("RGB"),
                            dtype=np.uint8)
                for s in steps
            }
            session = None
            step_boxes: list[tuple[int, list[float] | None]] = []
            last_track: dict[str, Any] | None = None
            prev = steps[0]
            for s in steps:
                dt_s = max((s - prev) / 60.0, 1.0 / 60.0)
                res, session = pclient.track_frame(
                    frames[s], session, text_prompt=SEED_PROMPT if s == steps[0] else None,
                )
                post_total += 1
                (raw / f"{run}_{name}_track_{s:06d}.json").write_text(
                    json.dumps(res, indent=2) + "\n")
                t = (pclient.pick_primary_track(res, target_label="robot")
                     if res.get("tracks") else None)
                if t is not None:
                    t = pclient.enrich_track_kinematics(t, session=session, dt_s=dt_s)
                    step_boxes.append((s, _det_box(t)))
                    last_track = t
                else:
                    step_boxes.append((s, None))
                prev = s

            drift = assess_box_drift([b for _, b in step_boxes])
            if last_track is None:
                track_result: dict[str, Any] = {"ok": False}
            else:
                last_track.setdefault("track_state", "tracking")
                last_track.setdefault("label", SEED_PROMPT)
                track_result = {
                    "ok": True, "tracks": [last_track], "session_ref": "session_local",
                    "session_continuity_verified": bool(session and session.session_id),
                }
            ev = build_temporal_evidence_from_track_result(
                track_result, source_request_id=f"v1d10_{run}_{name}",
                source_frame_id=f"v1d10_{run}_{name}_{steps[-1]}",
                drift_suspect=bool(drift["drift_suspect"]),
            )
            ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())

            wm = assess_window_motion(step_boxes)
            d21 = decide_dynamic_from_window_motion(
                wm, track_score=float(ev.score), canonical_entity=ev.canonical_entity,
                enable_depth_path=True,
            )
            gt = bool(cfg["gt_dynamic"])
            rows.append({
                "seed": seed, "window": name, "steps": [steps[0], steps[-1]],
                "gt_dynamic": gt,
                "n_boxes": sum(1 for _, b in step_boxes if b), "n_steps": len(steps),
                "step_boxes": [[s, b] for s, b in step_boxes],
                "window_metrics": wm,
                "v1_evidence_valid": bool(ev.valid),
                "v21": {"decision": d21.to_dict(),
                        "correct": d21.dynamic_triggered == gt},
            })

    n_ok = sum(1 for r in rows if r["v21"]["correct"])
    report = {
        "milestone": "V1-D10-S3",
        "date": time.strftime("%Y-%m-%d"),
        "family": "outer_lateral_patrol (out-of-family for depth calibration)",
        "rows": rows,
        "v21_correct": f"{n_ok}/{len(rows)}",
        "post_count": post_total,
        "retry_count": 0,
    }
    (out / "v1d10_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps([{
        "seed": r["seed"], "window": r["window"],
        "on_target": f"{r['n_boxes']}/{r['n_steps']}",
        "trans": round((r["window_metrics"] or {}).get("translation_rate_px_s") or -1, 1),
        "scale": round((r["window_metrics"] or {}).get("scale_rate_px_s") or -1, 1),
        "aspect": round((r["window_metrics"] or {}).get("aspect_change") or -1, 3),
        "trig": r["v21"]["decision"]["dynamic_triggered"],
        "bucket": r["v21"]["decision"]["motion_bucket"],
        "ok": r["v21"]["correct"],
    } for r in rows], indent=1))
    print("v21_correct:", report["v21_correct"], "post:", post_total)


if __name__ == "__main__":
    main()
