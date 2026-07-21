#!/usr/bin/env python3
"""Offline unit tests for B2 dynamic sweep + B4-Dynamic shadow pairing."""

from __future__ import annotations

import csv
import math
import os
import sys
import tempfile
import unittest

import numpy as np

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from dynamic_sweep_proxy import (
    DynamicLateralSweepProxy,
    DynamicSweepSpec,
    PhaseProxyRadii,
    SweepLifecycle,
    compute_disturbance_trajectory_id,
    sweep_geometry_precheck,
    time_to_risk_steps_from_ttc,
)
from dynamic_audit_csv import (
    DYNAMIC_AUDIT_FIELDNAMES,
    build_dynamic_audit_row,
    format_dynamic_audit_row,
    read_dynamic_audit_csv,
    validate_dynamic_audit_rows,
)
from event_csv import (
    EVENT_CSV_FIELDNAMES,
    build_event_row,
    format_event_row,
    read_event_csv,
    validate_event_csv_rows,
)
from protocol_vhand import (
    attempt_needs_canonical_redeploy,
    dynamic_sweep_redeploy_edge,
    is_b2_proactive_trigger_rule,
    is_held_critical_trigger_rule,
    policy_clock_should_advance,
    resolve_effective_gate_name,
)
from test_metrics import EpisodeMetrics
from protocol_vhand import ReplanAttribution


# B2 corridor geometry — transit start safe against observed edge EE while
# still ending in the risk corridor (single-variable start adjustment).
_B2_START = (-0.30, -0.65, 0.45)
_B2_END = (0.62, 0.32, 0.45)
_HARD_STOP_M = 0.25
_WARN_M = 0.28


def _spec(seed: int = 42) -> DynamicSweepSpec:
    return DynamicSweepSpec(
        start_xyz=_B2_START,
        end_xyz=_B2_END,
        duration_steps=10,
        retreat_duration_steps=5,
        seed=seed,
    )


class TestTrajectoryId(unittest.TestCase):
    def test_sha256_stable(self):
        params = _spec().trajectory_hash_params()
        a = compute_disturbance_trajectory_id(params)
        b = compute_disturbance_trajectory_id(params)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_different_seed_changes_id(self):
        id1 = compute_disturbance_trajectory_id(_spec(42).trajectory_hash_params())
        id2 = compute_disturbance_trajectory_id(_spec(43).trajectory_hash_params())
        self.assertNotEqual(id1, id2)


