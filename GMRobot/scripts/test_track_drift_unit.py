#!/usr/bin/env python3
"""Unit tests for track_drift.assess_box_drift and evidence wiring (V1-D4A)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "GMRobot" / "source" / "GMRobot"))

from GMRobot.vlm.track_drift import BoxDriftConfig, assess_box_drift
from GMRobot.vlm.temporal_evidence import (
    TemporalEvidenceConfig,
    build_temporal_evidence_from_track_result,
    validate_temporal_evidence,
)


def _translate(box, dx, dy=0.0):
    return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]


def test_pure_translation_not_flagged():
    b0 = [100.0, 200.0, 160.0, 270.0]
    boxes = [_translate(b0, 5.0 * i) for i in range(10)]
    a = assess_box_drift(boxes)
    assert a["drift_suspect"] is False
    assert a["first_flag_index"] is None


def test_one_sided_expansion_flagged():
    # Right edge grows while left edge is static: mask-leak signature.
    boxes = [[100.0, 200.0, 160.0 + 6.0 * i, 270.0] for i in range(8)]
    a = assess_box_drift(boxes)
    assert a["drift_suspect"] is True
    assert a["first_flag_index"] is not None


def test_shrink_flagged():
    boxes = [[100.0, 200.0, 160.0, 270.0], [110.0, 200.0, 140.0, 270.0]]
    a = assess_box_drift(boxes)  # width 60 -> 30, ratio 0.5, expansion 30
    assert a["drift_suspect"] is True


def test_small_jitter_not_flagged():
    b0 = [100.0, 200.0, 160.0, 270.0]
    boxes = [b0, [99.0, 201.0, 162.0, 269.0], [101.0, 199.0, 159.0, 271.0]]
    a = assess_box_drift(boxes)
    assert a["drift_suspect"] is False


def test_insufficient_history_and_none_entries():
    assert assess_box_drift([])["drift_suspect"] is False
    assert assess_box_drift([[0.0, 0.0, 10.0, 10.0]])["reason"] == "insufficient_history"
    a = assess_box_drift([None, [0.0, 0.0, 10.0, 10.0], None, [0.0, 0.0, 30.0, 10.0]])
    assert a["drift_suspect"] is True


def test_config_from_dict_roundtrip():
    cfg = BoxDriftConfig.from_dict({"size_ratio_max": 1.5, "min_expansion_px": 20.0})
    boxes = [[0.0, 0.0, 60.0, 60.0], [0.0, 0.0, 72.0, 60.0]]  # ratio 1.2, exp 12
    assert assess_box_drift(boxes, cfg)["drift_suspect"] is False
    assert assess_box_drift(boxes)["drift_suspect"] is True


def _valid_track_result():
    return {
        "ok": True,
        "tracks": [{
            "track_id": 1, "label": "robot", "track_state": "tracking",
            "score": 0.9, "speed_px_s": 50.0, "direction_deg": 180.0,
        }],
        "session_ref": "session_local",
        "session_continuity_verified": True,
    }


def test_evidence_without_drift_flag_still_valid():
    ev = build_temporal_evidence_from_track_result(
        _valid_track_result(), source_request_id="t", source_frame_id="f"
    )
    ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
    assert ev.valid is True


def test_drift_suspect_evidence_rejected():
    ev = build_temporal_evidence_from_track_result(
        _valid_track_result(), source_request_id="t", source_frame_id="f",
        drift_suspect=True,
    )
    ev = validate_temporal_evidence(ev, config=TemporalEvidenceConfig())
    assert ev.valid is False
    assert ev.rejection_reason == "track_drift_suspect"


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
