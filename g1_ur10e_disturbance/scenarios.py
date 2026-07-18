"""Time-based hand scenarios with spherical-EE tracking.

Instead of a fixed world position, the obstacle sits on a sphere surface
centered at the EE.  This keeps surface distance CONSTANT regardless of
where the EE moves during replan detours.

Geometry:
  R = 0.23 m (sphere radius from EE centre)
  surface_dist = R - ee_radius = 0.23 - 0.08 = 0.15 m  (warn band centre)

Actions:
  home     — obstacle at (0,0,2.0), distance 999 m (safe)
  block    — obstacle on sphere surface, direction = toward containers
  retreat  — same as home
  track_ee — obstacle follows EE at surface_dist = 0.08 m (STOP zone edge)

Block directions (param):
  "left"   — toward Container A (y < 0)
  "right"  — toward Container B (y > 0)
  "front"  — toward G1 approach side (x < 0.75)
  "path"   — toward transit midpoint (0.75, 0.0)
"""

from __future__ import annotations

import numpy as np

R_SPHERE = 0.23        # obstacle centre distance from EE centre (m)
R_HAND = 0.10          # small hand radius — surface extends toward EE
SURFACE_DIST = R_SPHERE - 0.08  # 0.15 m — warn band centre

CONTAINER_A = np.array([0.75, -0.25], dtype=np.float32)
CONTAINER_B = np.array([0.75,  0.25], dtype=np.float32)
TRANSIT_MID = np.array([0.75, 0.0], dtype=np.float32)


def scenario_transit_block():
    """Pulses: short block triggers replan, retreat lets UR10e finish."""
    return [
        (0.0,  "home",    ""),
        (3.0,  "block",   "left"),
        (6.0,  "retreat", ""),
        (10.0, "block",   "right"),
        (13.0, "retreat", ""),
        (17.0, "block",   "path"),
        (20.0, "retreat", ""),
        (24.0, "block",   "front"),
        (27.0, "retreat", ""),
        (31.0, "home",    ""),
    ]


def scenario_empty_box():
    """Single-direction pulses near container A."""
    return [
        (0.0,  "home",    ""),
        (3.0,  "block",   "left"),
        (6.0,  "retreat", ""),
        (10.0, "block",   "left"),
        (13.0, "retreat", ""),
        (17.0, "home",    ""),
    ]


def scenario_fast_approach():
    """Fast pulse cadence."""
    return [
        (0.0,  "home",    ""),
        (3.0,  "block",   "path"),
        (5.0,  "retreat", ""),
        (7.0,  "block",   "right"),
        (9.0,  "retreat", ""),
        (11.0, "block",   "left"),
        (13.0, "retreat", ""),
        (16.0, "home",    ""),
    ]


def scenario_knock_off():
    """Pulses during track-ee phase."""
    return [
        (0.0,  "track_ee",""),
        (3.0,  "block",   "front"),
        (5.0,  "retreat", ""),
        (8.0,  "home",    ""),
    ]


SCENARIOS = {
    "empty_box":      scenario_empty_box,
    "fast_approach":  scenario_fast_approach,
    "transit_block":  scenario_transit_block,
    "knock_off":      scenario_knock_off,
}


class ScenarioHand:
    """Time-driven hand controller.  Returns action + direction string."""

    def __init__(self, timeline: list[tuple[float, str, str]]):
        self._timeline = sorted(timeline, key=lambda x: x[0])
        self._step_s = 0.02
        self._sim_time = 0.0

    def update(self, head_pos, ee_pos) -> dict:
        self._sim_time += self._step_s
        action, direction = self._lookup(self._sim_time)
        return {"action": action, "direction": direction}

    def _lookup(self, t: float) -> tuple[str, str]:
        action, param = "home", ""
        for start, act, p in self._timeline:
            if t >= start:
                action, param = act, p
        return action, param
