"""Pure helpers for per-part virtual-hand protocol and replan attribution.

Testable without Isaac Sim.  Used by ``scripts/run_phase3.py`` and offline
event-CSV recomputation.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

# Structured geometry / distance / TTC / held-envelope rules that may count
# toward disturbance-attributed replan.  Workspace boundary is excluded.
GEOMETRY_REPLAN_RULES = frozenset({
    "ttc",
    "tier0",
    "warn",
    "static",
    "dynamic",
    "distance",
    "envelope",
    "surface",
    "l1_warn",
    "l1_ttc",
    # B1 paper path: TRANSIT held-object hard stop → immediate replan.
    "held_critical",
    "held_critical_early",
})

# B2 dynamic proactive rules (GMRobot canonical — not held_critical / static).
B2_PROACTIVE_TRIGGER_RULES = frozenset({"ttc", "ttc_forecast"})


def is_b2_proactive_trigger_rule(rule: str) -> bool:
    """True for TTC / forecast replan rules that count toward B2 proactive."""
    return (rule or "").strip().lower() in B2_PROACTIVE_TRIGGER_RULES


def is_held_critical_trigger_rule(rule: str) -> bool:
    r = (rule or "").strip().lower()
    return r in ("held_critical", "held_critical_early")


def snapshot_parts_placed(
    *,
    success: bool,
    parts_placed: int,
    total_parts: int,
) -> int:
    """Success-aware parts count for final CSV / JSONL."""
    return int(total_parts) if success else int(parts_placed)


def is_geometry_replan_rule(rule: str) -> bool:
    """Return True if *rule* is a structured distance/TTC/geometry trigger."""
    r = (rule or "").strip().lower()
    if not r:
        return False
    if r in GEOMETRY_REPLAN_RULES:
        return True
    # Allow compound names like "ttc_warn" / "l1_warn_sustained".
    return any(tok in r for tok in GEOMETRY_REPLAN_RULES)


def protocol_retreat_transition(
    prev_phase: str,
    cur_phase: str,
    retreated: bool,
    *,
    prefer_replan: bool = False,
    timed_out: bool = False,
    attempt_already_retreated: bool = False,
) -> tuple[bool, bool]:
    """Update retreated latch from a protocol phase edge (backup source).

    Returns
    -------
    (new_retreated, retreat_event_this_step)

    Primary retreat in B1 is replan-applied → ``on_replan()``.  Protocol
    edges are a backup: ``TRANSIT/PLACE → RESET``.  Cleared on
    ``RESET → PICK`` or any transition into ``TRANSIT``.

    When *prefer_replan* is True, ``TRANSIT → RESET`` only emits a retreat
    event on an actual phase timeout (deadlock fallback).  Natural
    ``PLACE → RESET`` still retreats if this attempt has no retreat yet.
    Duplicate edges are suppressed when the attempt already retreated.
    """
    prev = (prev_phase or "").lower()
    cur = (cur_phase or "").lower()

    # Backup retreat edges (timeout / natural stage advance into RESET).
    if prev in ("transit", "place") and cur == "reset":
        if retreated or attempt_already_retreated:
            return True, False  # already retreated — no duplicate edge
        if prefer_replan:
            # Replan-primary B1: only timeout-forced TRANSIT→RESET is a
            # backup retreat.  Natural PLACE→RESET / non-timeout TRANSIT→RESET
            # must not steal the attempt's retreat edge from replan-apply.
            if prev == "transit" and timed_out:
                return True, True
            return False, False
        return True, True

    # Clear latch so the next TRANSIT can form a new disturbance attempt.
    if retreated and (
        (prev == "reset" and cur == "pick")
        or (cur == "transit" and prev in ("reset", "pick", "place", ""))
    ):
        return False, False

    return bool(retreated), False


def find_open_attempt_id(recoveries: dict[int, "AttemptRecovery"]) -> int:
    """Return the newest attempt with retreat but no redeploy, else 0."""
    open_ids = [
        aid for aid, r in recoveries.items()
        if r.retreat_step >= 0 and r.redeploy_step < 0
    ]
    return max(open_ids) if open_ids else 0


def attempt_needs_canonical_redeploy(
    recoveries: dict[int, "AttemptRecovery"],
    attempt_id: int,
) -> bool:
    """True iff *attempt_id* has retreat but no redeploy yet (canonical slot open)."""
    aid = int(attempt_id)
    if aid <= 0:
        return False
    rec = recoveries.get(aid)
    if rec is None:
        return False
    return rec.retreat_step >= 0 and rec.redeploy_step < 0


def dynamic_sweep_redeploy_edge(
    lifecycle_was_retreating: bool,
    lifecycle_is_retreating: bool,
    *,
    already_emitted: bool = False,
) -> bool:
    """True on the canonical B2 recovery edge: lifecycle RETREATING→not.

    Must be driven by *lifecycle* state, not the protocol retreated latch.
    ``protocol_retreat_transition(..., attempt_already_retreated=True)`` may
    re-assert the latch on PLACE→RESET; that must not emit a second redeploy.
    """
    if already_emitted:
        return False
    return bool(lifecycle_was_retreating) and not bool(lifecycle_is_retreating)


def resolve_effective_gate_name(
    evaluated_gate_name: str | None,
    enforcement_mode: str,
) -> str | None:
    """Map evaluated gate → control-effective gate.

    *active* / *off*: effective == evaluated.
    *shadow*: effective is always ALLOW so evaluation cannot freeze the
    UR10e policy clock or modify commanded actions.
    """
    if evaluated_gate_name is None:
        return None
    mode = (enforcement_mode or "active").lower()
    if mode == "shadow":
        return "ALLOW"
    return str(evaluated_gate_name)


def policy_clock_should_advance(
    *,
    effective_gate_name: str | None,
    grasp_rewound: bool = False,
    replan_force_advance: bool = False,
) -> bool:
    """Whether the UR10e stage clock may advance this step.

    ``effective_gate_name`` must already be shadow-isolated (ALLOW under
    shadow).  Grasp rewind owns the clock for that step.
    """
    if grasp_rewound:
        return False
    if effective_gate_name is None:
        return True
    if effective_gate_name == "ALLOW":
        return True
    if replan_force_advance:
        return True
    return False


def validate_attempt_recoveries(
    recoveries: Iterable["AttemptRecovery"],
    *,
    task_completed: bool = False,
) -> list[str]:
    """Return human-readable invariant violations for attempt recovery rows."""
    errors: list[str] = []
    rows = list(recoveries)
    retreat_n = sum(1 for r in rows if r.retreat_step >= 0)
    recovered_n = sum(1 for r in rows if r.recovered)
    if recovered_n > retreat_n:
        errors.append(
            f"recovered_attempt_count={recovered_n} > retreat_attempt_count={retreat_n}"
        )
    for r in rows:
        if r.recovered and r.redeploy_step < 0 and not r.terminal_success:
            errors.append(
                f"attempt {r.attempt_id}: recovered=True without redeploy_step"
            )
        if r.terminal_success and not task_completed and r.redeploy_step < 0:
            # terminal_success is only valid when the episode completed.
            errors.append(
                f"attempt {r.attempt_id}: terminal_success without task_completed"
            )
    return errors

@dataclass
class ReplanAttribution:
    """Immutable attribution captured at the replan *trigger* step."""

    attempt_id: int
    trigger_rule: str
    trigger_source: str
    is_geometry_related: bool
    trigger_step: int = -1

    @classmethod
    def from_trigger(
        cls,
        *,
        attempt_id: int,
        trigger_rule: str,
        trigger_source: str,
        trigger_step: int = -1,
    ) -> "ReplanAttribution":
        return cls(
            attempt_id=int(attempt_id),
            trigger_rule=str(trigger_rule or ""),
            trigger_source=str(trigger_source or ""),
            is_geometry_related=is_geometry_replan_rule(trigger_rule),
            trigger_step=int(trigger_step),
        )

    def counts_as_disturbance_replan(self, disturbance_source: str = "") -> bool:
        """Whether a successful apply should increment ``d_replan_caused``."""
        if self.attempt_id <= 0:
            return False
        if not self.is_geometry_related:
            return False
        if not self.trigger_source:
            return False
        # Exclude non-disturbance trigger sources (workspace boundary / none).
        # Note: trigger_rule may be "held_critical"; trigger_source remains the
        # disturbance actor (e.g. scripted_virtual_hand).
        if self.trigger_source in ("workspace", "none"):
            return False
        if disturbance_source and self.trigger_source != disturbance_source:
            return False
        return True


def recompute_d_replan_caused_from_events(
    events: Iterable[dict],
    *,
    disturbance_source: str = "scripted_virtual_hand",
) -> int:
    """Offline recompute of ``d_replan_caused`` from an events CSV.

    Uses trigger-step attribution consumed at apply — does **not** require
    a live ``disturbance_active`` window at apply time.
    """
    pending: dict[int, ReplanAttribution] = {}
    counted_event_ids: set[int] = set()
    d_replan = 0

    for row in events:
        et = (row.get("event_type") or "").strip().lower()
        try:
            attempt_id = int(row.get("attempt_id") or 0)
        except ValueError:
            attempt_id = 0
        rule = row.get("trigger_rule") or ""
        source = row.get("trigger_source") or ""
        try:
            step = int(row.get("sim_step") or -1)
        except ValueError:
            step = -1

        if et == "trigger":
            pending[attempt_id] = ReplanAttribution.from_trigger(
                attempt_id=attempt_id,
                trigger_rule=rule,
                trigger_source=source,
                trigger_step=step,
            )
        elif et == "applied":
            attr = pending.pop(attempt_id, None)
            if attr is None:
                attr = ReplanAttribution.from_trigger(
                    attempt_id=attempt_id,
                    trigger_rule=rule,
                    trigger_source=source,
                    trigger_step=step,
                )
            try:
                event_id = int(row.get("event_id") or 0)
            except ValueError:
                event_id = 0
            if event_id <= 0 or event_id in counted_event_ids:
                continue
            if attr.counts_as_disturbance_replan(disturbance_source):
                d_replan += 1
                counted_event_ids.add(event_id)
    return d_replan


def recompute_d_replan_caused_from_csv(
    path: str,
    *,
    disturbance_source: str = "scripted_virtual_hand",
) -> int:
    with open(path, newline="") as f:
        return recompute_d_replan_caused_from_events(
            csv.DictReader(f),
            disturbance_source=disturbance_source,
        )


def resolve_per_part_attractor(
    *,
    phase: str,
    protocol_attractor_xy: Optional[np.ndarray],
    head_xy: np.ndarray,
    ee_xy: np.ndarray,
) -> np.ndarray:
    """Choose virtual-hand attractor for a per-part protocol step."""
    phase_l = (phase or "").lower()
    if phase_l == "transit":
        if protocol_attractor_xy is not None:
            return np.asarray(protocol_attractor_xy, dtype=np.float32).reshape(2).copy()
        return np.array([0.65, 0.0], dtype=np.float32)
    if phase_l in ("pick", "place"):
        if protocol_attractor_xy is not None:
            return np.asarray(protocol_attractor_xy, dtype=np.float32).reshape(2).copy()
        return np.asarray(ee_xy, dtype=np.float32).reshape(2).copy()
    return np.asarray(head_xy, dtype=np.float32).reshape(2).copy()


def per_part_radius(
    phase: str,
    *,
    transit_radius: float | None = None,
    pick_place_radius: float | None = None,
    reset_radius: float | None = None,
    transit_proxy_radius: float | None = None,
    pick_place_proxy_radius: float | None = None,
    reset_proxy_radius: float | None = None,
) -> float:
    """Phase-dependent *proxy* (occupancy) radius — not kinematic reach.

    Prefer ``*_proxy_radius`` kwargs; legacy ``*_radius`` aliases still work.
    """
    transit = float(
        transit_proxy_radius if transit_proxy_radius is not None
        else (transit_radius if transit_radius is not None else 0.40)
    )
    pick_place = float(
        pick_place_proxy_radius if pick_place_proxy_radius is not None
        else (pick_place_radius if pick_place_radius is not None else 0.08)
    )
    reset = float(
        reset_proxy_radius if reset_proxy_radius is not None
        else (reset_radius if reset_radius is not None else 0.30)
    )
    phase_l = (phase or "").lower()
    if phase_l == "transit":
        return transit
    if phase_l in ("pick", "place"):
        return pick_place
    return reset


# Alias used by new call sites / docs.
per_part_proxy_radius = per_part_radius


@dataclass
class AttemptRecovery:
    """Per-disturbance-attempt retreat / redeploy recovery record."""

    attempt_id: int
    retreat_step: int = -1
    redeploy_step: int = -1
    policy_at_retreat: int = 0
    parts_at_retreat: int = 0
    policy_delta_after_retreat: int = 0
    parts_delta_after_retreat: int = 0
    recovered: bool = False
    # True when the episode completed with this attempt still open (no redeploy).
    terminal_success: bool = False
    close_reason: str = ""  # "redeploy" | "terminal_success" | ""


@dataclass
class KnockOffTracker:
    """Deduplicate knock-off counts by unique part_id."""

    knocked_part_ids: set[int] = field(default_factory=set)
    object_drop_frame_count: int = 0
    unmatched_drop_frame_count: int = 0

    def observe_drop(self, part_id: int, *, disturbance_active: bool) -> None:
        self.object_drop_frame_count += 1
        if part_id is None or int(part_id) < 0:
            self.unmatched_drop_frame_count += 1
            return
        if disturbance_active:
            self.knocked_part_ids.add(int(part_id))

    @property
    def d_knock_off(self) -> int:
        return len(self.knocked_part_ids)


@dataclass
class CollisionEpisodeTracker:
    """Aggregate sustained collision frames into rising-edge episodes."""

    count: int = 0
    raw_frame_count: int = 0
    robot_object_count: int = 0
    _active: bool = False
    cooldown_left: int = 0
    cooldown_steps: int = 25  # ~0.5 s @ 50 Hz

    def observe(
        self,
        collision_this_frame: bool,
        *,
        robot_object: bool = False,
    ) -> None:
        if collision_this_frame:
            self.raw_frame_count += 1
        if self.cooldown_left > 0:
            self.cooldown_left -= 1
            if collision_this_frame:
                self._active = True
            return
        if collision_this_frame:
            if not self._active:
                self.count += 1
                if robot_object:
                    self.robot_object_count += 1
                self.cooldown_left = self.cooldown_steps
            self._active = True
        else:
            self._active = False