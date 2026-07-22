"""Strict TaskSemanticContext schema (enumerated; no answer leakage)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping

TASK_NAMES = frozenset({"pick_place", "unknown", "none"})
TASK_PHASES = frozenset(
    {"idle", "approach", "grasp", "lift", "transit", "place", "retreat", "unknown", "none"}
)
TASK_GOAL_TYPES = frozenset({"place_into_container", "unknown", "none"})
CONTAINER_IDS = frozenset({"container_a", "container_b", "unknown", "none"})
HELD_OBJECT_CLASSES = frozenset(
    {"industrial_part", "human_hand", "sphere", "unknown", "none"}
)
CONTEXT_SOURCES = frozenset(
    {
        "control_protocol",
        "scenario_protocol",
        "scene_config",
        "perception_confirmed",
        "unknown",
        "none",
    }
)
OCCUPIED_FLAGS = frozenset({"true", "false", "unknown", "none"})


def _norm_enum(value: Any, allowed: frozenset[str], *, default: str = "unknown") -> str:
    text = str(value if value is not None else default).strip().lower()
    if text in ("", "null", "nil"):
        text = default
    if text == "true":
        text = "true"
    if text == "false":
        text = "false"
    if text not in allowed:
        return default
    return text


@dataclass(frozen=True)
class TaskSemanticContext:
    """Structured task context for prompt v2 / fusion. Never carries risk answers."""

    task_name: str = "unknown"
    task_phase: str = "unknown"
    task_goal_type: str = "unknown"
    source_container: str = "unknown"
    target_container: str = "unknown"
    held_object_class: str = "unknown"
    transport_active: str = "false"  # true|false|unknown|none
    placement_target_occupied: str = "unknown"  # only when evidence-backed
    context_source: str = "unknown"
    context_sim_step: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TaskSemanticContext:
        d = dict(data or {})
        # Refuse answer leakage keys
        for banned in (
            "risk_type",
            "fused_risk_type",
            "recommended_action",
            "suggested_action",
            "risk_confidence",
        ):
            if banned in d:
                raise ValueError(f"TaskSemanticContext must not include answer field {banned!r}")
        return cls(
            task_name=_norm_enum(d.get("task_name"), TASK_NAMES),
            task_phase=_norm_enum(d.get("task_phase"), TASK_PHASES),
            task_goal_type=_norm_enum(d.get("task_goal_type"), TASK_GOAL_TYPES),
            source_container=_norm_enum(d.get("source_container"), CONTAINER_IDS),
            target_container=_norm_enum(d.get("target_container"), CONTAINER_IDS),
            held_object_class=_norm_enum(d.get("held_object_class"), HELD_OBJECT_CLASSES),
            transport_active=_norm_enum(d.get("transport_active"), OCCUPIED_FLAGS, default="false"),
            placement_target_occupied=_norm_enum(
                d.get("placement_target_occupied"), OCCUPIED_FLAGS, default="unknown"
            ),
            context_source=_norm_enum(d.get("context_source"), CONTEXT_SOURCES),
            context_sim_step=int(d.get("context_sim_step", -1)),
        )

    def provenance(self) -> dict[str, Any]:
        return {
            "context_source": self.context_source,
            "context_sim_step": self.context_sim_step,
            "fields": [f.name for f in fields(self)],
        }
