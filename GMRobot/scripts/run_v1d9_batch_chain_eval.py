#!/usr/bin/env python3
"""V1-D9 S1+S2: batch chain eval over 12 windows (seeds 46/47/48 x 4 phases).

Per window: GDINO text seed -> SAM2 dense tracking -> v1 evidence verdict
(observational) + rule v2 window-translation verdict. No GT seeding, no VLM.

Preregistered v2 predictions:
  dyn_sweep  (170-249): trigger.
  static_idle(420-465): no trigger.
  approach   (60-145) and retreat (325-400): NO trigger (depth motion is a
    documented fail-closed limitation of v2); recorded as expected_miss, not
    regression. These windows feed the D9A depth-discriminator screening.

Budget: 61 x 3 = 183 track POSTs. Single run, no retry.
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
SEEDS = (46, 47, 48)
WINDOWS = {
    "approach": {"steps": list(range(60, 146, 5)), "gt_dynamic": True,
                 "prediction_v2": "expected_miss_depth_fail_closed"},
    "dyn_sweep": {"steps": list(range(170, 246, 5)) + [249], "gt_dynamic": True,
                  "prediction_v2": "trigger"},
    "retreat": {"steps": list(range(325, 401, 5)), "gt_dynamic": True,
                "prediction_v2": "expected_miss_depth_fail_closed"},
    "static_idle": {"steps": list(range(420, 466, 5)), "gt_dynamic": False,
                    "prediction_v2": "no_trigger"},
}


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def eval_window(pclient: PerceptionClient, run: str, name: str,
                cfg: dict[str, Any], raw: Path) -> tuple[dict[str, Any], int]:
    steps: list[int] = cfg["steps"]
    frames = {
        s: np.array(Image.open(PD / run / f"scene/frame_{s:06d}_env0.png").convert("RGB"),
                    dtype=np.uint8)
        for s in steps
    }
    session = None
    step_boxes: list[tuple[int, list[float] | None]] = []
    last_track: dict[str, Any] | None = None
    post = 0
    prev = steps[0]
    for s in steps:
        dt_s = max((s - prev) / 60.0, 1.0 / 60.0)
        res, session = pclient.track_frame(
            frames[s], session, text_prompt=SEED_PROMPT if s == steps[0] else None,
        )
        post += 1
        (raw / f"{run}_{name}_track_{s:06d}.json").write_text(json.dumps(res, indent=2) + "\n")
        t = pclient.pick_primary_track(res, target_label="robot") if res.get("tracks") else None
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
        track_result, source_request_id=f"v1d9_{run}_{name}",
        source_frame_id=f"v1d9_{run}_{name}_{steps[-1]}",
        drift_suspect=bool(drift["drift_suspect"]),
    )
    ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())

    wm = assess_window_motion(step_boxes)
    d2 = decide_dynamic_from_window_motion(
        wm, track_score=float(ev.score), canonical_entity=ev.canonical_entity,
    )

    gt = bool(cfg["gt_dynamic"])
    pred = cfg["prediction_v2"]
    trig = bool(d2.dynamic_triggered)
    if pred == "trigger":
        prediction_confirmed = trig
    elif pred == "no_trigger":
        prediction_confirmed = not trig
    else:  # expected_miss_depth_fail_closed
        prediction_confirmed = not trig
    return {
        "run": run, "window": name, "steps": [steps[0], steps[-1]],
        "gt_dynamic": gt, "prediction_v2": pred,
        "n_boxes": sum(1 for _, b in step_boxes if b),
        "n_steps": len(steps),
        "step_boxes": [[s, b] for s, b in step_boxes],
        "window_metrics": wm,
        "v1": {"evidence_valid": bool(ev.valid), "drift_suspect": bool(drift["drift_suspect"]),
               "speed_px_s": float(ev.speed_px_s), "rejection_reason": ev.rejection_reason},
        "v2": {"decision": d2.to_dict(), "prediction_confirmed": prediction_confirmed},
    }, post


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D9 batch chain eval")
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
        run = f"v1d9_s1s2_seed{seed}_20260724"
        for name, cfg in WINDOWS.items():
            r, post = eval_window(pclient, run, name, cfg, raw)
            r["seed"] = seed
            rows.append(r)
            post_total += post

    n_conf = sum(1 for r in rows if r["v2"]["prediction_confirmed"])
    report = {
        "milestone": "V1-D9-S1S2",
        "date": time.strftime("%Y-%m-%d"),
        "seed_prompt": SEED_PROMPT,
        "rows": rows,
        "predictions_confirmed": f"{n_conf}/{len(rows)}",
        "post_count": post_total,
        "retry_count": 0,
        "note_d9a_holdout": "seed 48 approach/retreat step_boxes reserved as held-out set "
                            "for D9C; not to be consulted during D9A feature screening",
    }
    (out / "v1d9_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps([{
        "seed": r["seed"], "window": r["window"],
        "on_target_boxes": f"{r['n_boxes']}/{r['n_steps']}",
        "trans_rate": (r["window_metrics"] or {}).get("translation_rate_px_s"),
        "scale_rate": (r["window_metrics"] or {}).get("scale_rate_px_s"),
        "v2_trig": r["v2"]["decision"]["dynamic_triggered"],
        "pred_ok": r["v2"]["prediction_confirmed"],
        "v1_valid": r["v1"]["evidence_valid"],
    } for r in rows], indent=1))
    print("predictions_confirmed:", report["predictions_confirmed"], "post:", post_total)


if __name__ == "__main__":
    main()
