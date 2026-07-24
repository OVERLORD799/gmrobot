#!/usr/bin/env python3
"""V1-D8A: prospective validation of evidence rule v2 on an UNSEEN seed (45).

Preregistered predictions (written before any tracking):
  dyn window (steps 170-249, mirrored negative sweep):  v2 rule TRIGGERS.
  static window (steps 420-465, idle balance sway):     v2 rule does NOT trigger.
Both v1 (instantaneous speed + D4A size-band gate) and v2 (D7B window
translation) verdicts are recorded for comparison; v1 is expected to repeat
its D7A failure modes but this is observational, not a gate.

Seed 45 was never used in any calibration (D7B thresholds came from seeds
43/44 windows only). Budget: 27 track POSTs, no VLM. Single run, no retry.
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
RUN = "v1d8a_seed45_prospective_20260724"
SEED_PROMPT = "humanoid robot . robotic arm"

WINDOWS = {
    "dyn_sweep": {
        "steps": list(range(170, 246, 5)) + [249],
        "prediction_v2": "trigger",
        "gt_dynamic": True,
    },
    "static_idle": {
        "steps": list(range(420, 466, 5)),
        "prediction_v2": "no_trigger",
        "gt_dynamic": False,
    },
}


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D8A prospective eval")
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

    results: dict[str, Any] = {}
    post = 0
    for name, cfg in WINDOWS.items():
        steps: list[int] = cfg["steps"]
        frames = {
            s: np.array(Image.open(PD / RUN / f"scene/frame_{s:06d}_env0.png").convert("RGB"),
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
            post += 1
            (raw / f"{name}_track_{s:06d}.json").write_text(json.dumps(res, indent=2) + "\n")
            t = pclient.pick_primary_track(res, target_label="robot") if res.get("tracks") else None
            if t is not None:
                t = pclient.enrich_track_kinematics(t, session=session, dt_s=dt_s)
                step_boxes.append((s, _det_box(t)))
                last_track = t
            else:
                step_boxes.append((s, None))
            prev = s

        # ---- v1 verdict (instantaneous speed + D4A size-band drift gate)
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
            track_result, source_request_id=f"v1d8a_{name}",
            source_frame_id=f"v1d8a_{name}_{steps[-1]}",
            drift_suspect=bool(drift["drift_suspect"]),
        )
        ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())

        # ---- v2 verdict (window-aggregate translation, rule v2)
        wm = assess_window_motion(step_boxes)
        d2 = decide_dynamic_from_window_motion(
            wm,
            track_score=float(ev.score),
            canonical_entity=ev.canonical_entity,
        )

        gt = bool(cfg["gt_dynamic"])
        v2_ok = d2.dynamic_triggered == gt
        v1_trig = bool(ev.valid)
        results[name] = {
            "steps": [steps[0], steps[-1]],
            "gt_dynamic": gt,
            "prediction_v2": cfg["prediction_v2"],
            "n_boxes": sum(1 for _, b in step_boxes if b),
            "window_metrics": wm,
            "v1": {"evidence_valid": v1_trig, "drift_suspect": bool(drift["drift_suspect"]),
                   "speed_px_s": float(ev.speed_px_s),
                   "rejection_reason": ev.rejection_reason,
                   "correct": v1_trig == gt},
            "v2": {"decision": d2.to_dict(), "correct": v2_ok,
                   "prediction_confirmed": (d2.dynamic_triggered and cfg["prediction_v2"] == "trigger")
                   or (not d2.dynamic_triggered and cfg["prediction_v2"] == "no_trigger")},
        }

    all_confirmed = all(r["v2"]["prediction_confirmed"] for r in results.values())
    report = {
        "milestone": "V1-D8A",
        "date": time.strftime("%Y-%m-%d"),
        "capture_run": RUN,
        "seed": 45,
        "seed_unseen_in_calibration": True,
        "windows": results,
        "verdict": "D8A_PROSPECTIVE_PASS" if all_confirmed else "D8A_PROSPECTIVE_FAIL",
        "post_count": post,
        "retry_count": 0,
    }
    (out / "v1d8a_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        name: {
            "gt": r["gt_dynamic"],
            "translation_rate": r["window_metrics"]["translation_rate_px_s"],
            "scale_rate": r["window_metrics"]["scale_rate_px_s"],
            "v2_triggered": r["v2"]["decision"]["dynamic_triggered"],
            "v2_correct": r["v2"]["correct"],
            "v1_triggered": r["v1"]["evidence_valid"],
            "v1_correct": r["v1"]["correct"],
        } for name, r in results.items()
    } | {"verdict": report["verdict"], "post_count": post}, indent=1))


if __name__ == "__main__":
    main()
