#!/usr/bin/env python3
"""V1-D1A offline unit tests: far-corridor capture helpers (no Isaac / no POST)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.control_isolation import (  # noqa: E402
    SemanticLeakageCounters,
    control_decision_hash,
)
from shadow.v1d1a_capture import (  # noqa: E402
    CAPTURE_PLAN_STEPS,
    MIN_PROXY_PIXEL_AREA,
    MIN_SCREEN_DISPLACEMENT_PX,
    VISUAL_SEMANTIC_RISK,
    assert_b0_b4_untouched_by_config,
    audit_geometry_allow,
    build_capture_manifest,
    build_frame_record,
    detect_red_proxy_roi,
    trajectory_pose_hash,
    validate_capture_only_flags,
    _linear_pose_at_step,
)


CFG = ROOT / "configs" / "ivj_v1d1_far_corridor_motion.yaml"

# Matches YAML trajectory (keep in sync with config).
TRAJ = {
    "start_pos": [0.40, -0.55, 0.50],
    "end_pos": [0.40, 0.55, 0.50],
    "start_step": 0,
    "duration_steps": 200,
    "hold_steps": 40,
    "retreat_pos": [0.40, -0.55, 0.50],
    "retreat_duration_steps": 40,
}


def test_visual_semantic_risk_declared_low():
    assert VISUAL_SEMANTIC_RISK == "low"


def test_semantic_enforcement_default_is_shadow_capture_only():
    flags = validate_capture_only_flags()
    assert flags["ok"] is True
    assert flags["post_count_expected"] == 0
    assert flags["clients_initialized_expected"] is False
    assert flags["semantic_enforcement_mode"] == "shadow_or_off"


def test_capture_only_rejects_network_flags():
    bad = validate_capture_only_flags(enable_five_stage_shadow=True)
    assert bad["ok"] is False
    bad2 = validate_capture_only_flags(enable_vlm=True, enable_perception=True)
    assert bad2["ok"] is False
    bad3 = validate_capture_only_flags(enable_replan=True)
    assert bad3["ok"] is False


def test_trajectory_hash_stable_and_plan_steps_differ():
    h1 = trajectory_pose_hash(**TRAJ)
    h2 = trajectory_pose_hash(**TRAJ)
    assert h1 == h2
    assert len(h1) == 64
    p0, _ = _linear_pose_at_step(**TRAJ, step_index=0, control_dt=0.02)
    p1, _ = _linear_pose_at_step(**TRAJ, step_index=100, control_dt=0.02)
    assert not np.allclose(p0, p1)
    assert CAPTURE_PLAN_STEPS == (0, 100)


def test_config_does_not_touch_b0_b4():
    assert CFG.is_file()
    assert_b0_b4_untouched_by_config(CFG)
    text = CFG.read_text(encoding="utf-8")
    assert "enforcement_mode: live" not in text
    assert "visual_semantic_risk=low" in text or "visual_semantic_risk=low" in text.replace(" ", "")


def test_red_proxy_detection_and_manifest_round_trip():
    rgb = np.zeros((480, 640, 3), dtype=np.uint8)
    rgb[100:130, 200:240, 0] = 220
    rgb[100:130, 200:240, 1] = 40
    rgb[100:130, 200:240, 2] = 40
    roi = detect_red_proxy_roi(rgb)
    assert roi.visible is True
    assert roi.pixel_area >= MIN_PROXY_PIXEL_AREA

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        from PIL import Image

        paths = []
        for i, step in enumerate(CAPTURE_PLAN_STEPS):
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            x0 = 200 + i * 80
            img[100:140, x0 : x0 + 40, 0] = 220
            img[100:140, x0 : x0 + 40, 1] = 30
            img[100:140, x0 : x0 + 40, 2] = 30
            p = td_path / f"frame_{step:06d}_env0.png"
            Image.fromarray(img).save(p)
            paths.append(p)

        frames = []
        for step, p in zip(CAPTURE_PLAN_STEPS, paths):
            pos, vel = _linear_pose_at_step(**TRAJ, step_index=step, control_dt=0.02)
            frames.append(
                build_frame_record(
                    png_path=p,
                    sim_step=step,
                    wall_time_s=float(step) * 0.02,
                    proxy_pos=pos.tolist(),
                    proxy_vel=vel.tolist(),
                    proxy_radius_m=0.05,
                    dist_ee_human=0.45,
                    dist_held_proxy=None,
                    g_rule=0,
                    gate_reason="none",
                    protocol_phase="approach",
                    control_decision_hash=control_decision_hash(
                        gate_decision=0,
                        action=None,
                        should_advance=True,
                        protocol_phase="approach",
                        replan_event=None,
                        task_progression=step,
                    ),
                    safe_dist_warn=0.16,
                    safe_dist_hard_stop=0.13,
                    ttc_threshold=0.5,
                    ttc_warn_threshold=1.5,
                )
            )
        man = build_capture_manifest(
            frames,
            trajectory_hash=trajectory_pose_hash(**TRAJ),
            safety_config_sha256="abc",
            image_id="sha256:deadbeef",
            post_count=0,
            gate_counts={"ALLOW": 280, "STOP": 0, "SLOW_DOWN": 0},
            min_geometry_margin_m=0.2,
        )
        assert man["post_count"] == 0
        assert man["rgb_hashes_unique"] is True
        assert man["pixel_displacement_px"] is not None
        assert man["pixel_displacement_px"] >= MIN_SCREEN_DISPLACEMENT_PX
        assert frames[0]["frame_id"] != frames[1]["frame_id"]
        assert frames[0]["request_id"] != frames[1]["request_id"]

        out = td_path / "capture_manifest.json"
        out.write_text(json.dumps(man, indent=2), encoding="utf-8")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["frames"][0]["rgb_sha256"] == frames[0]["rgb_sha256"]
        assert loaded["frames"][0]["frame_id"] == frames[0]["frame_id"]


def test_geometry_allow_audit_and_leakage_zero():
    ok = audit_geometry_allow([0] * 50, replan_count=0)
    assert ok["ok"] is True
    bad = audit_geometry_allow([0, 2, 0], replan_count=0)
    assert bad["ok"] is False
    bad2 = audit_geometry_allow([0] * 10, replan_count=1)
    assert bad2["ok"] is False
    SemanticLeakageCounters().assert_all_zero()
    h0 = control_decision_hash(
        gate_decision=0,
        action=None,
        should_advance=True,
        protocol_phase=None,
        replan_event=None,
        task_progression=0,
    )
    h1 = control_decision_hash(
        gate_decision=0,
        action=None,
        should_advance=True,
        protocol_phase=None,
        replan_event=None,
        task_progression=0,
    )
    assert h0 == h1


def test_future_vlm_request_id_maps_from_frame_id():
    """frame_id / request_id are stable UUIDv5 mappings for future 2-POST filter."""
    with tempfile.TemporaryDirectory() as td:
        from PIL import Image

        p = Path(td) / "frame_000000_env0.png"
        Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(p)
        rec = build_frame_record(
            png_path=p,
            sim_step=0,
            wall_time_s=0.0,
            proxy_pos=[0.4, -0.55, 0.5],
            proxy_vel=[0.0, 0.0, 0.0],
            proxy_radius_m=0.05,
            dist_ee_human=0.5,
            dist_held_proxy=None,
            g_rule=0,
            gate_reason="none",
            protocol_phase=None,
            control_decision_hash="x",
            safe_dist_warn=0.16,
            safe_dist_hard_stop=0.13,
            ttc_threshold=0.5,
            ttc_warn_threshold=1.5,
        )
        # Re-build with same paths/step → same ids
        rec2 = build_frame_record(
            png_path=p,
            sim_step=0,
            wall_time_s=0.0,
            proxy_pos=[0.4, -0.55, 0.5],
            proxy_vel=[0.0, 0.0, 0.0],
            proxy_radius_m=0.05,
            dist_ee_human=0.5,
            dist_held_proxy=None,
            g_rule=0,
            gate_reason="none",
            protocol_phase=None,
            control_decision_hash="x",
            safe_dist_warn=0.16,
            safe_dist_hard_stop=0.13,
            ttc_threshold=0.5,
            ttc_warn_threshold=1.5,
        )
        assert rec["frame_id"] == rec2["frame_id"]
        assert rec["request_id"] == rec2["request_id"]


if __name__ == "__main__":
    test_visual_semantic_risk_declared_low()
    test_semantic_enforcement_default_is_shadow_capture_only()
    test_capture_only_rejects_network_flags()
    test_trajectory_hash_stable_and_plan_steps_differ()
    test_config_does_not_touch_b0_b4()
    test_red_proxy_detection_and_manifest_round_trip()
    test_geometry_allow_audit_and_leakage_zero()
    test_future_vlm_request_id_maps_from_frame_id()
    print("V1D1A_CAPTURE_UNIT_OK")
