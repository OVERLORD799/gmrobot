"""G1 disturbance controller — distance-based behaviour modes + stuck detection + scripted scenarios.

Phase 3 adds three proximity-gated behaviour modes that replace the simple
random-wander from Phase 2:

    AGGRESSIVE  (d > 0.30 m) — full-speed wandering, no avoidance
    MODERATE    (0.15–0.30 m) — half-speed, steer away from UR10e
    CAUTIOUS    (d < 0.15 m)  — retreat / full-stop

Stuck detection (Phase 3.1): when the controller commands a non-trivial
velocity but the G1 root fails to move for a sustained period (e.g. walking
into the table corner), the controller forces a retreat in a random
direction to dislodge the robot.

Scripted scenarios (Phase 3.2): when ``scripted_phases`` is provided, the
controller follows a timed sequence of velocity commands instead of random
wander.  This enables reproducible pressure-testing of the safety gate
(e.g. dashing through the UR10e workspace during a carry).

The velocity commands are written into a module-level buffer that the
disturbance command term reads from, injecting into the G1 walker
observation pipeline in place of ``UniformVelocityCommandCfg``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


# =============================================================================
# Distance thresholds for behaviour mode selection
# =============================================================================

# R6 L3: these module-level constants are DOCUMENTATION-ONLY when the
# constructor receives explicit values from config/default.yaml →
# config_loader.py → run_phase3.py.  Editing them here has NO EFFECT on
# phase3 runs.  To change behaviour, edit config/default.yaml.
CAUTIOUS_THRESHOLD = 0.15   # m — below this: retreat / stop
MODERATE_THRESHOLD = 0.55   # m — below this: slow + steer away (F1 fix: was 0.30, G1 never entered; G1 min observed ≈0.50m)

# Workspace bounds for the UR10e operating area (table + containers).
# G1 is allowed to wander within these limits.
WORKSPACE_X_RANGE = (0.0, 0.8)
WORKSPACE_Y_RANGE = (-0.5, 0.5)

# Velocity command ranges (match UniformVelocityCommandCfg in dual_env_cfg.py).
VX_RANGE = (-0.8, 0.8)
VY_RANGE = (-0.5, 0.5)
WZ_RANGE = (-1.57, 1.57)

# Speed multipliers per mode
SPEED_AGGRESSIVE = 0.20  # low-speed wander (reduced from 0.5 to prevent tilting)
SPEED_MODERATE   = 0.10  # very slow
SPEED_CAUTIOUS   = 0.0   # stop

# Stabilisation pause after each velocity resample (steps).
STABILISE_STEPS = 50  # 1.0 s @ 50 Hz — G1 stands still to recover balance

# Stuck detection thresholds
STUCK_CMD_SPEED_MIN = 0.10    # m/s — commanded speed below this is "standing", not stuck
STUCK_ACTUAL_SPEED_MAX = 0.02 # m/s — actual speed above this means we're moving
STUCK_CONSECUTIVE_STEPS = 100 # steps (2.0 s @ 50 Hz) before declaring stuck
STUCK_RECOVERY_STEPS = 80     # steps (1.6 s) to retreat before resuming normal behaviour


# =============================================================================
# Scripted phase definitions (Phase 3.2)
# =============================================================================

@dataclass
class ScriptedPhase:
    """One phase of a scripted disturbance scenario."""
    name: str
    duration_steps: int
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0
    arm_motion: str = "none"  # "none" | "wave" | "extend_forward" | "extend_left" | "extend_right"


# Pre-defined scenarios.
# Status key:
#   ✅ = CLI-tested and verified (arm_collision, arm_wave)
#   🔲 = phases defined but no execution path yet (table_bump, object_push,
#        circulate, combined — depend on physical arm control or CLI wiring)
ARM_COLLISION_PHASES: list[ScriptedPhase] = [
    # Phase 1: Let UR10e start picking (~2 s).
    ScriptedPhase("wait",         100,  vx=0.0, vy=0.0),
    # Phase 2: Walk toward container A at safe speed (~4 s, covers ~2 m).
    ScriptedPhase("approach",     200,  vx=0.5, vy=-0.08),
    # Phase 3: Slow near container, lateral sweep to block opening (~3 s).
    ScriptedPhase("block",        150,  vx=0.15, vy=0.05),
    # Phase 4: Retreat.
    ScriptedPhase("retreat",      100,  vx=-0.4, vy=0.0),
    # Phase 5: Idle.
    ScriptedPhase("idle",         9999, vx=0.0, vy=0.0),
]

ARM_WAVE_PHASES: list[ScriptedPhase] = [
    ScriptedPhase("approach",     150,  vx=0.4, vy=0.0),
    ScriptedPhase("settle",       60,   vx=0.1, vy=0.0),
    ScriptedPhase("stand",        150,  vx=0.0, vy=0.0),
    ScriptedPhase("retreat",      80,   vx=-0.3, vy=0.0),
    ScriptedPhase("idle",         9999, vx=0.0, vy=0.0),
]

# E01-Dyn-B: deterministic outer-lane lateral patrol. This is scripted
# locomotion only (not learned whole-body control, not human arm gesture).
OUTER_LATERAL_PATROL_PHASES: list[ScriptedPhase] = [
    ScriptedPhase("approach_outer_lane", 140, vx=0.34, vy=0.00),
    ScriptedPhase("settle_heading", 20, vx=0.04, vy=0.00),
    ScriptedPhase("lateral_positive_sweep", 90, vx=0.02, vy=0.22),
    ScriptedPhase("lateral_negative_sweep", 90, vx=-0.02, vy=-0.22),
    ScriptedPhase("retreat_outer_lane", 80, vx=-0.32, vy=0.00),
    ScriptedPhase("idle", 9999, vx=0.0, vy=0.0),
]

# M5 fix: TABLE_BUMP_PHASES, OBJECT_PUSH_PHASES, CIRCULATE_PHASES, COMBINED_PHASES
# removed — phases were defined but no CLI execution path existed and physical arm
# control is not supported by the current walk policy (0121_walk.pt).
# Restore from git history when needed (Phase 5+).

# Shorthand lookup.  Only ✅ entries have a verified execution path.
# 🔲 entries (table_bump, object_push, circulate, combined) were removed
# (M5 fix) — phases were defined but no CLI wiring existed and physical arm
# control is not supported by the walk policy.  Restore from git history
# when arm control or CLI wiring is added in Phase 5+.
SCENARIOS: dict[str, list[ScriptedPhase] | None] = {
    "arm_collision":      ARM_COLLISION_PHASES,
    "arm_wave":           ARM_WAVE_PHASES,
    "outer_lateral_patrol": OUTER_LATERAL_PATROL_PHASES,
    "constrained_wander": None,   # same as default (no phases, random wander)
    "vlm_explore":        None,   # placeholder (VLM guides behaviour, no fixed script)
}


class DisturbanceMode(Enum):
    """Proximity-gated behaviour tier."""
    AGGRESSIVE = "aggressive"
    MODERATE = "moderate"
    CAUTIOUS = "cautious"
    STUCK = "stuck"
    IDLE = "idle"


class DisturbancePhase(Enum):
    """Internal phase within the current mode."""
    IDLE = "idle"
    WANDER = "wander"
    APPROACH_ARM = "approach_arm"
    RETREAT = "retreat"
    STUCK_RETREAT = "stuck_retreat"


# =============================================================================
# Module-level command buffer — read by mdp.disturbance_commands
# =============================================================================
#
# ponytail: global mutable state; single-env only.  If multi-env support is
# ever added (num_envs > 1), replace with a per-env buffer keyed by env_idx.

_disturbance_cmd_buffer: np.ndarray = np.zeros(3, dtype=np.float32)


def set_disturbance_command(cmd: np.ndarray) -> None:
    """Write the disturbance controller's velocity into the shared buffer.

    Called by :meth:`G1DisturbanceController.update` after computing
    the mode-aware command.
    """
    global _disturbance_cmd_buffer
    _disturbance_cmd_buffer = cmd.astype(np.float32).copy()


def get_disturbance_command() -> np.ndarray:
    """Read the current disturbance velocity command.

    Returns a copy so callers cannot mutate the buffer.
    """
    return _disturbance_cmd_buffer.copy()


# =============================================================================
# Controller
# =============================================================================

class G1DisturbanceController:
    """Generates velocity commands for G1 with distance-gated behaviour.

    The velocity commands are injected into the G1 walker observation pipeline
    by writing to the module-level buffer via :func:`set_disturbance_command`.

    Mode selection (evaluated every step)::

        AGGRESSIVE  — G1-UR10e distance > 0.30 m : full wander
        MODERATE    — 0.15–0.30 m                : slow + steer away
        CAUTIOUS    — < 0.15 m                   : retreat / stop

    Scripted mode (Phase 3.2): when *scripted_phases* is provided, the
    controller follows a fixed phase sequence instead of random wander.
    Distance-gated safety (MODERATE / CAUTIOUS) and stuck detection
    remain active — they override the script when G1 gets too close to
    the UR10e or gets stuck against an obstacle.
    """

    def __init__(
        self,
        *,
        workspace_x: tuple[float, float] = WORKSPACE_X_RANGE,
        workspace_y: tuple[float, float] = WORKSPACE_Y_RANGE,
        cautious_threshold: float = CAUTIOUS_THRESHOLD,
        moderate_threshold: float = MODERATE_THRESHOLD,
        speed_aggressive: float = SPEED_AGGRESSIVE,
        speed_moderate: float = SPEED_MODERATE,
        speed_cautious: float = SPEED_CAUTIOUS,
        resample_interval: int = 200,  # steps between velocity changes
        scripted_phases: list[ScriptedPhase] | None = None,
        seed: int = 42,
        control_dt: float = 0.02,  # M4 fix: control timestep for stuck speed calc
        vy_scale: float = 0.0,     # F1 fix: lateral exploration scale (0=disabled, 0.05=narrow)
        vy_bias: float = 0.0,      # constant y-offset added to every velocity command (steers G1 toward a side)
        vx_bias: float = 0.0,      # constant x-offset — negative = walk backward (approach from behind table)
    ):
        # --- thresholds ---
        self.cautious_threshold = cautious_threshold
        self.moderate_threshold = moderate_threshold

        # --- speed multipliers ---
        self.speed_aggressive = speed_aggressive
        self.speed_moderate = speed_moderate
        self.speed_cautious = speed_cautious

        # R7 H1 fix: speed_aggressive=0 causes division by zero in MODERATE
        # scaling (line 414) and NaN in schedule generation (line 474).
        # speed_moderate/speed_cautious can be zero (stop), but aggressive cannot.
        if self.speed_aggressive <= 0:
            raise ValueError(
                f"speed_aggressive must be > 0, got {self.speed_aggressive}. "
                "Set speed_aggressive to a positive value in config YAML."
            )

        # --- workspace ---
        self.workspace_x = workspace_x
        self.workspace_y = workspace_y

        # --- resample ---
        self.resample_interval = resample_interval

        # --- scripted mode (Phase 3.2) ---
        self.scripted_phases = scripted_phases

        # M4 fix: control dt from config (default 0.02 = 50 Hz), used by stuck
        # detection to compute actual speed from per-step displacement.
        self.control_dt = float(control_dt)

        # F1 fix (2026-07-11): lateral exploration scale — 0 = safe default (vy=0),
        # 0.05 = narrow lateral drift for reaching container y=±0.25.
        # ponytail: exposed as config param so operators can dial it up/down
        # without code changes.  If G1 falls at vy_scale > 0.05, reduce it.
        self._vy_scale = float(vy_scale)

        # Steering bias: positive → G1 tends right (y>0), negative → left (y<0).
        self._vy_bias = float(vy_bias)
        # Forward bias: negative → walk backward (approach table from behind).
        self._vx_bias = float(vx_bias)

        # --- state ---
        self._mode = DisturbanceMode.IDLE
        self._phase = DisturbancePhase.IDLE
        self._step = 0
        self._cmd: np.ndarray = np.zeros(3, dtype=np.float32)  # (vx, vy, wz)
        self._g1_root_xy: Optional[np.ndarray] = None
        self._ur10e_ee_xy: Optional[np.ndarray] = None
        self._g1_ur10e_distance: float = float("inf")

        # --- stuck detection ---
        self._prev_root_xy: Optional[np.ndarray] = None
        self._stuck_step_counter: int = 0
        self._stuck_recovery_remaining: int = 0
        self._stuck_total_count: int = 0  # cumulative for metrics

        # --- stabilisation (Phase 4.3: anti-tilt) ---
        self._stabilise_remaining: int = 0

        # --- scripted mode state (Phase 3.2) ---
        self._scripted_phase_idx: int = 0
        self._scripted_step_in_phase: int = 0
        self._scripted_phase_name: str = "idle"

        # L2 fix: single seeded RNG for ALL random calls (schedule + stuck recovery).
        self._rng = np.random.RandomState(seed)

        # Pre-generate a velocity schedule so behaviour is reproducible.
        self._schedule = self._generate_schedule(10000)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def mode(self) -> DisturbanceMode:
        """Current behaviour tier."""
        return self._mode

    @property
    def phase(self) -> DisturbancePhase:
        """Current internal phase."""
        return self._phase

    @property
    def scenario_name(self) -> str:
        """Scripted phase name if active, otherwise 'wander'."""
        if self.scripted_phases is not None:
            return self._scripted_phase_name
        return "wander"

    @property
    def arm_motion(self) -> str:
        """Current arm motion for the active scripted phase, or 'none'."""
        if self.scripted_phases is not None:
            phase = self.scripted_phases[self._scripted_phase_idx]
            return phase.arm_motion
        return "none"

    @property
    def step_in_phase(self) -> int:
        """Steps elapsed since entering the current scripted phase."""
        return self._scripted_step_in_phase

    @property
    def command(self) -> np.ndarray:
        """Current velocity command (vx, vy, wz)."""
        return self._cmd.copy()

    @property
    def distance(self) -> float:
        """Last known G1–UR10e distance (XY plane, metres)."""
        return self._g1_ur10e_distance

    @property
    def stuck_count(self) -> int:
        """Total number of stuck-detection events this episode."""
        return self._stuck_total_count

    @property
    def is_stuck(self) -> bool:
        """True while the controller is executing a stuck-recovery retreat."""
        return self._mode == DisturbanceMode.STUCK

    def update(
        self,
        g1_root_pos: np.ndarray,   # (3,) world position of G1 root
        ur10e_ee_pos: np.ndarray,  # (3,) world position of UR10e EE
        *,
        force_retreat: bool = False,
        force_mode: DisturbanceMode | None = None,  # R7 C1 fix: override distance-gated mode BEFORE velocity computation
        contact_forces: np.ndarray | None = None,  # (num_bodies, 3) net contact forces
        surface_distance: float | None = None,  # H2 fix: surface-to-surface distance from safety adapter
    ) -> np.ndarray:
        """Compute the next velocity command and write to the shared buffer.

        Args:
            g1_root_pos: G1 root world position (uses x, y).
            ur10e_ee_pos: UR10e EE world position (uses x, y).
            force_retreat: if True, force CAUTIOUS / retreat regardless of distance.
            contact_forces: (num_bodies, 3) net contact forces from the G1
                body contact sensor.  Used by force-based stuck retreat.
            surface_distance: if set, overrides the root-to-EE center distance
                for mode selection — ensures G1 behaviour is consistent with
                what the safety gate actually sees (virtual hand surface, not
                G1 root centre).

        Returns:
            (3,) velocity command ``(vx, vy, wz)``.
        """
        self._step += 1
        self._g1_root_xy = g1_root_pos[:2].astype(np.float32)
        self._ur10e_ee_xy = ur10e_ee_pos[:2].astype(np.float32)
        self._contact_forces = contact_forces  # cached for stuck retreat

        # --- stuck detection (runs before mode selection) ---
        if self._stuck_recovery_remaining > 0:
            # Already in stuck-recovery retreat — count down.
            self._stuck_recovery_remaining -= 1
            self._mode = DisturbanceMode.STUCK
            self._phase = DisturbancePhase.STUCK_RETREAT
            self._cmd = self._stuck_retreat_command()
        else:
            # Check whether we just exited recovery.
            was_stuck = self._mode == DisturbanceMode.STUCK
            if was_stuck:
                self._stuck_step_counter = 0  # reset counter after recovery

            # --- distance evaluation ---
            self._g1_ur10e_distance = float(
                np.linalg.norm(self._g1_root_xy - self._ur10e_ee_xy)
            )
            # H2 fix (2026-07-13): use surface distance when available so the
            # disturbance controller's mode selection is consistent with what
            # the safety gate actually sees.  Virtual hand surface distance can
            # be near zero while G1 root is 0.5 m away — without this, G1 walks
            # at MODERATE speed toward a UR10e that is already STOPped.
            _effective_dist = surface_distance if surface_distance is not None else self._g1_ur10e_distance

            # --- mode selection ---
            # R7 C1 fix: force_mode overrides distance-gated selection for
            # AGGRESSIVE / MODERATE.  CAUTIOUS (distance < cautious_threshold)
            # still takes precedence as a safety floor — even --mode AGGRESSIVE
            # retreats when G1 is dangerously close.
            if force_mode is not None:
                self._mode = force_mode
            if force_retreat or _effective_dist < self.cautious_threshold:
                self._mode = DisturbanceMode.CAUTIOUS
            elif force_mode is None:
                if _effective_dist < self.moderate_threshold:
                    self._mode = DisturbanceMode.MODERATE
                else:
                    self._mode = DisturbanceMode.AGGRESSIVE

            # --- command generation ---
            if self._mode == DisturbanceMode.CAUTIOUS:
                self._phase = DisturbancePhase.RETREAT
                self._cmd = self._retreat_command()
            elif self.scripted_phases is not None:
                self._cmd = self._scripted_command()
                if self._mode == DisturbanceMode.MODERATE:
                    self._cmd[:2] *= self.speed_moderate
            elif self._stabilise_remaining > 0:
                # Stand still to recover balance after a velocity change.
                self._stabilise_remaining -= 1
                self._phase = DisturbancePhase.IDLE
                self._cmd = np.zeros(3, dtype=np.float32)
            elif self._step % self.resample_interval == 0:
                # Random wander: resample every N steps.
                self._phase = DisturbancePhase.WANDER
                idx = self._step // self.resample_interval
                self._cmd = self._schedule[idx % len(self._schedule)]
                if self._mode == DisturbanceMode.MODERATE:
                    self._cmd = self._cmd * (self.speed_moderate / self.speed_aggressive)
                # After resampling, schedule a stabilisation pause.
                self._stabilise_remaining = STABILISE_STEPS
            # else: carry over last command (no resample this step)

            # --- moderate steering: bias away from UR10e ---
            if self._mode == DisturbanceMode.MODERATE and self._phase != DisturbancePhase.RETREAT:
                self._cmd = self._steer_away(self._cmd)

            # Clamp to workspace — if G1 is near the boundary, steer inward.
            # Skip in scripted mode: the script controls the path explicitly.
            # S2 fix: also skip during CAUTIOUS/STUCK retreat — forcing G1
            # back toward UR10e when it is trying to escape creates an
            # oscillating boundary-bounce loop.
            if self.scripted_phases is None and self._mode not in (DisturbanceMode.CAUTIOUS, DisturbanceMode.STUCK):
                self._cmd = self._boundary_steer(self._cmd)

            # --- stuck detection: commanded vs actual velocity ---
            self._cmd = self._detect_and_handle_stuck(self._cmd)

        # Publish to the module-level buffer for the walker obs pipeline.
        set_disturbance_command(self._cmd)

        return self._cmd

    def reset(self):
        """Reset internal state for a new episode."""
        self._step = 0
        self._mode = DisturbanceMode.IDLE
        self._phase = DisturbancePhase.IDLE
        self._cmd = np.zeros(3, dtype=np.float32)
        self._g1_ur10e_distance = float("inf")
        self._prev_root_xy = None
        self._stuck_step_counter = 0
        self._stuck_recovery_remaining = 0
        self._stuck_total_count = 0
        self._stabilise_remaining = 0
        self._scripted_phase_idx = 0
        self._scripted_step_in_phase = 0
        self._scripted_phase_name = "idle"
        self._contact_forces = None  # L3 fix: clear stale contact force cache
        set_disturbance_command(self._cmd)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _generate_schedule(self, n: int) -> list[np.ndarray]:
        """Pre-generate random velocity commands at AGGRESSIVE speed.

        vy is hardcoded to 0 because the G1 walking policy (0121_walk.pt) was
        trained for forward locomotion only — lateral velocity commands
        destabilise the robot and cause falls.  y-axis variation comes from
        boundary steer and stuck recovery, not from random sampling.

        L2 fix: uses ``self._rng`` (same instance as stuck recovery) so all
        randomness flows through a single seeded generator.
        """
        schedule = []
        for _ in range(n):
            vx = self._rng.uniform(*VX_RANGE) * self.speed_aggressive + self._vx_bias
            vy = self._rng.uniform(-self._vy_scale, self._vy_scale) + self._vy_bias  # F1 + side-steer
            wz = self._rng.uniform(*WZ_RANGE) * 0.3
            schedule.append(np.array([vx, vy, wz], dtype=np.float32))
        return schedule

    def _retreat_command(self) -> np.ndarray:
        """Move away from the UR10e EE at cautious speed.

        If already very close, back straight up (negative x with respect
        to the workspace centre).

        S1 fix: retreat speed is now proportional to the urgency (closer =
        faster retreat) rather than a fixed 0.04 m/s.  Minimum retreat speed
        is 0.20 m/s at the cautious threshold boundary, ramping to 0.50 m/s
        when within 0.05 m.
        """
        if self._g1_root_xy is None or self._ur10e_ee_xy is None:
            return np.zeros(3, dtype=np.float32)

        away = self._g1_root_xy - self._ur10e_ee_xy
        dist = float(np.linalg.norm(away))

        if dist < 0.01:
            # Degenerate — UR10e is essentially on top of G1 root.
            # Retreat toward -x (away from table at x≈0.6).
            return np.array([-0.5, 0.0, 0.0], dtype=np.float32)

        direction = away / dist
        # Speed ramps from 0.20 at threshold boundary to 0.50 at 0.05 m.
        # ponytail: linear ramp on distance urgency; replace with
        # smoothstep if jerk becomes an issue.
        # R6 H2 fix: guard against division by zero when cautious_threshold
        # is set to ≤ 0.05 m.  Also reject thresholds that are too small to
        # leave room for the urgency ramp (minimum 0.10 m recommended).
        denom = max(self.cautious_threshold - 0.05, 1e-6)
        urgency = max(0.0, min(1.0, (self.cautious_threshold - dist) / denom))
        retreat_speed = 0.20 + urgency * 0.30  # 0.20 → 0.50 m/s
        return np.array(
            [direction[0] * retreat_speed, direction[1] * retreat_speed, 0.0],
            dtype=np.float32,
        )

    def _steer_away(self, cmd: np.ndarray) -> np.ndarray:
        """Bias the wander velocity away from the UR10e EE (MODERATE mode)."""
        if self._g1_root_xy is None or self._ur10e_ee_xy is None:
            return cmd

        away = self._g1_root_xy - self._ur10e_ee_xy
        dist = float(np.linalg.norm(away))
        if dist < 0.01:
            return cmd

        away_dir = away / dist

        # Blend: 70% original wander, 30% steering away
        steer_strength = 0.3
        out = cmd.copy()
        out[0] = (1.0 - steer_strength) * cmd[0] + steer_strength * away_dir[0] * np.abs(cmd[0])
        out[1] = (1.0 - steer_strength) * cmd[1] + steer_strength * away_dir[1] * np.abs(cmd[1])
        return out

    def _boundary_steer(self, cmd: np.ndarray) -> np.ndarray:
        """Steer away from workspace boundaries."""
        if self._g1_root_xy is None:
            return cmd

        out = cmd.copy()
        margin = 0.1
        x, y = self._g1_root_xy

        if x < self.workspace_x[0] + margin:
            out[0] = max(out[0], 0.3)
        elif x > self.workspace_x[1] - margin:
            out[0] = min(out[0], -0.3)

        if y < self.workspace_y[0] + margin:
            out[1] = max(out[1], 0.3)
        elif y > self.workspace_y[1] - margin:
            out[1] = min(out[1], -0.3)

        return out

    # ------------------------------------------------------------------
    # Stuck detection
    # ------------------------------------------------------------------

    def _detect_and_handle_stuck(self, cmd: np.ndarray) -> np.ndarray:
        """Check whether G1 is commanded to move but not actually moving.

        When the walk policy is told to go somewhere but the root position
        barely changes (e.g. table corner, wall), we increment a counter.
        After ``STUCK_CONSECUTIVE_STEPS`` consecutive stuck steps the
        controller forces a random-direction retreat to dislodge the robot.

        Returns the (possibly replaced) velocity command.
        """
        cmd_speed = float(np.linalg.norm(cmd[:2]))

        if cmd_speed < STUCK_CMD_SPEED_MIN:
            # Standing / near-zero command — reset the counter.
            self._stuck_step_counter = 0
            self._prev_root_xy = self._g1_root_xy.copy() if self._g1_root_xy is not None else None
            return cmd

        if self._prev_root_xy is None or self._g1_root_xy is None:
            self._prev_root_xy = self._g1_root_xy.copy() if self._g1_root_xy is not None else None
            return cmd

        # M4 fix: use configured control_dt instead of hardcoded 0.02.
        actual_disp = float(np.linalg.norm(self._g1_root_xy - self._prev_root_xy))
        actual_speed = actual_disp / self.control_dt

        if actual_speed < STUCK_ACTUAL_SPEED_MAX:
            self._stuck_step_counter += 1
        else:
            # Moved — decay counter (exponential forget).
            self._stuck_step_counter = max(0, self._stuck_step_counter - 2)

        self._prev_root_xy = self._g1_root_xy.copy()

        if self._stuck_step_counter >= STUCK_CONSECUTIVE_STEPS:
            self._stuck_total_count += 1
            self._stuck_step_counter = 0
            self._stuck_recovery_remaining = STUCK_RECOVERY_STEPS
            # The retreat command will be applied from the NEXT step onward
            # (this step still uses the pre-stuck command to avoid a sudden
            # discontinuity — the walk policy needs a smooth transition).

        return cmd

    def _stuck_retreat_command(self) -> np.ndarray:
        """Retreat + turn to dislodge from an unknown obstacle.

        Phase 4: when contact force data is available (from
        ``g1_contact_forces`` sensor), the retreat direction follows the
        net contact force vector — the obstacle pushes G1, so retreating
        *with* that push moves G1 away from the obstacle surface.

        Falls back to random-direction retreat when forces are unavailable
        or too small to determine a reliable direction.
        """
        if self._g1_root_xy is None:
            return np.array([-0.3, 0.0, 0.0], dtype=np.float32)

        retreat_speed = 0.3  # m/s

        # --- Phase 4: force-based direction ---
        force_dir = self._contact_force_direction()
        if force_dir is not None:
            fx, fy = force_dir
            # Retreat in the direction of the net contact force
            # (obstacle pushes → retreat with the push).
            vx = fx * retreat_speed
            vy = fy * retreat_speed
            wz = np.sign(vy) * 0.6 if abs(vy) > 0.05 else 0.0
            return np.array([vx, vy, wz], dtype=np.float32)

        # --- Fallback: random direction (M9 fix: use seeded RNG) ---
        angle = self._rng.uniform(-np.pi * 0.6, np.pi * 0.6)  # ±108°
        vx = -retreat_speed * np.cos(angle)
        vy = retreat_speed * np.sin(angle)
        wz = np.sign(vy) * self._rng.uniform(0.5, 1.2) if abs(vy) > 0.05 else self._rng.uniform(-0.8, 0.8)

        return np.array([vx, vy, wz], dtype=np.float32)

    def _contact_force_direction(self) -> np.ndarray | None:
        """Return the dominant XY contact force direction, or None.

        Sums net forces across all G1 bodies, and returns the normalized
        XY direction if the total force magnitude exceeds 5 N (enough to
        reliably indicate an obstacle surface normal).
        """
        forces = getattr(self, '_contact_forces', None)
        if forces is None or not isinstance(forces, np.ndarray):
            return None

        # Sum forces across all bodies → (3,)
        total = forces.sum(axis=0) if forces.ndim == 2 else forces
        fx, fy = float(total[0]), float(total[1])
        mag = np.sqrt(fx * fx + fy * fy)

        if mag < 5.0:  # N — too small to be a reliable obstacle signal
            return None

        return np.array([fx / mag, fy / mag], dtype=np.float32)

    # ------------------------------------------------------------------
    # Scripted scenario support (Phase 3.2)
    # ------------------------------------------------------------------

    def _scripted_command(self) -> np.ndarray:
        """Advance the scripted phase sequence and return the current velocity.

        Automatically advances to the next phase when the current one's
        duration is exhausted.  The last phase (typically ``"idle"`` with
        ``duration_steps=9999``) holds until episode end.
        """
        phases = self.scripted_phases
        assert phases is not None  # caller must guard

        phase = phases[self._scripted_phase_idx]
        self._scripted_phase_name = phase.name
        self._phase = DisturbancePhase.WANDER
        # M6 fix: do NOT overwrite self._mode — the main loop's distance-gated
        # mode (AGGRESSIVE/MODERATE/CAUTIOUS) is the ground truth.  Overwriting
        # it to AGGRESSIVE causes metrics/logs to report the wrong mode when G1
        # is in MODERATE range during a scripted scenario.

        self._scripted_step_in_phase += 1
        if self._scripted_step_in_phase >= phase.duration_steps:
            # Advance to next phase.
            self._scripted_step_in_phase = 0
            if self._scripted_phase_idx + 1 < len(phases):
                self._scripted_phase_idx += 1
                phase = phases[self._scripted_phase_idx]
                self._scripted_phase_name = phase.name

        return np.array([phase.vx, phase.vy, phase.wz], dtype=np.float32)
