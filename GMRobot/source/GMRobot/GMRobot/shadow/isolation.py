"""Pure shadow isolation helpers (no Isaac). Control path must never mutate."""

from __future__ import annotations

from typing import Any, Mapping


def shadow_control_decision(
    *,
    gate_decision: Any,
    action: Any,
    policy_clock_advance: bool,
    replan_event: str | None,
    protocol_phase: str | None,
    shadow_result: Mapping[str, Any] | None,
    enforcement_mode: str = "shadow",
) -> dict[str, Any]:
    """Return unchanged control fields plus would_* audit when in shadow mode.

    Live enforcement is intentionally unsupported in V0-A.
    """
    if enforcement_mode != "shadow":
        raise ValueError(
            "V0-A only supports enforcement_mode='shadow'; live enforcement disabled"
        )

    return {
        "gate_decision": gate_decision,
        "action": action,
        "policy_clock_advance": policy_clock_advance,
        "replan_event": replan_event,
        "protocol_phase": protocol_phase,
        "would_stop": bool((shadow_result or {}).get("would_stop")),
        "would_replan": bool((shadow_result or {}).get("would_replan")),
        "shadow_suggested_action": str(
            (shadow_result or {}).get("shadow_suggested_action")
            or (shadow_result or {}).get("suggested_action")
            or ""
        ),
        "leakage": {
            "shadow_gate_override_count": 0,
            "shadow_action_override_count": 0,
            "shadow_clock_blocked_steps": 0,
            "shadow_replan_applied_count": 0,
            "shadow_protocol_override_count": 0,
        },
    }
