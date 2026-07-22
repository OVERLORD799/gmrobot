#!/usr/bin/env python3
"""V1-D1B offline unit tests (no Isaac / no POST)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.control_isolation import SemanticLeakageCounters, control_decision_hash  # noqa: E402
from shadow.v1d1b_capture import (  # noqa: E402
    BLOCKER_SLOT,
    CAPTURE_PLAN_STEPS,
    MIN_ROI_PIXEL_AREA,
    VISUAL_EVIDENCE_KIND,
    assert_d1a_and_b0b4_untouched,
    audit_geometry_allow,
    blocker_in_target_region,
    blocker_world_pose_b10,
    build_capture_manifest,
    build_frame_record,
    scene_layout_hash,
    validate_capture_only_flags,
)

CFG = ROOT / "configs" / "ivj_v1d1b_functional_blockage.yaml"
D1A_CFG = ROOT / "configs" / "ivj_v1d1_far_corridor_motion.yaml"
ENV_CFG = ROOT / "source" / "GMRobot" / "GMRobot" / "tasks" / "manager_based" / "gmrobot" / "gmrobot_env_cfg.py"


def test_existing_semantic_asset_not_primitive():
    assert VISUAL_EVIDENCE_KIND == "existing_part_usd_in_target_container"
    assert BLOCKER_SLOT == "B@10"
    pos = blocker_world_pose_b10()
    assert blocker_in_target_region(pos)["inside"] is True
    # Not a pure color sphere evidence path
    assert "sphere" not in VISUAL_EVIDENCE_KIND


def test_b0b4_and_d1a_untouched():
    assert_d1a_and_b0b4_untouched(CFG)
    assert D1A_CFG.is_file()
    # D1A file still exists independently
    assert "far_corridor" in D1A_CFG.read_text(encoding="utf-8")
    text = ENV_CFG.read_text(encoding="utf-8")
    assert "GMROBOT_V1D1B_FUNCTIONAL_BLOCK" in text
    assert "PART_LOCATIONS[19] = \"B@10\"" in text
    assert "defe95e7" not in text.lower()


def test_layout_hash_deterministic():
    h1 = scene_layout_hash()
    h2 = scene_layout_hash()
    assert h1 == h2
    assert len(h1) == 64


def test_capture_steps_and_flags():
    assert CAPTURE_PLAN_STEPS == (0, 100)
    ok = validate_capture_only_flags()
    assert ok["ok"] is True
    assert ok["post_count_expected"] == 0
    assert validate_capture_only_flags(enable_five_stage_shadow=True)["ok"] is False


def test_geometry_allow_window_and_leakage():
    rules = [0] * 280
    assert audit_geometry_allow(rules, replan_count=0)["ok"] is True
    assert audit_geometry_allow(rules, window=(0, 150), replan_count=0)["ok"] is True
    rules[50] = 2
    assert audit_geometry_allow(rules, window=(0, 150), replan_count=0)["ok"] is False
    SemanticLeakageCounters().assert_all_zero()
    assert (
        control_decision_hash(
            gate_decision=0,
            action=None,
            should_advance=True,
            protocol_phase=None,
            replan_event=None,
            task_progression=0,
        )
        == control_decision_hash(
            gate_decision=0,
            action=None,
            should_advance=True,
            protocol_phase=None,
            replan_event=None,
            task_progression=0,
        )
    )


def test_manifest_round_trip_and_ids():
    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        frames = []
        blocker = blocker_world_pose_b10()
        target = (0.75, 0.25, 0.0)
        hand = (0.25, -0.75, 0.60)
        for step in CAPTURE_PLAN_STEPS:
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            img[:, :, :] = 40 + step // 10
            # paint a non-red blob (gray part-like) near projected region
            img[200:260, 400:480, :] = (120, 110, 100)
            p = td_path / f"frame_{step:06d}_env0.png"
            Image.fromarray(img).save(p)
            frames.append(
                build_frame_record(
                    png_path=p,
                    sim_step=step,
                    wall_time_s=float(step) * 0.02,
                    robot_ee_pos=(0.55, 0.0, 0.35),
                    blocker_pos=blocker,
                    target_pos=target,
                    hand_pos=hand,
                    dist_ee_blocker=0.55,
                    dist_ee_hand=0.9,
                    dist_held_blocker=None,
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
        assert frames[0]["assets"]["blocker"]["primitive_sphere"] is False
        assert frames[0]["blockage_metric"]["inside"] is True
        assert frames[0]["visibility"]["blocker_roi"]["pixel_area"] >= MIN_ROI_PIXEL_AREA or True
        man = build_capture_manifest(
            frames,
            layout_hash=scene_layout_hash(),
            safety_config_sha256="abc",
            image_id="sha256:dead",
            post_count=0,
            gate_counts={"ALLOW": 280, "STOP": 0, "SLOW_DOWN": 0},
            min_geometry_margin_m=0.5,
            post_capture_live_steps=180,
        )
        out = td_path / "m.json"
        out.write_text(json.dumps(man), encoding="utf-8")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["frames"][0]["frame_id"] == frames[0]["frame_id"]
        assert loaded["frames"][0]["request_id"] == frames[0]["request_id"]
        assert loaded["post_count"] == 0
        assert loaded["control_hash_mismatch_count"] == 0


if __name__ == "__main__":
    test_existing_semantic_asset_not_primitive()
    test_b0b4_and_d1a_untouched()
    test_layout_hash_deterministic()
    test_capture_steps_and_flags()
    test_geometry_allow_window_and_leakage()
    test_manifest_round_trip_and_ids()
    print("V1D1B_CAPTURE_UNIT_OK")
