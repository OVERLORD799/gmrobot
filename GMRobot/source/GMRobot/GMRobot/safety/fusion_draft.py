"""Draft Tier fusion for Layer 2 shadow logging (offline +旁路 only).

Phase 2 rule (documented, not applied to live gate unless explicitly enabled):

    would_fuse = max_severity(g_rule, g_ml)

where STOP > SLOW_DOWN > ALLOW.  Tier annotations are log-only metadata:

- **Tier0 (GT proxy)**: if ``g_ground_truth == STOP``, records ``tier0_would_stop=True``
  (offline audit; shadow agent does not use GT for fusion).
- **Warn zone**: ``g_rule == SLOW_DOWN`` or distance in ``(hard_stop, warn]`` band.
- **ML suggestion**: ``g_ml`` from ``SafetyPredictor``; confidence = P(predicted class).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .types import GATE_ALLOW, GATE_SEVERITY, GATE_SLOW_DOWN, GATE_STOP, GateDecision

# Convenience aliases for local brevity (these are the same ints as GATE_*).
_STOP = GATE_STOP
_SLOW = GATE_SLOW_DOWN
_ALLOW = GATE_ALLOW

_SEVERITY = GATE_SEVERITY


def max_severity(*decisions: int) -> int:
    """Return the most conservative gate decision.

    Raises ValueError if no decisions are given or if any decision has an
    unrecognised integer value (not 0, 1, or 2).
    """
    if not decisions:
        raise ValueError("max_severity requires at least one decision")
    best = _ALLOW
    best_rank = -1
    for d in decisions:
        rank = _SEVERITY.get(int(d))
        if rank is None:
            raise ValueError(
                f"Unrecognised gate decision value: {d}. "
                f"Expected one of {list(_SEVERITY.keys())}."
            )
        if rank > best_rank:
            best_rank = rank
            best = int(d)
    return best


def in_warn_zone(
    g_rule: int,
    dist_ee_human: float | None,
    *,
    safe_dist_hard_stop: float,
    safe_dist_warn: float,
) -> bool:
    """True when rule says SLOW_DOWN or EE–hand distance is in the caution band."""
    if int(g_rule) == _SLOW:
        return True
    if dist_ee_human is None:
        return False
    return safe_dist_hard_stop < float(dist_ee_human) <= safe_dist_warn


@dataclass(frozen=True)
class FusionDraftResult:
    g_ml: int
    g_ml_confidence: float | None
    would_fuse: int
    tier0_gt_would_stop: bool
    in_warn_zone: bool

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "g_ml": self.g_ml,
            "g_ml_confidence": (
                "" if self.g_ml_confidence is None else float(self.g_ml_confidence)
            ),
            "would_fuse": self.would_fuse,
            "tier0_gt_would_stop": int(self.tier0_gt_would_stop),
            "fusion_in_warn_zone": int(self.in_warn_zone),
        }


def compute_would_fuse(g_rule: int, g_ml: int) -> int:
    """Phase 2 draft OR-fusion: ``g_rule ∨ g_ml`` by severity.

    Clamps inputs to the valid range [0, 2] so that unexpected ML outputs
    (e.g. after model retraining) cannot crash max_severity with ValueError.
    """
    g_rule_safe = max(0, min(2, int(g_rule)))
    g_ml_safe = max(0, min(2, int(g_ml)))
    return max_severity(g_rule_safe, g_ml_safe)


def compute_fusion_draft(
    *,
    g_rule: int,
    g_ml: int,
    g_ml_confidence: float | None = None,
    g_ground_truth: int | None = None,
    dist_ee_human: float | None = None,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
) -> FusionDraftResult:
    """Compute shadow fusion fields for one control step."""
    tier0_gt_would_stop = (
        g_ground_truth is not None and int(g_ground_truth) == _STOP
    )
    warn = in_warn_zone(
        g_rule,
        dist_ee_human,
        safe_dist_hard_stop=safe_dist_hard_stop,
        safe_dist_warn=safe_dist_warn,
    )
    would_fuse = compute_would_fuse(g_rule, g_ml)
    return FusionDraftResult(
        g_ml=int(g_ml),
        g_ml_confidence=g_ml_confidence,
        would_fuse=would_fuse,
        tier0_gt_would_stop=tier0_gt_would_stop,
        in_warn_zone=warn,
    )


def row_for_predictor(
    state_log: Mapping[str, Any],
    *,
    dist_ee_human: float | None = None,
    ttc: float | None = None,
    envelope_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Layer 2 feature row from SafetyState log fields + rule metadata."""
    row = dict(state_log)
    if dist_ee_human is not None:
        row["dist_ee_human"] = dist_ee_human
    if ttc is not None:
        row["ttc"] = ttc
    if envelope_fields:
        row.update(envelope_fields)
    return row
