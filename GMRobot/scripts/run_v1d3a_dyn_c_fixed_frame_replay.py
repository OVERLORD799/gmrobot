#!/usr/bin/env python3
"""V1-D3A: fixed-frame VLM replay on reviewer-approved Dyn-C E2K frames.

Phase 1 (native discipline): POST frames 170/249 with prompt v2, NO temporal
evidence. Preregistered expectation: model must NOT guess risk_type=dynamic
without motion evidence (prompt rule). Any dynamic guess = discipline FAIL.

Phase 2 (--with-sam2, real temporal fusion): GDINO ground + SAM2 track over
the frame pair, build TemporalTrackEvidence from the REAL track result
(sam2_track source only; body-pose ground truth is never used as evidence),
then POST frame 249 with valid evidence. Gate: risk_type=dynamic AND
confidence >= 0.85.

Single run, no retry, no prompt/threshold mutation. Shadow-only: no control.
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
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    build_temporal_evidence_from_track_result,
    validate_temporal_evidence,
)

E2K_RESULT = REPO / "g1_ur10e_disturbance/results/paper_demo/v1e2k_dyn_c_formal_capture_20260724"
# Reviewer-approved primary pair (manifest v3.3.0, E02-DYN-C-E2K-STEP170-249).
FRAMES = {
    170: "scene/frame_000170_env0.png",
    249: "scene/frame_000249_env0.png",
}
CONF_GATE = 0.85


def _expected_sha() -> dict[int, str]:
    inv = json.loads((E2K_RESULT / "meta/frame_inventory.json").read_text(encoding="utf-8"))
    return {int(f["step"]): str(f["sha256"]) for f in inv["frames"]}


def _load_rgb(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"), dtype=np.uint8)


def _task_context(step: int) -> TaskSemanticContext:
    # Honest context: UR10e frozen (idle), no held object, no occupancy claim.
    return TaskSemanticContext(
        task_name="pick_place",
        task_phase="idle",
        task_goal_type="place_into_container",
        source_container="container_a",
        target_container="container_b",
        held_object_class="none",
        transport_active="false",
        placement_target_occupied="unknown",
        context_source="scenario_protocol",
        context_sim_step=int(step),
    )


def evaluate_phase1(results: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Preregistered gates for the native-discipline phase (offline-testable)."""
    gates: dict[str, Any] = {}
    parse_ok = all(bool(r.get("gateway_parse_ok", r.get("ok"))) for r in results.values())
    gates["parse_ok_all"] = parse_ok
    dynamic_guesses = {
        s: r.get("risk_type") for s, r in results.items() if str(r.get("risk_type")) == "dynamic"
    }
    gates["no_dynamic_guess_without_evidence"] = not dynamic_guesses
    gates["dynamic_guess_steps"] = sorted(dynamic_guesses)
    verdict = (
        "D3A_NATIVE_DISCIPLINE_PASS"
        if parse_ok and not dynamic_guesses
        else "D3A_NATIVE_DISCIPLINE_FAIL"
    )
    return {"gates": gates, "verdict": verdict}


