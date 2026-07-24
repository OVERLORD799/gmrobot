#!/usr/bin/env python3
"""V1-D4C.1: prompt-v3 speed titration (diagnostic_only, 3 POSTs).

D4C P3 found the VLM does not literally follow the ">=10 px/s" directive:
identical probe evidence yields static at 35.5 px/s but dynamic at 160 px/s
(D4B V6 / D4C P2). This titration brackets the implicit speed boundary with
everything except speed_px_s held fixed (perfect-tracker probe evidence,
humanoid entity, direction 180, bucket L, score 0.95, prompt v3).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

from GMRobot.vlm.client import VLMClient, VLMClientConfig  # noqa: E402
from GMRobot.vlm.prompt_v3 import build_temporal_prompt_v3  # noqa: E402
from GMRobot.vlm.task_context import TaskSemanticContext  # noqa: E402
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    TemporalTrackEvidence,
    validate_temporal_evidence,
)

FRAME = (
    REPO
    / "g1_ur10e_disturbance/results/paper_demo/v1d3c_dyn_c_dense_capture_20260724"
    / "scene/frame_000249_env0.png"
)
SPEEDS = [50.0, 80.0, 120.0]
CONF_GATE = 0.85


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D4C.1 prompt-v3 speed titration")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: result dir exists: {out}")
    (out / "raw").mkdir(parents=True)

    ctx = TaskSemanticContext(
        task_name="pick_place", task_phase="idle",
        task_goal_type="place_into_container",
        source_container="container_a", target_container="container_b",
        held_object_class="none", transport_active="false",
        placement_target_occupied="unknown",
        context_source="scenario_protocol", context_sim_step=249,
    )
    base = TemporalTrackEvidence(
        source_request_id="v1d4c1_probe", source_frame_id="v1d4c1_frm",
        track_id="probe", canonical_entity="humanoid",
        selected_label="small humanoid robot", track_state="tracking",
        session_continuity_verified=True, score=0.95, speed_px_s=0.0,
        direction_deg=180.0, motion_bucket="L", evidence_age_s=0.1,
        evidence_source="sam2_track", valid=False,
        session_ref="session_local", rejection_reason="pending_validation",
    )
    frame = np.array(Image.open(FRAME).convert("RGB"), dtype=np.uint8)
    client = VLMClient(VLMClientConfig(
        base_url=args.vlm_base_url, timeout_s=60.0, contract_mode="legacy_v2",
    ))

    rows: list[dict[str, Any]] = []
    for spd in SPEEDS:
        ev = validate_temporal_evidence(
            replace(base, speed_px_s=spd), config=TemporalEvidenceConfig()
        )
        assert ev.valid, ev.rejection_reason
        prompt, sha = build_temporal_prompt_v3(task_context=ctx, track_evidence=ev)
        res = client.analyze(frame, prompt=prompt, request_id=f"v1d4c1_s{int(spd)}",
                             frame_id=f"v1d4c1_s{int(spd)}_frm")
        (out / "raw" / f"speed_{int(spd)}.json").write_text(json.dumps(res, indent=2) + "\n")
        try:
            conf = float(res.get("risk_confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        rows.append({
            "speed_px_s": spd, "prompt_sha256": sha,
            "risk_type": res.get("risk_type"), "risk_confidence": conf,
            "keywords": res.get("keywords"),
            "dynamic_ge_gate": res.get("risk_type") == "dynamic" and conf >= CONF_GATE,
        })

    known = [
        {"speed_px_s": 35.5, "risk_type": "static", "risk_confidence": 0.7,
         "source": "D4C P3"},
        {"speed_px_s": 160.0, "risk_type": "dynamic", "risk_confidence": 0.9,
         "source": "D4B V6 / D4C P2 (entity differs in P2)"},
    ]
    report = {
        "milestone": "V1-D4C.1",
        "date": time.strftime("%Y-%m-%d"),
        "diagnostic_only": True,
        "fixed_factors": "probe evidence identical except speed_px_s; prompt v3; frame 249",
        "titration_rows": rows,
        "known_anchors": known,
        "post_count": len(rows),
        "retry_count": 0,
    }
    (out / "v1d4c1_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"rows": [
        {k: r[k] for k in ("speed_px_s", "risk_type", "risk_confidence")} for r in rows
    ]}, indent=1))


if __name__ == "__main__":
    main()
