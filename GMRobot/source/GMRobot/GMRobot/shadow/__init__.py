"""Five-stage VLM/perception shadow package (V0-A)."""

from .config_resolve import resolve_component_config_path, resolve_shadow_client_configs
from .control_isolation import (
    SemanticLeakageCounters,
    control_decision_hash,
    validate_semantic_supervisor_shadow_flags,
)
from .five_stage_worker import FiveStageShadowWorker, ShadowLeakageCounters, ShadowMetrics
from .isolation import shadow_control_decision
from .logger import FiveStageShadowLogger
from .scheduler import FiveStageShadowScheduler, result_log_key

__all__ = [
    "FiveStageShadowWorker",
    "FiveStageShadowLogger",
    "FiveStageShadowScheduler",
    "ShadowLeakageCounters",
    "ShadowMetrics",
    "SemanticLeakageCounters",
    "SemanticShadowBridge",
    "control_decision_hash",
    "validate_semantic_supervisor_shadow_flags",
    "result_log_key",
    "resolve_component_config_path",
    "resolve_shadow_client_configs",
    "shadow_control_decision",
]


def __getattr__(name: str):
    # Lazy export: avoid importing semantic_bridge (and GMRobot.safety) on every
    # `from shadow import ...` used by offline five-stage unit tests.
    if name == "SemanticShadowBridge":
        from .semantic_bridge import SemanticShadowBridge as _SemanticShadowBridge

        return _SemanticShadowBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
