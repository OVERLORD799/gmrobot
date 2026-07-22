#!/usr/bin/env python3
"""State / cooldown / episode isolation tests for SemanticSafetySupervisor."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import types

ROOT = Path(__file__).resolve().parents[1]
_SAFETY = ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))
_pkg = types.ModuleType("safety")
_pkg.__path__ = [str(_SAFETY)]
sys.modules["safety"] = _pkg

from safety.semantic_supervisor import (  # noqa: E402
    GATE_ALLOW,
    GATE_SLOW_DOWN,
    REASON_CONSISTENCY_PENDING,
    REASON_COOLDOWN,
    SemanticAdvisoryInput,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
)


def _cfg(**kw) -> SemanticSupervisorConfig:
    base = dict(
        enabled=True,
        enforcement_mode="shadow",
        allowed_actions=("slow_down",),
        allowed_risk_types=("dynamic", "functional"),
        min_risk_confidence=0.85,
        max_result_age_s=2.0,
        min_consistent_results=2,
        consistency_window_s=10.0,
        cooldown_s=5.0,
        limited_active_speed_scale=0.5,
        reject_static_risk_in_v1=True,
    )
    base.update(kw)
    return SemanticSupervisorConfig.from_dict(base)


def _good(**kw) -> SemanticAdvisoryInput:
    data = dict(
        episode_id="0",
        sim_step=0,
        current_time_s=1.0,
        request_id="req-a",
        frame_id="frm-a",
        result_age_s=0.1,
        schema_version="five_stage_vlm_v1",
        gateway_parse_ok=True,
        risk_type="dynamic",
        risk_confidence=0.92,
        affected_entities=["human"],
        predicted_consequence="potential collision",
        prediction_horizon_s=1.5,
        suggested_action="slow_down",
        spatial_hint="left",
        current_geometry_gate=GATE_ALLOW,
        synthetic=True,
    )
    data.update(kw)
    return SemanticAdvisoryInput(**data)


def _accept_pair(s: SemanticSafetySupervisor, *, episode_id: str, t0: float, prefix: str):
    d1 = s.evaluate(
        _good(
            episode_id=episode_id,
            request_id=f"{prefix}-1",
            frame_id=f"{prefix}-f1",
            current_time_s=t0,
        )
    )
    assert d1.rejection_reason == REASON_CONSISTENCY_PENDING
    d2 = s.evaluate(
        _good(
            episode_id=episode_id,
            request_id=f"{prefix}-2",
            frame_id=f"{prefix}-f2",
            current_time_s=t0 + 0.5,
            sim_step=1,
        )
    )
    assert d2.accepted is True
    return d2


def test_cooldown_blocks_repeat_advisory():
    s = SemanticSafetySupervisor(_cfg(cooldown_s=5.0))
    _accept_pair(s, episode_id="0", t0=1.0, prefix="a")
    d = s.evaluate(
        _good(request_id="a-3", frame_id="a-f3", current_time_s=2.0, sim_step=2)
    )
    # third consistent result inside cooldown
    assert d.accepted is False
    assert d.rejection_reason == REASON_COOLDOWN
    assert d.cooldown_active is True
    assert d.intentional_control_effect is False


def test_episode_reset_clears_state():
    s = SemanticSafetySupervisor(_cfg())
    _accept_pair(s, episode_id="0", t0=1.0, prefix="a")
    s.reset("0")
    d = s.evaluate(_good(request_id="b-1", frame_id="b-f1", current_time_s=10.0))
    assert d.rejection_reason == REASON_CONSISTENCY_PENDING
    assert d.consistency_count == 1


def test_multi_episode_isolation():
    s = SemanticSafetySupervisor(_cfg())
    s.evaluate(_good(episode_id="epA", request_id="a1", frame_id="af1", current_time_s=1.0))
    d_b = s.evaluate(
        _good(episode_id="epB", request_id="b1", frame_id="bf1", current_time_s=1.0)
    )
    assert d_b.rejection_reason == REASON_CONSISTENCY_PENDING
    assert d_b.consistency_count == 1
    # epA still needs one more; epB independent
    d_a2 = s.evaluate(
        _good(episode_id="epA", request_id="a2", frame_id="af2", current_time_s=1.5)
    )
    assert d_a2.accepted is True
    d_b2 = s.evaluate(
        _good(episode_id="epB", request_id="b2", frame_id="bf2", current_time_s=1.5)
    )
    assert d_b2.accepted is True


def test_thread_safe_under_lock():
    s = SemanticSafetySupervisor(_cfg(min_consistent_results=1, cooldown_s=0.0))
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            d = s.evaluate(
                _good(
                    episode_id="0",
                    request_id=f"t-{i}",
                    frame_id=f"f-{i}",
                    current_time_s=float(i),
                )
            )
            assert d.would_stop is False
            assert d.would_replan is False
            assert d.intentional_control_effect is False
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_requested_gate_only_slow_or_empty():
    s = SemanticSafetySupervisor(_cfg())
    d = _accept_pair(s, episode_id="0", t0=1.0, prefix="c")
    assert d.requested_gate in ("", GATE_SLOW_DOWN)
    assert d.requested_gate == GATE_SLOW_DOWN


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("PASS")
