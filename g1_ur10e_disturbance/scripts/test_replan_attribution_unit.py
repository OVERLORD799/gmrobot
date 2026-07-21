"""Unit tests for §6.1 replan event edge-detection and gate attribution.

Verifies:
  - replan sticky-state does NOT cause false positive d_replan_caused.
  - replan_event_id dedup works across attempts.
  - gate_trigger_source is only set for distance/geometry-related triggers.
"""

from __future__ import annotations

import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ_ROOT)

from test_metrics import EpisodeMetrics


def test_replan_event_id_dedup_prevents_sticky_state():
    """A single replan with event_id=1 counted once; subsequent steps with
    replan_success=True but same event_id do NOT increment d_replan_caused.
    P0-2: requires disturbance_active + source match."""
    m = EpisodeMetrics(episode_id=0)
    # Step 1: replan applied with event_id=1, disturbance-attributed
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.3,
        gate_decision="SLOW_DOWN", gate_trigger="warn",
        replan_success=True, replan_event_id=1,
        replan_trigger_source="scripted_virtual_hand",
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source="scripted_virtual_hand",
        gate_trigger_source="scripted_virtual_hand",
    )
    assert m.d_replan_caused == 1
    # Step 2: same attempt, sticky replan_success=True but NO new event_id
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.3,
        gate_decision="ALLOW", gate_trigger="allow",
        replan_success=True, replan_event_id=0,  # no new event
        replan_trigger_source="scripted_virtual_hand",
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source="scripted_virtual_hand",
        gate_trigger_source="scripted_virtual_hand",
    )
    assert m.d_replan_caused == 1  # NOT incremented
    # Step 3: same attempt, same stale True, still no increment
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.3,
        gate_decision="ALLOW", gate_trigger="allow",
        replan_success=True, replan_event_id=0,
        replan_trigger_source="scripted_virtual_hand",
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source="scripted_virtual_hand",
        gate_trigger_source="scripted_virtual_hand",
    )
    assert m.d_replan_caused == 1


def test_replan_carries_to_next_attempt_only_with_new_event():
    """Old replan_success=True entering a new attempt without new event_id
    must NOT count as a new replan."""
    m = EpisodeMetrics(episode_id=0)
    _src = "scripted_virtual_hand"
    # Attempt 1: replan event_id=1
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.2,
        gate_decision="SLOW_DOWN", gate_trigger="warn",
        replan_success=True, replan_event_id=1,
        replan_trigger_source=_src,
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source=_src, gate_trigger_source=_src,
    )
    assert m.d_replan_caused == 1
    # Attempt 2: new attempt, still replan_success=True but NO new event
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.5, surface_distance=0.1,
        gate_decision="SLOW_DOWN", gate_trigger="warn",
        replan_success=True, replan_event_id=0,  # stale — no new event
        replan_trigger_source=_src,
        disturbance_active=True, disturbance_attempt_id=2,
        disturbance_source=_src, gate_trigger_source=_src,
    )
    assert m.d_replan_caused == 1  # NOT incremented
    # Attempt 2: now a real new replan with event_id=2
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.4, surface_distance=0.08,
        gate_decision="SLOW_DOWN", gate_trigger="warn",
        replan_success=True, replan_event_id=2,  # new event
        replan_trigger_source=_src,
        disturbance_active=True, disturbance_attempt_id=2,
        disturbance_source=_src, gate_trigger_source=_src,
    )
    assert m.d_replan_caused == 2


def test_replan_dedup_by_event_id_not_attempt_id():
    """Two replans in the same attempt (different event_ids) are both counted."""
    m = EpisodeMetrics(episode_id=0)
    _src = "scripted_virtual_hand"
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.2,
        gate_decision="SLOW_DOWN", gate_trigger="warn",
        replan_success=True, replan_event_id=1,
        replan_trigger_source=_src,
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source=_src, gate_trigger_source=_src,
    )
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.3, surface_distance=0.05,
        gate_decision="SLOW_DOWN", gate_trigger="warn",
        replan_success=True, replan_event_id=2,  # different event, same attempt
        replan_trigger_source=_src,
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source=_src, gate_trigger_source=_src,
    )
    assert m.d_replan_caused == 2


def test_gate_attribution_only_on_distance_triggers():
    """gate_trigger_source populated only when caller passes a non-empty value.
    The caller (run_phase3) now only passes the disturbance source when
    _gate_is_distance_related.  The metric forward-fills (empty does NOT
    overwrite previous non-empty value — correct for CSV schema)."""
    m = EpisodeMetrics(episode_id=0)
    # Distance-related trigger → source stored
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.2,
        gate_decision="STOP", gate_trigger="tier0",
        disturbance_source="scripted_virtual_hand",
        gate_trigger_source="scripted_virtual_hand",
        disturbance_active=True, disturbance_attempt_id=1,
    )
    assert m.gate_trigger_source == "scripted_virtual_hand"
    # Non-distance trigger → source NOT passed by caller, metric forward-fills
    # the previous value (empty string does not overwrite non-empty).
    m2 = EpisodeMetrics(episode_id=0)
    m2.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.2,
        gate_decision="STOP", gate_trigger="held_critical",
        disturbance_source="g1_body",
        gate_trigger_source="",  # caller filtered it out
        disturbance_active=True, disturbance_attempt_id=1,
    )
    assert m2.gate_trigger_source == ""  # never set, stays empty
    # Verify the forward-fill behavior: after setting a value, empty does NOT clear.
    m2.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.2,
        gate_decision="ALLOW", gate_trigger="allow",
        disturbance_source="g1_body",
        gate_trigger_source="g1_body",  # distance trigger
        disturbance_active=True, disturbance_attempt_id=1,
    )
    assert m2.gate_trigger_source == "g1_body"
    m2.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.2,
        gate_decision="ALLOW", gate_trigger="allow",
        disturbance_source="g1_body",
        gate_trigger_source="",  # no trigger this step → clears previous
        disturbance_active=False, disturbance_attempt_id=1,
    )
    assert m2.gate_trigger_source == ""  # P1: empty clears previous (no stale forward-fill)


