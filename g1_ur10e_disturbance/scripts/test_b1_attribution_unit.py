"""Regression tests for B1 attribution / retreat / knock-off P0 fixes.

Uses existing paper_demo ``*_events.csv`` failure samples for offline recompute.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ_ROOT)

from batch_runner import BatchTestRunner
from protocol_vhand import (
    ReplanAttribution,
    CollisionEpisodeTracker,
    KnockOffTracker,
    protocol_retreat_transition,
    recompute_d_replan_caused_from_csv,
    recompute_d_replan_caused_from_events,
)
from test_metrics import EpisodeMetrics
import numpy as np


EVENTS_S42 = (
    Path(_PROJ_ROOT)
    / "results/paper_demo/static_occupancy_proxy_s42_113910"
    / "static_occupancy_proxy_s42_113910_events.csv"
)
EVENTS_S43 = (
    Path(_PROJ_ROOT)
    / "results/paper_demo/static_occupancy_proxy_r1_s43_115812"
    / "static_occupancy_proxy_r1_s43_115812_events.csv"
)
EVENTS_S44 = (
    Path(_PROJ_ROOT)
    / "results/paper_demo/static_occupancy_proxy_r2_s44_121745"
    / "static_occupancy_proxy_r2_s44_121745_events.csv"
)


# ---------------------------------------------------------------------------
# P0-2: offline event CSV → d_replan_caused=15
# ---------------------------------------------------------------------------

def test_offline_recompute_existing_b1_events_s42():
    assert EVENTS_S42.exists(), EVENTS_S42
    n = recompute_d_replan_caused_from_csv(str(EVENTS_S42))
    assert n == 15, n


def test_offline_recompute_all_three_b1_seeds():
    for path in (EVENTS_S42, EVENTS_S43, EVENTS_S44):
        if not path.exists():
            continue
        n = recompute_d_replan_caused_from_csv(str(path))
        assert n == 15, (path.name, n)


def test_ttc_apply_after_warn_window_still_attributed():
    """Trigger captured while active; apply counted without live disturbance_active."""
    m = EpisodeMetrics(episode_id=0, parts_total=20)
    attr = ReplanAttribution.from_trigger(
        attempt_id=3,
        trigger_rule="ttc",
        trigger_source="scripted_virtual_hand",
        trigger_step=100,
    )
    # Apply step: disturbance_active=False (window already closed)
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_active=False,
        disturbance_source="scripted_virtual_hand",
        disturbance_attempt_id=3,
        replan_success=True,
        replan_event_id=7,
        replan_attribution=attr,
        replan_trigger_source="scripted_virtual_hand",
    )
    assert m.d_replan_caused == 1


def test_workspace_replan_not_counted():
    m = EpisodeMetrics(episode_id=0, parts_total=20)
    attr = ReplanAttribution.from_trigger(
        attempt_id=1,
        trigger_rule="workspace",
        trigger_source="workspace",
    )
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_source="scripted_virtual_hand",
        replan_success=True,
        replan_event_id=1,
        replan_attribution=attr,
    )
    assert m.d_replan_caused == 0


# ---------------------------------------------------------------------------
# P0-1: replan → retreat → redeploy chain
# ---------------------------------------------------------------------------

def test_replan_retreat_redeploy_metrics_chain():
    m = EpisodeMetrics(episode_id=0, parts_total=20)
    attr = ReplanAttribution.from_trigger(
        attempt_id=1, trigger_rule="ttc",
        trigger_source="scripted_virtual_hand",
    )
    # Apply + retreat edge
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.4,
        disturbance_source="scripted_virtual_hand",
        disturbance_attempt_id=1,
        replan_success=True, replan_event_id=1,
        replan_attribution=attr,
        retreat_event_this_step=True,
        vhand_retreated=True,
        policy_step=100, parts_placed_now=2,
    )
    assert m.d_replan_caused == 1
    assert 1 in m._attempt_recoveries
    assert m._attempt_recoveries[1].retreat_step > 0

    # Progress while retreated
    for i in range(5):
        m.record_step(
            g1_root_z=0.9, g1_ur10e_distance=0.5,
            disturbance_attempt_id=1,
            vhand_retreated=True,
            policy_step=100 + (i + 1) * 10,
            parts_placed_now=2,
        )
    # Redeploy
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=1,
        redeploy_event_this_step=True,
        vhand_retreated=False,
        policy_step=200, parts_placed_now=3,
    )
    m.parts_placed = 5
    m.policy_steps = 250
    m.finalise()
    assert m.progress_after_retreat is True
    assert m.recovered_attempt_count >= 1
    assert m.parts_placed_after_retreat >= 1


def test_protocol_place_to_reset_is_backup_retreat():
    retreated, edge = protocol_retreat_transition("place", "reset", False)
    assert retreated is True and edge is True
    retreated, edge = protocol_retreat_transition("reset", "pick", True)
    assert retreated is False and edge is False


# ---------------------------------------------------------------------------
# P0-4: knock-off / collision dedupe
# ---------------------------------------------------------------------------

def test_knock_off_dedupes_by_part_id_and_ignores_unmatched():
    tr = KnockOffTracker()
    for _ in range(100):
        tr.observe_drop(3, disturbance_active=True)
        tr.observe_drop(5, disturbance_active=True)
        tr.observe_drop(-1, disturbance_active=True)
    assert tr.d_knock_off == 2
    assert tr.object_drop_frame_count == 300
    assert tr.unmatched_drop_frame_count == 100

    m = EpisodeMetrics(episode_id=0, parts_total=20)
    for _ in range(50):
        m.record_step(
            g1_root_z=0.9, g1_ur10e_distance=0.5,
            disturbance_active=True,
            mat_events=[
                SimpleNamespace(event_type="object_drop", part_id=1),
                SimpleNamespace(event_type="object_drop", part_id=-1),
            ],
        )
    m.finalise()
    assert m.d_knock_off == 1
    assert m.object_drop_frame_count == 100
    assert m.d_knock_off <= m.parts_total


def test_collision_rising_edge_episodes():
    tr = CollisionEpisodeTracker(cooldown_steps=3)
    # Sustained contact = 1 episode
    for _ in range(10):
        tr.observe(True)
    assert tr.count == 1
    # Gap then new contact
    for _ in range(5):
        tr.observe(False)
    tr.observe(True)
    assert tr.count == 2


def test_batch_runner_rejects_excessive_knock_off():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = str(Path(tmp) / "bad.csv")
        fields = [
            "episode_id", "total_steps", "parts_placed", "parts_total",
            "policy_steps", "task_completed", "d_knock_off",
            "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
            "d_stop_caused", "d_slow_caused", "d_replan_caused",
            "object_drop_count", "collision_count", "footstep_count",
            "f_consecutive_stop_max", "h_vlm_action", "h_vlm_latency_ms",
            "min_g1_ur10e_distance_m", "min_surface_distance_m",
            "mean_g1_ur10e_distance_m",
            "disturbance_source", "disturbance_scenario",
            "gate_trigger_source", "replan_trigger_source",
            "disturbance_attempt_id",
        ]
        row = {k: "0" for k in fields}
        row.update({
            "episode_id": "0", "total_steps": "100", "parts_placed": "5",
            "parts_total": "20", "task_completed": "False",
            "d_knock_off": "425", "object_drop_count": "425",
        })
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerow(row)
        Path(tmp, "stdout.txt").write_text("ok\n")
        Path(tmp, "stderr.txt").write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        ep = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))._parse_output(
            "b1", "r1", csv_path, result, 1.0
        )
        assert ep.subprocess_validated is False
        assert "d_knock_off" in (ep.subprocess_validation_errors or "")


def test_live_metrics_match_offline_recompute_for_synthetic_events():
    events = []
    for i in range(1, 16):
        events.append({
            "sim_step": str(i * 100),
            "event_type": "trigger",
            "attempt_id": str(i),
            "event_id": "",
            "trigger_rule": "ttc",
            "trigger_source": "scripted_virtual_hand",
            "applied_step": "",
        })
        events.append({
            "sim_step": str(i * 100),
            "event_type": "applied",
            "attempt_id": str(i),
            "event_id": str(i),
            "trigger_rule": "ttc",
            "trigger_source": "scripted_virtual_hand",
            "applied_step": str(i * 100),
        })
    assert recompute_d_replan_caused_from_events(events) == 15

    m = EpisodeMetrics(episode_id=0, parts_total=20)
    for i in range(1, 16):
        attr = ReplanAttribution.from_trigger(
            attempt_id=i, trigger_rule="ttc",
            trigger_source="scripted_virtual_hand",
        )
        m.record_step(
            g1_root_z=0.9, g1_ur10e_distance=0.5,
            disturbance_active=False,  # window already closed
            disturbance_source="scripted_virtual_hand",
            disturbance_attempt_id=i,
            replan_success=True,
            replan_event_id=i,
            replan_attribution=attr,
            retreat_event_this_step=True,
            policy_step=i * 10,
            parts_placed_now=i - 1,
        )
    assert m.d_replan_caused == 15


# ---------------------------------------------------------------------------
# Attempt uniqueness / recovery pairing / prefer_replan
# ---------------------------------------------------------------------------

def test_prefer_replan_suppresses_non_timeout_transit_retreat():
    retreated, edge = protocol_retreat_transition(
        "transit", "reset", False, prefer_replan=True, timed_out=False,
    )
    assert retreated is False and edge is False
    retreated, edge = protocol_retreat_transition(
        "transit", "reset", False, prefer_replan=True, timed_out=True,
    )
    assert retreated is True and edge is True
    # Natural PLACE→RESET must not steal the retreat edge from replan.
    retreated, edge = protocol_retreat_transition(
        "place", "reset", False, prefer_replan=True, timed_out=False,
    )
    assert retreated is False and edge is False


def test_duplicate_retreat_edge_suppressed():
    retreated, edge = protocol_retreat_transition(
        "place", "reset", False, attempt_already_retreated=True,
    )
    assert retreated is True and edge is False
    retreated, edge = protocol_retreat_transition(
        "place", "reset", True,  # already retreated latch
    )
    assert retreated is True and edge is False


def test_recovery_requires_redeploy_pairing():
    m = EpisodeMetrics(episode_id=0, parts_total=3)
    # Protocol-only retreat without redeploy must NOT count as recovered.
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=1,
        retreat_event_this_step=True,
        policy_step=10, parts_placed_now=0,
    )
    for i in range(20):
        m.record_step(
            g1_root_z=0.9, g1_ur10e_distance=0.5,
            disturbance_attempt_id=1,
            vhand_retreated=True,
            policy_step=20 + i, parts_placed_now=1,
        )
    m.parts_placed = 3
    m.policy_steps = 100
    m.finalise()
    assert m._attempt_recoveries[1].redeploy_step < 0
    # task completed → terminal_success may close the last open attempt
    assert m._attempt_recoveries[1].terminal_success is True
    assert m._attempt_recoveries[1].recovered is True
    assert m.attempt_invariant_errors() == []

    # Mid-episode orphan (task not complete) must not be recovered.
    m2 = EpisodeMetrics(episode_id=0, parts_total=3)
    m2.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=1,
        retreat_event_this_step=True,
        policy_step=10, parts_placed_now=0,
    )
    m2.parts_placed = 1
    m2.policy_steps = 50
    m2.finalise()
    assert m2._attempt_recoveries[1].recovered is False
    assert m2._attempt_recoveries[1].terminal_success is False


def test_redeploy_attaches_to_open_attempt():
    m = EpisodeMetrics(episode_id=0, parts_total=3)
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=1,
        retreat_event_this_step=True,
        policy_step=10, parts_placed_now=0,
    )
    # Redeploy with mismatched/zero id should still pair.
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=0,
        redeploy_event_this_step=True,
        policy_step=40, parts_placed_now=1,
    )
    m.parts_placed = 1
    m.policy_steps = 40
    m.finalise()
    assert m._attempt_recoveries[1].redeploy_step > 0
    assert m._attempt_recoveries[1].recovered is True


def test_recovery_delta_frozen_at_redeploy_not_episode_end():
    """Redeployed attempt deltas must not be recomputed against episode end."""
    m = EpisodeMetrics(episode_id=0, parts_total=3)
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=1,
        retreat_event_this_step=True,
        policy_step=200, parts_placed_now=0,
    )
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=0.5,
        disturbance_attempt_id=1,
        redeploy_event_this_step=True,
        policy_step=500, parts_placed_now=1,
    )
    assert m._attempt_recoveries[1].policy_delta_after_retreat == 300
    assert m._attempt_recoveries[1].parts_delta_after_retreat == 1
    # Episode continues far beyond redeploy.
    m.parts_placed = 3
    m.policy_steps = 1400
    m.finalise()
    assert m._attempt_recoveries[1].policy_delta_after_retreat == 300
    assert m._attempt_recoveries[1].parts_delta_after_retreat == 1
    assert m._attempt_recoveries[1].recovered is True
    assert m._attempt_recoveries[1].close_reason == "redeploy"


def test_virtual_source_does_not_zero_real_collision_fields():
    m = EpisodeMetrics(episode_id=0, parts_total=3)
    for _ in range(5):
        m.record_step(
            g1_root_z=0.9, g1_ur10e_distance=0.5,
            disturbance_source="scripted_virtual_hand",
            mat_events=[SimpleNamespace(event_type="collision_impact_robot")],
        )
    m.finalise()
    assert m.raw_collision_frame_count == 5
    assert m.collision_count >= 1
    assert m.collision_episode_count >= 1
    assert m.robot_object_collision_count >= 1
    assert m.proxy_physical_contact_count == 0


def test_gait_zone_not_collision():
    from mat_event_detector import MatEventDetector
    et = MatEventDetector._classify(
        world_xy=(0.10, 0.0),
        foot_xy={
            "left": np.array([0.5, 0.5], dtype=np.float32),
            "right": np.array([0.5, -0.5], dtype=np.float32),
        },
        total_force=80.0,
        area=6,
    )
    assert et.startswith("footstep")


def test_foot_proximity_beats_workspace_collision():
    from mat_event_detector import MatEventDetector
    et = MatEventDetector._classify(
        world_xy=(0.40, 0.0),
        foot_xy={
            "left": np.array([0.42, 0.02], dtype=np.float32),
            "right": np.array([0.9, 0.9], dtype=np.float32),
        },
        total_force=80.0,
        area=6,
    )
    assert et == "footstep_left"


def test_per_part_radius_reads_scenario_overrides():
    from protocol_vhand import per_part_radius
    assert per_part_radius("transit") == 0.40
    assert per_part_radius("pick") == 0.08
    assert per_part_radius("place") == 0.08
    assert per_part_radius("reset") == 0.30
    assert per_part_radius("transit", transit_radius=0.40) == 0.40
    assert per_part_radius("transit", transit_radius=0.42) == 0.42
    assert per_part_radius("transit", transit_proxy_radius=0.40) == 0.40
    assert per_part_radius("pick", pick_place_proxy_radius=0.09) == 0.09


def test_transit_telemetry_slow_streak_and_replan():
    m = EpisodeMetrics(episode_id=0, parts_total=3)
    assert m.note_transit_observation(proxy_distance=0.50, is_slow=False) == 0
    assert m.transit_min_proxy_distance == 0.50
    # streak start
    assert m.note_transit_observation(proxy_distance=0.22, is_slow=True) == 0
    assert m.note_transit_observation(proxy_distance=0.21, is_slow=True) == 0
    assert m.note_transit_observation(proxy_distance=0.20, is_slow=True) == 0
    assert m.transit_slow_count == 3
    assert m.transit_consecutive_slow_max == 3
    assert m.transit_min_proxy_distance == 0.20
    # streak end
    ended = m.note_transit_observation(proxy_distance=0.40, is_slow=False)
    assert ended == 3
    m.note_transit_replan()
    m.note_transit_replan()
    assert m.transit_replan_count == 2
    m.finalise()
    d = m.as_dict()
    assert d["transit_slow_count"] == 3
    assert d["transit_consecutive_slow_max"] == 3
    assert d["transit_replan_count"] == 2
    assert d["transit_min_proxy_distance"] == 0.20


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"All {len(tests)} B1 attribution P0 unit tests passed.")
