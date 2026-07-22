#!/usr/bin/env python3
"""V1-D2A temporal fusion offline unit tests (0 POST / no network / no Isaac)."""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_PKG = ROOT / "source" / "GMRobot" / "GMRobot"
# Canonical install root only for GMRobot.* (worker temporal path).
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))
# Leaf-package path retained for offline unit imports that still use
# top-level safety/vlm/shadow stubs (documented script_compat; runtime uses GMRobot.*).
sys.path.insert(0, str(_PKG))


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


def _install_host_stubs() -> None:
    """Torch stub so GMRobot.safety.* leaf imports do not require Isaac/torch."""
    torch = _ensure_module("torch")
    torch.device = lambda *_a, **_k: "cpu"
    torch.tensor = lambda *a, **k: a
    torch.float32 = "float32"
    torch.no_grad = lambda: type(
        "NG", (), {"__enter__": lambda s: None, "__exit__": lambda *a: None}
    )()
    _ensure_module("torch.nn")
    _ensure_module("numpy", array=lambda *a, **k: a, ndarray=object)


_install_host_stubs()

# Avoid safety/__init__.py (torch) for legacy top-level test imports.
_safety = types.ModuleType("safety")
_safety.__path__ = [str(_PKG / "safety")]
sys.modules["safety"] = _safety

from GMRobot.safety.semantic_key_v2 import build_semantic_key_v2  # noqa: E402
from GMRobot.safety.semantic_supervisor import (  # noqa: E402
    GATE_ALLOW,
    REASON_CONSISTENCY_PENDING,
    REASON_RISK_TYPE_NOT_ALLOWED,
    SemanticAdvisoryInput,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
)
from GMRobot.safety.semantic_temporal_fusion import (  # noqa: E402
    MIN_CONFIDENCE,
    fuse_semantic_evidence,
)
from GMRobot.shadow.control_isolation import (  # noqa: E402
    SemanticLeakageCounters,
    control_decision_hash,
)
from GMRobot.shadow.five_stage_worker import FiveStageShadowWorker, ShadowLeakageCounters  # noqa: E402
from GMRobot.shadow.logger import FiveStageShadowLogger, SHADOW_STEP_FIELDS  # noqa: E402
from GMRobot.vlm.prompt_v2 import build_temporal_prompt_v2  # noqa: E402
from GMRobot.vlm.task_context import TaskSemanticContext  # noqa: E402
from GMRobot.vlm.temporal_evidence import (  # noqa: E402
    TemporalEvidenceConfig,
    TemporalTrackEvidence,
    age_evidence,
    build_temporal_evidence_from_track_result,
    canonicalize_entity,
    validate_temporal_evidence,
)
from GMRobot.vlm.versions import (  # noqa: E402
    FUSION_VERSION_V1,
    PROMPT_VERSION_V1,
    PROMPT_VERSION_V2_TEMPORAL,
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
)

FIX = ROOT / "scripts" / "fixtures" / "v1d2a"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _track_ev(name: str, *, age_s: float = 0.1) -> TemporalTrackEvidence:
    raw = _load(name)
    ev = build_temporal_evidence_from_track_result(
        raw,
        source_request_id="prev_req",
        source_frame_id="prev_frm",
        now_age_s=0.0,
    )
    return age_evidence(ev, age_s=age_s)


def _cfg_sup(**kw) -> SemanticSupervisorConfig:
    base = dict(
        enabled=True,
        enforcement_mode="shadow",
        allowed_actions=("slow_down",),
        allowed_risk_types=("dynamic", "functional"),
        min_risk_confidence=0.85,
        max_result_age_s=2.0,
        min_prediction_horizon_s=0.0,
        max_prediction_horizon_s=3.0,
        min_consistent_results=2,
        consistency_window_s=10.0,
        cooldown_s=5.0,
        reject_static_risk_in_v1=True,
        semantic_key_version="v2",
    )
    base.update(kw)
    return SemanticSupervisorConfig.from_dict(base)


