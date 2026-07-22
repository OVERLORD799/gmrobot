"""Semantic supervisor shadow bridge (V1-C0).

Reads five-stage results and decision-time geometry gate; emits advisory
logs only. Never mutates gate/action/clock/protocol/replan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from GMRobot.safety.semantic_supervisor import (
    GATE_ALLOW,
    SemanticAdvisoryDecision,
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
    advisory_input_from_shadow_row,
    normalize_gate,
)
from GMRobot.safety.semantic_supervisor_logger import SemanticSupervisorLogger

from .control_isolation import (
    SemanticLeakageCounters,
    control_decision_hash,
    validate_semantic_supervisor_shadow_flags,
)

__all__ = [
    "SemanticShadowBridge",
    "SemanticLeakageCounters",
    "control_decision_hash",
    "validate_semantic_supervisor_shadow_flags",
]


@dataclass
class SemanticShadowBridge:
    """Queue unique five-stage results; evaluate with decision-time geometry gate."""

    supervisor: SemanticSafetySupervisor
    logger: SemanticSupervisorLogger | None
    config: SemanticSupervisorConfig
    control_dt: float = 0.02
    episode_id: str = "0"
    leakage: SemanticLeakageCounters = field(default_factory=SemanticLeakageCounters)
    _pending: list[dict[str, Any]] = field(default_factory=list)
    _consumed_request_ids: set[str] = field(default_factory=set)
    advisory_count: int = 0
    last_control_hash: str = ""
    control_hash_mismatch_count: int = 0

    def enqueue_unique_result(self, result: Mapping[str, Any] | None) -> None:
        if result is None:
            return
        self._pending.append(dict(result))

    def pending_count(self) -> int:
        return len(self._pending)

    def flush(
        self,
        *,
        geometry_gate: Any,
        geometry_gate_reason: str = "",
        decision_sim_step: int,
        decision_time_s: float | None = None,
        current_speed_scale: float = 1.0,
        transport_phase: str = "",
        held_object: str = "",
        control_snapshot: Mapping[str, Any] | None = None,
    ) -> list[SemanticAdvisoryDecision]:
        """Evaluate pending unique results once with decision-time geometry.

        Never mutates control_snapshot. effective_control_gate always equals geometry.
        """
        if control_snapshot is not None:
            self.last_control_hash = control_decision_hash(
                gate_decision=control_snapshot.get("gate_decision", geometry_gate),
                action=control_snapshot.get("action"),
                should_advance=control_snapshot.get("should_advance"),
                protocol_phase=control_snapshot.get("protocol_phase"),
                replan_event=control_snapshot.get("replan_event"),
                task_progression=control_snapshot.get("task_progression"),
            )

        try:
            geo_norm = normalize_gate(geometry_gate)
        except Exception:  # noqa: BLE001
            geo_norm = GATE_ALLOW

        decisions: list[SemanticAdvisoryDecision] = []
        pending, self._pending = self._pending, []
        t_decision = (
            float(decision_time_s)
            if decision_time_s is not None
            else float(decision_sim_step) * float(self.control_dt)
        )

        for result in pending:
            rid = str(result.get("request_id") or "").strip()
            if rid and rid in self._consumed_request_ids:
                continue
            if rid:
                self._consumed_request_ids.add(rid)

            capture_step = int(
                result.get("sim_step", result.get("source_capture_sim_step", 0)) or 0
            )
            capture_time = float(capture_step) * float(self.control_dt)
            age = result.get("result_age_s")
            if age is None:
                completed = result.get("completed_at_s")
                if completed is not None:
                    age = max(0.0, t_decision - float(completed))
                else:
                    age = max(0.0, t_decision - capture_time)

            inp = advisory_input_from_shadow_row(
                result,
                episode_id=str(result.get("episode_id", self.episode_id)),
                sim_step=int(decision_sim_step),
                current_time_s=t_decision,
                current_geometry_gate=geometry_gate,
                result_age_s=float(age),
                synthetic=bool(result.get("synthetic", False)),
            )
            inp.current_geometry_gate = geometry_gate
            inp.current_geometry_reason = str(geometry_gate_reason or "")
            inp.current_speed_scale = float(current_speed_scale)
            inp.transport_phase = str(transport_phase or "")
            inp.held_object = str(held_object or "")
            inp.sim_step = int(decision_sim_step)
            inp.current_time_s = t_decision
            inp.result_age_s = float(age)

            decision = self.supervisor.evaluate(inp)
            evaluated = str(decision.requested_gate or "")
            effective_control = geo_norm

            audit = {
                "source_capture_sim_step": capture_step,
                "source_capture_time": capture_time,
                "result_completed_time": float(
                    result.get("completed_at_s") or (t_decision - float(age))
                ),
                "decision_sim_step": int(decision_sim_step),
                "decision_time": t_decision,
                "result_age_s": float(age),
                "geometry_gate_decision": geo_norm,
                "geometry_gate_reason": str(geometry_gate_reason or ""),
                "evaluated_semantic_gate": evaluated,
                "effective_control_gate": effective_control,
                "would_slow_down": bool(decision.would_slow),
                "control_decision_hash": self.last_control_hash,
            }
            if self.logger is not None:
                self.logger.log_decision(decision, audit=audit)
            self.advisory_count += 1
            decisions.append(decision)
            self.leakage.assert_all_zero()

        return decisions

    def summary(self) -> dict[str, Any]:
        return {
            "semantic_advisory_count": self.advisory_count,
            "semantic_leakage": self.leakage.as_dict(),
            "consumed_request_ids": len(self._consumed_request_ids),
            "pending_at_end": len(self._pending),
            "last_control_hash": self.last_control_hash,
            "control_hash_mismatch_count": self.control_hash_mismatch_count,
            "intentional_control_effect": False,
            "enforcement_mode": self.config.enforcement_mode,
        }

    def close(self) -> dict[str, Any]:
        log_summary: dict[str, Any] = {}
        if self.logger is not None:
            log_summary = self.logger.close()
        out = self.summary()
        out["logger_summary"] = log_summary
        self.leakage.assert_all_zero()
        return out
