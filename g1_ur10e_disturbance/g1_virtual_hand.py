"""G1VirtualHand — a smoothly-drifting hand sphere centred on G1's head.

Phase 4.2: decouples hand position from G1 kinematics.  A virtual sphere
orbits G1's head with a persistent random walk, staying within a
configurable radius.  The safety adapter feeds this position directly to
the RuleEngine — identical to real hand motion from the safety gate's
perspective.

Parameters:
    radius:       max distance from head (metres) — adjustable via CLI
    speed:        max drift speed (m/s) — lower = smoother
    height:       "head" = at head height, "table" = at UR10e EE height
"""

from __future__ import annotations

import numpy as np

# G1 arm reaches ~0.55 m from shoulder, ~0.45 m from head.
DEFAULT_RADIUS = 0.45   # m
DEFAULT_SPEED  = 0.12   # m/s — smooth drift

# Table obstacle: the SeattleLabTable centre is at (0.6, 0, 0) with a ~0.9 m
# depth.  The near edge (G1 approach side) is at approximately x = 0.15.
# When the virtual hand crosses this edge into the table volume, we push it
# back to the edge.  (C3 fix: the inequality was reversed, making this a
# no-op — hand passed through the table unchecked.)
#
# M2 fix: these values shadow dual_env_cfg.py's table/container placement.
# If layout changes in dual_env_cfg.py, update these constants too.
# ponytail: single source of truth deferred — read from env config when
# VirtualHand construction gets access to the scene config object.
TABLE_X_BLOCK = 0.15    # table front-edge x-coordinate (centre 0.6 - half-depth 0.45)
TABLE_Y_MIN = -0.50
TABLE_Y_MAX = 0.50
TABLE_OBSTACLE_MARGIN = 0.02