class TestVersionsAndCompat(unittest.TestCase):
    def test_01_v1_versions_unchanged(self):
        self.assertEqual(PROMPT_VERSION_V1, "five_stage_safety_v1")
        self.assertEqual(SCHEMA_VERSION_V1, "five_stage_vlm_v1")

    def test_02_v2_explicit_versions(self):
        self.assertEqual(PROMPT_VERSION_V2_TEMPORAL, "five_stage_safety_v2_temporal")
        self.assertEqual(SCHEMA_VERSION_V2, "five_stage_vlm_v2")
        self.assertEqual(FUSION_VERSION_V1, "five_stage_temporal_fusion_v1")

    def test_03_worker_default_no_temporal(self):
        seen = {}

        def vlm(rgb, **kw):
            seen["prompt"] = kw.get("prompt", "")
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "scene_summary": "s",
                "keywords": ["hand"],
                "risk_type": "static",
                "risk_confidence": 0.3,
                "affected_entities": ["hand"],
                "predicted_consequence": "c",
                "prediction_horizon_s": 1.0,
                "explanation": "e",
                "suggested_action": "slow_down",
                "spatial_hint": "left",
                "prompt_version": PROMPT_VERSION_V1,
                "schema_version": SCHEMA_VERSION_V1,
                "model_id": "fake",
                "latency_ms": 1.0,
            }

        def ground(rgb, **kw):
            return {
                "ok": True,
                "detections": [],
                "keyword_detection_map": {},
                "perception_status": "ok",
                "model_versions": {},
            }

        w = FiveStageShadowWorker(vlm_analyze=vlm, perception_ground=ground)
        self.assertFalse(w._temporal_fusion_enabled)
        w.start()
        w.submit(np.zeros((8, 8, 3), dtype=np.uint8), sim_step=0, request_id="r0", frame_id="f0")
        import time

        for _ in range(50):
            r = w.latest_result()
            if r and r.get("processed_frames", 0) or (r and r.get("request_id") == "r0"):
                if r and r.get("request_id") == "r0":
                    break
            time.sleep(0.02)
        w.stop()
        self.assertEqual(seen.get("prompt", ""), "")
        self.assertFalse(bool((r or {}).get("temporal_fusion_enabled")))


class TestPromptV2(unittest.TestCase):
    def test_04_prompt_deterministic_hash(self):
        tc = TaskSemanticContext.from_dict(_load("task_place_b_occupied.json"))
        ev = _track_ev("track_valid_hand_moving.json")
        p1, h1 = build_temporal_prompt_v2(task_context=tc, track_evidence=ev)
        p2, h2 = build_temporal_prompt_v2(task_context=tc, track_evidence=ev)
        self.assertEqual(p1, p2)
        self.assertEqual(h1, h2)
        self.assertIn("static:", p1)
        self.assertIn("dynamic:", p1)
        self.assertIn("functional:", p1)

    def test_05_prompt_no_secret_path_session(self):
        tc = TaskSemanticContext.from_dict(_load("task_place_b_occupied.json"))
        ev = _track_ev("track_valid_hand_moving.json")
        prompt, _ = build_temporal_prompt_v2(task_context=tc, track_evidence=ev)
        low = prompt.lower()
        self.assertNotIn("api_key", low)
        self.assertNotIn("bearer", low)
        self.assertNotIn("/home/", low)
        self.assertNotIn("session_id=", low)


class TestTaskContext(unittest.TestCase):
    def test_06_task_context_rejects_answer_leak(self):
        with self.assertRaises(ValueError):
            TaskSemanticContext.from_dict({"risk_type": "dynamic", "task_phase": "place"})


