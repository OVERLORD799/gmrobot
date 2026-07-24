#!/usr/bin/env python3
"""Unit tests for prompt v3 and the F7 humanoid-entity schema fix (V1-D4C)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

from GMRobot.vlm.prompt_v2 import build_temporal_prompt_v2
from GMRobot.vlm.prompt_v3 import EVIDENCE_TRUST_DIRECTIVE, build_temporal_prompt_v3
from GMRobot.vlm.task_context import TaskSemanticContext
from GMRobot.vlm.temporal_evidence import (
    TemporalTrackEvidence,
    canonicalize_entity,
    entities_compatible,
)
from GMRobot.vlm.versions import (
    ALLOWED_PROMPT_VERSIONS,
    PROMPT_VERSION_V3_TEMPORAL,
)


def test_f7_humanoid_canonicalization():
    assert canonicalize_entity("humanoid robot") == "humanoid"
    assert canonicalize_entity("small humanoid robot") == "humanoid"
    assert canonicalize_entity("white humanoid robot") == "humanoid"
    assert canonicalize_entity("Humanoid") == "humanoid"


def test_f7_bare_robot_no_longer_robotic_arm():
    assert canonicalize_entity("robot") == "unknown"


def test_f7_robotic_arm_regressions_hold():
    assert canonicalize_entity("robotic arm") == "robotic_arm"
    assert canonicalize_entity("industrial robotic arm") == "robotic_arm"
    assert canonicalize_entity("arm") == "robotic_arm"
    assert canonicalize_entity("hand") == "human_hand"
    assert canonicalize_entity("orange sphere") == "sphere"


def test_humanoid_entities_compatible():
    assert entities_compatible("humanoid robot", "small humanoid robot") is True
    assert entities_compatible("humanoid robot", "robotic arm") is False


def _ev(valid: bool = True) -> TemporalTrackEvidence:
    return TemporalTrackEvidence(
        source_request_id="t", source_frame_id="f", track_id="1",
        canonical_entity="humanoid", selected_label="small humanoid robot",
        track_state="tracking", session_continuity_verified=True,
        score=0.9, speed_px_s=35.0, direction_deg=180.0, motion_bucket="L",
        evidence_age_s=0.1, valid=valid, session_ref="session_local",
        rejection_reason="" if valid else "track_drift_suspect",
    )


def test_v3_contains_directive_at_end_and_v3_version():
    p3, sha3 = build_temporal_prompt_v3(
        task_context=TaskSemanticContext(), track_evidence=_ev()
    )
    assert p3.endswith(EVIDENCE_TRUST_DIRECTIVE)
    assert PROMPT_VERSION_V3_TEMPORAL in p3
    assert "five_stage_safety_v2_temporal\"" not in p3
    assert len(sha3) == 64
    assert PROMPT_VERSION_V3_TEMPORAL in ALLOWED_PROMPT_VERSIONS


def test_v3_differs_from_v2_only_by_version_and_directive():
    ctx = TaskSemanticContext()
    p2, _ = build_temporal_prompt_v2(task_context=ctx, track_evidence=_ev())
    p3, _ = build_temporal_prompt_v3(task_context=ctx, track_evidence=_ev())
    reconstructed = p2.replace(
        "five_stage_safety_v2_temporal", PROMPT_VERSION_V3_TEMPORAL
    ) + EVIDENCE_TRUST_DIRECTIVE
    assert p3 == reconstructed


def test_v3_deterministic():
    ctx = TaskSemanticContext()
    a = build_temporal_prompt_v3(task_context=ctx, track_evidence=_ev())
    b = build_temporal_prompt_v3(task_context=ctx, track_evidence=_ev())
    assert a == b


def test_v3_renders_invalid_evidence_as_invalid():
    p3, _ = build_temporal_prompt_v3(
        task_context=TaskSemanticContext(), track_evidence=_ev(valid=False)
    )
    assert '"valid":false' in p3
    assert "track_drift_suspect" in p3


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                fails += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if fails else 0)
