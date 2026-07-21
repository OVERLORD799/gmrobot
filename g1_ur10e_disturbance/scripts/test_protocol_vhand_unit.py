"""Regression tests for P0-1/P0-2/P0-3 per-part protocol control flow.

These tests exercise the real phase sequence and helpers used by run_phase3,
without requiring Isaac Sim.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ_ROOT)

from batch_runner import BatchTestRunner
from per_part_state import PerPartTester, Phase
from protocol_vhand import (
    snapshot_parts_placed,
    protocol_retreat_transition,
    resolve_per_part_attractor,
    per_part_radius,
)
from test_metrics import EpisodeMetrics, MetricsWriter


# ---------------------------------------------------------------------------
# P0-1: success-aware parts snapshot
# ---------------------------------------------------------------------------

def test_snapshot_success_overrides_stale_index():
    """Controller success=True with internal index 19 must write 20/20."""
    placed = snapshot_parts_placed(success=True, parts_placed=19, total_parts=20)
    assert placed == 20


def test_snapshot_failure_keeps_raw_count():
    placed = snapshot_parts_placed(success=False, parts_placed=7, total_parts=20)
    assert placed == 7


def test_final_csv_writes_20_of_20_when_controller_success():
    """MetricsWriter must emit task_completed=True with parts_placed=20."""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = str(Path(tmp) / "ep.csv")
        metrics = EpisodeMetrics(episode_id=0, parts_total=20)
        metrics.total_steps = 100
        metrics.policy_steps = 100
        # Simulate the stale controller index that previously overwrote the fix.
        metrics.parts_placed = snapshot_parts_placed(
            success=True, parts_placed=19, total_parts=20,
        )
        MetricsWriter(csv_path).write(metrics)

        with open(csv_path, newline="") as f:
            row = next(csv.DictReader(f))
        assert row["parts_placed"] == "20"
        assert row["parts_total"] == "20"
        assert row["task_completed"] in ("True", "true", "1")

        jsonl = Path(csv_path.replace(".csv", ".jsonl")).read_text()
        assert '"parts_placed": 20' in jsonl
        assert '"task_completed": true' in jsonl


# ---------------------------------------------------------------------------
# P0-2: retreat edge + clear across TRANSIT→RESET→PICK→TRANSIT
# ---------------------------------------------------------------------------

def test_protocol_retreat_edge_and_clear_sequence():
    """TRANSIT→RESET emits one edge; RESET→PICK and →TRANSIT clear latch."""
    retreated = False
    events = []

    sequence = [
        ("", "transit"),
        ("transit", "transit"),       # hold: no edge
        ("transit", "reset"),         # retreat edge
        ("reset", "reset"),           # hold retreated
        ("reset", "pick"),            # clear
        ("pick", "transit"),          # still clear, re-deploy
        ("transit", "reset"),         # second retreat edge
    ]
    for prev, cur in sequence:
        retreated, edge = protocol_retreat_transition(prev, cur, retreated)
        events.append((prev, cur, retreated, edge))

    # First retreat edge only on transit→reset
    assert events[2] == ("transit", "reset", True, True)
    # Holding RESET keeps latch, no new edge
    assert events[3][2] is True and events[3][3] is False
    # RESET→PICK clears
    assert events[4][2] is False and events[4][3] is False
    # Entering TRANSIT stays clear
    assert events[5][2] is False
    # Second TRANSIT→RESET produces a second edge
    assert events[6] == ("transit", "reset", True, True)

    edge_count = sum(1 for *_, edge in events if edge)
    assert edge_count == 2


def test_metrics_retreat_uses_event_not_long_lived_state():
    """Long-lived retreated=True must not keep counting retreat edges."""
    m = EpisodeMetrics(episode_id=0, parts_total=20)
    # Step 1: genuine edge
    m.record_step(
        g1_root_z=0.9, g1_ur10e_distance=1.0,
        disturbance_attempt_id=1,
        retreat_event_this_step=True, vhand_retreated=True, policy_step=10,
    )
    first = m._retreat_step
    assert first == 1
    # Steps 2-4: latch stays True but no new edge
    for _ in range(3):
        m.record_step(
            g1_root_z=0.9, g1_ur10e_distance=1.0,
            disturbance_attempt_id=1,
            retreat_event_this_step=False, vhand_retreated=True, policy_step=20,
        )
    assert m._retreat_step == first


def test_second_transit_gets_new_attempt_id():
    """Simulate protocol-driven disturbance attempt windows across two TRANSIT cycles."""
    retreated = False
    disturbance_active = False
    attempt_id = 0
    attempt_ids_seen: list[int] = []

    phases = [
        "transit", "transit", "transit",
        "reset", "reset",
        "pick", "pick",
        "transit", "transit",
    ]
    prev = ""
    for cur in phases:
        retreated, _edge = protocol_retreat_transition(prev, cur, retreated)
        protocol_transit = cur == "transit" and not retreated
        if protocol_transit:
            if not disturbance_active:
                disturbance_active = True
                attempt_id += 1
                attempt_ids_seen.append(attempt_id)
        else:
            disturbance_active = False
        prev = cur

    assert attempt_ids_seen == [1, 2], attempt_ids_seen


# ---------------------------------------------------------------------------
# P0-3: TRANSIT attractor stays on corridor, not EE
# ---------------------------------------------------------------------------

def test_transit_attractor_is_static_corridor_not_ee():
    block = np.array([0.62, -0.05], dtype=np.float32)
    ee = np.array([0.80, 0.10], dtype=np.float32)
    head = np.array([0.10, 0.00], dtype=np.float32)

    attr = resolve_per_part_attractor(
        phase="transit",
        protocol_attractor_xy=block,
        head_xy=head,
        ee_xy=ee,
    )
    assert np.allclose(attr, block)
    assert not np.allclose(attr, ee)


def test_pick_place_use_small_radius_and_ee_attractor():
    ee = np.array([0.70, 0.05], dtype=np.float32)
    head = np.array([0.10, 0.00], dtype=np.float32)
    for phase in ("pick", "place"):
        attr = resolve_per_part_attractor(
            phase=phase,
            protocol_attractor_xy=ee,
            head_xy=head,
            ee_xy=ee,
        )
        assert np.allclose(attr, ee)
        assert per_part_radius(phase) == 0.08


def test_reset_attractor_is_head():
    head = np.array([0.12, -0.03], dtype=np.float32)
    ee = np.array([0.80, 0.10], dtype=np.float32)
    attr = resolve_per_part_attractor(
        phase="reset",
        protocol_attractor_xy=None,
        head_xy=head,
        ee_xy=ee,
    )
    assert np.allclose(attr, head)


def test_per_part_tester_transit_block_stable_across_ee_motion():
    """PerPartTester TRANSIT attractor must not track moving EE."""
    cmds = [{"pick": "A@1", "place": "B@1"}]
    tester = PerPartTester(cmds)
    head = np.array([0.1, 0.0, 0.9], dtype=np.float32)
    ee1 = np.array([0.55, -0.1, 0.4], dtype=np.float32)
    ee2 = np.array([0.70, 0.2, 0.45], dtype=np.float32)

    # Enter TRANSIT via stage name
    tester.update("lift_slot_A_1", ee1, head, True)
    assert tester.phase == Phase.TRANSIT
    first = tester.attractor_xy.copy()
    assert first is not None

    # EE moves — attractor must stay on the corridor block
    tester.update("move_above_box_with_slot_A_1", ee2, head, True)
    assert tester.phase == Phase.TRANSIT
    second = tester.attractor_xy.copy()
    assert np.allclose(first, second)
    assert not np.allclose(second, ee2[:2])

    resolved = resolve_per_part_attractor(
        phase=tester.phase.value,
        protocol_attractor_xy=tester.attractor_xy,
        head_xy=head[:2],
        ee_xy=ee2[:2],
    )
    assert np.allclose(resolved, first)


def test_full_phase_sequence_transit_reset_pick_transit():
    """End-to-end protocol state + retreat latch across one part cycle."""
    cmds = [{"pick": "A@1", "place": "B@1"}, {"pick": "A@2", "place": "B@2"}]
    tester = PerPartTester(cmds)
    head = np.array([0.1, 0.0, 0.9], dtype=np.float32)
    ee = np.array([0.6, 0.0, 0.4], dtype=np.float32)

    retreated = False
    prev = ""
    attempt_id = 0
    disturbance_active = False
    edges = 0
    transit_attrs: list[np.ndarray] = []

    stages = [
        ("descend_to_slot_A_1", False),
        ("close_gripper_slot_A_1", True),
        ("lift_slot_A_1", True),
        ("move_above_box_with_slot_A_1", True),
        ("lift_after_releasing_slot_B_1", False),  # RESET
        ("descend_to_slot_A_2", False),            # next PICK
        ("lift_slot_A_2", True),                   # next TRANSIT
    ]

    for stage, grasping in stages:
        tester.update(stage, ee, head, grasping)
        cur = tester.phase.value
        retreated, edge = protocol_retreat_transition(prev, cur, retreated)
        if edge:
            edges += 1
        protocol_transit = cur == "transit" and not retreated
        if protocol_transit:
            if not disturbance_active:
                disturbance_active = True
                attempt_id += 1
            transit_attrs.append(
                resolve_per_part_attractor(
                    phase=cur,
                    protocol_attractor_xy=tester.attractor_xy,
                    head_xy=head[:2],
                    ee_xy=ee[:2] + np.array([0.05 * attempt_id, 0.0]),
                )
            )
        else:
            disturbance_active = False
        prev = cur

    assert edges == 1  # only one TRANSIT→RESET edge in this sequence
    assert attempt_id == 2  # two TRANSIT windows
    assert len(transit_attrs) >= 2
    # No TRANSIT attractor equals the moving EE offset
    for attr in transit_attrs:
        assert not np.allclose(attr, ee[:2])


# ---------------------------------------------------------------------------
# Batch runner: semantic inconsistency fails validation after all checks
# ---------------------------------------------------------------------------

def _write_min_csv(path: str, **overrides):
    fields = [
        "episode_id", "total_steps", "parts_placed", "parts_total",
        "policy_steps", "task_completed",
        "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
        "d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off",
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
        "episode_id": "0",
        "total_steps": "500",
        "parts_placed": "19",
        "parts_total": "20",
        "task_completed": "True",
        "policy_steps": "500",
    })
    row.update(overrides)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(row)


def test_batch_runner_rejects_task_completed_with_short_parts():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = str(Path(tmp) / "bad.csv")
        _write_min_csv(csv_path, parts_placed="19", parts_total="20",
                       task_completed="True")
        Path(tmp, "stdout.txt").write_text("ALL PARTS PLACED\n")
        Path(tmp, "stderr.txt").write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("b1", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is False
        assert "Data inconsistency" in (ep.subprocess_validation_errors or "")
        assert ep.success is True
        assert ep.parts_placed == 19


def test_batch_runner_accepts_consistent_20_of_20():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = str(Path(tmp) / "ok.csv")
        _write_min_csv(csv_path, parts_placed="20", parts_total="20",
                       task_completed="True")
        Path(tmp, "stdout.txt").write_text(
            "Failed to startup plugin carb.windowing-glfw.plugin\n"
            "ALL PARTS PLACED\n"
        )
        Path(tmp, "stderr.txt").write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("b1", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is True, ep.subprocess_validation_errors
        assert ep.parts_placed == 20
        assert ep.success is True


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  PASS  {fn.__name__}")
    print(f"All {len(tests)} protocol P0 unit tests passed.")