class TestTemporalEvidenceRules(unittest.TestCase):
    def test_07_same_frame_not_fed_to_own_vlm(self):
        """Worker stores evidence after track; VLM of same frame must not see it."""
        prompts = []

        def vlm(rgb, **kw):
            prompts.append(kw.get("prompt", ""))
            return {
                "ok": True,
                "request_id": kw.get("request_id"),
                "frame_id": kw.get("frame_id"),
                "scene_summary": "s",
                "keywords": ["human hand"],
                "risk_type": "static",
                "risk_confidence": 0.9,
                "affected_entities": ["human hand"],
                "predicted_consequence": "collision",
                "prediction_horizon_s": 1.0,
                "explanation": "e",
                "suggested_action": "slow_down",
                "spatial_hint": "left",
                "prompt_version": PROMPT_VERSION_V2_TEMPORAL,
                "schema_version": SCHEMA_VERSION_V2,
                "model_id": "fake",
                "latency_ms": 1.0,
                "synthetic": True,
            }

        def ground(rgb, **kw):
            return {
                "ok": True,
                "detections": [{"detection_id": "d0", "label": "human hand", "score": 0.9}],
                "keyword_detection_map": {"human hand": ["d0"]},
                "perception_status": "ok",
                "model_versions": {},
            }

        def track(rgb, **kw):
            return _load("track_valid_hand_moving.json")

        w = FiveStageShadowWorker(
            vlm_analyze=vlm,
            perception_ground=ground,
            perception_track=track,
            temporal_fusion_enabled=True,
            temporal_evidence_config=TemporalEvidenceConfig(),
            task_context_provider=lambda **kw: TaskSemanticContext.from_dict(
                _load("task_place_b_occupied.json")
            ),
        )
        w.start()
        rgb = np.zeros((8, 8, 3), dtype=np.uint8)
        w.submit(rgb, sim_step=0, request_id="r0", frame_id="f0")
        import time

        r0 = None
        for _ in range(100):
            r0 = w.latest_result()
            if r0 and r0.get("request_id") == "r0":
                break
            time.sleep(0.02)
        self.assertIsNotNone(r0)
        # Frame0 prompt must not claim previous valid moving evidence from itself.
        self.assertIn('"present":false', prompts[0].replace(" ", "").lower() or prompts[0])
        # or present false in JSON
        self.assertTrue(
            '"present": false' in prompts[0] or '"present":false' in prompts[0].replace(" ", "")
        )
        w.submit(rgb, sim_step=50, request_id="r1", frame_id="f1")
        r1 = None
        for _ in range(100):
            r1 = w.latest_result()
            if r1 and r1.get("request_id") == "r1":
                break
            time.sleep(0.02)
        self.assertIsNotNone(r1)
        self.assertEqual(r1.get("temporal_source_frame_id"), "f0")
        w.stop()
        self.assertIsNone(w._prev_track_evidence)

    def test_08_valid_motion_elevates_static(self):
        vlm = _load("synthetic_static_highconf_for_temporal.json")
        ev = validate_temporal_evidence(
            _track_ev("track_valid_hand_moving.json"),
            entity_hint="human hand",
        )
        self.assertTrue(ev.valid)
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertTrue(fused.fusion_accepted)
        self.assertEqual(fused.fused_risk_type, "dynamic")
        self.assertEqual(fused.risk_type_source, "temporal_fusion")
        self.assertEqual(fused.motion_evidence_source, "sam2_track")
        self.assertLessEqual(fused.fused_confidence, vlm["risk_confidence"] + 1e-9)

    def test_09_low_vlm_conf_rejects_despite_fast_track(self):
        vlm = _load("synthetic_high_speed_low_vlm_conf.json")
        ev = validate_temporal_evidence(
            _track_ev("track_valid_hand_moving.json"), entity_hint="human hand"
        )
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertFalse(fused.fusion_accepted)
        self.assertEqual(fused.rejection_reason, "native_confidence_below_threshold")

    def test_10_speed_below_threshold_rejects(self):
        vlm = _load("synthetic_high_vlm_stationary_track.json")
        ev = validate_temporal_evidence(
            _track_ev("track_stationary.json"), entity_hint="human hand"
        )
        self.assertFalse(ev.valid)
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertFalse(fused.fusion_accepted)

    def test_11_stale_evidence_rejects(self):
        vlm = _load("synthetic_static_highconf_for_temporal.json")
        ev = validate_temporal_evidence(
            _track_ev("track_valid_hand_moving.json", age_s=5.0),
            entity_hint="human hand",
        )
        self.assertEqual(ev.rejection_reason, "evidence_stale")
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertFalse(fused.fusion_accepted)

    def test_12_lost_track_rejects(self):
        vlm = _load("synthetic_static_highconf_for_temporal.json")
        ev = validate_temporal_evidence(
            _track_ev("track_lost.json"), entity_hint="human hand"
        )
        self.assertIn("lost", ev.rejection_reason)
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertFalse(fused.fusion_accepted)

    def test_13_session_mismatch_rejects(self):
        vlm = _load("synthetic_static_highconf_for_temporal.json")
        ev = validate_temporal_evidence(
            _track_ev("track_valid_hand_moving.json"),
            entity_hint="human hand",
            current_session_ref="session_other",
        )
        self.assertEqual(ev.rejection_reason, "session_mismatch")

    def test_14_entity_mismatch_rejects(self):
        vlm = _load("synthetic_entity_mismatch_vlm.json")
        ev = validate_temporal_evidence(
            _track_ev("track_hand_for_mismatch.json"), entity_hint="container"
        )
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertFalse(fused.fusion_accepted)
        self.assertEqual(fused.rejection_reason, "entity_mismatch")

    def test_15_re_detected_rejects(self):
        raw = _load("track_valid_hand_moving.json")
        raw["tracks"][0]["re_detected"] = True
        ev = build_temporal_evidence_from_track_result(
            raw, source_request_id="r", source_frame_id="f"
        )
        ev = validate_temporal_evidence(age_evidence(ev, age_s=0.1), entity_hint="human hand")
        self.assertEqual(ev.rejection_reason, "re_detected_reset_required")


