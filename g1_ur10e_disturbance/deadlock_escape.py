#!/usr/bin/env python3
"""DeadlockDetector: sliding-window deadlock detection with 3-tier escape.

Extracted from run_phase3.py.  Encapsulates the positive-feedback deadlock
pattern (hand close -> STOP -> EE frozen -> hand stays near EE -> STOP
persists) and the escalation ladder: L1 jitter -> L2 repel -> L3 G1 retreat,
with hysteresis cooldown to prevent bounce-back.

Integration (replaces ~80 lines in run_phase3):

    detector = DeadlockDetector()

    # each step:
    action = detector.update(ee_pos, hand_pos, attractor_xy,
                             hand_dist_surface, consecutive_gate_count,
                             has_active_part=per_part is not None)
    if action["attractor_xy_add"] is not None:
        virtual_hand._attractor += action["attractor_xy_add"]  # before .step()
    # ... virtual_hand.step() ...
    if action["hand_offset"] is not None:
        adapter.human_hand_pos += action["hand_offset"]
    if action["force_reset"] and per_part is not None:
        per_part.state.phase = Phase.RESET
        per_part.state.step_in_phase = 0
        per_part.state.timed_out = False
        per_part.state.attractor_xy = None
    if action["g1_retreat_velocity"] is not None:
        inject_disturbance_velocity(env, action["g1_retreat_velocity"], device)
        virtual_hand._attractor = np.array([0.5, 0.0], dtype=np.float32)
        virtual_hand._local_xy = np.zeros(2, dtype=np.float32)
    csv_tier = int(action["tier"])
"""

from __future__ import annotations

from collections import deque

import numpy as np


