"""Five-stage shadow step scheduler (submit on interval, poll every step)."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from .isolation import shadow_control_decision
from .logger import FiveStageShadowLogger
from .five_stage_worker import FiveStageShadowWorker


def result_log_key(result: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identity for deduplicated logging of a completed shadow result."""
    return (
        result.get("request_id"),
        result.get("frame_id"),
        result.get("completed_at_s"),
    )


class FiveStageShadowScheduler:
    """Drive FiveStageShadowWorker independently of the safety gate path.

    - poll every simulation step (non-blocking)
    - submit only on inference interval (under max_submissions / halt latch)
    - log each unique result at most once
    - after the sim loop: drain in-flight results before stopping the worker
    - never touches gate/action/clock/replan/protocol
    """

    def __init__(
        self,
        worker: FiveStageShadowWorker,
        logger: FiveStageShadowLogger | None,
        *,
        interval: int = 50,
        max_submissions: int = 0,
        stop_submissions_on_pipeline_error: bool = True,
        shutdown_drain_timeout_s: float = 15.0,
        episode_id: str = "0",
        extract_rgb: Callable[[Any], Any] | None = None,
        on_unique_result: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.worker = worker
        self.logger = logger
        self.interval = max(1, int(interval))
        self.configured_max_submissions = int(max_submissions)
        self.stop_submissions_on_pipeline_error = bool(stop_submissions_on_pipeline_error)
        self.shutdown_drain_timeout_s = float(shutdown_drain_timeout_s)
        self.episode_id = str(episode_id)
        self._extract_rgb = extract_rgb
        self._on_unique_result = on_unique_result
        self.submitted_count = 0
        self.logged_result_count = 0
        self.last_logged_result_key: tuple[Any, ...] | None = None
        self.halt_submissions = False
        self.halt_reason = ""
        self._accepting_submissions = True
        self._closed = False
        # Shutdown / drain diagnostics
        self.shutdown_drain_started = False
        self.shutdown_drain_elapsed_s = 0.0
        self.shutdown_drain_complete = False
        self.pending_at_shutdown_start = 0
        self.pending_at_shutdown_end = 0
        self.processed_at_shutdown = 0
        self.logged_at_shutdown = 0
        self.worker_thread_alive_after_stop = False
        self.last_stop_status: dict[str, Any] = {}

    def _maybe_log(self, result: Mapping[str, Any] | None) -> bool:
        if result is None or self.logger is None:
            return False
        key = result_log_key(result)
        if key == self.last_logged_result_key:
            return False
        # Isolation proof only — does not mutate control fields.
        _ = shadow_control_decision(
            gate_decision="ALLOW",
            action=None,
            policy_clock_advance=True,
            replan_event=None,
            protocol_phase=None,
            shadow_result=result,
            enforcement_mode="shadow",
        )
        self.worker.assert_no_control_side_effects()
        self.logger.record(result)
        self.last_logged_result_key = key
        self.logged_result_count += 1
        if self._on_unique_result is not None:
            self._on_unique_result(result)
        return True

    def _apply_pipeline_halt(self, result: Mapping[str, Any] | None) -> None:
        if not self.stop_submissions_on_pipeline_error or result is None:
            return
        if result.get("pipeline_ok") is False:
            self.halt_submissions = True
            stage = str(result.get("pipeline_error_stage") or "")
            err = str(result.get("pipeline_error") or result.get("error") or "")
            self.halt_reason = f"pipeline_error:{stage}:{err}"[:300]

    def can_submit(self, step_counter: int) -> bool:
        if self._closed or not self._accepting_submissions:
            return False
        if self.halt_submissions:
            return False
        if step_counter % self.interval != 0:
            return False
        if self.configured_max_submissions > 0 and self.submitted_count >= self.configured_max_submissions:
            return False
        return True

    def on_step(self, obs: Any, step_counter: int) -> dict[str, Any]:
        """Poll first (may latch halt), then submit if still allowed."""
        latest = self.worker.latest_result()
        self._apply_pipeline_halt(latest)
        logged = self._maybe_log(latest)

        submitted = False
        if self.can_submit(step_counter):
            rgb = None
            if self._extract_rgb is not None:
                rgb = self._extract_rgb(obs)
            if rgb is not None:
                self.worker.submit(
                    rgb,
                    sim_step=step_counter,
                    episode_id=self.episode_id,
                )
                self.submitted_count += 1
                submitted = True

        return {
            "submitted": submitted,
            "logged": logged,
            "submitted_count": self.submitted_count,
            "logged_result_count": self.logged_result_count,
            "halt_submissions": self.halt_submissions,
            "halt_reason": self.halt_reason,
            "latest": latest,
        }

    def _drain_pending(self, *, drain_timeout_s: float) -> None:
        """Poll until processed/logged catch submitted, or timeout. No new submits."""
        processed = int(self.worker.metrics.processed_frames)
        pending = max(0, self.submitted_count - min(processed, self.logged_result_count))
        self.pending_at_shutdown_start = pending
        if processed >= self.submitted_count and self.logged_result_count >= self.submitted_count:
            self.shutdown_drain_complete = True
            self.pending_at_shutdown_end = 0
            self.shutdown_drain_elapsed_s = 0.0
            return

        self.shutdown_drain_started = True
        t0 = time.monotonic()
        deadline = t0 + max(0.0, float(drain_timeout_s))
        while time.monotonic() < deadline:
            latest = self.worker.latest_result()
            self._apply_pipeline_halt(latest)
            self._maybe_log(latest)
            processed = int(self.worker.metrics.processed_frames)
            if processed >= self.submitted_count and self.logged_result_count >= self.submitted_count:
                self.shutdown_drain_complete = True
                break
            time.sleep(0.05)
        self.shutdown_drain_elapsed_s = time.monotonic() - t0
        processed = int(self.worker.metrics.processed_frames)
        self.pending_at_shutdown_end = max(
            0, self.submitted_count - min(processed, self.logged_result_count)
        )
        if not self.shutdown_drain_complete:
            self.shutdown_drain_complete = False

    def shutdown(
        self,
        *,
        stop_timeout_s: float = 2.0,
        drain_timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """End-of-episode only: forbid submit → drain → stop worker → close logger."""
        if self._closed:
            return self.last_stop_status or {"already_closed": True}

        # 1) Forbid new submits (does not block the already-finished control loop).
        self._accepting_submissions = False
        self.halt_submissions = True
        if not self.halt_reason:
            self.halt_reason = "shutdown"

        # 2) Snapshot counts
        processed = int(self.worker.metrics.processed_frames)
        # One opportunistic poll/log before deciding to drain
        latest = self.worker.latest_result()
        self._apply_pipeline_halt(latest)
        self._maybe_log(latest)
        processed = int(self.worker.metrics.processed_frames)

        drain_s = (
            self.shutdown_drain_timeout_s if drain_timeout_s is None else float(drain_timeout_s)
        )
        self.shutdown_drain_timeout_s = float(drain_s)

        # 3) Drain if needed
        if processed < self.submitted_count or self.logged_result_count < self.submitted_count:
            self._drain_pending(drain_timeout_s=drain_s)
        else:
            self.pending_at_shutdown_start = 0
            self.pending_at_shutdown_end = 0
            self.shutdown_drain_complete = True
            self.shutdown_drain_elapsed_s = 0.0

        self.worker.assert_no_control_side_effects()

        # 4) Stop worker after drain (short join; do not pretend success if alive)
        stop_status = self.worker.stop(timeout_s=stop_timeout_s)
        self.last_stop_status = dict(stop_status)
        self.worker_thread_alive_after_stop = bool(stop_status.get("thread_alive"))

        # Final non-blocking poll in case completion landed during stop join
        latest = self.worker.latest_result()
        self._maybe_log(latest)

        self.processed_at_shutdown = int(self.worker.metrics.processed_frames)
        self.logged_at_shutdown = int(self.logged_result_count)
        self.pending_at_shutdown_end = max(
            0,
            self.submitted_count - min(self.processed_at_shutdown, self.logged_at_shutdown),
        )
        if (
            self.processed_at_shutdown >= self.submitted_count
            and self.logged_at_shutdown >= self.submitted_count
        ):
            self.shutdown_drain_complete = True

        summary_extra = {
            "leakage": self.worker.leakage.as_dict(),
            "submitted_count": self.submitted_count,
            "logged_result_count": self.logged_result_count,
            "configured_max_submissions": self.configured_max_submissions,
            "stop_submissions_on_pipeline_error": self.stop_submissions_on_pipeline_error,
            "halt_submissions": self.halt_submissions,
            "halt_reason": self.halt_reason,
            "stale_result_count": self.worker.metrics.stale_result_count,
            "stale_poll_count": self.worker.metrics.stale_poll_count,
            "shutdown_drain_started": self.shutdown_drain_started,
            "shutdown_drain_timeout_s": self.shutdown_drain_timeout_s,
            "shutdown_drain_elapsed_s": self.shutdown_drain_elapsed_s,
            "shutdown_drain_complete": self.shutdown_drain_complete,
            "pending_at_shutdown_start": self.pending_at_shutdown_start,
            "pending_at_shutdown_end": self.pending_at_shutdown_end,
            "processed_at_shutdown": self.processed_at_shutdown,
            "logged_at_shutdown": self.logged_at_shutdown,
            "worker_thread_alive_after_stop": self.worker_thread_alive_after_stop,
            "stop_status": self.last_stop_status,
        }

        # 5) Logger closes last — after all logging attempts
        if self.logger is not None:
            self.logger.flush_summary(summary_extra)
            self.logger.close()
        self._closed = True
        return summary_extra
