"""Per-part structured testing protocol — Phase-driven hand behaviour.

Replaces the random-walk virtual hand with a four-phase testing cycle per part:
  PICK   — hand follows EE, testing STOP response during grasp
  TRANSIT — hand blocks the computed transit path, testing replan
  PLACE  — hand follows EE, testing STOP response during place
  RESET  — hand retreats to G1 head, UR10e completes undisturbed

Phase detection from ``stage_name`` prefixes.  Slot positions are interpolated
from container base coordinates (Container A at (0.75,-0.25), B at (0.75,0.25))
with 0.04 m vertical slot spacing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

import numpy as np


class Phase(Enum):
    PICK = "pick"
    TRANSIT = "transit"
    PLACE = "place"
    RESET = "reset"


# Container world positions (must match dual_env_cfg.py layout).
CONTAINER_A_XY = np.array([0.75, -0.25], dtype=np.float32)
CONTAINER_B_XY = np.array([0.75, 0.25], dtype=np.float32)
SLOT_Z_SPACING = 0.04   # m between consecutive slots
SLOT_Z_BASE = 0.05      # m — lowest slot Z above container floor
APPROACH_Z = 0.40       # m — UR10e approach height
TRANSIT_Z = 0.45        # m — transit height for block point


def _slot_world_xy(container: str, slot_num: int) -> np.ndarray:
    """Return the world XY of a slot in *container* ('A' or 'B')."""
    return CONTAINER_A_XY.copy() if container.upper() == "A" else CONTAINER_B_XY.copy()


def _slot_world_z(slot_num: int) -> float:
    """Z of slot *slot_num* (1-indexed, bottom-up)."""
    return SLOT_Z_BASE + (slot_num - 1) * SLOT_Z_SPACING


@dataclass
class PartInfo:
    """Metadata for one pick-and-place command."""
    part_index: int          # 0-based
    pick_container: str      # "A" or "B"
    pick_slot: int           # 1-based slot number
    place_container: str
    place_slot: int


@dataclass
class PhaseState:
    """Mutable per-phase tracking."""
    phase: Phase = Phase.RESET
    step_in_phase: int = 0
    part_index: int = 0       # current part (0-based, -1 = none started)
    timed_out: bool = False
    # Per-phase timeout in steps (50 Hz).
    timeout_steps: int = 0
    # RC4: True when the current phase was entered via timeout, not stage
    # detection.  Suppresses _phase_from_stage() overwrite until the UR10e
    # actually moves to a new stage (detected by _last_stage change).
    _timeout_forced: bool = False

    # Phase-specific targets.
    block_xy: np.ndarray | None = None    # transit block point (world XY)
    attractor_xy: np.ndarray | None = None # where the hand should drift toward


class PerPartTester:
    """Orchestrates the virtual hand through Pick→Transit→Place→Reset per part.

    Usage per step::

        tester.update(stage_name, ee_pos, head_pos, is_grasping)
        # tester.attractor_xy  → hand target
        # tester.phase          → current phase
    """

    # Stage-name prefix → phase mapping.  Order matters: TRANSIT patterns
    # are checked before PICK so "move_above_box_with_slot" (transit with
    # a held part) is not mistaken for an approach.
    _TRANSIT_PREFIXES = (
        "lift_slot_", "move_above_box_with_slot_",
    )
    _PICK_PREFIXES = (
        "descend_to_slot_", "grasp_slot_", "close_gripper_slot_",
    )
    _PLACE_PREFIXES = (
        "descend_to_box_with_slot_", "open_gripper_to_release_",
    )
    _RESET_PREFIXES = (
        "lift_after_releasing_",
    )
    # Stages where the EE is safe (hand can retreat without blocking a
    # critical operation).
    _SAFE_PREFIXES = (
        "lift_after_releasing_", "move_above_box_with_slot_",
        "move_above_slot_",
    )

    # Phase timeouts (steps @ 50 Hz).  PICK/PLACE have generous safety-net
    # timeouts — the protocol prefers stage-name transitions over timeouts.
    # TRANSIT gets a moderate timeout; RESET is the longest.
    _TIMEOUT_PICK = 600      # 12 s safety net (prefer natural lift_slot transition)
    _TIMEOUT_TRANSIT = 200   # 4 s — short: if UR10e frozen, retreat quickly
    _TIMEOUT_PLACE = 600     # 12 s safety net
    _TIMEOUT_RESET = 900     # 18 s — generous: let UR10e complete freely

    def __init__(self, user_commands: list[dict[str, str]]):
        """*user_commands* from ``SingleEnvPickAndPlacePolicy.user_commands``.

        Each entry: ``{"pick": "A@3", "place": "B@5"}``.
        """
        self._parts = _parse_commands(user_commands)
        self._total_parts = len(self._parts)
        self.state = PhaseState()
        self._last_stage: str = ""
        self._last_real_stage: str = ""  # R7: last non-replan stage name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self.state.phase

    @property
    def attractor_xy(self) -> np.ndarray | None:
        """Where the virtual hand should go this step, or None if hand is
        fully retreated (use G1 head position)."""
        return self.state.attractor_xy

    @property
    def part_index(self) -> int:
        """0-based index into ``user_commands``, or -1 if none started."""
        return self.state.part_index

    @property
    def parts_total(self) -> int:
        return self._total_parts

    @property
    def timed_out(self) -> bool:
        return self.state.timed_out

    def update(
        self,
        stage_name: str,
        ee_pos: np.ndarray,        # (3,) world
        head_pos: np.ndarray,       # (3,) world
        is_grasping: bool,
    ) -> None:
        """Advance the protocol state machine by one step.

        Call BEFORE setting the virtual hand attractor.  After this returns,
        read ``self.attractor_xy`` to know where to place the hand.
        """
        s = self.state
        s.step_in_phase += 1

        # ── Detect part transitions ──────────────────────────────────
        part_idx = self._part_index_from_stage(stage_name)
        if part_idx is not None and part_idx != s.part_index and part_idx >= 0:
            s.part_index = part_idx
            s.step_in_phase = 0
            s.timed_out = False

        # ── Detect phase from stage name ─────────────────────────────
        detected = self._phase_from_stage(stage_name)

        # RC4 fix: if a timeout forced the current phase, suppress
        # stage-name detection until the UR10e actually moves to a new
        # stage.  Without this, a timeout-induced RESET is reverted to
        # TRANSIT/PICK on the very next sim step (one-step flicker).
        if not s._timeout_forced:
            if detected is not None and detected != s.phase:
                s.phase = detected
                s.step_in_phase = 0
                s.timed_out = False
                self._on_phase_enter(ee_pos, head_pos, is_grasping)
        elif detected is None or self._last_stage != stage_name:
            # Stage actually changed — timeout-forced phase served its purpose.
            s._timeout_forced = False

        # ── Phase timeout ────────────────────────────────────────────
        if s.timeout_steps > 0 and s.step_in_phase >= s.timeout_steps:
            if not s.timed_out:
                s.timed_out = True
                s._timeout_forced = True
                self._on_timeout(ee_pos, head_pos)

        self._last_stage = stage_name

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def _phase_from_stage(self, stage: str) -> Phase | None:
        """Classify a stage name into a phase."""
        # R7: replan detour stages preserve the current phase, but we
        # remember the last non-replan stage so phase detection works
        # correctly when the detour ends.
        if stage.startswith("replan_"):
            return None
        # Update the "last real stage" tracker (non-replan stages only).
        self._last_real_stage = stage
        for prefix in self._RESET_PREFIXES:
            if stage.startswith(prefix):
                return Phase.RESET
        for prefix in self._TRANSIT_PREFIXES:
            if stage.startswith(prefix):
                return Phase.TRANSIT
        for prefix in self._PLACE_PREFIXES:
            if stage.startswith(prefix):
                return Phase.PLACE
        for prefix in self._PICK_PREFIXES:
            if stage.startswith(prefix):
                return Phase.PICK
        # Stages like "start", "reset_parts" → RESET
        if self.state.part_index < 0:
            return Phase.RESET
        return None  # no change

    def _on_phase_enter(
        self, ee_pos: np.ndarray, head_pos: np.ndarray, is_grasping: bool,
    ) -> None:
        """Set attractor and timeout for the new phase."""
        s = self.state
        part = self._parts[s.part_index] if 0 <= s.part_index < self._total_parts else None

        if s.phase == Phase.PICK:
            s.timeout_steps = self._TIMEOUT_PICK
            # Hand follows EE to test STOP during grasp.
            s.attractor_xy = ee_pos[:2].copy()

        elif s.phase == Phase.TRANSIT:
            s.timeout_steps = self._TIMEOUT_TRANSIT
            if part is not None:
                pick_xy = _slot_world_xy(part.pick_container, part.pick_slot)
                place_xy = _slot_world_xy(part.place_container, part.place_slot)
                # Block at the midpoint of the transit path, offset 0.10 m
                # toward G1's side (x < 0.75 → toward the front).
                mid = (pick_xy + place_xy) / 2.0
                away = mid - np.array([0.75, 0.0], dtype=np.float32)
                d = float(np.linalg.norm(away))
                if d < 1e-6:
                    away = np.array([-0.10, 0.0], dtype=np.float32)
                else:
                    away = away / d * 0.10
                s.block_xy = mid + away
                s.attractor_xy = s.block_xy.copy()
            else:
                s.attractor_xy = np.array([0.65, 0.0], dtype=np.float32)

        elif s.phase == Phase.PLACE:
            s.timeout_steps = self._TIMEOUT_PLACE
            s.attractor_xy = ee_pos[:2].copy()

        else:  # RESET
            s.timeout_steps = self._TIMEOUT_RESET
            # Retreat hand to G1 head — no blocking.
            s.attractor_xy = None
            s.block_xy = None

    def _on_timeout(self, ee_pos: np.ndarray, head_pos: np.ndarray) -> None:
        """Advance or escape based on which phase timed out.

        PICK → TRANSIT: normal progression, hand was small, now test transit.
        TRANSIT → RESET: UR10e is stuck, hand is blocking too hard, retreat.
        PLACE → RESET: same, retreat hand to let UR10e finish.
        RESET → next part PICK or keep waiting.
        """
        s = self.state
        if s.phase == Phase.PICK:
            s.phase = Phase.TRANSIT
            s.step_in_phase = 0
            s.timed_out = False
            s.timeout_steps = self._TIMEOUT_TRANSIT
            part = self._parts[s.part_index] if 0 <= s.part_index < self._total_parts else None
            if part is not None:
                pick_xy = _slot_world_xy(part.pick_container, part.pick_slot)
                place_xy = _slot_world_xy(part.place_container, part.place_slot)
                mid = (pick_xy + place_xy) / 2.0
                away = mid - np.array([0.75, 0.0], dtype=np.float32)
                d = float(np.linalg.norm(away))
                away = away / d * 0.10 if d > 1e-6 else np.array([-0.10, 0.0], dtype=np.float32)
                s.block_xy = mid + away
                s.attractor_xy = s.block_xy.copy()
            else:
                s.attractor_xy = np.array([0.65, 0.0], dtype=np.float32)
        elif s.phase in (Phase.TRANSIT, Phase.PLACE):
            # UR10e stuck — hand blocking too aggressively.  Retreat.
            s.phase = Phase.RESET
            s.step_in_phase = 0
            s.timed_out = False
            s.timeout_steps = self._TIMEOUT_RESET
            s.attractor_xy = None
            s.block_xy = None
        elif s.phase == Phase.RESET:
            next_idx = s.part_index + 1
            if next_idx < self._total_parts:
                s.part_index = next_idx
                s.phase = Phase.PICK
                s.step_in_phase = 0
                s.timed_out = False
                s.timeout_steps = self._TIMEOUT_PICK
                s.attractor_xy = ee_pos[:2].copy()
                s.block_xy = None
            else:
                s.step_in_phase = 0
                s.timed_out = False

    # ------------------------------------------------------------------
    # Part index extraction
    # ------------------------------------------------------------------

    def _part_index_from_stage(self, stage: str) -> int | None:
        """Extract the part number from a stage name.

        Stage names encode the slot number in different positions:
          - "descend_to_slot_A_3"     → slot 3
          - "grasp_slot_A_5"          → slot 5
          - "descend_to_box_with_slot_B_2" → slot 2

        The part index is derived by matching the slot number against the
        known sequence of pick/place commands.
        """
        # Try to extract container + slot from known patterns.
        m = re.search(r'slot_([AB])_(\d+)', stage)
        if not m:
            return None
        container = m.group(1)
        slot_num = int(m.group(2))

        # Find the part whose pick or place slot matches.
        for i, part in enumerate(self._parts):
            if part.pick_container.upper() == container and part.pick_slot == slot_num:
                return i
            if part.place_container.upper() == container and part.place_slot == slot_num:
                return i
        return None


# ------------------------------------------------------------------
# Command parsing
# ------------------------------------------------------------------

def _parse_commands(user_commands: list[dict[str, str]]) -> list[PartInfo]:
    """Parse ``user_commands`` into a list of :class:`PartInfo`."""
    parts: list[PartInfo] = []
    for i, cmd in enumerate(user_commands):
        pick_str = cmd.get("pick", "A@1")
        place_str = cmd.get("place", "B@1")
        pick_cont, pick_slot = _parse_slot(pick_str)
        place_cont, place_slot = _parse_slot(place_str)
        parts.append(PartInfo(
            part_index=i,
            pick_container=pick_cont,
            pick_slot=pick_slot,
            place_container=place_cont,
            place_slot=place_slot,
        ))
    return parts


def _parse_slot(slot_str: str) -> tuple[str, int]:
    """Parse "A@3" → ("A", 3)."""
    parts = slot_str.split("@")
    container = parts[0].strip().upper()
    slot_num = int(parts[1].strip()) if len(parts) > 1 else 1
    return container, slot_num