class DeadlockDetector:
    """Sliding-window deadlock detection + 3-tier escalation with hysteresis.

    Three conditions must ALL hold for deadlock:
      1. consecutive STOP > 50 steps (temporal)
      2. EE position variance < 0.001 m^2 over window (spatial freeze)
      3. hand-EE surface distance variance < 0.0001 m^2 (distance stable)

    Escape tiers:
      L1 — jitter hand position by +/- 5 cm
      L2 — repel hand 50 cm away from EE
      L3 — inject G1 retreat velocity + full hand reset

    Hysteresis: after L2/L3 escape, hand must stay > ``hysteresis_dist``
    for ``hysteresis_steps`` before re-approach is allowed.  During cooldown
    the attractor is pushed away from the EE to prevent drift-back.
    """

    def __init__(
        self,
        window: int = 50,
        hysteresis_dist: float = 0.30,
        hysteresis_steps: int = 30,
    ) -> None:
        self._window = window
        self._hysteresis_dist = hysteresis_dist
        self._hysteresis_steps_req = hysteresis_steps

        # sliding windows (fixed-length deques for O(1) append/pop)
        self._ee_history: deque[np.ndarray] = deque(maxlen=window)
        self._dist_history: deque[float] = deque(maxlen=window)

        self._tier: float = 0.0           # float for smooth decay; cast to int on read
        self._hysteresis_remaining: int = 0

        # ponytail: deques give us O(1) push/pop; no need for a ring-buffer class.

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        ee_pos: np.ndarray,              # UR10e end-effector position [x, y, z]
        hand_pos: np.ndarray,            # virtual-hand surface position [x, y, z]
        attractor_xy: np.ndarray,        # virtual_hand._attractor [x, y]
        hand_dist_surface: float,        # adapter.closest_body_distance
        consecutive_gate_count: int,     # number of consecutive STOP decisions
        has_active_part: bool = False,   # per_part is not None (for force-reset gating)
    ) -> dict:
        """Advance detector one step and return a dict of actions to apply.

        Returns
        -------
        dict with keys:
            tier : int
                0=normal, 1=jitter, 2=repel, 3=g1_retreat (for CSV logging).
            hand_offset : np.ndarray | None
                [dx, dy, dz] to **add** to ``adapter.human_hand_pos``.
            attractor_xy_add : np.ndarray | None
                [dx, dy] to **add** to ``virtual_hand._attractor`` (apply
                *before* ``virtual_hand.step()``).
            force_reset : bool
                Per-part RESET needed (STOP>30 + hand<0.10 m proximity).
            g1_retreat_velocity : np.ndarray | None
                Velocity [vx, vy, vz] for ``inject_disturbance_velocity`` (L3).
        """
        # -- update sliding windows ---------------------------------------
        self._ee_history.append(ee_pos.copy())
        self._dist_history.append(float(hand_dist_surface))

        action: dict = {
            "tier": 0,
            "hand_offset": None,
            "attractor_xy_add": None,
            "force_reset": False,
            "g1_retreat_velocity": None,
        }

        # -- hysteresis attractor push (runs every step while cooldown active) -
        attractor_offset = self._compute_attractor_push(attractor_xy, ee_pos)
        if attractor_offset is not None:
            action["attractor_xy_add"] = attractor_offset

        # Not enough data yet.
        if len(self._ee_history) < self._window:
            return action

        # -- variance computation -----------------------------------------
        ee_arr = np.array(self._ee_history)       # (window, 3)
        dist_arr = np.array(self._dist_history)   # (window,)
        ee_var = float(np.var(ee_arr[:, 0]) + np.var(ee_arr[:, 1]) + np.var(ee_arr[:, 2]))
        dist_var = float(np.var(dist_arr))

        # -- FORCE RESET: sustained close-proximity STOP -------------------
        # ponytail: single compound condition; split only if a sub-condition
        # is reused elsewhere.
        if has_active_part and consecutive_gate_count > 30 and hand_dist_surface < 0.10:
            self._tier = 0.0
            self._ee_history.clear()
            self._dist_history.clear()
            action["tier"] = 0
            action["force_reset"] = True
            return action

        # -- deadlock detection -------------------------------------------
        is_deadlocked = (
            consecutive_gate_count > 50
            and ee_var < 0.001
            and dist_var < 0.0001
        )

        if is_deadlocked:
            self._tier = min(self._tier + 1.0, 3.0)

            if self._tier <= 1.0:
                # L1 — jitter: random +/- 5 cm, damped on Z
                jitter = np.random.uniform(-0.05, 0.05, 3)
                jitter[2] *= 0.2
                action["hand_offset"] = jitter.astype(np.float32)

            elif self._tier <= 2.0:
                # L2 — repel: push hand 0.5 m away from EE along EE->hand direction
                action["hand_offset"] = self._repel_offset(hand_pos, ee_pos, 0.50)
                self._hysteresis_remaining = self._hysteresis_steps_req

            else:
                # L3 — G1 retreat + full hand reset
                action["g1_retreat_velocity"] = np.array([-0.50, 0.0, 0.0], dtype=np.float32)
                self._tier = 0.0
                self._ee_history.clear()
                self._dist_history.clear()
                self._hysteresis_remaining = self._hysteresis_steps_req

        else:
            # Not deadlocked — decay tier slowly.
            if self._tier > 0.0:
                self._tier = max(0.0, self._tier - 0.05)

        # -- hysteresis cooldown hand push (separate from escape actions) --
        hyst_offset = self._compute_hysteresis_hand_push(
            hand_pos, ee_pos, hand_dist_surface
        )
        if hyst_offset is not None:
            if action["hand_offset"] is not None:
                action["hand_offset"] = action["hand_offset"] + hyst_offset
            else:
                action["hand_offset"] = hyst_offset

        action["tier"] = int(self._tier)
        return action

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _repel_offset(
        self, hand_pos: np.ndarray, ee_pos: np.ndarray, distance: float
    ) -> np.ndarray:
        """Offset to push hand *distance* metres away from EE."""
        to_ee = ee_pos - hand_pos
        d = float(np.linalg.norm(to_ee))
        if d < 1e-6:
            return np.array([distance, 0.0, 0.0], dtype=np.float32)
        return (-(to_ee / d) * distance).astype(np.float32)

    def _compute_attractor_push(
        self, attractor_xy: np.ndarray, ee_pos: np.ndarray
    ) -> np.ndarray | None:
        """Attractor XY offset to keep it > hysteresis_dist from EE during cooldown."""
        if self._hysteresis_remaining <= 0:
            return None

        to_ee_xy = attractor_xy - ee_pos[:2]
        d_xy = float(np.linalg.norm(to_ee_xy))
        if d_xy >= self._hysteresis_dist:
            return None

        if d_xy < 1e-6:
            new_xy = ee_pos[:2] + np.array([self._hysteresis_dist, 0.0])
        else:
            new_xy = ee_pos[:2] + (to_ee_xy / d_xy) * self._hysteresis_dist

        return (new_xy - attractor_xy).astype(np.float32)

    def _compute_hysteresis_hand_push(
        self, hand_pos: np.ndarray, ee_pos: np.ndarray, hand_dist_surface: float,
    ) -> np.ndarray | None:
        """During hysteresis cooldown, push hand away if it drifts too close."""
        if self._hysteresis_remaining <= 0:
            return None

        # Decrement / reset counter based on surface distance.
        if hand_dist_surface > self._hysteresis_dist:
            self._hysteresis_remaining -= 1
        else:
            self._hysteresis_remaining = self._hysteresis_steps_req

        # Push hand away if still too close.
        if self._hysteresis_remaining > 0 and hand_dist_surface < self._hysteresis_dist:
            magnitude = self._hysteresis_dist - hand_dist_surface + 0.05
            return self._repel_offset(hand_pos, ee_pos, magnitude)

        return None

    # ------------------------------------------------------------------
    # Self-check
    # ------------------------------------------------------------------

    def demo(self) -> None:
        """Smoke test: deadlock conditions trigger escalation, variance alone does not."""
        rng = np.random.default_rng(42)
        ee = np.array([0.5, 0.0, 0.8], dtype=np.float32)
        hand = np.array([0.6, 0.0, 0.8], dtype=np.float32)
        attr = np.array([0.5, 0.0], dtype=np.float32)

        # Not deadlocked: moving EE
        for i in range(60):
            ee_moving = ee + rng.normal(0, 0.1, 3).astype(np.float32)
            a = self.update(ee_moving, hand, attr, 0.15, 60)
            assert a["tier"] == 0 and not a["force_reset"], f"step {i}: false positive"

        # Deadlocked: frozen EE + STOP > 50.  Pre-fill the window so
        # the first iteration already has 50 data points.
        self._tier = 0.0
        self._ee_history.clear()
        self._dist_history.clear()
        for _ in range(50):
            self.update(ee, hand, attr, 0.15, 0)   # pre-fill, no STOP
        for i in range(5):
            a = self.update(ee, hand, attr, 0.15, 55)  # STOP>50 + frozen
            # L1(i=0), L2(i=1), L3(i=2, resets tier to 0), then decays back
            if i == 0:
                assert a["tier"] == 1, f"step {i}: L1 jitter expected, got {a['tier']}"
            elif i == 1:
                assert a["tier"] == 2, f"step {i}: L2 repel expected, got {a['tier']}"

        # FORCE RESET: sustained close-proximity STOP with active part.
        # Pre-fill with no-STOP data so the window stays full.
        self._tier = 0.0
        self._ee_history.clear()
        self._dist_history.clear()
        self._hysteresis_remaining = 0
        for _ in range(60):
            self.update(ee, hand, attr, 0.05, 0, has_active_part=False)
        a = self.update(ee, hand, attr, 0.05, 55, has_active_part=True)
        assert a["force_reset"], "sustained proximity should trigger force reset"

        print("[deadlock_escape] demo: all assertions passed.")


if __name__ == "__main__":
    DeadlockDetector().demo()
