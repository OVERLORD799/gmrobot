#!/usr/bin/env python3
"""V1-D9A: offline depth-motion discriminator feature screening (0 POSTs).

Question: can box-shape features separate TRUE camera-axis depth motion from
(a) static balance sway and (b) mask-leak growth, so that the depth windows
currently fail-closed missed by rule v2 become detectable?

Calibration sets (seed 48 depth/static/dyn windows are HELD OUT for D9C):
  depth_true : d9 approach/retreat seeds 46,47 + d7a b2
  lateral    : d9 dyn seeds 46,47 + d6a + d7a b1,b4
  static     : d9 idle seeds 46,47 + d7a b3
  leak       : d3c top-down leak window (must NOT look like depth motion)

Candidate features per window (from step-box sequences):
  scale_rate_px_s      (D7B definition)
  height_trend_ratio   |net dh| / sum|dh| (monotonic growth vs oscillation)
  width_trend_ratio    likewise for width
  aspect_change        |log aspect(last) - log aspect(first)|
  top_edge_rate        |dT|/dur (bottom edge is clipped at 479 in front views)
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PD = REPO / "g1_ur10e_disturbance/results/paper_demo"


def d9_boxes(seed: int, window: str) -> list[tuple[int, list[float] | None]]:
    r = json.loads((PD / "v1d9_batch_chain_eval_20260724/v1d9_report.json").read_text())
    for row in r["rows"]:
        if row["seed"] == seed and row["window"] == window:
            return [(s, b) for s, b in row["step_boxes"]]
    raise KeyError((seed, window))


def d7a_boxes(name: str) -> list[tuple[int, list[float] | None]]:
    r = json.loads((PD / "v1d7a_batch_chain_eval_20260724/v1d7a_report.json").read_text())
    return [(f["step"], f["box"]) for f in r["captures"][name]["per_frame"]]


def d6a_boxes() -> list[tuple[int, list[float] | None]]:
    r = json.loads((PD / "v1d6a_front_camera_eval_20260724/v1d6a_report.json").read_text())
    return [(f["step"], f["box"]) for f in r["phase_t_production_chain"]["per_frame"]]


def d3c_boxes() -> list[tuple[int, list[float] | None]]:
    import glob
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


def features(seq: list[tuple[int, list[float] | None]]) -> dict[str, float]:
    seq = [(s, b) for s, b in seq if b]
    (s0, b0), (s1, b1) = seq[0], seq[-1]
    dur = (s1 - s0) / 60.0
    ws = [b[2] - b[0] for _, b in seq]
    hs = [b[3] - b[1] for _, b in seq]
    dh_net, dw_net = hs[-1] - hs[0], ws[-1] - ws[0]
    dh_path = sum(abs(hs[i + 1] - hs[i]) for i in range(len(hs) - 1)) or 1e-6
    dw_path = sum(abs(ws[i + 1] - ws[i]) for i in range(len(ws) - 1)) or 1e-6
    d_l, d_r = b1[0] - b0[0], b1[2] - b0[2]
    d_t, d_b = b1[1] - b0[1], b1[3] - b0[3]
    return {
        "scale_rate_px_s": (abs(d_r - d_l) + abs(d_b - d_t)) / 2.0 / dur,
        "height_trend_ratio": abs(dh_net) / dh_path,
        "width_trend_ratio": abs(dw_net) / dw_path,
        "aspect_change": abs(math.log((ws[-1] / hs[-1]) / (ws[0] / hs[0]))),
        "top_edge_rate": abs(d_t) / dur,
        "translation_rate_px_s": (((d_l + d_r) / 2) ** 2 + ((d_t + d_b) / 2) ** 2) ** 0.5 / dur,
    }


def main() -> None:
    sets: list[tuple[str, str, list[tuple[int, list[float] | None]]]] = [
        ("depth_true", "d9_approach_s46", d9_boxes(46, "approach")),
        ("depth_true", "d9_approach_s47", d9_boxes(47, "approach")),
        ("depth_true", "d9_retreat_s46", d9_boxes(46, "retreat")),
        ("depth_true", "d9_retreat_s47", d9_boxes(47, "retreat")),
        ("depth_true", "d7a_b2_retreat", d7a_boxes("b2_retreat_depth")),
        ("lateral", "d9_dyn_s46", d9_boxes(46, "dyn_sweep")),
        ("lateral", "d9_dyn_s47", d9_boxes(47, "dyn_sweep")),
        ("lateral", "d6a_front", d6a_boxes()),
        ("lateral", "d7a_b1_reverse", d7a_boxes("b1_reverse_sweep")),
        ("lateral", "d7a_b4_outer", d7a_boxes("b4_outer_traj")),
        ("static", "d9_idle_s46", d9_boxes(46, "static_idle")),
        ("static", "d9_idle_s47", d9_boxes(47, "static_idle")),
        ("static", "d7a_b3_idle", d7a_boxes("b3_static_idle")),
        ("leak", "d3c_topdown", d3c_boxes()),
    ]
    rows = []
    for cat, name, seq in sets:
        f = features(seq)
        rows.append({"category": cat, "case": name, **f})
        print(f"{cat:11s} {name:18s} " + " ".join(
            f"{k}={f[k]:7.2f}" for k in
            ("scale_rate_px_s", "height_trend_ratio", "width_trend_ratio",
             "aspect_change", "top_edge_rate", "translation_rate_px_s")))

    out = PD / "v1d9a_depth_feature_screening_20260724"
    if out.exists():
        raise SystemExit(f"REFUSE: exists {out}")
    out.mkdir(parents=True)
    (out / "v1d9a_features.json").write_text(json.dumps({
        "milestone": "V1-D9A", "date": time.strftime("%Y-%m-%d"),
        "holdout_excluded": "all seed 48 windows",
        "rows": rows, "post_count": 0,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