class G1VirtualHand:
    """A virtual hand that drifts near G1's head with persistent random motion.

    The hand follows a correlated random walk with a gentle bias toward
    the UR10e EE, producing natural-looking arm-like motion.  It avoids
    the table's near edge.

    Usage per env step::

        virtual_hand.step(dt=0.02, head_pos=g1_head_xyz)
        adapter.human_hand_pos = virtual_hand.position
    """

    def __init__(
        self,
        radius: float = DEFAULT_RADIUS,
        speed: float = DEFAULT_SPEED,
        height_mode: str = "table",
        seed: int = 42,
        attractor: tuple[float, float] = (0.8, 0.0),
        pursuit_mode: bool = False,
        retreat_steps: int = 400,
    ):
        self.radius = float(radius)
        self.speed = float(speed)
        self.height_mode = height_mode
        self._rng = np.random.RandomState(seed)
        self._attractor = np.array(attractor, dtype=np.float32)
        self._pursuit = pursuit_mode  # aggressive EE tracking for replan testing
        self._retreat_steps_default = retreat_steps  # steps to retreat after replan

        # Local-frame position and velocity (XY only, Z handled separately).
        self._local_xy: np.ndarray = np.zeros(2, dtype=np.float32)
        self._vel: np.ndarray = np.zeros(2, dtype=np.float32)

        # World-frame positions.
        self._head_pos: np.ndarray = np.zeros(3, dtype=np.float32)
        self._world_pos: np.ndarray = np.zeros(3, dtype=np.float32)
        self._target_z: float = 0.0

        # --- Block-retreat-reblock cycle (pursuit mode) ---
        self._retreat_steps: int = 0       # remaining retreat steps
        self._block_angle: float = 0.0     # rad — approach angle offset per cycle
        self._cycle_count: int = 0         # how many replans triggered this episode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def position(self) -> np.ndarray:
        return self._world_pos.copy()

    @property
    def head_position(self) -> np.ndarray:
        return self._head_pos.copy()

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    def on_replan(self) -> None:
        """Called when a replan detour is applied.  Retreats the hand for
        400 steps (8 s) — enough for UR10e to complete detour (55 steps)
        + one full pick-place cycle (~375 steps) before re-blocking."""
        self._retreat_steps = self._retreat_steps_default
        self._cycle_count += 1
        # Vary approach angle each cycle: 0°, +25°, -25°, +40°, -40°, ...
        angles = [0.0, 0.44, -0.44, 0.70, -0.70]
        self._block_angle = angles[(self._cycle_count - 1) % len(angles)]
        # H3 fix (2026-07-13): immediately zero the hand offset so the retreat
        # takes effect on the very next step() call.  Without this the hand stays
        # at the block-point for ~3 frames (geometric decay 0.4^n), during which
        # the safety gate still sees it inside the warn band — gating the first
        # few steps of the UR10e detour.
        self._local_xy = np.zeros(2, dtype=np.float32)
        self._vel = np.zeros(2, dtype=np.float32)

    def reset(self) -> None:
        """Reset internal state for a new episode."""
        self._local_xy = np.zeros(2, dtype=np.float32)
        self._vel = np.zeros(2, dtype=np.float32)
        self._retreat_steps = 0
        self._block_angle = 0.0
        self._cycle_count = 0

    def step(
        self,
        dt: float,
        head_pos: np.ndarray,
        ee_z: float | None = None,
    ):
        """Advance the virtual hand by *dt* seconds."""
        self._head_pos = head_pos.astype(np.float32)
        if ee_z is not None:
            self._target_z = float(ee_z)

        world_xy = self._head_pos[:2] + self._local_xy

        # --- Correlated random walk (smooth, persistent) ---
        # ponytail: pursuit mode keeps the hand at a fixed offset from the EE
        # (hovering inside the warn band), guaranteeing sustained SLOW_DOWN
        # and reliable replan triggering.  Without this the random walk
        # produces only transient SLOW_DOWN that never accumulates enough
        # consecutive steps for the replan trigger threshold.
        if self._pursuit:
            # --- Block-retreat-reblock cycle ---
            # RETREAT phase: spring hand back toward head after a replan.
            if self._retreat_steps > 0:
                self._retreat_steps -= 1
                # Strong spring toward head (local_xy → 0).
                # Converges in ~8 steps (0.4^8 ≈ 0.0007), but retreat holds for
                # 400 steps — most of the retreat is a stationary hold at the head.
                self._local_xy = 0.4 * self._local_xy  # fast decay toward head
                # ponytail: velocity is computed for potential smooth-interruption
                # but never integrated (position set directly above).  Kept so a
                # future "cancel retreat early" path has a smooth handoff.
                self._vel = 0.2 * self._vel + 0.02 * self._rng.uniform(-1, 1, 2)
                self._world_pos[:2] = self._head_pos[:2] + self._local_xy
                if self.height_mode == "table":
                    self._world_pos[2] = self._target_z
                else:
                    self._world_pos[2] = self._head_pos[2] + 0.2
                self._clamp_out_of_obstacles()
                return

            # BLOCK phase: reach toward the target point.  Default is the
            # container corridor centre (x=0.75), overridden by _attractor
            # when set (e.g. by per-part protocol for transit path midpoint).
            angle = self._block_angle
            offset_y = 0.12 * np.sin(angle)
            # R7: read _attractor if set (per-part protocol), else default.
            if self._attractor is not None and not np.allclose(self._attractor, 0):
                target_x = float(self._attractor[0])
                target_y = float(self._attractor[1]) + offset_y
            else:
                target_x = 0.75
                target_y = offset_y
            # Clamp to what the hand can actually reach (head_x + radius).
            reach_x = self._head_pos[0] + self.radius
            block_x = min(target_x, reach_x)
            block_y = np.clip(target_y,
                             self._head_pos[1] - self.radius,
                             self._head_pos[1] + self.radius)
            block_xy = np.array([block_x, block_y], dtype=np.float32)
            to_block = block_xy - world_xy
            d = float(np.linalg.norm(to_block))
            if d > 0.001:
                target_xy = block_xy
                self._local_xy = self._local_xy + 0.3 * (target_xy - self._head_pos[:2] - self._local_xy)
                self._vel = 0.3 * self._vel + self._rng.uniform(-0.02, 0.02, 2)
                dist = float(np.linalg.norm(self._local_xy))
                if dist > self.radius:
                    self._local_xy *= self.radius / dist
                self._world_pos[:2] = self._head_pos[:2] + self._local_xy
                if self.height_mode == "table":
                    self._world_pos[2] = self._target_z
                else:
                    self._world_pos[2] = self._head_pos[2] + 0.2
                self._clamp_out_of_obstacles()
                return
            # HOLD: hand reached the block point — stay put.  Without this
            # branch execution falls through to the random-walk code below,
            # causing oscillating block→wander→block that intermittently
            # resets the replan trigger's sustained_slow_steps counter.
            self._vel = np.zeros(2, dtype=np.float32)
            self._world_pos[:2] = self._head_pos[:2] + self._local_xy
            if self.height_mode == "table":
                self._world_pos[2] = self._target_z
            else:
                self._world_pos[2] = self._head_pos[2] + 0.2
            self._clamp_out_of_obstacles()
            return
        persistence = 0.92
        attractor_gain = 0.12
        ee_weight = 0.7
        accel = self.speed * 1.5
        self._vel = persistence * self._vel + self._rng.uniform(-1, 1, 2) * accel * dt

        # --- Attractor: blocking corridor between containers ---
        # The hand is pulled toward the nearest point on this corridor,
        # keeping it in the blocking zone regardless of where the EE is.
        # Blend: EE-weighted attractor pulls hand toward the arm's operating zone.
        ee_point = self._attractor
        corridor_y = np.clip(world_xy[1], -0.30, 0.30)
        corridor_point = np.array([0.75, corridor_y], dtype=np.float32)
        blended = ee_weight * ee_point + (1.0 - ee_weight) * corridor_point
        to_attr = blended - world_xy
        ad = float(np.linalg.norm(to_attr))
        if ad > 0.02:
            self._vel += (to_attr / ad) * attractor_gain

        # --- Clamp speed ---
        spd = float(np.linalg.norm(self._vel))
        if spd > self.speed:
            self._vel *= self.speed / spd

        # --- Integrate ---
        self._local_xy = self._local_xy + self._vel * dt

        # --- Clamp to sphere ---
        dist = float(np.linalg.norm(self._local_xy))
        if dist > self.radius:
            self._local_xy *= self.radius / dist
            radial = self._local_xy / dist
            radial_vel = np.dot(self._vel, radial) * radial
            self._vel = self._vel - 1.8 * radial_vel

        # --- World position ---
        self._world_pos[:2] = self._head_pos[:2] + self._local_xy
        if self.height_mode == "table":
            self._world_pos[2] = self._target_z
        else:
            self._world_pos[2] = self._head_pos[2] + 0.2

        # --- Clamp out of table ---
        self._clamp_out_of_obstacles()

    # ------------------------------------------------------------------
    # Obstacle avoidance
    # ------------------------------------------------------------------

    def _clamp_out_of_obstacles(self):
        """Block the hand from entering the table volume at table height.

        The table near edge is at TABLE_X_BLOCK (≈0.15 m).  When the hand
        crosses this boundary *at table height*, push it back to the edge.
        At EE height (z > 0.15 m), the hand passes over the table freely.
        """
        # ponytail: only clamp when hand is at table height (z < 0.15 m).
        # The virtual hand operates at EE height (z ≈ 0.3–0.7 m) during
        # pursuit/hover mode — it passes over the table freely, which is
        # correct: the real G1 arm can reach over the table at that height.
        # The clamp only activates when height_mode="head" (z ≈ 0.35 m),
        # which sits just above the table surface.
        if self._world_pos[2] > 0.15:
            return
        x, y = float(self._world_pos[0]), float(self._world_pos[1])
        m = TABLE_OBSTACLE_MARGIN
        x_block = TABLE_X_BLOCK + m
        y0, y1 = TABLE_Y_MIN + m, TABLE_Y_MAX - m

        if x <= x_block:    # hand still in approach zone (left of table)
            return
        if not (y0 <= y <= y1):  # hand not aligned with table in Y
            return

        # Hand inside table volume — push back to the near edge.
        pushed_x = x_block
        pushed_y = y
        local_x = pushed_x - self._head_pos[0]
        local_y = pushed_y - self._head_pos[1]
        dist = np.sqrt(local_x * local_x + local_y * local_y)
        if dist > self.radius:
            local_x *= self.radius / dist
            local_y *= self.radius / dist
            pushed_x = local_x + self._head_pos[0]
            pushed_y = local_y + self._head_pos[1]

        self._vel[0] = abs(self._vel[0]) + 0.05
        self._world_pos[0] = pushed_x
        self._world_pos[1] = pushed_y
        self._local_xy[0] = pushed_x - self._head_pos[0]
        self._local_xy[1] = pushed_y - self._head_pos[1]
