#!/usr/bin/env python3
"""V1-D4B: VLM temporal-evidence sensitivity ablation (diagnostic_only).

Fixed image (E2K step 249), varying ONLY the temporal evidence rendered into
prompt v2 (plus one task-context variant and one directive-prompt variant).
Evidence variants V2..V6 use synthetic probe values — they are sensitivity
probes of the VLM layer, never dataset labels or end-to-end claims.
Single run, no retry. POST budget: 7 analyze calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

from GMRobot.vlm.client import VLMClient, VLMClientConfig  # noqa: E402
from GMRobot.vlm.prompt_v2 import build_temporal_prompt_v2  # noqa: E402
from GMRobot.vlm.task_context import TaskSemanticContext  # noqa: E402
from GMRobot.vlm.temporal_evidence import TemporalTrackEvidence  # noqa: E402

FRAME = (
    REPO
    / "g1_ur10e_disturbance/results/paper_demo/v1e2k_dyn_c_formal_capture_20260724"
    / "scene/frame_000249_env0.png"
)
CONF_GATE = 0.85

DIRECTIVE = (
    "\n\nIMPORTANT OVERRIDE-SAFE RULE: temporal_track_evidence is produced by a"
    " separate verified motion tracker. If temporal_track_evidence.valid is true"
    " and speed_px_s >= 10, a real object in the scene IS moving even if a single"
    " image cannot show motion; you must then classify risk_type as dynamic and"
    " set risk_confidence accordingly."
)


def _ev(**kw: Any) -> TemporalTrackEvidence:
    base: dict[str, Any] = dict(
        source_request_id="v1d4b_probe", source_frame_id="v1d4b_frm",
        track_id="1", track_state="tracking", session_continuity_verified=True,
        score=0.9, evidence_age_s=0.1, evidence_source="sam2_track",
        valid=True, session_ref="session_local", rejection_reason="",
    )
    base.update(kw)
    return TemporalTrackEvidence(**base)


def _ctx(task_phase: str = "idle", transport: str = "false") -> TaskSemanticContext:
    return TaskSemanticContext(
        task_name="pick_place", task_phase=task_phase,
        task_goal_type="place_into_container",
        source_container="container_a", target_container="container_b",
        held_object_class="none", transport_active=transport,
        placement_target_occupied="unknown",
        context_source="scenario_protocol", context_sim_step=249,
    )


VARIANTS: list[dict[str, Any]] = [
    {"id": "V0_no_evidence", "evidence": None, "ctx": _ctx(), "directive": False,
     "note": "baseline replication (D3A phase 1)"},
    {"id": "V1_real_d3c_replay", "directive": False, "ctx": _ctx(),
     "evidence": _ev(canonical_entity="robotic_arm", selected_label="robot",
                     speed_px_s=160.08, direction_deg=0.36, motion_bucket="R",
                     score=0.9468),
     "note": "exact D3C evidence values (entity canonicalized to robotic_arm)"},
    {"id": "V2_entity_unknown_humanoid", "directive": False, "ctx": _ctx(),
     "evidence": _ev(canonical_entity="unknown", selected_label="small humanoid robot",
                     speed_px_s=160.0, direction_deg=180.0, motion_bucket="L"),
     "note": "same speed, humanoid label (schema has no humanoid class -> unknown)"},
    {"id": "V3_high_speed_toward", "directive": False, "ctx": _ctx(),
     "evidence": _ev(canonical_entity="unknown", selected_label="small humanoid robot",
                     speed_px_s=300.0, direction_deg=90.0, motion_bucket="toward"),
     "note": "extreme speed, approaching"},
    {"id": "V4_slow_mover", "directive": False, "ctx": _ctx(),
     "evidence": _ev(canonical_entity="unknown", selected_label="small humanoid robot",
                     speed_px_s=15.0, direction_deg=180.0, motion_bucket="L"),
     "note": "barely above min speed"},
    {"id": "V5_transit_context", "directive": False, "ctx": _ctx("transit", "true"),
     "evidence": _ev(canonical_entity="unknown", selected_label="small humanoid robot",
                     speed_px_s=160.0, direction_deg=180.0, motion_bucket="L"),
     "note": "task context in active transit"},
    {"id": "V6_directive_prompt", "directive": True, "ctx": _ctx(),
     "evidence": _ev(canonical_entity="unknown", selected_label="small humanoid robot",
                     speed_px_s=160.0, direction_deg=180.0, motion_bucket="L"),
     "note": "prompt v3 candidate: explicit evidence-trust directive appended"},
]


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D4B VLM evidence sensitivity ablation")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: result dir exists: {out}")
    (out / "raw").mkdir(parents=True)

    frame = np.array(Image.open(FRAME).convert("RGB"), dtype=np.uint8)
    client = VLMClient(VLMClientConfig(
        base_url=args.vlm_base_url, timeout_s=60.0, contract_mode="legacy_v2",
    ))

    rows: list[dict[str, Any]] = []
    for v in VARIANTS:
        prompt, _sha = build_temporal_prompt_v2(task_context=v["ctx"], track_evidence=v["evidence"])
        if v["directive"]:
            prompt = prompt + DIRECTIVE
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
        res = client.analyze(
            frame, prompt=prompt,
            request_id=f"v1d4b_{v['id']}", frame_id=f"v1d4b_{v['id']}_frm",
        )
        (out / "raw" / f"{v['id']}.json").write_text(json.dumps(res, indent=2) + "\n")
        (out / "raw" / f"{v['id']}_prompt.txt").write_text(prompt)
        try:
            conf = float(res.get("risk_confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        rows.append({
            "variant": v["id"], "note": v["note"], "prompt_sha256": prompt_sha,
            "risk_type": res.get("risk_type"), "risk_confidence": conf,
            "keywords": res.get("keywords"),
            "dynamic_ge_gate": res.get("risk_type") == "dynamic" and conf >= CONF_GATE,
        })

    any_dynamic = any(r["dynamic_ge_gate"] for r in rows)
    report = {
        "milestone": "V1-D4B",
        "date": time.strftime("%Y-%m-%d"),
        "image": str(FRAME.relative_to(REPO)),
        "diagnostic_only": True,
        "synthetic_probe_evidence_variants": [v["id"] for v in VARIANTS if v["evidence"] is not None and v["id"] != "V1_real_d3c_replay"],
        "rows": rows,
        "any_variant_reached_dynamic_gate": any_dynamic,
        "post_count": len(rows),
        "retry_count": 0,
        "boundary": {
            "probe_values_never_dataset_labels": True,
            "confidence_gate_0_85_unchanged": True,
            "production_prompt_v2_module_untouched": True,
        },
    }
    (out / "v1d4b_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"rows": [
        {k: r[k] for k in ("variant", "risk_type", "risk_confidence", "dynamic_ge_gate")}
        for r in rows
    ], "any_dynamic_ge_gate": any_dynamic}, indent=1))


if __name__ == "__main__":
    main()
