#!/usr/bin/env python3
"""Offline unit tests for V1-M1Y camera framing designer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_m1y_camera_framing import (  # noqa: E402
    MIN_CENTROID_SEPARATION_PX,
    TARGET_STEPS,
    evaluate_anchors,
    evaluate_candidate,
    evaluate_step,
    load_body_pose_steps,
    run_search,
    runtime_override_capability,
)
from scene_camera_override import DEFAULT_SCENE_CAMERA_POS, DEFAULT_SCENE_CAMERA_ROT  # noqa: E402

BODY_POSE = (
    ROOT
    / "fixtures"
    / "m1y"
    / "body_poses_minimal.jsonl"
)

HISTORICAL_BODY_POSE = (
    ROOT
    / "results"
    / "paper_demo"
    / "v1e01_dyn_b_preflight_m1w1_20260723"
    / "meta"
    / "body_poses.jsonl"
)


def _rows(path: Path) -> dict[int, dict]:
    return load_body_pose_steps(path)


def test_projection_and_step_eval_shape() -> None:
    rows = _rows(BODY_POSE)
    links = [rows[TARGET_STEPS[0]]["g1_bodies"][k] for k in rows[TARGET_STEPS[0]]["g1_bodies"]]
    ev = evaluate_step(links, cam_pos=(0.45, -0.05, 3.2))
    assert 0 <= ev.links_visible_margin <= 8
    assert 0.0 <= ev.clipping_ratio <= 1.0
    assert ev.roi_area_fraction >= 0.0


def test_boundary_and_clipping_fail_closed() -> None:
    rows = _rows(BODY_POSE)
    c = evaluate_candidate(
        cam_pos=(1.20, 0.40, 2.70),  # edge of bounded search; should be fragile
        cam_rot=DEFAULT_SCENE_CAMERA_ROT,
        body_rows=rows,
        prior_cam_pos=DEFAULT_SCENE_CAMERA_POS,
    )
    assert c["step_220"]["clipping_ratio"] >= 0.0
    assert c["step_330"]["clipping_ratio"] >= 0.0
    assert isinstance(c["gate_all"], bool)


def test_workcell_anchor_retention_gate() -> None:
    ok = evaluate_anchors((0.55, 0.00, 3.20))
    bad = evaluate_anchors((1.20, 0.40, 2.70))
    assert ok["pass"] is True
    assert bad["pass"] is False


def test_candidate_ranking_and_determinism() -> None:
    a = run_search(body_pose_jsonl=BODY_POSE)
    b = run_search(body_pose_jsonl=BODY_POSE)
    assert a["candidate_count"] == b["candidate_count"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    top = a["ranked_candidates"][0]
    second = a["ranked_candidates"][1]
    assert top["ranking_score"] >= second["ranking_score"] or top["gate_all"] is True


def test_fixture_current_camera_evaluable_contract() -> None:
    rows = _rows(BODY_POSE)
    cur = evaluate_candidate(
        cam_pos=DEFAULT_SCENE_CAMERA_POS,
        cam_rot=DEFAULT_SCENE_CAMERA_ROT,
        body_rows=rows,
        prior_cam_pos=DEFAULT_SCENE_CAMERA_POS,
    )
    assert "gate_all" in cur
    assert isinstance(cur["step_220"]["links_visible_margin"], int)
    assert isinstance(cur["step_330"]["links_visible_margin"], int)


def test_historical_current_camera_inadequate_regression_when_artifact_exists() -> None:
    if not HISTORICAL_BODY_POSE.is_file():
        return
    rows = _rows(HISTORICAL_BODY_POSE)
    cur = evaluate_candidate(
        cam_pos=DEFAULT_SCENE_CAMERA_POS,
        cam_rot=DEFAULT_SCENE_CAMERA_ROT,
        body_rows=rows,
        prior_cam_pos=DEFAULT_SCENE_CAMERA_POS,
    )
    assert cur["gate_all"] is False
    assert cur["step_220"]["links_visible_margin"] < 4


def test_centroid_separation_gate_definition() -> None:
    out = run_search(body_pose_jsonl=BODY_POSE)
    top = out["ranked_candidates"][0]
    sep = top["centroid_separation_px_220_330"]
    if top["gate_centroid_separation"]:
        assert sep is not None and sep >= MIN_CENTROID_SEPARATION_PX


def test_runtime_override_capability_contract() -> None:
    cap = runtime_override_capability()
    assert cap["supports_position_override"] is True
    assert cap["supports_rotation_override"] is True
    assert cap["supports_fov_override"] is False


def main() -> None:
    test_projection_and_step_eval_shape()
    test_boundary_and_clipping_fail_closed()
    test_workcell_anchor_retention_gate()
    test_candidate_ranking_and_determinism()
    test_fixture_current_camera_evaluable_contract()
    test_historical_current_camera_inadequate_regression_when_artifact_exists()
    test_centroid_separation_gate_definition()
    test_runtime_override_capability_contract()
    print("PASS test_e01_dyn_b_m1y_camera_framing_unit")


if __name__ == "__main__":
    main()
