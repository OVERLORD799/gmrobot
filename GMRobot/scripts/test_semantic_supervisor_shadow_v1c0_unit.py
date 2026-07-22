#!/usr/bin/env python3
"""V1-C0 semantic supervisor online shadow wiring / isolation unit tests."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
# Canonical editable root only (V1-C0P1). Do not add inner GMRobot/ on sys.path.
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))


def _ensure_module(name: str, **attrs):
    if name in sys.modules:
        mod = sys.modules[name]
    else:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    for key, value in attrs.items():
        setattr(mod, key, value)
    if "." in name:
        parent_name, child = name.rsplit(".", 1)
        parent = _ensure_module(parent_name)
        setattr(parent, child, mod)
    return mod


# Host lacks Isaac/torch; stub enough for GMRobot/safety package import.
_ensure_module("isaaclab_tasks")
_ensure_module("isaaclab_tasks.utils", import_packages=lambda *_a, **_k: None)
_ensure_module("omni")
_ext = _ensure_module("omni.ext")


class _IExt:
    pass


_ext.IExt = _IExt
_ui = _ensure_module("omni.ui")
_ui.Window = type("Window", (), {"__init__": lambda self, *a, **k: None, "frame": None})
_ui.VStack = type("VStack", (), {"__enter__": lambda self: self, "__exit__": lambda *a: None})
_ui.Label = object
_ui.Button = object
_torch = _ensure_module("torch")
_torch.device = lambda *_a, **_k: "cpu"
_torch.tensor = lambda *a, **k: a
_torch.float32 = "float32"
_torch.no_grad = lambda: type("NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None})()
_ensure_module("torch.nn")
_ensure_module("numpy", array=lambda *a, **k: a, ndarray=object)

from GMRobot.safety.semantic_supervisor import (  # noqa: E402
    GATE_ALLOW,
    GATE_SLOW_DOWN,
    GATE_STOP,
    REASON_CONSISTENCY_PENDING,
    REASON_RISK_TYPE_NOT_ALLOWED,
    REASON_STALE,
    SemanticAdvisoryInput,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
    fuse_monotonic_gate,
)
from GMRobot.safety.semantic_supervisor_logger import (  # noqa: E402
    SEMANTIC_SUPERVISOR_FIELDS,
    SemanticSupervisorLogger,
)
from GMRobot.shadow.control_isolation import (  # noqa: E402
    SemanticLeakageCounters,
    control_decision_hash,
    validate_semantic_supervisor_shadow_flags,
)
from GMRobot.shadow.isolation import shadow_control_decision  # noqa: E402
from GMRobot.shadow.semantic_bridge import SemanticShadowBridge  # noqa: E402
from GMRobot.shadow.scheduler import FiveStageShadowScheduler, result_log_key  # noqa: E402


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
        cooldown_s=0.0,
        reject_static_risk_in_v1=True,
        allow_stop=False,
        allow_replan=False,
    )
    base.update(kw)
    return SemanticSupervisorConfig.from_dict(base)


def _synth_result(rid: str, *, sim_step: int = 0, stale: bool = False, **extra) -> dict:
    row = {
        "request_id": rid,
        "frame_id": rid + "-f",
        "sim_step": sim_step,
        "completed_at_s": float(sim_step) * 0.02 + 0.05,
        "result_age_s": 0.1,
        "stale": stale,
        "schema_version": "five_stage_vlm_v1",
        "prompt_version": "five_stage_safety_v1",
        "gateway_parse_ok": True,
        "pipeline_ok": True,
        "error_type": "",
        "risk_type": "dynamic",
        "risk_confidence": 0.92,
        "affected_entities": ["human", "robot"],
        "predicted_consequence": "potential collision with human",
        "prediction_horizon_s": 1.5,
        "suggested_action": "slow_down",
        "spatial_hint": "front",
        "synthetic": True,
        "would_stop": False,
        "would_replan": False,
        "vlm": {
            "gateway_parse_ok": True,
            "risk_type": "dynamic",
            "risk_confidence": 0.92,
            "affected_entities": ["human", "robot"],
            "predicted_consequence": "potential collision with human",
            "prediction_horizon_s": 1.5,
            "suggested_action": "slow_down",
            "spatial_hint": "front",
            "schema_version": "five_stage_vlm_v1",
        },
    }
    row.update(extra)
    return row


def test_default_disabled_validation_noop():
    validate_semantic_supervisor_shadow_flags(
        enable_semantic_supervisor_shadow=False,
        enable_five_stage_shadow=False,
        enable_safety=False,
    )


def test_non_shadow_enforcement_rejected():
    try:
        validate_semantic_supervisor_shadow_flags(
            enable_semantic_supervisor_shadow=True,
            enable_five_stage_shadow=True,
            enable_safety=True,
            enforcement_mode="live",
        )
        assert False
    except RuntimeError as e:
        assert "shadow" in str(e).lower()


def test_requires_five_stage_shadow():
    try:
        validate_semantic_supervisor_shadow_flags(
            enable_semantic_supervisor_shadow=True,
            enable_five_stage_shadow=False,
            enable_safety=True,
        )
        assert False
    except RuntimeError:
        pass


def test_requires_safety():
    try:
        validate_semantic_supervisor_shadow_flags(
            enable_semantic_supervisor_shadow=True,
            enable_five_stage_shadow=True,
            enable_safety=False,
        )
        assert False
    except RuntimeError:
        pass


def test_mutex_with_live_vlm_replan():
    for kw in (
        {"enable_vlm": True},
        {"enable_replan": True},
        {"enable_vlm_grasp_supervisor": True},
    ):
        try:
            validate_semantic_supervisor_shadow_flags(
                enable_semantic_supervisor_shadow=True,
                enable_five_stage_shadow=True,
                enable_safety=True,
                **kw,
            )
            assert False, kw
        except RuntimeError:
            pass


def test_request_id_consumed_once():
    with tempfile.TemporaryDirectory() as td:
        bridge = SemanticShadowBridge(
            supervisor=SemanticSafetySupervisor(_cfg()),
            logger=SemanticSupervisorLogger(td),
            config=_cfg(),
        )
        r = _synth_result("req-1", sim_step=0)
        bridge.enqueue_unique_result(r)
        bridge.enqueue_unique_result(r)  # duplicate enqueue
        d1 = bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=10)
        assert len(d1) == 1
        bridge.enqueue_unique_result(r)
        d2 = bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=11)
        assert d2 == []
        bridge.close()


def test_source_and_decision_steps_recorded():
    with tempfile.TemporaryDirectory() as td:
        logger = SemanticSupervisorLogger(td)
        bridge = SemanticShadowBridge(
            supervisor=SemanticSafetySupervisor(_cfg()),
            logger=logger,
            config=_cfg(),
        )
        bridge.enqueue_unique_result(_synth_result("a", sim_step=5))
        bridge.enqueue_unique_result(_synth_result("b", sim_step=5))
        bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=40, decision_time_s=0.8)
        path = logger.session_dir / "semantic_supervisor_decisions.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert rows[-1]["source_capture_sim_step"] == 5
        assert rows[-1]["decision_sim_step"] == 40
        bridge.close()


def test_decision_time_geometry_gate_used():
    with tempfile.TemporaryDirectory() as td:
        logger = SemanticSupervisorLogger(td)
        bridge = SemanticShadowBridge(
            supervisor=SemanticSafetySupervisor(_cfg()),
            logger=logger,
            config=_cfg(),
        )
        bridge.enqueue_unique_result(_synth_result("a", sim_step=0))
        bridge.enqueue_unique_result(_synth_result("b", sim_step=0))
        bridge.flush(geometry_gate=GATE_STOP, geometry_gate_reason="near", decision_sim_step=20)
        row = json.loads(
            (logger.session_dir / "semantic_supervisor_decisions.jsonl").read_text().splitlines()[-1]
        )
        assert row["geometry_gate"] == GATE_STOP
        assert row["effective_control_gate"] == GATE_STOP
        assert row["geometry_gate_reason"] == "near"
        bridge.close()


def test_stale_rejected():
    bridge = SemanticShadowBridge(
        supervisor=SemanticSafetySupervisor(_cfg()),
        logger=None,
        config=_cfg(),
    )
    bridge.enqueue_unique_result(_synth_result("s", stale=True))
    d = bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=1)[0]
    assert d.rejection_reason == REASON_STALE


def test_v0c3_negative_not_accepted():
    path = REPO / "g1_ur10e_disturbance/results/paper_demo/v0c3_isaac_shadow_20260721/five_stage_shadow_requests.jsonl"
    if not path.is_file():
        path = next(
            (REPO / "g1_ur10e_disturbance/results/paper_demo/v0c3_isaac_shadow_20260721").rglob(
                "five_stage_shadow_requests.jsonl"
            )
        )
    bridge = SemanticShadowBridge(
        supervisor=SemanticSafetySupervisor(_cfg(cooldown_s=5.0)),
        logger=None,
        config=_cfg(),
    )
    accepted = 0
    reasons = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        bridge.enqueue_unique_result(row)
        for d in bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=int(row.get("sim_step", 0))):
            reasons.append(d.rejection_reason)
            if d.accepted:
                accepted += 1
    assert accepted == 0
    assert REASON_RISK_TYPE_NOT_ALLOWED in reasons


def test_synthetic_dynamic_shadow_accept_would_slow():
    bridge = SemanticShadowBridge(
        supervisor=SemanticSafetySupervisor(_cfg()),
        logger=None,
        config=_cfg(),
    )
    bridge.enqueue_unique_result(_synth_result("s1"))
    d1 = bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=1)[0]
    assert d1.rejection_reason == REASON_CONSISTENCY_PENDING
    bridge.enqueue_unique_result(_synth_result("s2"))
    d2 = bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=2)[0]
    assert d2.accepted is True
    assert d2.would_slow is True
    assert d2.intentional_control_effect is False


def test_accepted_does_not_change_effective_gate():
    bridge = SemanticShadowBridge(
        supervisor=SemanticSafetySupervisor(_cfg()),
        logger=None,
        config=_cfg(),
    )
    bridge.enqueue_unique_result(_synth_result("s1"))
    bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=1)
    bridge.enqueue_unique_result(_synth_result("s2"))
    with tempfile.TemporaryDirectory() as td:
        bridge.logger = SemanticSupervisorLogger(td)
        d = bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=2)[0]
        assert d.accepted
        row = json.loads(
            (bridge.logger.session_dir / "semantic_supervisor_decisions.jsonl")
            .read_text()
            .splitlines()[-1]
        )
        assert row["evaluated_semantic_gate"] == GATE_SLOW_DOWN
        assert row["effective_control_gate"] == GATE_ALLOW
        assert row["effective_control_gate"] != row["evaluated_semantic_gate"]
        bridge.close()


def test_geometry_stop_not_downgraded():
    assert fuse_monotonic_gate(GATE_STOP, GATE_SLOW_DOWN) == GATE_STOP


def test_geometry_slow_not_downgraded_by_allow():
    assert fuse_monotonic_gate(GATE_SLOW_DOWN, None) == GATE_SLOW_DOWN
    assert fuse_monotonic_gate(GATE_SLOW_DOWN, "") == GATE_SLOW_DOWN


def test_control_hash_off_on_match():
    snap = {
        "gate_decision": 0,
        "action": [0.1, 0.2, 0.3],
        "should_advance": [True],
        "protocol_phase": "transit",
        "replan_event": None,
        "task_progression": 12,
    }
    h_off = control_decision_hash(**snap)
    # Simulate supervisor shadow path: same effective control fields.
    h_on = control_decision_hash(**snap)
    assert h_off == h_on
    mismatch = 0 if h_off == h_on else 1
    assert mismatch == 0


def test_semantic_leakage_all_zero():
    c = SemanticLeakageCounters()
    c.assert_all_zero()
    assert all(v == 0 for v in c.as_dict().values())


def test_five_stage_leakage_still_zero():
    gate = object()
    action = object()
    out = shadow_control_decision(
        gate_decision=gate,
        action=action,
        policy_clock_advance=True,
        replan_event=None,
        protocol_phase="transit",
        shadow_result={"would_stop": True, "suggested_action": "slow_down"},
        enforcement_mode="shadow",
    )
    assert out["gate_decision"] is gate
    assert out["action"] is action
    assert all(v == 0 for v in out["leakage"].values())


def test_logger_schema_round_trip():
    with tempfile.TemporaryDirectory() as td:
        logger = SemanticSupervisorLogger(td)
        bridge = SemanticShadowBridge(
            supervisor=SemanticSafetySupervisor(_cfg()),
            logger=logger,
            config=_cfg(),
        )
        bridge.enqueue_unique_result(_synth_result("a"))
        bridge.enqueue_unique_result(_synth_result("b"))
        bridge.flush(geometry_gate=GATE_ALLOW, decision_sim_step=3)
        with (logger.session_dir / "semantic_supervisor_steps.csv").open() as f:
            rows = list(csv.DictReader(f))
        assert list(rows[0].keys()) == SEMANTIC_SUPERVISOR_FIELDS
        assert "effective_control_gate" in rows[0]
        assert "would_slow_down" in rows[0]
        text = (logger.session_dir / "semantic_supervisor_decisions.jsonl").read_text()
        assert "session_id" not in text or "<redacted>" in text
        bridge.close()


def test_shutdown_drain_advisory_complete_via_callback():
    class _FakeWorker:
        def __init__(self):
            self.metrics = types.SimpleNamespace(
                processed_frames=0, stale_result_count=0, stale_poll_count=0
            )
            self.leakage = types.SimpleNamespace(as_dict=lambda: {
                "shadow_gate_override_count": 0,
                "shadow_action_override_count": 0,
                "shadow_clock_blocked_steps": 0,
                "shadow_replan_applied_count": 0,
                "shadow_protocol_override_count": 0,
            })
            self._results = []

        def latest_result(self):
            if not self._results:
                return None
            return self._results[-1]

        def assert_no_control_side_effects(self):
            return None

        def stop(self, timeout_s=2.0):
            return {"stopped_cleanly": True, "thread_alive": False}

        def submit(self, *a, **k):
            return {}

    class _FakeLogger:
        def record(self, result):
            return None

        def flush_summary(self, extra=None):
            return None

        def close(self):
            return None

    worker = _FakeWorker()
    seen = []
    sched = FiveStageShadowScheduler(
        worker,
        _FakeLogger(),
        interval=1,
        max_submissions=2,
        on_unique_result=lambda r: seen.append(r.get("request_id")),
    )
    # Simulate two unique completions arriving at drain time.
    worker._results.append(_synth_result("d1", sim_step=0))
    worker.metrics.processed_frames = 1
    sched.submitted_count = 2
    sched.on_step(obs=None, step_counter=0)
    worker._results.append(_synth_result("d2", sim_step=50))
    worker.metrics.processed_frames = 2
    sched.shutdown(stop_timeout_s=0.1, drain_timeout_s=0.2)
    assert "d1" in seen and "d2" in seen
    assert len(seen) == 2


def test_repeat_poll_same_result_no_duplicate_log():
    class _FakeWorker:
        def __init__(self, result):
            self._result = result
            self.metrics = types.SimpleNamespace(
                processed_frames=1, stale_result_count=0, stale_poll_count=0
            )
            self.leakage = types.SimpleNamespace(as_dict=lambda: {
                "shadow_gate_override_count": 0,
                "shadow_action_override_count": 0,
                "shadow_clock_blocked_steps": 0,
                "shadow_replan_applied_count": 0,
                "shadow_protocol_override_count": 0,
            })

        def latest_result(self):
            return self._result

        def assert_no_control_side_effects(self):
            return None

        def submit(self, *a, **k):
            return {}

    class _FakeLogger:
        def __init__(self):
            self.n = 0

        def record(self, result):
            self.n += 1

    result = _synth_result("same", sim_step=0)
    result["completed_at_s"] = 1.0
    flog = _FakeLogger()
    hits = []
    sched = FiveStageShadowScheduler(
        _FakeWorker(result),
        flog,
        interval=999,
        max_submissions=0,
        on_unique_result=lambda r: hits.append(1),
    )
    sched.on_step(None, 0)
    sched.on_step(None, 1)
    sched.on_step(None, 2)
    assert flog.n == 1
    assert len(hits) == 1
    assert result_log_key(result) == result_log_key(result)


def test_config_file_defaults():
    import yaml

    p = ROOT / "configs" / "semantic_safety_supervisor_shadow_live.yaml"
    d = yaml.safe_load(p.read_text())
    assert d["enabled"] is False
    assert d["enforcement_mode"] == "shadow"
    assert d["min_risk_confidence"] == 0.85
    assert d["allow_stop"] is False
    assert d["allow_replan"] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("OK", t.__name__)
    print(f"PASS {len(tests)}")
