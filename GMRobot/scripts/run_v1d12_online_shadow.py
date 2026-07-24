#!/usr/bin/env python3
"""V1-D12 (B6): ONLINE shadow supervisor — realtime closed-loop shadow run.

Unlike all prior offline replays, this process runs CONCURRENTLY with the
Isaac simulation: it polls the capture directory, processes each frame as it
lands (SAM2 track -> sliding-window motion -> rule v2.2 decision), and logs
wall-clock latency. Actions are recorded, never executed (shadow mode).

Protocol: mirrored_outer_lateral_patrol, seed 53, capture steps 60..540/5
(97 frames). Sliding window = last 14 boxes (65 sim steps, matching the
calibration window length). Decisions before the window fills are fail-closed.

Preregistered gates (phase-core windows = sliding window fully inside one
scripted phase; mirrored phase table: approach 0-150, settle 150-180,
neg sweep 180-250, pos sweep 250-320, retreat 320-410, idle 410+):
  G1 sweep cores  {245,250} u {315,320}: ALL dynamic.
  G2 retreat core {385..410}: >=5/6 dynamic.
  G3 idle core    {475..540}: ZERO dynamic (no false positives).
  G4 realtime: supervisor keeps pace (max backlog <= 2 frames).
Observational (not gates): approach core {125..145} (known slow-motion
sensitivity gap), transition windows, per-frame latency stats.

Budget: 97 track POSTs, no VLM, single run, no retry.
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

SEED_PROMPT = "humanoid robot . robotic arm"
WINDOW_BOXES = 14

PHASES = [
    ("approach", 0, 150), ("settle", 150, 180), ("neg_sweep", 180, 250),
    ("pos_sweep", 250, 320), ("retreat", 320, 410), ("idle", 410, 10 ** 9),
]


def phase_of(step: int) -> str:
    for name, a, b in PHASES:
        if a <= step < b:
            return name
    return "?"


def core_phase(window_start: int, window_end: int) -> str | None:
    """Phase containing the whole sliding window, else None (transition)."""
    for name, a, b in PHASES:
        if a <= window_start and window_end <= b:
            return name
    return None


def _det_box(d: dict[str, Any]) -> list[float] | None:
    for k in ("box_xyxy", "bbox_xyxy", "box", "bbox"):
        if d.get(k) is not None:
            return [float(x) for x in d[k]]
    return None


def _read_frame(path: Path) -> np.ndarray | None:
    try:
        return np.array(Image.open(path).convert("RGB"), dtype=np.uint8)
    except Exception:
        return None  # partial write; retry next poll


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D12 online shadow supervisor")
    ap.add_argument("--capture-dir", required=True)
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--step-start", type=int, default=60)
    ap.add_argument("--step-end", type=int, default=540)
    ap.add_argument("--step-stride", type=int, default=5)
    ap.add_argument("--timeout-s", type=float, default=900.0)
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    args = ap.parse_args()

    cap = Path(args.capture_dir)
    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    out.mkdir(parents=True)

    steps = list(range(args.step_start, args.step_end + 1, args.step_stride))
    pclient = PerceptionClient(PerceptionClientConfig(
        base_url=args.perception_base_url, timeout_s=300.0, track_target_label="robot",
    ))

    session = None
    boxes: list[tuple[int, list[float] | None]] = []
    timeline: list[dict[str, Any]] = []
    t0 = time.monotonic()
    deadline = t0 + args.timeout_s
    post = 0
    max_backlog = 0
    idx = 0

    while idx < len(steps) and time.monotonic() < deadline:
        # backlog = frames already on disk beyond the one we're waiting for
        pending = [s for s in steps[idx:] if (cap / f"frame_{s:06d}_env0.png").exists()]
        max_backlog = max(max_backlog, max(0, len(pending) - 1))

        s = steps[idx]
        fpath = cap / f"frame_{s:06d}_env0.png"
        if not fpath.exists():
            time.sleep(0.2)
            continue
        frame = _read_frame(fpath)
        if frame is None:
            time.sleep(0.2)
            continue

        t_detect = time.monotonic()
        res, session = pclient.track_frame(
            frame, session, text_prompt=SEED_PROMPT if idx == 0 else None,
        )
        post += 1
        t = pclient.pick_primary_track(res, target_label="robot") if res.get("tracks") else None
        boxes.append((s, _det_box(t) if t else None))
        window = boxes[-WINDOW_BOXES:]

        if len(window) < WINDOW_BOXES:
            decision_row = {"triggered": False, "bucket": "none",
                            "reason": "window_filling_fail_closed"}
            wm = None
        else:
            wm = assess_window_motion(window)
            d = decide_dynamic_from_window_motion(
                wm, track_score=0.9, canonical_entity="humanoid", enable_depth_path=True,
            )
            decision_row = {"triggered": bool(d.dynamic_triggered),
                            "bucket": d.motion_bucket,
                            "reason": d.rejection_reason,
                            "recommended_action_shadow": d.recommended_action}
        t_done = time.monotonic()
        timeline.append({
            "step": s, "wall_s": round(t_done - t0, 3),
            "latency_s": round(t_done - t_detect, 3),
            "phase_at_step": phase_of(s),
            "core_phase": core_phase(window[0][0], s) if len(window) == WINDOW_BOXES else None,
            "box_present": window[-1][1] is not None,
            "window_metrics": {k: wm[k] for k in
                               ("translation_rate_px_s", "scale_rate_px_s", "aspect_change",
                                "dynamic_by_translation", "depth_motion_suspect")} if wm else None,
            **decision_row,
        })
        idx += 1

    (out / "timeline.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in timeline))

    # ---- gate evaluation
    def rows_core(name: str, lo: int, hi: int) -> list[dict[str, Any]]:
        return [r for r in timeline if r["core_phase"] == name and lo <= r["step"] <= hi]

    sweep_rows = rows_core("neg_sweep", 245, 250) + rows_core("pos_sweep", 315, 320)
    retreat_rows = rows_core("retreat", 385, 410)
    idle_rows = rows_core("idle", 475, 540)
    approach_rows = rows_core("approach", 125, 145)

    g1 = len(sweep_rows) > 0 and all(r["triggered"] for r in sweep_rows)
    g2 = len(retreat_rows) >= 6 and sum(r["triggered"] for r in retreat_rows) >= 5
    g3 = len(idle_rows) > 0 and not any(r["triggered"] for r in idle_rows)
    g4 = max_backlog <= 2 and idx == len(steps)

    lat = sorted(r["latency_s"] for r in timeline) or [0.0]
    report = {
        "milestone": "V1-D12-B6",
        "date": time.strftime("%Y-%m-%d"),
        "mode": "online_shadow_concurrent_with_sim",
        "frames_processed": f"{idx}/{len(steps)}",
        "boxes_present": sum(1 for r in timeline if r["box_present"]),
        "gates": {
            "G1_sweep_cores_all_dynamic": {"pass": g1, "n": len(sweep_rows),
                                           "triggered": sum(r["triggered"] for r in sweep_rows)},
            "G2_retreat_core_5of6": {"pass": g2, "n": len(retreat_rows),
                                     "triggered": sum(r["triggered"] for r in retreat_rows)},
            "G3_idle_core_zero_fp": {"pass": g3, "n": len(idle_rows),
                                     "triggered": sum(r["triggered"] for r in idle_rows)},
            "G4_realtime_keeps_pace": {"pass": g4, "max_backlog": max_backlog},
        },
        "observational": {
            "approach_core": {"n": len(approach_rows),
                              "triggered": sum(r["triggered"] for r in approach_rows)},
            "latency_s": {"median": lat[len(lat) // 2], "p95": lat[int(len(lat) * 0.95) - 1],
                          "max": lat[-1]},
        },
        "verdict": "D12_ONLINE_SHADOW_PASS" if (g1 and g2 and g3 and g4)
                   else "D12_ONLINE_SHADOW_FAIL",
        "post_count": post, "retry_count": 0,
    }
    (out / "v1d12_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