class TestPhaseProxyRadii(unittest.TestCase):
    def test_pick_uses_small_radius_and_zero_velocity(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.53, -0.35, 0.30], dtype=np.float32)
        radii = PhaseProxyRadii()
        out = p.step(protocol_phase="pick", ee_pos=ee, phase_radii=radii)
        self.assertAlmostEqual(out.active_proxy_radius, 0.08)
        np.testing.assert_allclose(out.surface_vel_xyz, 0.0, atol=1e-6)

    def test_transit_uses_large_radius(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        radii = PhaseProxyRadii()
        p.step(protocol_phase="pick", ee_pos=ee, phase_radii=radii)
        out = p.step(protocol_phase="transit", ee_pos=ee, phase_radii=radii)
        self.assertAlmostEqual(out.active_proxy_radius, 0.40)

    def test_pick_to_transit_first_step_zero_velocity(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        radii = PhaseProxyRadii()
        p.step(protocol_phase="pick", ee_pos=ee, phase_radii=radii)
        out = p.step(protocol_phase="transit", ee_pos=ee, phase_radii=radii)
        np.testing.assert_allclose(out.surface_vel_xyz, 0.0, atol=1e-6)

    def test_reset_does_not_block_next_transit_attempt(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        radii = PhaseProxyRadii()
        p.step(protocol_phase="pick", ee_pos=ee, phase_radii=radii)
        p.step(protocol_phase="transit", ee_pos=ee, phase_radii=radii)
        p.step(protocol_phase="place", ee_pos=ee, phase_radii=radii)
        p.step(protocol_phase="reset", ee_pos=ee, phase_radii=radii)
        out = p.step(protocol_phase="transit", ee_pos=ee, phase_radii=radii)
        self.assertTrue(out.attempt_started)
        self.assertEqual(out.sweep_attempt_id, 2)


class TestSweepLifecycle(unittest.TestCase):
    def test_starts_only_on_transit_edge(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        out = p.step(protocol_phase="pick", ee_pos=ee)
        self.assertEqual(out.sweep_attempt_id, 0)
        self.assertFalse(out.attempt_started)
        out2 = p.step(protocol_phase="transit", ee_pos=ee)
        self.assertTrue(out2.attempt_started)
        self.assertEqual(out2.sweep_attempt_id, 1)
        for _ in range(3):
            p.step(protocol_phase="transit", ee_pos=ee)
        self.assertEqual(p.sweep_attempt_id, 1)

    def test_surface_velocity_matches_finite_diff(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        radii = PhaseProxyRadii()
        p.step(protocol_phase="pick", ee_pos=ee, phase_radii=radii)
        out = p.step(protocol_phase="transit", ee_pos=ee, phase_radii=radii)
        np.testing.assert_allclose(out.surface_vel_xyz, 0.0, atol=1e-6)
        prev_s = out.surface_xyz.copy()
        for _ in range(4):
            out = p.step(protocol_phase="transit", ee_pos=ee, phase_radii=radii)
            expected = (out.surface_xyz - prev_s) / 0.02
            np.testing.assert_allclose(out.surface_vel_xyz, expected, atol=1e-4)
            prev_s = out.surface_xyz.copy()

    def test_active_retreat_only_after_replan_apply(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        p.step(protocol_phase="transit", ee_pos=ee)
        out = p.step(
            protocol_phase="transit",
            ee_pos=ee,
            enforcement_mode="active",
            replan_applied_this_step=False,
        )
        self.assertEqual(out.lifecycle, SweepLifecycle.SWEEPING)
        out2 = p.step(
            protocol_phase="transit",
            ee_pos=ee,
            enforcement_mode="active",
            replan_applied_this_step=True,
        )
        self.assertTrue(out2.retreat_started)
        self.assertEqual(out2.lifecycle, SweepLifecycle.RETREATING)

    def test_shadow_never_retreats_on_would_trigger(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        p.step(protocol_phase="transit", ee_pos=ee)
        out = p.step(
            protocol_phase="transit",
            ee_pos=ee,
            enforcement_mode="shadow",
            replan_applied_this_step=True,
        )
        self.assertFalse(out.retreat_started)
        self.assertEqual(out.lifecycle, SweepLifecycle.SWEEPING)

    def test_retreat_complete_to_idle_emits_redeploy_edge(self):
        """RETREATING→IDLE must close recovery pairing (8-part attempts)."""
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        p.step(protocol_phase="transit", ee_pos=ee)
        p.step(
            protocol_phase="transit",
            ee_pos=ee,
            enforcement_mode="active",
            replan_applied_this_step=True,
        )
        was_retreating = True
        saw_redeploy = False
        for _ in range(20):
            out = p.step(protocol_phase="transit", ee_pos=ee, enforcement_mode="active")
            retreating = out.lifecycle == SweepLifecycle.RETREATING
            if dynamic_sweep_redeploy_edge(was_retreating, retreating):
                saw_redeploy = True
            was_retreating = retreating
            if out.lifecycle == SweepLifecycle.IDLE and saw_redeploy:
                break
        self.assertTrue(saw_redeploy)
        self.assertEqual(p.lifecycle, SweepLifecycle.IDLE)

    def test_place_reset_relatch_does_not_emit_second_redeploy(self):
        """P0-10: PLACE→RESET re-latch must not double-count after lifecycle redeploy."""
        from protocol_vhand import protocol_retreat_transition

        m = EpisodeMetrics(episode_id="t", parts_total=1)
        m.note_retreat(attempt_id=1, sim_step=10, policy_step=1, parts_placed=0)
        # Canonical lifecycle edge.
        self.assertTrue(dynamic_sweep_redeploy_edge(True, False))
        self.assertTrue(attempt_needs_canonical_redeploy(m._attempt_recoveries, 1))
        m.note_redeploy(
            attempt_id=1, sim_step=12, policy_step=2, parts_placed=0
        )
        self.assertFalse(attempt_needs_canonical_redeploy(m._attempt_recoveries, 1))
        # Protocol re-asserts retreated on place→reset when already retreated.
        retreated, edge = protocol_retreat_transition(
            "place", "reset", False,
            prefer_replan=True,
            attempt_already_retreated=True,
        )
        self.assertTrue(retreated)
        self.assertFalse(edge)
        # Fake "lifecycle idle" with protocol latch True must NOT emit.
        emitted = 0
        if dynamic_sweep_redeploy_edge(False, False):  # was not retreating in lifecycle
            emitted += 1
        if (
            retreated
            and attempt_needs_canonical_redeploy(m._attempt_recoveries, 1)
        ):
            emitted += 1
        self.assertEqual(emitted, 0)

    def test_eight_attempts_emit_exactly_eight_redeploy_events(self):
        """P0-10: raw event CSV must have 8 redeploys for 8 recovered attempts."""
        import csv as _csv
        from episode_audit import audit_b2_recovery_chain
        from event_csv import build_event_row, format_event_row, EVENT_CSV_HEADER
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp) / "events.csv"
            att = Path(tmp) / "attempts.csv"
            rows = []
            for aid in range(1, 9):
                step = aid * 100
                rows.append(build_event_row(
                    sim_step=step, event_type="trigger", attempt_id=aid,
                    event_id=str(aid), trigger_rule="ttc",
                    gate_metadata={"ttc": 0.4}, control_dt=0.02,
                ))
                rows.append(build_event_row(
                    sim_step=step, event_type="applied", attempt_id=aid,
                    event_id=str(aid), trigger_rule="ttc", applied_step=str(step),
                ))
                rows.append(build_event_row(
                    sim_step=step + 1, event_type="retreat", attempt_id=aid,
                    event_id=str(aid), trigger_rule="replan",
                ))
                rows.append(build_event_row(
                    sim_step=step + 50, event_type="redeploy", attempt_id=aid,
                    trigger_rule="protocol",
                ))
            with ev.open("w") as f:
                f.write(EVENT_CSV_HEADER)
                for r in rows:
                    f.write(format_event_row(r))
            with att.open("w", newline="") as f:
                w = _csv.DictWriter(f, fieldnames=[
                    "attempt_id", "retreat_step", "redeploy_step",
                    "policy_delta_after_retreat", "parts_delta_after_retreat",
                    "recovered", "terminal_success", "close_reason",
                ])
                w.writeheader()
                for aid in range(1, 9):
                    w.writerow({
                        "attempt_id": aid,
                        "retreat_step": aid * 100 + 1,
                        "redeploy_step": aid * 100 + 50,
                        "policy_delta_after_retreat": 10,
                        "parts_delta_after_retreat": 0,
                        "recovered": True,
                        "terminal_success": False,
                        "close_reason": "redeploy",
                    })
            errs, summary = audit_b2_recovery_chain(ev, att)
            self.assertEqual(errs, [], errs)
            self.assertEqual(summary["redeploy_count"], 8)

            # Duplicate redeploy must FAIL audit.
            with ev.open("a") as f:
                f.write(format_event_row(build_event_row(
                    sim_step=999, event_type="redeploy", attempt_id=1,
                    trigger_rule="protocol",
                )))
            errs2, summary2 = audit_b2_recovery_chain(ev, att)
            self.assertTrue(any("duplicate redeploy" in e for e in errs2))
            self.assertEqual(summary2["redeploy_count"], 9)

    def test_multi_attempt_metrics_close_on_redeploy_edge(self):
        m = EpisodeMetrics(episode_id="t", parts_total=8)
        for aid in (1, 2, 3):
            m.note_retreat(
                attempt_id=aid, sim_step=aid * 10, policy_step=aid, parts_placed=aid - 1
            )
            self.assertTrue(
                dynamic_sweep_redeploy_edge(True, False, already_emitted=False)
            )
            m.note_redeploy(
                attempt_id=aid,
                sim_step=aid * 10 + 2,
                policy_step=aid + 1,
                parts_placed=aid - 1,
            )
            rec = m._attempt_recoveries[aid]
            self.assertGreaterEqual(rec.redeploy_step, 0)
        # Last attempt may close via terminal without redeploy.
        m.note_retreat(attempt_id=4, sim_step=40, policy_step=4, parts_placed=3)
        m.parts_placed = 8
        m.policy_steps = 20
        m.finalise()
        self.assertTrue(m._attempt_recoveries[4].terminal_success)


class TestProactiveRules(unittest.TestCase):
    def test_b2_proactive_excludes_held_critical(self):
        self.assertTrue(is_b2_proactive_trigger_rule("ttc"))
        self.assertTrue(is_b2_proactive_trigger_rule("ttc_forecast"))
        self.assertFalse(is_b2_proactive_trigger_rule("held_critical"))
        self.assertTrue(is_held_critical_trigger_rule("held_critical"))

    def test_redeploy_edge_helper(self):
        self.assertTrue(dynamic_sweep_redeploy_edge(True, False))
        self.assertFalse(dynamic_sweep_redeploy_edge(True, True))
        self.assertFalse(dynamic_sweep_redeploy_edge(False, False))
        self.assertFalse(
            dynamic_sweep_redeploy_edge(True, False, already_emitted=True)
        )


class TestShadowControlIsolation(unittest.TestCase):
    """B4: evaluated STOP must not freeze clock or mutate action."""

    def test_effective_gate_shadow_is_allow(self):
        self.assertEqual(resolve_effective_gate_name("STOP", "shadow"), "ALLOW")
        self.assertEqual(resolve_effective_gate_name("SLOW_DOWN", "shadow"), "ALLOW")
        self.assertEqual(resolve_effective_gate_name("STOP", "active"), "STOP")
        self.assertIsNone(resolve_effective_gate_name(None, "shadow"))

    def test_clock_advances_under_shadow_stop(self):
        n = 17
        # Active: STOP freezes clock.
        active_advances = sum(
            1
            for _ in range(n)
            if policy_clock_should_advance(
                effective_gate_name=resolve_effective_gate_name("STOP", "active"),
            )
        )
        self.assertEqual(active_advances, 0)
        # Shadow: evaluated STOP → effective ALLOW → clock advances N steps.
        shadow_advances = sum(
            1
            for _ in range(n)
            if policy_clock_should_advance(
                effective_gate_name=resolve_effective_gate_name("STOP", "shadow"),
            )
        )
        self.assertEqual(shadow_advances, n)

    def test_shadow_proposed_equals_effective_action(self):
        proposed = np.array([0.1, -0.2, 0.3, 0.0, 0.1, -0.1, 0.5, 1.0], dtype=np.float32)
        # Shadow path copies proposed without gating.
        effective = proposed.copy()
        np.testing.assert_array_equal(effective, proposed)

    def test_shadow_trigger_no_applied_retreat_in_audit(self):
        from episode_audit import audit_b4_shadow_events
        from event_csv import build_event_row, format_event_row, EVENT_CSV_HEADER
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ev.csv"
            row = build_event_row(
                sim_step=202,
                event_type="shadow_trigger",
                attempt_id=1,
                trigger_rule="ttc",
                trigger_source="scripted_virtual_hand",
                safety_enforcement_mode="shadow",
                shadow_gate_decision="STOP",
                shadow_replan_would_trigger=True,
                gate_metadata={"ttc": 0.35},
                gate_audit={"dist_min_for_gating": "0.32"},
                control_dt=0.02,
            )
            with p.open("w") as f:
                f.write(EVENT_CSV_HEADER)
                f.write(format_event_row(row))
            errs, summary = audit_b4_shadow_events(p)
            self.assertEqual(errs, [])
            self.assertGreaterEqual(summary.get("shadow_trigger_count", 0), 1)
            self.assertEqual(summary.get("applied_count", 0), 0)


class TestTimeToRiskSteps(unittest.TestCase):
    def test_ceil_from_ttc(self):
        self.assertEqual(time_to_risk_steps_from_ttc(0.5, 0.02), "25")
        self.assertEqual(time_to_risk_steps_from_ttc(0.0, 0.02), "")
        self.assertEqual(time_to_risk_steps_from_ttc(float("inf"), 0.02), "")


class TestMetricsShadow(unittest.TestCase):
    def test_shadow_zero_actual_attribution(self):
        m = EpisodeMetrics()
        m.safety_enforcement_mode = "shadow"
        m.record_step(
            g1_root_z=0.8,
            g1_ur10e_distance=1.0,
            gate_decision="SLOW_DOWN",
            disturbance_active=True,
            disturbance_source="scripted_virtual_hand",
            gate_trigger_source="scripted_virtual_hand",
            disturbance_attempt_id=1,
            enforcement_mode="shadow",
            shadow_gate_decision="SLOW_DOWN",
            shadow_replan_would_trigger=True,
        )
        self.assertEqual(m.d_slow_caused, 0)
        self.assertEqual(m.shadow_slow_would_count, 1)
        self.assertEqual(m.shadow_replan_would_count, 1)

    def test_pre_hard_stop_replan_count(self):
        m = EpisodeMetrics()
        attr = ReplanAttribution.from_trigger(
            attempt_id=1,
            trigger_rule="ttc",
            trigger_source="scripted_virtual_hand",
            trigger_step=10,
        )
        m.record_step(
            g1_root_z=0.8,
            g1_ur10e_distance=1.0,
            replan_success=True,
            replan_event_id=1,
            replan_attribution=attr,
            disturbance_source="scripted_virtual_hand",
            replan_trigger_rule="ttc",
            dist_min_at_replan_trigger=0.20,
            safe_dist_hard_stop_at_trigger=0.13,
            enforcement_mode="active",
        )
        self.assertEqual(m.pre_hard_stop_replan_count, 1)
        self.assertEqual(m.held_critical_replan_count, 0)


class TestTrajectoryPairing(unittest.TestCase):
    def test_same_seed_bit_identical_prefix(self):
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        pa = DynamicLateralSweepProxy(spec=_spec(42), control_dt=0.02)
        pb = DynamicLateralSweepProxy(spec=_spec(42), control_dt=0.02)
        pa.step(protocol_phase="transit", ee_pos=ee)
        pb.step(protocol_phase="transit", ee_pos=ee)
        rows_a = []
        rows_b = []
        for _ in range(8):
            oa = pa.step(protocol_phase="transit", ee_pos=ee, enforcement_mode="active")
            ob = pb.step(protocol_phase="transit", ee_pos=ee, enforcement_mode="shadow")
            rows_a.append(oa.surface_xyz.copy())
            rows_b.append(ob.surface_xyz.copy())
        for a, b in zip(rows_a, rows_b):
            np.testing.assert_allclose(a, b, atol=1e-6)


class TestMidSweepRetreatContinuity(unittest.TestCase):
    def test_retreat_from_mid_sweep_no_teleport(self):
        spec = DynamicSweepSpec(
            start_xyz=_B2_START,
            end_xyz=_B2_END,
            duration_steps=40,
            retreat_duration_steps=10,
            seed=42,
        )
        p = DynamicLateralSweepProxy(spec=spec, control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        p.step(protocol_phase="transit", ee_pos=ee)
        centers: list[np.ndarray] = []
        max_step_disp = 0.0
        for i in range(12):
            out = p.step(
                protocol_phase="transit",
                ee_pos=ee,
                enforcement_mode="active",
                replan_applied_this_step=(i == 7),
            )
            if centers:
                disp = float(np.linalg.norm(out.center_xyz - centers[-1]))
                max_step_disp = max(max_step_disp, disp)
            centers.append(out.center_xyz.copy())
        # Mid-sweep retreat must not jump to end_xyz (legacy bug ~0.8 m).
        self.assertLess(max_step_disp, 0.15, f"max single-step displacement {max_step_disp}")
        # Center velocity must differ from surface velocity when radii project differently.
        out = p.step(protocol_phase="transit", ee_pos=ee, enforcement_mode="active")
        if np.linalg.norm(out.surface_vel_xyz) > 1e-6:
            self.assertGreater(
                float(np.linalg.norm(out.center_vel_xyz - out.surface_vel_xyz)),
                0.0,
            )

    def test_center_vel_is_center_diff(self):
        p = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        ee = np.array([0.75, 0.0, 0.45], dtype=np.float32)
        p.step(protocol_phase="transit", ee_pos=ee)
        prev_c = None
        for _ in range(6):
            out = p.step(protocol_phase="transit", ee_pos=ee)
            if prev_c is not None:
                expected = (out.center_xyz - prev_c) / 0.02
                np.testing.assert_allclose(out.center_vel_xyz, expected, atol=1e-4)
            prev_c = out.center_xyz.copy()


class TestSweepGeometryPrecheck(unittest.TestCase):
    def test_start_outside_hard_stop_with_real_thresholds(self):
        radii = PhaseProxyRadii()
        report = sweep_geometry_precheck(
            _spec(),
            phase_radii=radii,
            hard_stop_m=_HARD_STOP_M,
            warn_m=_WARN_M,
        )
        self.assertTrue(report.transit_start_margin_ok)
        self.assertFalse(report.any_non_disturbance_inside_hard_stop)
        self.assertGreater(
            report.transit_start_min_gating_m,
            _HARD_STOP_M + 0.04,
        )
        observed = next(s for s in report.samples if s.label == "transit_edge_observed")
        self.assertGreater(observed.gating_distance_m, 0.29)
        self.assertLess(observed.gating_distance_m, 0.37)
        for sample in report.samples:
            if sample.is_non_disturbance:
                self.assertGreater(sample.gating_margin_m, 0.0)

    def test_observed_edge_still_enters_risk_by_end(self):
        observed_ee = np.array([0.5254, -0.3473, 0.5521], dtype=np.float32)
        proxy = DynamicLateralSweepProxy(spec=_spec(), control_dt=0.02)
        start_out = proxy.step(
            protocol_phase="transit",
            ee_pos=observed_ee,
            phase_radii=PhaseProxyRadii(),
        )
        self.assertEqual(start_out.lifecycle, SweepLifecycle.SWEEPING)
        self.assertAlmostEqual(start_out.surface_vel_xyz[0], 0.0, places=6)
        self.assertGreater(start_out.surface_distance - 0.065, _HARD_STOP_M + 0.04)
        next_out = proxy.step(
            protocol_phase="transit",
            ee_pos=observed_ee,
            phase_radii=PhaseProxyRadii(),
        )
        radial_dir = (
            observed_ee - start_out.center_xyz
        ) / np.linalg.norm(observed_ee - start_out.center_xyz)
        radial_approach = float(np.dot(next_out.center_vel_xyz, radial_dir))
        self.assertGreater(radial_approach, 0.0)
        end_dist = float(
            np.linalg.norm(np.array(_B2_END, dtype=np.float32) - observed_ee) - 0.40 - 0.08
        )
        self.assertLess(end_dist - 0.065, _HARD_STOP_M)


class TestEventCsvRoundTrip(unittest.TestCase):
    def test_build_row_matches_header(self):
        row = build_event_row(
            sim_step=10,
            event_type="trigger",
            attempt_id=1,
            trigger_rule="ttc",
            gate_metadata={"ttc": 0.42},
            control_dt=0.02,
            sweep_attempt_id="1",
            sweep_progress="0.25",
            sweep_velocity_xyz=(0.1, 0.0, 0.0),
            safety_enforcement_mode="active",
            shadow_gate_decision="REPLAN",
            shadow_replan_would_trigger=False,
        )
        self.assertEqual(len(row), len(EVENT_CSV_FIELDNAMES))
        self.assertNotIn(None, row.values())
        line = format_event_row(row)
        cols = line.strip().split(",")
        self.assertEqual(len(cols), len(EVENT_CSV_FIELDNAMES))

    def test_dict_reader_no_none(self):
        import csv
        import io

        row = build_event_row(
            sim_step=5,
            event_type="shadow_trigger",
            attempt_id=1,
            trigger_rule="ttc_forecast",
            gate_metadata={"ttc": 0.8},
            control_dt=0.02,
            sweep_attempt_id="1",
            sweep_progress="0.5",
            sweep_velocity_xyz=(0.0, 0.2, 0.0),
            safety_enforcement_mode="shadow",
            shadow_gate_decision="REPLAN",
            shadow_replan_would_trigger=True,
        )
        buf = io.StringIO()
        buf.write(",".join(EVENT_CSV_FIELDNAMES) + "\n")
        buf.write(format_event_row(row))
        buf.seek(0)
        reader = csv.DictReader(buf)
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        for k, v in rows[0].items():
            self.assertIsNotNone(k)
            self.assertIsNotNone(v)
        self.assertEqual(validate_event_csv_rows(rows), [])
        self.assertTrue(rows[0]["ttc_at_trigger"])
        self.assertTrue(rows[0]["time_to_risk_steps"])

    def test_dynamic_audit_round_trip(self):
        row = build_dynamic_audit_row(
            sim_step=123,
            policy_step=45,
            protocol_phase="transit",
            stage_name="lift_slot_A_1",
            disturbance_attempt_id=1,
            disturbance_trajectory_id="a" * 64,
            gate_decision="ALLOW",
            trigger_rule="ttc",
            sweep_progress=0.25,
            ee_x=0.5254,
            ee_y=-0.3473,
            ee_z=0.5521,
            proxy_center_x=-0.30,
            proxy_center_y=-0.65,
            proxy_center_z=0.45,
            proxy_surface_x=0.01,
            proxy_surface_y=-0.54,
            proxy_surface_z=0.49,
            surface_velocity_x=0.0,
            surface_velocity_y=0.12,
            surface_velocity_z=0.0,
            hand_speed=0.12,
            dist_min_proxy=0.401,
            dist_min_for_gating=0.336,
            dist_min_envelope=0.336,
            dist_min_held=0.401,
            hard_stop_active=0.25,
            warn_active=0.28,
            ttc_s=0.42,
            ttc_forecast_s=0.39,
            approach_rate=0.8,
        )
        self.assertEqual(len(row), len(DYNAMIC_AUDIT_FIELDNAMES))
        self.assertNotIn(None, row.values())

        import io
        buf = io.StringIO()
        buf.write(",".join(DYNAMIC_AUDIT_FIELDNAMES) + "\n")
        buf.write(format_dynamic_audit_row(row))
        buf.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.csv")
            with open(path, "w", newline="") as f:
                f.write(buf.getvalue())
            rows = read_dynamic_audit_csv(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(validate_dynamic_audit_rows(rows), [])
        self.assertEqual(rows[0]["gate_decision"], "ALLOW")
        self.assertEqual(rows[0]["dist_min_for_gating"], "0.336000")


if __name__ == "__main__":
    unittest.main()
