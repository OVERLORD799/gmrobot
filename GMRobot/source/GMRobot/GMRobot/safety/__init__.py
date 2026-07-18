"""Layer 1 rule-based safety gating for GM-SafePick."""

from .config import EnvelopeConfig, SafetyConfig, load_safety_config
from .envelope import (
    EnvelopeEvaluator,
    EnvelopeResult,
    compute_envelope_audit,
    compute_min_dist,
)
from .gate import SafetyGate
from .ground_truth import (
    compute_ground_truth_from_state,
    compute_ground_truth_v12_from_envelope,
    episode_outcome_from_ground_truth,
)
from .gt_branches import GtBranchResult, compute_gt_branches
from .human_motion import HumanMotionController
from .logger import SafetyLogger
from .metrics import SafetyMetrics
from .rule_engine import RuleEngine
from .types import (
    GATE_ALLOW,
    GATE_SLOW_DOWN,
    GATE_STOP,
    GATE_SEVERITY,
    GateDecision,
    GateResult,
    HELD_CRITICAL_STOP_M,
    SafetyState,
)

__all__ = [
    "EnvelopeConfig",
    "EnvelopeEvaluator",
    "EnvelopeResult",
    "GATE_ALLOW",
    "GATE_SLOW_DOWN",
    "GATE_STOP",
    "GATE_SEVERITY",
    "GateDecision",
    "GateResult",
    "HELD_CRITICAL_STOP_M",
    "HumanMotionController",
    "RuleEngine",
    "SafetyConfig",
    "SafetyGate",
    "SafetyLogger",
    "SafetyMetrics",
    "SafetyState",
    "compute_envelope_audit",
    "compute_ground_truth_from_state",
    "compute_ground_truth_v12_from_envelope",
    "compute_gt_branches",
    "compute_min_dist",
    "episode_outcome_from_ground_truth",
    "GtBranchResult",
    "load_safety_config",
]
