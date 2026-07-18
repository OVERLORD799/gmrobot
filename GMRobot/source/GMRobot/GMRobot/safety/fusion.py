"""Tier-based Layer 2 fusion (Phase 2+).

Replaces pure OR-fusion for online gate and shadow logging:

- **Tier0**: ``dist < safe_dist_hard_stop`` → STOP (non-overridable hard collision).
- **Tier1**: ``g_rule == STOP`` in static warn zone → if ``g_ml == ALLOW`` → ALLOW.
- **Tier2**: ``g_rule == SLOW_DOWN`` → ML may downgrade to ALLOW; else SLOW_DOWN.
- **No upgrade**: when ``g_rule == ALLOW``, output stays ALLOW (``g_ml`` cannot
  escalate to STOP/SLOW_DOWN).

Legacy OR-fusion ``max_severity(g_rule, g_ml)`` is retained as ``would_fuse_or`` for
shadow comparison only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .fusion_draft import compute_would_fuse, in_warn_zone, row_for_predictor
from .types import GATE_ALLOW, GATE_SLOW_DOWN, GATE_STOP, GateDecision

# Convenience aliases for local brevity.
_STOP = GATE_STOP
_SLOW = GATE_SLOW_DOWN
_ALLOW = GATE_ALLOW


@dataclass(frozen=True)
class FusionConfig:
    """Tier fusion parameters (loaded from configs/safety_fusion.yaml)."""

    ml_override_theta: float = 0.65
    safe_dist_hard_stop: float = 0.13
    safe_dist_warn: float = 0.16  # Match Layer 1 code default (config.py StaticSafetySubConfig)

    # ml_override_theta: Tier1 max P(STOP) to still downgrade static STOP → ALLOW.

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FusionConfig:
        tier = data.get("tier_fusion", data)
        return cls(
            ml_override_theta=float(tier.get("ml_override_theta", 0.65)),
            safe_dist_hard_stop=float(tier.get("safe_dist_hard_stop", 0.13)),
            safe_dist_warn=float(tier.get("safe_dist_warn", 0.16)),
        )


def load_fusion_config(path: str | Path | None = None) -> FusionConfig:
    if path is None:
        from .config import _default_config_path
        path = _default_config_path("safety_fusion.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return FusionConfig.from_dict(data)


@dataclass(frozen=True)
class FusionResult:
    g_ml: int
    g_ml_confidence: float | None
    would_fuse: int
    would_fuse_or: int
    fusion_tier: int | None
    tier0_would_stop: bool
    in_warn_zone: bool

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "g_ml": self.g_ml,
            "g_ml_confidence": (
                "" if self.g_ml_confidence is None else float(self.g_ml_confidence)
            ),
            "would_fuse": self.would_fuse,
            "would_fuse_or": self.would_fuse_or,
            "fusion_tier": "" if self.fusion_tier is None else int(self.fusion_tier),
            "tier0_would_stop": int(self.tier0_would_stop),
            "fusion_in_warn_zone": int(self.in_warn_zone),
        }


def compute_tier_fusion(
    *,
    g_rule: int,
    g_ml: int,
    g_ml_confidence: float | None = None,
    dist_ee_human: float | None = None,
    dist_min_envelope: float | None = None,
    envelope_gating: bool = False,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
    ml_override_theta: float = 0.65,
    trigger_rule: str = "",
) -> tuple[int, int | None]:
    """Return (would_fuse_tier, fusion_tier)."""
    tier0_dist = _tier0_distance(
        dist_ee_human,
        dist_min_envelope,
        envelope_gating=envelope_gating,
    )
    would_fuse_or = compute_would_fuse(int(g_rule), int(g_ml))
    warn = in_warn_zone(
        g_rule,
        tier0_dist,
        safe_dist_hard_stop=safe_dist_hard_stop,
        safe_dist_warn=safe_dist_warn,
    )

    # Tier0: hard collision envelope — never overridden by ML.
    # The tier0_dist is the MINIMUM distance across ALL arm links + EE + held
    # box primitives.  A value below safe_dist_hard_stop means at least one
    # robot body part is dangerously close to the hand — this is always a
    # hard STOP regardless of where the EE alone is.  We intentionally do NOT
    # apply the rule_engine L110 guard here (that guard only gates SLOW_DOWN,
    # not STOP).  Tier0 means "something will collide" — there is no safe
    # bypass.
    if tier0_dist is not None and float(tier0_dist) < safe_dist_hard_stop:
        return _STOP, 0

    # Tier2: explicit slow-down from rule — ML may downgrade to ALLOW.
    if int(g_rule) == _SLOW:
        if int(g_ml) == _ALLOW:
            return _ALLOW, 1
        return _SLOW, 2

    # Tier1: static STOP beyond true collision — ML may downgrade to ALLOW.
    if int(g_rule) == _STOP and _is_tier1_eligible(
        trigger_rule,
        tier0_dist,
        safe_dist_hard_stop,
        safe_dist_warn,
    ):
        # Static bubble (e.g. 0.25 m preset) can fire while EE is beyond warn;
        # online trajectories then see g_ml P(STOP)≈0.70 and block ML downgrade.
        # F2 fix: only bypass ML when ML also agrees the situation is safe.
        # A VLM-detected anomaly with g_ml=STOP must not be silently overridden.
        #
        # F7 fix: when envelope gating is active and the envelope distance is
        # within the warn zone (≤ safe_dist_warn), do NOT apply the wide-bubble
        # bypass — the actual collision risk is on an arm link, not the EE.
        # Fall through to the normal ML-override logic instead.
        _wide_bubble = (
            trigger_rule == "static"
            and dist_ee_human is not None
            and float(dist_ee_human) > safe_dist_warn
        )
        _envelope_in_warn = (
            envelope_gating
            and dist_min_envelope is not None
            and float(dist_min_envelope) <= safe_dist_warn
        )
        if _wide_bubble and not _envelope_in_warn:
            if int(g_ml) == _ALLOW:
                return _ALLOW, 1
            # ML disagrees — fall through to ML override logic below.
        if int(g_ml) == _ALLOW:
            return _ALLOW, 1
        if (
            int(g_ml) == _STOP
            and g_ml_confidence is not None
            and float(g_ml_confidence) < ml_override_theta
        ):
            return _ALLOW, 1
        return _STOP, 1

    # Non-warn STOP (TTC, workspace, static hard) — keep conservative.
    if int(g_rule) == _STOP:
        return _STOP, None

    # ML may downgrade g_rule but must not upgrade severity (no ALLOW→STOP via g_ml).
    if int(g_rule) == _ALLOW:
        return _ALLOW, None

    return would_fuse_or, None


def _tier0_distance(
    dist_ee_human: float | None,
    dist_min_envelope: float | None,
    *,
    envelope_gating: bool,
) -> float | None:
    """Distance for Tier0 / warn-zone checks; envelope min when gating is on."""
    if envelope_gating and dist_min_envelope is not None:
        return float(dist_min_envelope)
    if dist_ee_human is not None:
        return float(dist_ee_human)
    return None


def _is_tier1_eligible(
    trigger_rule: str,
    tier0_dist: float | None,
    safe_dist_hard_stop: float,
    safe_dist_warn: float,
) -> bool:
    """Static rule STOP that is not a Tier0 hard collision (ML may override).

    ``tier0_dist`` is the distance used for Tier0 gating: ``dist_min_envelope``
    under envelope gating, ``dist_ee_human`` otherwise (see ``_tier0_distance``).
    """
    if trigger_rule not in ("static",):
        return False
    if tier0_dist is None:
        return False  # Conservative: don't override STOP when distance is unmeasured
    dist = float(tier0_dist)
    if dist < safe_dist_hard_stop:
        return False
    if safe_dist_hard_stop < dist <= safe_dist_warn:
        return True
    # Rule threshold wider than fusion hard_stop (e.g. stress preset 0.25 m).
    return dist > safe_dist_warn


def compute_fusion(
    *,
    g_rule: int,
    g_ml: int,
    g_ml_confidence: float | None = None,
    g_ground_truth: int | None = None,
    dist_ee_human: float | None = None,
    dist_min_envelope: float | None = None,
    envelope_gating: bool = False,
    safe_dist_hard_stop: float = 0.13,
    safe_dist_warn: float = 0.16,
    ml_override_theta: float = 0.65,
    trigger_rule: str = "",
) -> FusionResult:
    """Compute tier fusion + shadow OR baseline for one control step."""
    tier0_dist = _tier0_distance(
        dist_ee_human,
        dist_min_envelope,
        envelope_gating=envelope_gating,
    )
    tier0_would_stop = (
        g_ground_truth is not None and int(g_ground_truth) == _STOP
    ) or (
        tier0_dist is not None and float(tier0_dist) < safe_dist_hard_stop
    )
    warn = in_warn_zone(
        g_rule,
        tier0_dist,
        safe_dist_hard_stop=safe_dist_hard_stop,
        safe_dist_warn=safe_dist_warn,
    )
    would_fuse_or = compute_would_fuse(int(g_rule), int(g_ml))
    would_fuse, fusion_tier = compute_tier_fusion(
        g_rule=g_rule,
        g_ml=g_ml,
        g_ml_confidence=g_ml_confidence,
        dist_ee_human=dist_ee_human,
        dist_min_envelope=dist_min_envelope,
        envelope_gating=envelope_gating,
        safe_dist_hard_stop=safe_dist_hard_stop,
        safe_dist_warn=safe_dist_warn,
        ml_override_theta=ml_override_theta,
        trigger_rule=trigger_rule,
    )
    return FusionResult(
        g_ml=int(g_ml),
        g_ml_confidence=g_ml_confidence,
        would_fuse=would_fuse,
        would_fuse_or=would_fuse_or,
        fusion_tier=fusion_tier,
        tier0_would_stop=tier0_would_stop,
        in_warn_zone=warn,
    )


__all__ = [
    "FusionConfig",
    "FusionResult",
    "compute_fusion",
    "compute_tier_fusion",
    "load_fusion_config",
    "row_for_predictor",
]
