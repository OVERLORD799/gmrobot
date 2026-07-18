"""Motion Replan package (Phase 3.5 / 4a)."""

from .executor import GeometryReplanV0, ReplanRuntimeState
from .route_conflict import (
    RouteConflictResult,
    build_proactive_route_replan_request,
    evaluate_route_conflict,
)
from .strategy import (
    DetourPlan,
    DetourStrategy,
    select_detour_strategy,
    should_defer_for_held_critical,
)
from .triggers import (
    L1WarnReplanTrigger,
    ReplanTriggerConfig,
    enrich_gate_metadata_from_envelope,
    enrich_gate_metadata_from_perception_track,
)
from .types import MotionReplanExecutor, ReplanHint, ReplanRequest, ReplanResult

__all__ = [
    "RouteConflictResult",
    "build_proactive_route_replan_request",
    "evaluate_route_conflict",
    "DetourPlan",
    "DetourStrategy",
    "GeometryReplanV0",
    "L1WarnReplanTrigger",
    "MotionReplanExecutor",
    "ReplanHint",
    "ReplanRequest",
    "ReplanResult",
    "ReplanRuntimeState",
    "ReplanTriggerConfig",
    "enrich_gate_metadata_from_envelope",
    "enrich_gate_metadata_from_perception_track",
    "select_detour_strategy",
    "should_defer_for_held_critical",
]
