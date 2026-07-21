"""Unit tests for episode_audit helpers."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from episode_audit import (
    audit_b2_recovery_chain,
    audit_b4_shadow_episode,
    audit_b4_shadow_events,
    audit_empty_event_chain,
    audit_events_for_episode,
    audit_trigger_apply_latency,
)
from event_csv import EVENT_CSV_FIELDNAMES, build_event_row, format_event_row


def _write_events(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        f.write(",".join(EVENT_CSV_FIELDNAMES) + "\n")
        for row in rows:
            f.write(format_event_row(row))


def _proactive_trigger_row(
    *,
    sim_step: int,
    event_type: str = "trigger",
    event_id: str = "1",
    attempt_id: int = 1,
) -> dict:
    return build_event_row(
        sim_step=sim_step,
        event_type=event_type,
        attempt_id=attempt_id,
        event_id=event_id,
        trigger_rule="ttc",
        gate_metadata={"ttc": 0.5},
        control_dt=0.02,
        sweep_attempt_id="1",
        sweep_progress="0.3",
        sweep_velocity_xyz=(0.0, 0.1, 0.0),
        safety_enforcement_mode=(
            "shadow" if event_type == "shadow_trigger" else "active"
        ),
        shadow_gate_decision="REPLAN" if event_type == "shadow_trigger" else "",
        shadow_replan_would_trigger=event_type == "shadow_trigger",
    )


class TestEpisodeAudit(unittest.TestCase):
    def test_trigger_apply_latency_same_step(self):
        rows = [
            _proactive_trigger_row(sim_step=10, event_id="1"),
            build_event_row(
                sim_step=10, event_type="applied", attempt_id=1,
                event_id="1", trigger_rule="ttc", applied_step="10",
            ),
            build_event_row(
                sim_step=11, event_type="retreat", attempt_id=1,
                event_id="1", trigger_rule="replan", applied_step="11",
            ),
        ]
        errs, lat = audit_trigger_apply_latency(rows)
        self.assertEqual(errs, [])
        self.assertEqual(lat, 0)

    def test_runtime_shaped_active_csv_audit_pass(self):
        """Simulate run_phase3: trigger(N) → applied(N) → retreat(N+1)."""
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "active_events.csv"
            rows = [
                _proactive_trigger_row(sim_step=100, event_id="1"),
                build_event_row(
                    sim_step=100, event_type="applied", attempt_id=1,
                    event_id="1", trigger_rule="ttc", applied_step="100",
                ),
                build_event_row(
                    sim_step=101, event_type="retreat", attempt_id=1,
                    event_id="1", trigger_rule="replan", applied_step="101",
                ),
            ]
            _write_events(ep, rows)
            errs, summary = audit_b2_recovery_chain(ep)
            self.assertEqual(errs, [], errs)
            self.assertEqual(summary["max_trigger_apply_latency"], 0)
            ids = [r.get("event_id") for r in rows]
            self.assertEqual(ids, ["1", "1", "1"])

    def test_runtime_shaped_active_missing_trigger_id_fails(self):
        """Reproduce pre-P0-5 bug: trigger without event_id."""
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "bad_events.csv"
            rows = [
                build_event_row(
                    sim_step=100, event_type="trigger", attempt_id=1,
                    trigger_rule="ttc",
                    gate_metadata={"ttc": 0.5}, control_dt=0.02,
                    sweep_attempt_id="1", sweep_progress="0.3",
                    sweep_velocity_xyz=(0.0, 0.1, 0.0),
                ),
                build_event_row(
                    sim_step=100, event_type="applied", attempt_id=1,
                    event_id="1", trigger_rule="ttc", applied_step="100",
                ),
                build_event_row(
                    sim_step=101, event_type="retreat", attempt_id=1,
                    trigger_rule="replan", applied_step="101",
                ),
            ]
            _write_events(ep, rows)
            errs, _ = audit_b2_recovery_chain(ep)
            self.assertTrue(any("no matching trigger" in e for e in errs))
            self.assertTrue(any("missing paired retreat" in e for e in errs))

    def test_b2_chain_pass_with_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "ep_events.csv"
            rows = [
                _proactive_trigger_row(sim_step=10, event_id="1"),
                build_event_row(
                    sim_step=10, event_type="applied", attempt_id=1,
                    event_id="1", trigger_rule="ttc", applied_step="10",
                ),
                build_event_row(
                    sim_step=11, event_type="retreat", attempt_id=1,
                    event_id="1", trigger_rule="replan", applied_step="11",
                ),
                build_event_row(
                    sim_step=50, event_type="redeploy", attempt_id=1,
                    trigger_rule="protocol",
                ),
            ]
            _write_events(ep, rows)
            ap = Path(tmp) / "ep_attempts.csv"
            with ap.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "attempt_id", "retreat_step", "redeploy_step",
                    "policy_delta_after_retreat", "parts_delta_after_retreat",
                    "recovered", "terminal_success", "close_reason",
                ])
                w.writeheader()
                w.writerow({
                    "attempt_id": "1", "retreat_step": "11", "redeploy_step": "50",
                    "policy_delta_after_retreat": "5", "parts_delta_after_retreat": "0",
                    "recovered": "True", "terminal_success": "False", "close_reason": "redeploy",
                })
            errs, summary = audit_b2_recovery_chain(ep, ap)
            self.assertEqual(errs, [], errs)
            self.assertEqual(summary["proactive_trigger_count"], 1)

    def test_runtime_shaped_shadow_csv_audit_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "shadow_events.csv"
            rows = [
                _proactive_trigger_row(
                    sim_step=50, event_type="shadow_trigger", event_id="",
                ),
            ]
            _write_events(ep, rows)
            errs, summary = audit_b4_shadow_events(ep)
            self.assertEqual(errs, [], errs)
            self.assertEqual(summary["shadow_trigger_count"], 1)
            self.assertEqual(summary["applied_count"], 0)

    def test_shadow_applied_or_retreat_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "shadow_bad.csv"
            rows = [
                _proactive_trigger_row(sim_step=50, event_type="shadow_trigger"),
                build_event_row(
                    sim_step=50, event_type="applied", attempt_id=1,
                    event_id="1", trigger_rule="ttc",
                ),
            ]
            _write_events(ep, rows)
            errs, _ = audit_b4_shadow_events(ep)
            self.assertTrue(any("must not emit applied" in e for e in errs))

            ep2 = Path(tmp) / "shadow_bad2.csv"
            rows2 = [
                _proactive_trigger_row(sim_step=50, event_type="shadow_trigger"),
                build_event_row(
                    sim_step=51, event_type="retreat", attempt_id=1,
                    event_id="1", trigger_rule="replan",
                ),
            ]
            _write_events(ep2, rows2)
            errs2, _ = audit_b4_shadow_events(ep2)
            self.assertTrue(any("must not emit retreat" in e for e in errs2))

    def test_audit_dispatch_by_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            shadow_path = Path(tmp) / "sh.csv"
            _write_events(shadow_path, [
                _proactive_trigger_row(sim_step=1, event_type="shadow_trigger"),
            ])
            errs_sh, _ = audit_events_for_episode(
                shadow_path, enforcement_mode="shadow",
            )
            self.assertEqual(errs_sh, [])

            active_path = Path(tmp) / "ac.csv"
            _write_events(active_path, [
                _proactive_trigger_row(sim_step=1, event_id="1"),
                build_event_row(
                    sim_step=1, event_type="applied", attempt_id=1,
                    event_id="1", trigger_rule="ttc", applied_step="1",
                ),
                build_event_row(
                    sim_step=2, event_type="retreat", attempt_id=1,
                    event_id="1", trigger_rule="replan",
                ),
            ])
            errs_ac, summ = audit_events_for_episode(
                active_path, enforcement_mode="active",
            )
            self.assertEqual(errs_ac, [])
            self.assertEqual(summ["max_trigger_apply_latency"], 0)

    def test_b4_shadow_episode_metrics_pass(self):
        errs = audit_b4_shadow_episode({
            "safety_enforcement_mode": "shadow",
            "success": True,
            "d_stop_caused": 0,
            "d_slow_caused": 0,
            "d_replan_caused": 0,
            "shadow_replan_would_count": 1,
            "shadow_slow_would_count": 0,
            "shadow_clock_blocked_steps": 0,
            "shadow_action_modified_steps": 0,
            "shadow_replan_applied_count": 0,
            "shadow_retreat_count": 0,
            "disturbance_trajectory_id": "a" * 64,
            "retreat_attempt_count": 0,
        })
        self.assertEqual(errs, [])

    def test_b4_shadow_fails_incomplete_task(self):
        errs = audit_b4_shadow_episode({
            "safety_enforcement_mode": "shadow",
            "success": False,
            "d_stop_caused": 0,
            "d_slow_caused": 0,
            "d_replan_caused": 0,
            "shadow_replan_would_count": 1,
            "shadow_clock_blocked_steps": 0,
            "shadow_action_modified_steps": 0,
            "shadow_replan_applied_count": 0,
            "shadow_retreat_count": 0,
            "disturbance_trajectory_id": "a" * 64,
            "retreat_attempt_count": 0,
        })
        self.assertTrue(any("task_completed" in e for e in errs))

    def test_b4_shadow_fails_retreat(self):
        errs = audit_b4_shadow_episode({
            "safety_enforcement_mode": "shadow",
            "success": True,
            "d_stop_caused": 0,
            "d_slow_caused": 0,
            "d_replan_caused": 0,
            "shadow_replan_would_count": 1,
            "shadow_clock_blocked_steps": 0,
            "shadow_action_modified_steps": 0,
            "shadow_replan_applied_count": 0,
            "shadow_retreat_count": 0,
            "disturbance_trajectory_id": "a" * 64,
            "retreat_attempt_count": 1,
        })
        self.assertTrue(any("retreat" in e for e in errs))

    def test_apply_failed_does_not_require_retreat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "failed.csv"
            rows = [
                _proactive_trigger_row(sim_step=20, event_id="2"),
                build_event_row(
                    sim_step=20, event_type="apply_failed", attempt_id=1,
                    event_id="2", trigger_rule="ttc", applied_step="20",
                ),
            ]
            _write_events(ep, rows)
            errs, summary = audit_b2_recovery_chain(ep)
            self.assertFalse(any("missing paired retreat" in e for e in errs))
            self.assertEqual(summary["max_trigger_apply_latency"], -1)

    def test_active_header_only_events_fails_empty_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "header_only.csv"
            with ep.open("w", newline="") as f:
                f.write(",".join(EVENT_CSV_FIELDNAMES) + "\n")
            errs, _ = audit_b2_recovery_chain(ep)
            self.assertIn("no proactive trigger/event chain", errs)

    def test_shadow_header_only_events_fails_empty_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "shadow_header_only.csv"
            with ep.open("w", newline="") as f:
                f.write(",".join(EVENT_CSV_FIELDNAMES) + "\n")
            errs, _ = audit_b4_shadow_events(ep)
            self.assertIn("no shadow_trigger rows", errs)

    def test_audit_empty_event_chain_helper(self):
        self.assertEqual(
            audit_empty_event_chain([], enforcement_mode="active"),
            ["no proactive trigger/event chain"],
        )
        self.assertEqual(
            audit_empty_event_chain([], enforcement_mode="shadow"),
            ["no shadow_trigger rows"],
        )


if __name__ == "__main__":
    unittest.main()