class TestFusionGates(unittest.TestCase):
    def test_16_static_alone_rejects(self):
        vlm = _load("synthetic_static_highconf_for_temporal.json")
        fused = fuse_semantic_evidence(vlm, track_evidence=None, synthetic=True)
        self.assertFalse(fused.fusion_accepted)

    def test_17_slow_down_alone_not_enough(self):
        vlm = {
            "ok": True,
            "risk_type": "none",
            "risk_confidence": 0.9,
            "suggested_action": "slow_down",
            "affected_entities": ["human hand"],
            "keywords": ["human hand"],
            "synthetic": True,
        }
        fused = fuse_semantic_evidence(vlm, synthetic=True)
        self.assertFalse(fused.fusion_accepted)

    def test_18_task_context_alone_rejects(self):
        vlm = _load("p1_frame0_static.json")
        tc = TaskSemanticContext.from_dict(_load("task_place_b_occupied.json"))
        fused = fuse_semantic_evidence(vlm, task_context=tc, synthetic=False)
        self.assertFalse(fused.fusion_accepted)

    def test_19_functional_native_target_match(self):
        vlm = _load("synthetic_functional_native.json")
        tc = TaskSemanticContext.from_dict(_load("task_place_b_occupied.json"))
        fused = fuse_semantic_evidence(vlm, task_context=tc, synthetic=True)
        self.assertTrue(fused.fusion_accepted)
        self.assertEqual(fused.fused_risk_type, "functional")
        self.assertEqual(fused.risk_type_source, "task_context_fusion")

    def test_20_functional_target_mismatch(self):
        vlm = _load("synthetic_functional_native.json")
        tc = TaskSemanticContext.from_dict(
            {**_load("task_place_b_occupied.json"), "target_container": "unknown"}
        )
        fused = fuse_semantic_evidence(vlm, task_context=tc, synthetic=True)
        self.assertFalse(fused.fusion_accepted)

    def test_21_fused_confidence_never_raised(self):
        vlm = _load("synthetic_static_highconf_for_temporal.json")
        ev = validate_temporal_evidence(
            _track_ev("track_valid_hand_moving.json"), entity_hint="human hand"
        )
        fused = fuse_semantic_evidence(vlm, track_evidence=ev, synthetic=True)
        self.assertLessEqual(fused.fused_confidence, float(vlm["risk_confidence"]) + 1e-9)
        self.assertGreaterEqual(fused.fused_confidence, MIN_CONFIDENCE - 1e-9)

    def test_22_confidence_threshold_frozen(self):
        self.assertEqual(MIN_CONFIDENCE, 0.85)


