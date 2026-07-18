"""Per-part status tracker for pick-and-place task monitoring.

Tracks each part (1..N) through its lifecycle: pending → picked → in_transit → placed (or dropped).
Generates an episode-end transport report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class PartStatus(Enum):
    """Lifecycle states for a single grasped part."""

    PENDING = "pending"          # Not yet picked — still at source
    PICKED = "picked"            # Grasped, pre-lift validation passed
    IN_TRANSIT = "in_transit"    # Being carried to target
    PLACED = "placed"            # Successfully released at target
    DROPPED = "dropped"          # Lost during transit (knock-off / grasp failure)
    SKIPPED = "skipped"          # Never attempted (rewind exhausted / VLM retry exceeded)


@dataclass
class PartRecord:
    """Per-part tracking state."""

    part_index: int
    status: PartStatus = PartStatus.PENDING
    last_known_pos: tuple[float, float, float] | None = None  # world xyz
    picked_at_step: int | None = None                          # task_time_step when grasped
    placed_at_step: int | None = None                          # task_time_step when released
    drop_step: int | None = None                               # task_time_step when dropped
    transport_distance_m: float = 0.0                          # approximate travel distance
    rewind_count: int = 0
    vlm_retry_count: int = 0


@dataclass
class PartTransportReport:
    """Episode-end summary of part transport results."""

    total_parts: int
    parts_placed: list[int]        # successfully placed part indices
    parts_dropped: list[int]       # dropped during transit
    parts_skipped: list[int]       # never completed
    parts_in_transit: list[int]    # still being carried at episode end
    parts_pending: list[int]       # never picked
    placed_count: int = 0
    dropped_count: int = 0
    skipped_count: int = 0
    in_transit_count: int = 0
    pending_count: int = 0
    success_rate: float = 0.0
    total_transport_distance_m: float = 0.0
    details: list[dict[str, Any]] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [
            "=" * 60,
            " Part Transport Report",
            "=" * 60,
            f"  Total parts:       {self.total_parts}",
            f"  Successfully placed: {self.placed_count:>3d}  → {self.parts_placed[:10]}{'...' if len(self.parts_placed) > 10 else ''}",
            f"  Dropped in transit:  {self.dropped_count:>3d}  → {self.parts_dropped or 'none'}",
            f"  Skipped / exhausted: {self.skipped_count:>3d}  → {self.parts_skipped or 'none'}",
            f"  In transit (end):    {self.in_transit_count:>3d}  → {self.parts_in_transit or 'none'}",
            f"  Still pending:      {self.pending_count:>3d}  → {self.parts_pending[:10]}{'...' if len(self.parts_pending) > 10 else ''}",
            f"  Success rate:       {self.success_rate:.1%}",
            f"  Total transport dist: {self.total_transport_distance_m:.2f} m",
        ]
        # Per-part details for non-placed parts
        problem_parts = self.dropped_count + self.skipped_count + self.in_transit_count
        if problem_parts > 0 and self.details:
            lines.append("  --- Problem parts ---")
            for d in self.details:
                if d["status"] != "placed":
                    pos_str = ""
                    if d.get("last_known_pos"):
                        p = d["last_known_pos"]
                        pos_str = f"  pos=({p[0]:.3f},{p[1]:.3f},{p[2]:.3f})"
                    drop_str = f"  drop_step={d['drop_step']}" if d.get("drop_step") else ""
                    lines.append(
                        f"    part {d['part_index']:>2d}: {d['status']:12s}"
                        f"{pos_str}{drop_str}"
                    )
        lines.append("=" * 60)
        return lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_parts": self.total_parts,
            "placed_count": self.placed_count,
            "dropped_count": self.dropped_count,
            "skipped_count": self.skipped_count,
            "in_transit_count": self.in_transit_count,
            "pending_count": self.pending_count,
            "success_rate": self.success_rate,
            "total_transport_distance_m": self.total_transport_distance_m,
            "parts_placed": self.parts_placed,
            "parts_dropped": self.parts_dropped,
            "parts_skipped": self.parts_skipped,
            "parts_in_transit": self.parts_in_transit,
            "parts_pending": self.parts_pending,
            "details": self.details,
        }


class PartTracker:
    """Tracks lifecycle of each part across the episode.

    Call ``update()`` every control step with the current task state; the
    tracker infers part status transitions from gripper state, stage name,
    and held-part pose.
    """

    def __init__(self, num_parts: int = 20):
        self.num_parts = num_parts
        self._records: dict[int, PartRecord] = {
            i: PartRecord(part_index=i) for i in range(1, num_parts + 1)
        }
        self._prev_carrying = False
        self._prev_part_idx: int | None = None
        self._pick_positions: dict[int, tuple[float, float, float]] = {}
        # Track which parts were placed via the policy stage transition
        self._prev_stage_name: str = ""

    def update(
        self,
        task_time_step: int,
        part_idx: int | None,
        is_carrying: bool,
        held_part_pos: np.ndarray | None,
        stage_name: str = "",
        *,
        grasp_hold_validated: bool = False,
        grasp_rewound: bool = False,
        vlm_retry_triggered: bool = False,
    ) -> PartRecord | None:
        """Update tracking state for the current step.

        Returns the PartRecord that changed, or None if no transition occurred.
        """
        changed: PartRecord | None = None

        # Detect place transitions: gripper was carrying, now it's not
        if self._prev_carrying and not is_carrying and self._prev_part_idx is not None:
            prev = self._records[self._prev_part_idx]
            if prev.status == PartStatus.IN_TRANSIT:
                # Check if this is a normal release (open_gripper stage) vs drop
                is_release_stage = stage_name.startswith("open_gripper_to_release_")
                if is_release_stage:
                    prev.status = PartStatus.PLACED
                    prev.placed_at_step = task_time_step
                    self._update_transport_distance(prev, held_part_pos)
                else:
                    prev.status = PartStatus.DROPPED
                    prev.drop_step = task_time_step
                    if held_part_pos is not None:
                        prev.last_known_pos = self._to_tuple(held_part_pos)
                changed = prev

        # Detect pick + lift transitions (grasp validated → now in transit)
        elif grasp_hold_validated and part_idx is not None:
            rec = self._records[part_idx]
            if rec.status == PartStatus.PICKED:
                rec.status = PartStatus.IN_TRANSIT
                rec.picked_at_step = task_time_step
                if held_part_pos is not None:
                    rec.last_known_pos = self._to_tuple(held_part_pos)
                changed = rec
            elif rec.status == PartStatus.PENDING and is_carrying:
                rec.status = PartStatus.PICKED
                if held_part_pos is not None:
                    rec.last_known_pos = self._to_tuple(held_part_pos)
                    self._pick_positions[part_idx] = self._to_tuple(held_part_pos)
                changed = rec

        # Track position for in-transit parts
        if is_carrying and part_idx is not None and held_part_pos is not None:
            rec = self._records[part_idx]
            rec.last_known_pos = self._to_tuple(held_part_pos)
            if rec.status == PartStatus.PICKED and grasp_hold_validated:
                rec.status = PartStatus.IN_TRANSIT

        # Track rewind / retry
        if grasp_rewound and part_idx is not None:
            rec = self._records[part_idx]
            rec.rewind_count += 1
            if rec.rewind_count > 2:
                rec.status = PartStatus.SKIPPED

        if vlm_retry_triggered and part_idx is not None:
            rec = self._records[part_idx]
            rec.vlm_retry_count += 1
            if rec.vlm_retry_count > 2:
                rec.status = PartStatus.SKIPPED

        self._prev_carrying = is_carrying
        self._prev_part_idx = part_idx
        self._prev_stage_name = stage_name
        return changed

    def part_status(self, part_idx: int) -> PartStatus:
        """Return current status of a part."""
        return self._records[part_idx].status

    def record(self, part_idx: int) -> PartRecord:
        """Return the tracking record for a part."""
        return self._records[part_idx]

    def generate_report(self) -> PartTransportReport:
        """Produce an episode-end transport summary."""
        placed: list[int] = []
        dropped: list[int] = []
        skipped: list[int] = []
        in_transit: list[int] = []
        pending: list[int] = []
        details: list[dict[str, Any]] = []
        total_dist = 0.0

        for idx in range(1, self.num_parts + 1):
            rec = self._records[idx]
            pos = (
                list(rec.last_known_pos)
                if rec.last_known_pos is not None
                else None
            )
            detail = {
                "part_index": idx,
                "status": rec.status.value,
                "last_known_pos": pos,
                "picked_at_step": rec.picked_at_step,
                "placed_at_step": rec.placed_at_step,
                "drop_step": rec.drop_step,
                "transport_distance_m": rec.transport_distance_m,
                "rewind_count": rec.rewind_count,
                "vlm_retry_count": rec.vlm_retry_count,
            }
            details.append(detail)
            total_dist += rec.transport_distance_m

            if rec.status == PartStatus.PLACED:
                placed.append(idx)
            elif rec.status == PartStatus.DROPPED:
                dropped.append(idx)
            elif rec.status == PartStatus.SKIPPED:
                skipped.append(idx)
            elif rec.status == PartStatus.IN_TRANSIT:
                in_transit.append(idx)
            else:
                pending.append(idx)

        placed_count = len(placed)
        in_transit_count = len(in_transit)
        total_attempted = placed_count + len(dropped) + len(skipped) + in_transit_count
        success_rate = placed_count / max(total_attempted, 1)

        return PartTransportReport(
            total_parts=self.num_parts,
            parts_placed=placed,
            parts_dropped=dropped,
            parts_skipped=skipped,
            parts_in_transit=in_transit,
            parts_pending=pending,
            placed_count=placed_count,
            dropped_count=len(dropped),
            skipped_count=len(skipped),
            in_transit_count=len(in_transit),
            pending_count=len(pending),
            success_rate=success_rate,
            total_transport_distance_m=total_dist,
            details=details,
        )

    @staticmethod
    def _to_tuple(pos: np.ndarray) -> tuple[float, float, float]:
        arr = np.asarray(pos, dtype=np.float64).reshape(-1)
        return (float(arr[0]), float(arr[1]), float(arr[2]))

    @staticmethod
    def _update_transport_distance(
        rec: PartRecord,
        held_part_pos: np.ndarray | None,
    ) -> None:
        if held_part_pos is not None:
            arr = np.asarray(held_part_pos, dtype=np.float64).reshape(-1)[:3]
            if rec.last_known_pos is not None:
                delta = np.linalg.norm(
                    arr - np.asarray(rec.last_known_pos, dtype=np.float64)
                )
                rec.transport_distance_m += float(delta)
            rec.last_known_pos = (
                float(arr[0]), float(arr[1]), float(arr[2]),
            )