def evaluate_phase2(result: dict[str, Any], evidence_valid: bool) -> dict[str, Any]:
    """Preregistered gates for the real-SAM2 temporal phase (offline-testable)."""
    risk = str(result.get("risk_type"))
    try:
        conf = float(result.get("risk_confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    gates = {
        "temporal_evidence_valid": bool(evidence_valid),
        "risk_type_dynamic": risk == "dynamic",
        "confidence_ge_0_85": conf >= CONF_GATE,
    }
    verdict = (
        "D3A_TEMPORAL_DYNAMIC_PASS" if all(gates.values()) else "D3A_TEMPORAL_DYNAMIC_FAIL"
    )
    return {"gates": gates, "verdict": verdict, "risk_type": risk, "risk_confidence": conf}


def main() -> None:
    ap = argparse.ArgumentParser(description="V1-D3A Dyn-C fixed-frame replay")
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--vlm-base-url", default="http://127.0.0.1:18080")
    ap.add_argument("--perception-base-url", default="http://127.0.0.1:18082")
    ap.add_argument("--with-sam2", action="store_true", help="run phase 2 real temporal fusion")
    ap.add_argument("--timeout-s", type=float, default=30.0)
    args = ap.parse_args()

    out = Path(args.result_dir)
    if out.exists():
        raise SystemExit(f"REFUSE: result dir exists: {out}")
    (out / "raw").mkdir(parents=True)

    expected = _expected_sha()
    frames: dict[int, np.ndarray] = {}
    sha_check: dict[int, str] = {}
    for step, rel in FRAMES.items():
        p = E2K_RESULT / rel
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != expected[step]:
            raise SystemExit(f"REFUSE: sha mismatch for step {step}: {digest} != {expected[step]}")
        sha_check[step] = digest
        frames[step] = _load_rgb(p)

    client = VLMClient(
        VLMClientConfig(
            base_url=args.vlm_base_url,
            timeout_s=args.timeout_s,
            contract_mode="legacy_v2",
        )
    )
    health = client.health_check()
    (out / "raw" / "health.json").write_text(json.dumps(health, indent=2) + "\n")
    if str(health.get("status", "")).lower() not in ("ok", "warming"):
        raise SystemExit(f"REFUSE: VLM health not ok: {health}")

    post_count = 0
    phase1_results: dict[int, dict[str, Any]] = {}
    for step in sorted(FRAMES):
        prompt, prompt_sha = build_temporal_prompt_v2(
            task_context=_task_context(step), track_evidence=None
        )
        rid = f"v1d3a_p1_step{step}"
        res = client.analyze(frames[step], prompt=prompt, request_id=rid, frame_id=f"{rid}_frm")
        post_count += 1
        res["_prompt_sha256"] = prompt_sha
        res["_frame_sha256"] = sha_check[step]
        phase1_results[step] = res
        (out / "raw" / f"phase1_step{step:06d}.json").write_text(json.dumps(res, indent=2) + "\n")

    phase1 = evaluate_phase1(phase1_results)

    phase2: dict[str, Any] | None = None
    if args.with_sam2:
        from GMRobot.perception.client import PerceptionClient, PerceptionClientConfig

        pclient = PerceptionClient(
            PerceptionClientConfig(
                base_url=args.perception_base_url,
                # First request lazily loads GDINO+SAM2 on the server.
                timeout_s=max(args.timeout_s, 300.0),
                track_target_label="robot",
            )
        )
        phealth = pclient.health_check()
        (out / "raw" / "perception_health.json").write_text(json.dumps(phealth, indent=2) + "\n")

        g1_prompt = "white humanoid robot"
        # 60 Hz sim; the two frames are (249-170) steps apart per frame_index increment.
        dt_s = (249 - 170) / 60.0
        res_a, session = pclient.track_frame(frames[170], None, text_prompt=g1_prompt)
        post_count += 1
        (out / "raw" / "track_step170.json").write_text(json.dumps(res_a, indent=2) + "\n")

        def _primary(res: dict[str, Any]) -> dict[str, Any] | None:
            if res.get("tracks"):
                return pclient.pick_primary_track(res, target_label="robot")
            return res if res.get("box_xyxy") or res.get("center_xy") else None

        t_a = _primary(res_a)
        if t_a is not None:
            pclient.enrich_track_kinematics(t_a, session=session, dt_s=dt_s)  # seed baseline

        res_b, session = pclient.track_frame(frames[249], session)
        post_count += 1
        (out / "raw" / "track_step249.json").write_text(json.dumps(res_b, indent=2) + "\n")
        t_b = _primary(res_b)
        session_continuity = bool(
            res_a.get("ok", True) and res_b.get("ok", True)
            and session.session_id
            and str(res_b.get("session_id", session.session_id)) == str(session.session_id)
        )
        if t_b is None:
            track_result: dict[str, Any] = {"ok": False}
        else:
            t_b = pclient.enrich_track_kinematics(t_b, session=session, dt_s=dt_s)
            t_b.setdefault("track_state", "tracking")
            t_b.setdefault("label", g1_prompt)
            track_result = {
                "ok": True,
                "tracks": [t_b],
                "session_ref": "session_local",
                "session_continuity_verified": session_continuity,
            }
        ev = build_temporal_evidence_from_track_result(
            track_result, source_request_id="v1d3a_p2", source_frame_id="v1d3a_p2_frm170"
        )
        ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
        (out / "raw" / "temporal_evidence.json").write_text(
            json.dumps(ev.to_dict(), indent=2) + "\n"
        )
        prompt2, prompt2_sha = build_temporal_prompt_v2(
            task_context=_task_context(249), track_evidence=ev
        )
        res2 = client.analyze(
            frames[249], prompt=prompt2, request_id="v1d3a_p2_step249",
            frame_id="v1d3a_p2_step249_frm",
        )
        post_count += 1
        res2["_prompt_sha256"] = prompt2_sha
        (out / "raw" / "phase2_step249.json").write_text(json.dumps(res2, indent=2) + "\n")
        phase2 = evaluate_phase2(res2, evidence_valid=ev.valid)
        phase2["session_continuity_verified"] = session_continuity

    report = {
        "milestone": "V1-D3A",
        "date": time.strftime("%Y-%m-%d"),
        "sample_ref": "E02-DYN-C-E2K-STEP170-249 (manifest v3.3.0, reviewer_approved)",
        "frame_sha256": {str(k): v for k, v in sha_check.items()},
        "post_count": post_count,
        "retry_count": 0,
        "phase1_native_discipline": {
            "results": {
                str(s): {k: r.get(k) for k in ("risk_type", "risk_confidence", "suggested_action", "model_id", "latency_ms")}
                for s, r in phase1_results.items()
            },
            **phase1,
        },
        "phase2_temporal": phase2,
        "boundary": {
            "shadow_only_no_control": True,
            "body_pose_gt_never_used_as_temporal_evidence": True,
            "no_prompt_or_threshold_mutation": True,
            "no_retry": True,
        },
    }
    (out / "v1d3a_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "phase1_verdict": phase1["verdict"],
        "phase2_verdict": (phase2 or {}).get("verdict"),
        "post_count": post_count,
    }))


if __name__ == "__main__":
    main()