class TestSemanticKeyV2(unittest.TestCase):
    def test_23_explanation_hint_do_not_change_key(self):
        a = build_semantic_key_v2(
            fused_risk_type="dynamic",
            recommended_action="slow_down",
            canonical_entity="human_hand",
            target_container="container_b",
            task_phase="place",
            motion_bucket="L",
        )
        b = build_semantic_key_v2(
            fused_risk_type="dynamic",
            recommended_action="slow_down",
            canonical_entity="human hand",
            target_container="container_b",
            task_phase="place",
            motion_bucket="L",
        )
        self.assertEqual(a["semantic_key"], b["semantic_key"])

    def test_24_entity_target_phase_motion_change_key(self):
        base = dict(
            fused_risk_type="dynamic",
            recommended_action="slow_down",
            canonical_entity="human_hand",
            target_container="container_b",
            task_phase="place",
            motion_bucket="L",
        )
        k0 = build_semantic_key_v2(**base)["semantic_key"]
        self.assertNotEqual(
            k0,
            build_semantic_key_v2(**{**base, "canonical_entity": "container"})["semantic_key"],
        )
        self.assertNotEqual(
            k0,
            build_semantic_key_v2(**{**base, "target_container": "container_a"})["semantic_key"],
        )
        self.assertNotEqual(
            k0, build_semantic_key_v2(**{**base, "task_phase": "transit"})["semantic_key"]
        )
        self.assertNotEqual(
            k0, build_semantic_key_v2(**{**base, "motion_bucket": "R"})["semantic_key"]
        )


class TestSupervisorConsistency(unittest.TestCase):
    def _inp(self, **kw) -> SemanticAdvisoryInput:
        key = build_semantic_key_v2(
            fused_risk_type=kw.get("risk_type", "dynamic"),
            recommended_action="slow_down",
            canonical_entity=kw.get("canonical_entity", "human_hand"),
            target_container=kw.get("target_container", "container_b"),
            task_phase=kw.get("task_phase", "place"),
            motion_bucket=kw.get("motion_bucket", "L"),
        )
        data = dict(
            episode_id="0",
            sim_step=0,
            current_time_s=1.0,
            request_id="req-a",
            frame_id="frm-a",
            result_age_s=0.1,
            schema_version=SCHEMA_VERSION_V2,
            prompt_version=PROMPT_VERSION_V2_TEMPORAL,
            model_id="synthetic",
            gateway_parse_ok=True,
            risk_type="dynamic",
            risk_confidence=0.9,
            affected_entities=["human hand"],
            predicted_consequence="potential collision",
            prediction_horizon_s=1.5,
            suggested_action="slow_down",
            spatial_hint="left",
            current_geometry_gate=GATE_ALLOW,
            synthetic=True,
            semantic_key_override=key["semantic_key"],
            canonical_entity="human_hand",
            target_container="container_b",
            task_phase="place",
            motion_bucket="L",
        )
        data.update(kw)
        if "semantic_key_override" not in kw and "risk_type" in kw:
            data["semantic_key_override"] = build_semantic_key_v2(
                fused_risk_type=kw["risk_type"],
                recommended_action="slow_down",
                canonical_entity=data["canonical_entity"],
                target_container=data["target_container"],
                task_phase=data["task_phase"],
                motion_bucket=data["motion_bucket"],
            )["semantic_key"]
        return SemanticAdvisoryInput(**data)

    def test_25_same_request_not_double_counted(self):
        s = SemanticSafetySupervisor(_cfg_sup())
        d1 = s.evaluate(self._inp(request_id="same", frame_id="f1", current_time_s=1.0))
        d2 = s.evaluate(self._inp(request_id="same", frame_id="f2", current_time_s=1.1))
        self.assertEqual(d1.rejection_reason, REASON_CONSISTENCY_PENDING)
        self.assertEqual(d2.rejection_reason, "duplicate_request")

    def test_26_two_requests_same_key_consistency(self):
        s = SemanticSafetySupervisor(_cfg_sup())
        d1 = s.evaluate(self._inp(request_id="r1", frame_id="f1", current_time_s=1.0))
        d2 = s.evaluate(self._inp(request_id="r2", frame_id="f2", current_time_s=1.2))
        self.assertEqual(d1.rejection_reason, REASON_CONSISTENCY_PENDING)
        self.assertTrue(d2.accepted)
        self.assertFalse(d2.intentional_control_effect)


