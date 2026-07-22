#!/usr/bin/env python3
"""E01-Dyn-A offline unit tests (no Isaac / no POST)."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_a_capture import (  # noqa: E402
    E01_DYN_A_CAPTURE_STEPS,
    E01_DYN_A_SCENARIO,
    E01_DYN_A_SEED,
    GEOMETRY_WINDOW,
    MOTION_SOURCE_ARM_WAVE,
    assert_b0_b4_files_unchanged,
    audit_episode_gates,
    audit_geometry_window,
    build_capture_manifest,
    build_frame_record,
    paper_scenario_sha_map,
    validate_dyn_a_capture_flags,
)
from scene_camera_override import (  # noqa: E402
    DEFAULT_SCENE_CAMERA_POS,
    DEFAULT_SCENE_CAMERA_ROT,
    E01_DYN_A_SCENE_CAMERA_POS,
    E01_DYN_A_SCENE_CAMERA_ROT,
    arm_wave_phase_at_step,
    g1_roi_from_body_points,
    resolve_scene_camera_pose,
    scene_camera_override_enabled,
)


def test_camera_override_default_off():
    env = {"GMDISTURB_SCENE_CAMERA_POS": "0.2,0.0,3.2"}
    assert scene_camera_override_enabled(env) is False
    pos, rot = resolve_scene_camera_pose(env)
    assert pos == DEFAULT_SCENE_CAMERA_POS
    assert rot == DEFAULT_SCENE_CAMERA_ROT


def test_camera_override_unchanged_without_flag():
    env = {
        "GMDISTURB_SCENE_CAMERA_POS": "9,9,9",
        "GMDISTURB_SCENE_CAMERA_ROT": "1,0,0,0",
    }
    assert resolve_scene_camera_pose(env) == (
        DEFAULT_SCENE_CAMERA_POS,
        DEFAULT_SCENE_CAMERA_ROT,
    )


def test_dyn_a_camera_pose_when_override_on():
    env = {
        "GMDISTURB_SCENE_CAMERA_OVERRIDE": "1",
        "GMDISTURB_SCENE_CAMERA_POS": "0.2,0.0,3.2",
        "GMDISTURB_SCENE_CAMERA_ROT": "0.7071,0.0,0.7071,0.0",
    }
    pos, rot = resolve_scene_camera_pose(env)
    assert pos == E01_DYN_A_SCENE_CAMERA_POS
    assert rot == E01_DYN_A_SCENE_CAMERA_ROT


def test_scenario_seed_motion_capture_steps():
    flags = validate_dyn_a_capture_flags()
    assert flags["ok"] is True
    assert E01_DYN_A_SCENARIO == "arm_wave"
    assert E01_DYN_A_SEED == 42
    assert MOTION_SOURCE_ARM_WAVE == "scripted_g1_locomotion_arm_wave"
    assert E01_DYN_A_CAPTURE_STEPS == (210, 280)
    assert arm_wave_phase_at_step(210) == "settle"
    assert arm_wave_phase_at_step(280) == "stand"


def test_virtual_hand_and_post_rejected():
    bad = validate_dyn_a_capture_flags(virtual_hand=True)
    assert bad["ok"] is False
    bad2 = validate_dyn_a_capture_flags(enable_vlm=True, post_count=1)
    assert bad2["ok"] is False
    assert bad2["clients_initialized_expected"] is False


def test_roi_and_displacement():
    cam = E01_DYN_A_SCENE_CAMERA_POS
    pts_a = [(-0.4, 0.0, 0.9), (-0.4, 0.15, 0.7), (-0.35, -0.1, 0.5)]
    pts_b = [(0.1, 0.0, 0.9), (0.1, 0.15, 0.7), (0.15, -0.1, 0.5)]
    r0 = g1_roi_from_body_points(pts_a, cam_pos=cam)
    r1 = g1_roi_from_body_points(pts_b, cam_pos=cam)
    assert r0["roi_source"] == "projected_g1_body_points"
    assert r0["roi_area_px2"] >= 400.0
    assert r1["roi_area_px2"] >= 400.0
    c0, c1 = r0["centroid_uv"], r1["centroid_uv"]
    disp = ((c1[0] - c0[0]) ** 2 + (c1[1] - c0[1]) ** 2) ** 0.5
    assert disp >= 40.0


def test_geometry_window_and_manifest_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        csv_path = td_path / "steps.csv"
        header = (
            "step,gate,gate_trigger,replan_count,replan_event_id,"
            "replan_applied_step,dist_min_for_gating\n"
        )
        lines = [header]
        for s in range(200, 301):
            lines.append(f"{s},ALLOW,,0,0,0,0.85\n")
        csv_path.write_text("".join(lines), encoding="utf-8")
        geom = audit_geometry_window(csv_path, window=GEOMETRY_WINDOW)
        assert geom["ok"] is True
        assert geom["stop"] == 0 and geom["slow"] == 0
        ep = audit_episode_gates(csv_path)
        assert ep["gate_counts"]["ALLOW"] == 101

        # Fail case
        bad_csv = td_path / "bad.csv"
        bad_lines = [header]
        for s in range(210, 281):
            gate = "STOP" if s == 250 else "ALLOW"
            bad_lines.append(f"{s},{gate},tier0,0,0,0,0.10\n")
        bad_csv.write_text("".join(bad_lines), encoding="utf-8")
        bad_geom = audit_geometry_window(bad_csv)
        assert bad_geom["ok"] is False
        assert bad_geom["verdict"] == "GEOMETRY_WINDOW_FAIL"

        png0 = td_path / "f0.png"
        png1 = td_path / "f1.png"
        png0.write_bytes(b"\x89PNG_fake_0")
        png1.write_bytes(b"\x89PNG_fake_1")
        cam = {"pos": list(E01_DYN_A_SCENE_CAMERA_POS), "rot": list(E01_DYN_A_SCENE_CAMERA_ROT)}
        pts_a = [(-0.4, 0.0, 0.9), (-0.4, 0.15, 0.7), (-0.35, -0.1, 0.5)]
        pts_b = [(0.1, 0.0, 0.9), (0.1, 0.15, 0.7), (0.15, -0.1, 0.5)]
        f0 = build_frame_record(
            step=210, rgb_path=png0, body_points=pts_a, cam_pos=cam["pos"], gate="ALLOW"
        )
        f1 = build_frame_record(
            step=280, rgb_path=png1, body_points=pts_b, cam_pos=cam["pos"], gate="ALLOW"
        )
        man = build_capture_manifest(
            frames=[f0, f1],
            camera_pose=cam,
            geometry_window=geom,
            episode_gates=ep,
        )
        roundtrip = json.loads(json.dumps(man))
        assert roundtrip["motion_source"] == MOTION_SOURCE_ARM_WAVE
        assert roundtrip["seed"] == 42
        assert roundtrip["scenario"] == "arm_wave"
        assert roundtrip["visual_gate_ok"] is True


def test_b0_b4_sha_stable():
    sha_map = paper_scenario_sha_map(ROOT)
    assert sha_map, "expected paper_scenarios YAMLs"
    assert_b0_b4_files_unchanged(ROOT, sha_map)
    # Fingerprint for report (stable within this worktree).
    blob = json.dumps(sha_map, sort_keys=True).encode()
    assert len(hashlib.sha256(blob).hexdigest()) == 64


def main():
    test_camera_override_default_off()
    test_camera_override_unchanged_without_flag()
    test_dyn_a_camera_pose_when_override_on()
    test_scenario_seed_motion_capture_steps()
    test_virtual_hand_and_post_rejected()
    test_roi_and_displacement()
    test_geometry_window_and_manifest_roundtrip()
    test_b0_b4_sha_stable()
    print("PASS test_e01_dyn_a_capture_unit")


if __name__ == "__main__":
    main()
