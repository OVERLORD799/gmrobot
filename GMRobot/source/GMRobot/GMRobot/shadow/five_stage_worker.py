"""Five-stage VLM/perception shadow worker (async, no control-loop HTTP)."""

from __future__ import annotations

import copy
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

try:
    from ..perception.schema import normalize_keywords
except ImportError:  # unit-test path: shadow as top-level package
    from perception.schema import normalize_keywords


@dataclass
class ShadowFrameJob:
    episode_id: str
    sim_step: int
    frame_id: str
    request_id: str
    rgb: np.ndarray
    submitted_at_s: float = field(default_factory=time.monotonic)


@dataclass
class ShadowLeakageCounters:
    shadow_gate_override_count: int = 0
    shadow_action_override_count: int = 0
    shadow_clock_blocked_steps: int = 0
    shadow_replan_applied_count: int = 0
    shadow_protocol_override_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "shadow_gate_override_count": self.shadow_gate_override_count,
            "shadow_action_override_count": self.shadow_action_override_count,
            "shadow_clock_blocked_steps": self.shadow_clock_blocked_steps,
            "shadow_replan_applied_count": self.shadow_replan_applied_count,
            "shadow_protocol_override_count": self.shadow_protocol_override_count,
        }

    def all_zero(self) -> bool:
        return all(v == 0 for v in self.as_dict().values())