class TestHistoricalNegatives(unittest.TestCase):
    def test_27_v0c3_still_accepted_0(self):
        s = SemanticSafetySupervisor(_cfg_sup(semantic_key_version="v1"))
        for name, rid in [
            ("v0c3_frame0_static.json", "c3-0"),
            ("v0c3_frame1_dynamic_lowconf.json", "c3-1"),
        ]:
            v = _load(name)
            d = s.evaluate(
                SemanticAdvisoryInput(
                    episode_id="c3",
                    sim_step=0,
                    current_time_s=1.0,
                    request_id=rid,
                    frame_id=rid,
                    result_age_s=0.1,
                    schema_version=SCHEMA_VERSION_V1,
                    prompt_version=PROMPT_VERSION_V1,
                    model_id="hist",
                    gateway_parse_ok=True,
                    risk_type=v["risk_type"],
                    risk_confidence=float(v["risk_confidence"]),
                    affected_entities=v["affected_entities"],
                    predicted_consequence=v["predicted_consequence"],
                    prediction_horizon_s=1.5,
                    suggested_action=v["suggested_action"],
                    spatial_hint=v["spatial_hint"],
                    current_geometry_gate=GATE_ALLOW,
                    synthetic=False,
                )
            )
            self.assertFalse(d.accepted)

    def test_28_p1_still_accepted_0(self):
        s = SemanticSafetySupervisor(_cfg_sup(semantic_key_version="v1"))
        for name, rid in [("p1_frame0_static.json", "p1-0"), ("p1_frame1_static.json", "p1-1")]:
            v = _load(name)
            d = s.evaluate(
                SemanticAdvisoryInput(
                    episode_id="p1",
                    sim_step=0,
                    current_time_s=1.0,
                    request_id=rid,
                    frame_id=rid,
                    result_age_s=0.1,
                    schema_version=SCHEMA_VERSION_V1,
                    prompt_version=PROMPT_VERSION_V1,
                    model_id="hist",
                    gateway_parse_ok=True,
                    risk_type=v["risk_type"],
                    risk_confidence=float(v["risk_confidence"]),
                    affected_entities=v["affected_entities"],
                    predicted_consequence=v["predicted_consequence"],
                    prediction_horizon_s=1.5,
                    suggested_action=v["suggested_action"],
                    spatial_hint=v["spatial_hint"],
                    current_geometry_gate=GATE_ALLOW,
                    synthetic=False,
                )
            )
            self.assertFalse(d.accepted)
            self.assertEqual(d.rejection_reason, REASON_RISK_TYPE_NOT_ALLOWED)

    def test_29_d1bs_still_accepted_0(self):
        s = SemanticSafetySupervisor(_cfg_sup())
        for name, rid in [
            ("d1bs_step100_static.json", "d1b-100"),
            ("d1bs_step200_static.json", "d1b-200"),
        ]:
            v = _load(name)
            # Even with valid track, low conf must reject
            ev = validate_temporal_evidence(
                _track_ev("track_valid_hand_moving.json"),
                entity_hint=v["affected_entities"][-1],
            )
            fused = fuse_semantic_evidence(v, track_evidence=ev, synthetic=False)
            self.assertFalse(fused.fusion_accepted)
            d = s.evaluate(
                SemanticAdvisoryInput(
                    episode_id="d1b",
                    sim_step=0,
                    current_time_s=1.0,
                    request_id=rid,
                    frame_id=rid,
                    result_age_s=0.1,
                    schema_version=SCHEMA_VERSION_V2,
                    prompt_version=PROMPT_VERSION_V2_TEMPORAL,
                    model_id="hist",
                    gateway_parse_ok=True,
                    risk_type=v["risk_type"],
                    risk_confidence=float(v["risk_confidence"]),
                    affected_entities=v["affected_entities"],
                    predicted_consequence=v["predicted_consequence"],
                    prediction_horizon_s=1.5,
                    suggested_action=v["suggested_action"],
                    spatial_hint=v["spatial_hint"],
                    current_geometry_gate=GATE_ALLOW,
                    synthetic=False,
                )
            )
            self.assertFalse(d.accepted)


