"""Control isolation helpers for semantic supervisor shadow (no Isaac / no safety import)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


def canonicalize_control_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float, str)):
        if isinstance(value, float):
            return round(float(value), 9)
        return value
    if isinstance(value, (list, tuple)):
        return [canonicalize_control_value(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): canonicalize_control_value(value[k]) for k in sorted(value.keys(), key=str)}
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return canonicalize_control_value(tolist())
        except Exception:  # noqa: BLE001
            pass
    return repr(value)


def control_decision_hash(
    *,
    gate_decision: Any,
    action: Any,
    should_advance: Any,
    protocol_phase: Any,
    replan_event: Any,
    task_progression: Any = None,
) -> str:
    payload = {
        "gate_decision": canonicalize_control_value(gate_decision),
        "action": canonicalize_control_value(action),
        "should_advance": canonicalize_control_value(should_advance),
        "protocol_phase": canonicalize_control_value(protocol_phase),
        "replan_event": canonicalize_control_value(replan_event),
        "task_progression": canonicalize_control_value(task_progression),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class SemanticLeakageCounters:
    semantic_gate_apply_count: int = 0
    semantic_action_apply_count: int = 0
    semantic_clock_block_count: int = 0
    semantic_replan_apply_count: int = 0
    semantic_protocol_mutation_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "semantic_gate_apply_count": int(self.semantic_gate_apply_count),
            "semantic_action_apply_count": int(self.semantic_action_apply_count),
            "semantic_clock_block_count": int(self.semantic_clock_block_count),
            "semantic_replan_apply_count": int(self.semantic_replan_apply_count),
            "semantic_protocol_mutation_count": int(self.semantic_protocol_mutation_count),
        }

    def assert_all_zero(self) -> None:
        bad = {k: v for k, v in self.as_dict().items() if v != 0}
        if bad:
            raise AssertionError(f"semantic leakage non-zero: {bad}")


def validate_semantic_supervisor_shadow_flags(
    *,
    enable_semantic_supervisor_shadow: bool,
    enable_five_stage_shadow: bool,
    enable_safety: bool,
    enable_vlm: bool = False,
    enable_replan: bool = False,
    enable_vlm_grasp_supervisor: bool = False,
    enforcement_mode: str = "shadow",
) -> None:
    """Startup validation. Raises RuntimeError on illegal combinations (no silent degrade)."""
    if not enable_semantic_supervisor_shadow:
        return
    if not enable_five_stage_shadow:
        raise RuntimeError(
            "--enable_semantic_supervisor_shadow requires --enable_five_stage_shadow"
        )
    if not enable_safety:
        raise RuntimeError(
            "--enable_semantic_supervisor_shadow requires --enable_safety"
        )
    if str(enforcement_mode or "").strip().lower() != "shadow":
        raise RuntimeError(
            "semantic supervisor online wiring requires enforcement_mode=shadow"
        )
    if enable_vlm:
        raise RuntimeError(
            "--enable_semantic_supervisor_shadow is mutually exclusive with --enable_vlm "
            "(legacy live VLM path)"
        )
    if enable_replan:
        raise RuntimeError(
            "--enable_semantic_supervisor_shadow is mutually exclusive with --enable_replan "
            "(legacy live replan path)"
        )
    if enable_vlm_grasp_supervisor:
        raise RuntimeError(
            "--enable_semantic_supervisor_shadow is mutually exclusive with "
            "--enable_vlm_grasp_supervisor"
        )