@dataclass
class ShadowMetrics:
    submitted_frames: int = 0
    processed_frames: int = 0
    dropped_frames: int = 0
    queue_depth: int = 0
    queue_wait_ms: float = 0.0
    vlm_latency_ms: float = 0.0
    ground_latency_ms: float = 0.0
    track_latency_ms: float = 0.0
    end_to_end_latency_ms: float = 0.0
    timeout_count: int = 0
    parse_error_count: int = 0
    stale_result_count: int = 0
    stale_poll_count: int = 0
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class FiveStageShadowWorker:
    """Bounded latest-frame-wins queue; control thread never performs HTTP."""

    def __init__(
        self,
        *,
        vlm_analyze: Callable[..., dict[str, Any]],
        perception_ground: Callable[..., dict[str, Any]],
        perception_track: Callable[..., dict[str, Any]] | None = None,
        queue_size: int = 1,
        max_result_age_s: float = 2.0,
        enforcement_mode: str = "shadow",
        temporal_fusion_enabled: bool = False,
        temporal_evidence_config: Any | None = None,
        task_context_provider: Callable[..., Any] | None = None,
    ):
        if enforcement_mode != "shadow":
            raise ValueError("V0-A worker only supports enforcement_mode='shadow'")
        self._vlm_analyze = vlm_analyze
        self._perception_ground = perception_ground
        self._perception_track = perception_track
        self._queue: queue.Queue[ShadowFrameJob | None] = queue.Queue(maxsize=max(1, queue_size))
        self._queue_size = max(1, queue_size)
        self._max_result_age_s = float(max_result_age_s)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._last_stale_counted_key: tuple[Any, ...] | None = None
        self.metrics = ShadowMetrics()
        self.leakage = ShadowLeakageCounters()
        # V1-D2A: explicit opt-in only (never auto-switch from health/response).
        self._temporal_fusion_enabled = bool(temporal_fusion_enabled)
        self._temporal_evidence_config = temporal_evidence_config
        self._task_context_provider = task_context_provider
        self._prev_track_evidence: Any | None = None
        self._prev_track_completed_at_s: float | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="five-stage-shadow", daemon=True)
        self._thread.start()

    def reset_temporal_evidence(self) -> None:
        """Clear previous-frame track evidence (episode reset / reacquire / shutdown)."""
        with self._lock:
            self._prev_track_evidence = None
            self._prev_track_completed_at_s = None

    def stop(self, timeout_s: float = 2.0) -> dict[str, Any]:
        """Request worker exit and join with a bounded timeout.

        Returns an explicit status. If the thread is still alive after join,
        ``_thread`` is NOT cleared (never pretend the worker is gone).
        """
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
                self.metrics.dropped_frames += 1
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

        thread_alive = False
        if self._thread is not None:
            self._thread.join(timeout=float(timeout_s))
            thread_alive = self._thread.is_alive()
            if not thread_alive:
                self._thread = None

        # Drain/shutdown must not leave stale temporal evidence for a later start.
        self.reset_temporal_evidence()

        with self._lock:
            queue_depth = self._queue.qsize()
            processed = int(self.metrics.processed_frames)

        return {
            "stopped_cleanly": not thread_alive,
            "thread_alive": thread_alive,
            "processed_frames": processed,
            "queue_depth": queue_depth,
        }

    def thread_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(
        self,
        rgb: np.ndarray,
        *,
        sim_step: int,
        episode_id: str = "0",
        frame_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Non-blocking enqueue. Never performs HTTP."""
        job = ShadowFrameJob(
            episode_id=str(episode_id),
            sim_step=int(sim_step),
            frame_id=str(frame_id or uuid.uuid4()),
            request_id=str(request_id or uuid.uuid4()),
            rgb=np.asarray(rgb),
        )
        with self._lock:
            self.metrics.submitted_frames += 1
        dropped = 0
        while True:
            try:
                self._queue.put_nowait(job)
                break
            except queue.Full:
                try:
                    _ = self._queue.get_nowait()
                    dropped += 1
                except queue.Empty:
                    continue
        with self._lock:
            self.metrics.dropped_frames += dropped
            self.metrics.queue_depth = self._queue.qsize()
        return {
            "accepted": True,
            "request_id": job.request_id,
            "frame_id": job.frame_id,
            "dropped_to_enqueue": dropped,
        }

    def latest_result(self, *, now_s: float | None = None) -> dict[str, Any] | None:
        now = time.monotonic() if now_s is None else float(now_s)
        with self._lock:
            if self._latest is None:
                return None
            snap = copy.deepcopy(self._latest)
            age = now - float(snap.get("completed_at_s", now))
            snap["result_age_s"] = age
            snap["stale"] = age > self._max_result_age_s
            if snap["stale"]:
                # Unique stale *results* (not poll count). Same request/result → count once.
                key = (
                    snap.get("request_id"),
                    snap.get("frame_id"),
                    snap.get("completed_at_s"),
                )
                self.metrics.stale_poll_count += 1
                if key != self._last_stale_counted_key:
                    self.metrics.stale_result_count += 1
                    self._last_stale_counted_key = key
            snap["metrics"] = self.metrics.as_dict()
            snap["leakage"] = self.leakage.as_dict()
            return snap

    def assert_no_control_side_effects(self) -> None:
        if not self.leakage.all_zero():
            raise AssertionError(f"shadow leakage non-zero: {self.leakage.as_dict()}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                result = self._process(job)
            except Exception as exc:  # noqa: BLE001 — isolate from control loop
                with self._lock:
                    self.metrics.last_error = str(exc)
                    self.metrics.parse_error_count += 1
                result = {
                    "ok": False,
                    "pipeline_ok": False,
                    "pipeline_error_stage": "worker",
                    "pipeline_error": str(exc),
                    "request_id": job.request_id,
                    "frame_id": job.frame_id,
                    "error_type": "worker_exception",
                    "error": str(exc),
                    "sim_step": job.sim_step,
                    "episode_id": job.episode_id,
                }
            result["completed_at_s"] = time.monotonic()
            result["end_to_end_latency_ms"] = (
                result["completed_at_s"] - job.submitted_at_s
            ) * 1000.0
            with self._lock:
                self._latest = result
                self.metrics.processed_frames += 1
                self.metrics.queue_depth = self._queue.qsize()
                self.metrics.end_to_end_latency_ms = float(result["end_to_end_latency_ms"])
                self.metrics.queue_wait_ms = float(result.get("queue_wait_ms", 0.0))

    def _process(self, job: ShadowFrameJob) -> dict[str, Any]:
        wait_ms = (time.monotonic() - job.submitted_at_s) * 1000.0

        # --- v2 temporal context (explicit opt-in only; never uses same-frame track) ---
        task_ctx = None
        prev_evidence = None
        prompt_override = ""
        prompt_hash = ""
        temporal_context_present = False
        task_context_present = False
        if self._temporal_fusion_enabled:
            from GMRobot.vlm.prompt_v2 import build_temporal_prompt_v2
            from GMRobot.vlm.task_context import TaskSemanticContext
            from GMRobot.vlm.temporal_evidence import age_evidence

            if self._task_context_provider is not None:
                raw_ctx = self._task_context_provider(
                    sim_step=job.sim_step,
                    episode_id=job.episode_id,
                    request_id=job.request_id,
                    frame_id=job.frame_id,
                )
                if isinstance(raw_ctx, TaskSemanticContext):
                    task_ctx = raw_ctx
                elif isinstance(raw_ctx, dict):
                    task_ctx = TaskSemanticContext.from_dict(raw_ctx)
                else:
                    task_ctx = TaskSemanticContext(context_sim_step=job.sim_step)
            else:
                task_ctx = TaskSemanticContext(context_sim_step=job.sim_step)
            task_context_present = True

            with self._lock:
                stored = self._prev_track_evidence
                completed_at = self._prev_track_completed_at_s
            if stored is not None and completed_at is not None:
                age_s = max(0.0, time.monotonic() - float(completed_at))
                prev_evidence = age_evidence(stored, age_s=age_s)
                temporal_context_present = True
            prompt_override, prompt_hash = build_temporal_prompt_v2(
                task_context=task_ctx,
                track_evidence=prev_evidence,
            )

        t_vlm = time.monotonic()
        vlm_kwargs: dict[str, Any] = {
            "request_id": job.request_id,
            "frame_id": job.frame_id,
            "meta": {
                "sim_step": job.sim_step,
                "episode_id": job.episode_id,
                "temporal_fusion_enabled": bool(self._temporal_fusion_enabled),
            },
        }
        if prompt_override:
            vlm_kwargs["prompt"] = prompt_override
            vlm_kwargs["meta"]["prompt_hash"] = prompt_hash
        vlm = self._vlm_analyze(job.rgb, **vlm_kwargs)
        vlm_ms = (time.monotonic() - t_vlm) * 1000.0
        with self._lock:
            self.metrics.vlm_latency_ms = vlm_ms
            if vlm.get("ok") is False:
                et = str(vlm.get("error_type") or "")
                if et == "timeout":
                    self.metrics.timeout_count += 1
                if et in ("parse_error", "schema_error"):
                    self.metrics.parse_error_count += 1
                self.metrics.last_error = str(vlm.get("error") or et)

        # Normalize once; same list feeds ground + track (keyword-match-first selection).
        keywords = normalize_keywords(vlm.get("keywords") if vlm.get("ok") else [])
        ground: dict[str, Any]
        t_g = time.monotonic()
        if vlm.get("ok") is not True:
            ground = {
                "ok": False,
                "request_id": job.request_id,
                "frame_id": job.frame_id,
                "parent_request_id": job.request_id,
                "perception_status": "skipped_vlm_error",
                "detections": [],
                "keyword_detection_map": {},
            }
        elif not keywords:
            ground = {
                "ok": True,
                "request_id": job.request_id,
                "frame_id": job.frame_id,
                "parent_request_id": job.request_id,
                "perception_status": "skipped_no_keywords",
                "detections": [],
                "keyword_detection_map": {},
                "latency_ms": 0.0,
            }
        else:
            ground = self._perception_ground(
                job.rgb,
                keywords=keywords,
                request_id=job.request_id,
                frame_id=job.frame_id,
                meta={"parent_request_id": job.request_id},
                allow_default_prompt=False,
            )
            ground = dict(ground)
            ground.setdefault("parent_request_id", job.request_id)
            ground.setdefault("request_id", job.request_id)
            ground.setdefault("frame_id", job.frame_id)
        ground_ms = (time.monotonic() - t_g) * 1000.0
        with self._lock:
            self.metrics.ground_latency_ms = ground_ms

        track: dict[str, Any] | None = None
        track_ms = 0.0
        if self._perception_track is not None and ground.get("detections"):
            t_t = time.monotonic()
            # V0-B3.1: always forward normalized VLM keywords (not detections-only).
            track = self._perception_track(
                job.rgb,
                parent_request_id=job.request_id,
                frame_id=job.frame_id,
                detections=ground.get("detections") or [],
                keywords=keywords,
            )
            track_ms = (time.monotonic() - t_t) * 1000.0
            with self._lock:
                self.metrics.track_latency_ms = track_ms

        suggested = str(vlm.get("suggested_action") or "") if vlm.get("ok") else ""
        would_stop = suggested in ("stop",)
        would_replan = suggested in ("replan",)

        primary_track: dict[str, Any] = {}
        if track:
            tracks_list = track.get("tracks") or []
            if isinstance(tracks_list, list) and tracks_list and isinstance(tracks_list[0], dict):
                primary_track = tracks_list[0]
        # Preserve track_id=0 (do not use truthiness / `or ""` on the id itself)
        track_id_val = primary_track.get("track_id") if primary_track else track.get("track_id") if track else None
        if track_id_val is None and track:
            track_id_val = track.get("track_id")
        track_state_val = ""
        if primary_track.get("track_state"):
            track_state_val = str(primary_track.get("track_state"))
        elif track:
            track_state_val = str(track.get("track_state") or "")

        # Save THIS frame's track as evidence for the *next* frame only (never feed into this VLM).
        fusion_fields: dict[str, Any] = {
            "temporal_fusion_enabled": bool(self._temporal_fusion_enabled),
            "prompt_hash": prompt_hash,
            "temporal_context_present": temporal_context_present,
            "temporal_source_frame_id": "",
            "temporal_evidence_age_s": "",
            "temporal_entity": "",
            "temporal_speed_px_s": "",
            "temporal_motion_bucket": "",
            "temporal_valid": False,
            "task_context_present": task_context_present,
            "task_phase": "",
            "task_target": "",
            "native_risk_type": str(vlm.get("risk_type") or ""),
            "native_risk_confidence": vlm.get("risk_confidence", ""),
            "fused_risk_type": "",
            "fused_confidence": "",
            "risk_type_source": "",
            "motion_evidence_source": "none",
            "task_context_source": "",
            "fusion_rule": "",
            "fusion_rejection_reason": "",
            "fusion_accepted": False,
            "semantic_key_version": "",
            "semantic_key": "",
            "intentional_control_effect": False,
        }
        if self._temporal_fusion_enabled:
            from GMRobot.vlm.temporal_evidence import build_temporal_evidence_from_track_result
            from GMRobot.safety.semantic_temporal_fusion import fuse_semantic_evidence

            if task_ctx is not None:
                fusion_fields["task_phase"] = task_ctx.task_phase
                fusion_fields["task_target"] = task_ctx.target_container
                fusion_fields["task_context_source"] = task_ctx.context_source
            if prev_evidence is not None:
                fusion_fields["temporal_source_frame_id"] = prev_evidence.source_frame_id
                fusion_fields["temporal_evidence_age_s"] = prev_evidence.evidence_age_s
                fusion_fields["temporal_entity"] = prev_evidence.canonical_entity
                fusion_fields["temporal_speed_px_s"] = prev_evidence.speed_px_s
                fusion_fields["temporal_motion_bucket"] = prev_evidence.motion_bucket
                fusion_fields["temporal_valid"] = bool(prev_evidence.valid)

            fused = fuse_semantic_evidence(
                vlm if vlm.get("ok") else {**vlm, "risk_type": "", "risk_confidence": 0.0},
                task_context=task_ctx,
                track_evidence=prev_evidence,
                temporal_config=self._temporal_evidence_config,
                synthetic=bool(vlm.get("synthetic", False)),
            )
            fusion_fields.update(
                {
                    "native_risk_type": fused.native_risk_type,
                    "native_risk_confidence": fused.native_risk_confidence,
                    "fused_risk_type": fused.fused_risk_type,
                    "fused_confidence": fused.fused_confidence,
                    "risk_type_source": fused.risk_type_source,
                    "motion_evidence_source": fused.motion_evidence_source,
                    "task_context_source": fused.task_context_source,
                    "fusion_rule": fused.fusion_rule,
                    "fusion_rejection_reason": fused.rejection_reason,
                    "fusion_accepted": fused.fusion_accepted,
                    "semantic_key_version": fused.semantic_key_version,
                    "semantic_key": fused.semantic_key,
                    "canonical_entity": fused.canonical_entity,
                    "motion_bucket": fused.motion_bucket,
                    "fusion": fused.to_dict(),
                }
            )

            # Persist completed track for next frame; clear on lost/reset/re_detected.
            new_ev = build_temporal_evidence_from_track_result(
                track,
                source_request_id=job.request_id,
                source_frame_id=job.frame_id,
                config=self._temporal_evidence_config,
                now_age_s=0.0,
            )
            state_l = str(new_ev.track_state or "").lower()
            if state_l in ("lost", "reset") or new_ev.re_detected or track is None:
                with self._lock:
                    self._prev_track_evidence = None
                    self._prev_track_completed_at_s = None
            else:
                with self._lock:
                    self._prev_track_evidence = new_ev
                    self._prev_track_completed_at_s = time.monotonic()

        pipeline_ok = True
        pipeline_error_stage = ""
        pipeline_error = ""
        # Preserve nested stage errors; annotate transport/pipeline status separately.
        if vlm.get("ok") is not True:
            pipeline_ok = False
            pipeline_error_stage = "vlm"
            pipeline_error = str(vlm.get("error") or vlm.get("error_type") or "vlm_error")
        elif (
            str(ground.get("perception_status") or "") not in {"skipped_vlm_error", "skipped_no_keywords"}
            and ground.get("ok") is False
        ):
            # Legitimate empty detections with ok=True are not transport errors.
            pipeline_ok = False
            pipeline_error_stage = "ground"
            pipeline_error = str(ground.get("error") or ground.get("error_type") or "ground_error")
        elif track is not None and track.get("ok") is False:
            pipeline_ok = False
            pipeline_error_stage = "track"
            pipeline_error = str(track.get("error") or track.get("error_type") or "track_error")

        # Exposed risk fields: v1 keeps native; v2 exposes fused for supervisor consumers.
        out_risk_type = fusion_fields.get("fused_risk_type") or vlm.get("risk_type", "")
        out_risk_conf = (
            fusion_fields.get("fused_confidence")
            if self._temporal_fusion_enabled
            else vlm.get("risk_confidence", "")
        )
        if not self._temporal_fusion_enabled:
            out_risk_type = vlm.get("risk_type", "")

        result = {
            "ok": bool(vlm.get("ok")),
            "pipeline_ok": pipeline_ok,
            "pipeline_error_stage": pipeline_error_stage,
            "pipeline_error": pipeline_error,
            "episode_id": job.episode_id,
            "sim_step": job.sim_step,
            "frame_id": job.frame_id,
            "request_id": job.request_id,
            "parent_request_id": job.request_id,
            "vlm": vlm,
            "ground": ground,
            "track": track,
            "keywords": keywords,
            "scene_summary": vlm.get("scene_summary", ""),
            "risk_type": out_risk_type,
            "risk_confidence": out_risk_conf,
            "predicted_consequence": vlm.get("predicted_consequence", ""),
            "prediction_horizon_s": vlm.get("prediction_horizon_s", ""),
            "suggested_action": suggested,
            "spatial_hint": vlm.get("spatial_hint", ""),
            "shadow_suggested_action": suggested,
            "would_stop": would_stop,
            "would_replan": would_replan,
            "keyword_detection_map": ground.get("keyword_detection_map") or {},
            "perception_status": ground.get("perception_status", ""),
            "track_session_id": (track or {}).get("track_session_id", ""),
            "track_id": "" if track_id_val is None else track_id_val,
            "track_state": track_state_val,
            "track_state_native": bool((track or {}).get("track_state_native", False)),
            "track_state_source": str((track or {}).get("track_state_source") or ""),
            "session_present": bool((track or {}).get("session_present", False)),
            "session_match": (track or {}).get("session_match"),
            "session_match_applicable": bool((track or {}).get("session_match_applicable", False)),
            "session_continuity_verified": bool(
                (track or {}).get("session_continuity_verified", False)
            ),
            "session_generation": (track or {}).get("session_generation"),
            "session_ref": str((track or {}).get("session_ref") or ""),
            "vlm_remote_contract": str(vlm.get("remote_contract") or ""),
            "perception_remote_contract": str(
                ground.get("remote_contract") or (track or {}).get("remote_contract") or ""
            ),
            "id_source": str(
                vlm.get("id_source")
                or ground.get("id_source")
                or (track or {}).get("id_source")
                or ""
            ),
            "gateway_parse_ok": bool(
                vlm.get("gateway_parse_ok", vlm.get("ok"))
                if "gateway_parse_ok" in vlm or "remote_contract" in vlm
                else True
            )
            and bool(ground.get("gateway_parse_ok", True)),
            "gateway_mapping_errors": list(vlm.get("gateway_mapping_errors") or [])
            + list(ground.get("gateway_mapping_errors") or [])
            + list((track or {}).get("gateway_mapping_errors") or []),
            "status": "ok" if vlm.get("ok") else str(vlm.get("error_type") or "error"),
            "error_type": vlm.get("error_type", ""),
            "queue_wait_ms": wait_ms,
            "vlm_latency_ms": vlm_ms,
            "ground_latency_ms": ground_ms,
            "track_latency_ms": track_ms,
            "schema_version": vlm.get("schema_version", ""),
            "prompt_version": vlm.get("prompt_version", ""),
            "vlm_model_id": vlm.get("model_id", ""),
            "gdino_model_id": ((ground.get("model_versions") or {}).get("gdino_model_id", "")),
            "sam2_model_id": ((ground.get("model_versions") or {}).get("sam2_model_id", "")),
            "leakage": self.leakage.as_dict(),
            "enforcement_mode": "shadow",
        }
        result.update(fusion_fields)
        return result