class TestLeakageAndLogger(unittest.TestCase):
    def test_30_leakage_counters_zero(self):
        sem = SemanticLeakageCounters()
        fs = ShadowLeakageCounters()
        sem.assert_all_zero()
        self.assertTrue(fs.all_zero())

    def test_31_control_hash_stable(self):
        h1 = control_decision_hash(
            gate_decision=0,
            action=None,
            should_advance=True,
            protocol_phase="transit",
            replan_event=False,
            task_progression=10,
        )
        h2 = control_decision_hash(
            gate_decision=0,
            action=None,
            should_advance=True,
            protocol_phase="transit",
            replan_event=False,
            task_progression=10,
        )
        self.assertEqual(h1, h2)

    def test_32_logger_roundtrip_new_fields(self):
        with tempfile.TemporaryDirectory() as td:
            lg = FiveStageShadowLogger(td, enabled=True)
            row = {k: "" for k in SHADOW_STEP_FIELDS}
            row.update(
                {
                    "episode_id": "0",
                    "sim_step": 1,
                    "request_id": "r",
                    "frame_id": "f",
                    "prompt_hash": "abc",
                    "fused_risk_type": "dynamic",
                    "semantic_key": "deadbeef",
                    "intentional_control_effect": False,
                    "track_session_id": "RAWSECRETSESSION",
                }
            )
            lg.record(row)
            text = (lg.session_dir / "five_stage_shadow_requests.jsonl").read_text()
            self.assertIn("<redacted>", text)
            self.assertNotIn("RAWSECRETSESSION", text)
            lg.close() if hasattr(lg, "close") else None
            # csv header contains new fields
            csv_head = (lg.session_dir / "five_stage_shadow_steps.csv").read_text().splitlines()[0]
            self.assertIn("fused_risk_type", csv_head)
            self.assertIn("semantic_key", csv_head)

    def test_33_track_id_zero_legal(self):
        raw = _load("track_valid_hand_moving.json")
        self.assertEqual(raw["tracks"][0]["track_id"], 0)
        ev = build_temporal_evidence_from_track_result(
            raw, source_request_id="r", source_frame_id="f"
        )
        self.assertEqual(ev.track_id, "0")

    def test_34_no_silent_v1_fallback_on_v2_reject(self):
        vlm = _load("d1bs_step100_static.json")
        fused = fuse_semantic_evidence(vlm, track_evidence=None, synthetic=False)
        self.assertFalse(fused.fusion_accepted)
        # Must not invent dynamic/functional from legacy
        self.assertNotEqual(fused.fused_risk_type, "dynamic")
        self.assertNotEqual(fused.risk_type_source, "vlm_native")

    def test_35_canonicalize_aliases_stable(self):
        self.assertEqual(canonicalize_entity("orange sphere"), canonicalize_entity("spherical object"))


if __name__ == "__main__":
    unittest.main()