def test_workspace_stop_not_counted_as_disturbance():
    """STOP with gate_trigger_source='' (workspace/held_critical) must NOT increment d_stop_caused."""
    m = EpisodeMetrics(episode_id=0)
    # Workspace STOP: disturbance_active=True but gate_trigger_source empty
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.5,
        gate_decision="STOP", gate_trigger="workspace",
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source="g1_body",
        gate_trigger_source="",  # workspace violation — not attributed to G1
    )
    assert m.d_stop_caused == 0, "workspace STOP must not count as disturbance STOP"

    # Distance STOP: gate_trigger_source matches disturbance_source
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.3, surface_distance=0.05,
        gate_decision="STOP", gate_trigger="tier0",
        disturbance_active=True, disturbance_attempt_id=1,
        disturbance_source="g1_body",
        gate_trigger_source="g1_body",  # distance trigger attributed to G1
    )
    assert m.d_stop_caused == 1, "distance STOP must be counted"


def test_three_attempts_report_three():
    """Three distinct attempts with attributed STOPs must each be counted."""
    m = EpisodeMetrics(episode_id=0)
    for attempt_id in (1, 2, 3):
        m.record_step(
            g1_root_z=0.8, g1_ur10e_distance=0.3, surface_distance=0.05,
            gate_decision="STOP", gate_trigger="tier0",
            disturbance_active=True, disturbance_attempt_id=attempt_id,
            disturbance_source="scripted_virtual_hand",
            gate_trigger_source="scripted_virtual_hand",
        )
    assert m.d_stop_caused == 3, f"3 attempts must count 3, got {m.d_stop_caused}"


def test_retreat_recovery_tracking():
    """After retreat, if policy_step advances, progress_after_retreat must be True."""
    m = EpisodeMetrics(episode_id=0)
    m.policy_steps = 100
    # Before retreat
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.05,
        gate_decision="ALLOW", gate_trigger="allow",
        disturbance_active=True, disturbance_attempt_id=1,
        vhand_retreated=False, policy_step=100,
    )
    # Retreat occurs
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.05,
        gate_decision="ALLOW", gate_trigger="allow",
        disturbance_active=False, disturbance_attempt_id=1,
        vhand_retreated=True, policy_step=100,
    )
    # After retreat, policy clock advances
    m.policy_steps = 150
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.05,
        gate_decision="ALLOW", gate_trigger="allow",
        disturbance_active=False, disturbance_attempt_id=0,
        vhand_retreated=False, policy_step=150,
    )
    m.finalise()
    assert m.progress_after_retreat is True, f"policy_step went {m._policy_step_at_retreat}→{m.policy_steps}"


def test_b1_deadlock_fails():
    """B1 with no progress after retreat must FAIL."""
    from batch_runner import EpisodeResult, BatchTestRunner
    ep = EpisodeResult(
        config_name="static_occupancy_proxy", run_id="b1_deadlock",
        parts_placed=3, parts_total=20,
        d_stop_caused=1, d_slow_caused=0, d_replan_caused=1,
        disturbance_source="scripted_virtual_hand",
        progress_after_retreat=False,  # deadlocked after retreat
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "static_occupancy_proxy",
             "safety": {"enable_replan": True}}
    )
    assert ep.scenario_pass is False, "B1 deadlock must FAIL"
    assert "retreat" in ep.scenario_failure_reasons.lower()


def test_workspace_replan_not_counted_as_disturbance():
    """Replan without disturbance_active or source match must NOT increment d_replan_caused."""
    m = EpisodeMetrics(episode_id=0)
    # Workspace replan: no disturbance, no source match
    m.record_step(
        g1_root_z=0.8, g1_ur10e_distance=0.9, surface_distance=0.5,
        gate_decision="STOP", gate_trigger="workspace",
        replan_success=True, replan_event_id=1,
        replan_trigger_source="",  # workspace — not attributed
        disturbance_active=False, disturbance_attempt_id=0,
        disturbance_source="scripted_virtual_hand",
    )
    assert m.d_replan_caused == 0, "workspace replan must not count as disturbance"
    assert m.f_replan_success is True, "replan success still recorded"


def test_unknown_scenario_not_evaluated():
    """Unknown scenario must return scenario_pass=None (NOT_EVALUATED)."""
    from batch_runner import EpisodeResult, BatchTestRunner
    ep = EpisodeResult(
        config_name="some_future_scenario", run_id="unknown",
        parts_placed=10, parts_total=20,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "some_future_scenario"}
    )
    assert ep.scenario_pass is None, "unknown scenario must be NOT_EVALUATED"
    assert "NOT_EVALUATED" in ep.scenario_failure_reasons


if __name__ == "__main__":
    test_replan_event_id_dedup_prevents_sticky_state()
    test_replan_carries_to_next_attempt_only_with_new_event()
    test_replan_dedup_by_event_id_not_attempt_id()
    test_gate_attribution_only_on_distance_triggers()
    test_workspace_stop_not_counted_as_disturbance()
    test_three_attempts_report_three()
    test_retreat_recovery_tracking()
    test_b1_deadlock_fails()
    test_unknown_scenario_not_evaluated()
    test_workspace_replan_not_counted_as_disturbance()
    print("All replan attribution unit tests passed.")
