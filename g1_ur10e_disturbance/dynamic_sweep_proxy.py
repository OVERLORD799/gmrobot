"""World-coordinate lateral sweep proxy for B2 / B4-Dynamic pairing.

Pure-Python, testable without Isaac Sim.  Drives a scripted virtual-hand
centre through a fixed world trajectory during ``protocol_phase == transit``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

import numpy as np

from protocol_vhand import per_part_radius

# B2 proactive replan rules (GMRobot canonical names).
B2_PROACTIVE_TRIGGER_RULES = frozenset({"ttc", "ttc_forecast"})


class SweepLifecycle(str, Enum):
    IDLE = "idle"
    SWEEPING = "sweeping"
    RETREATING = "retreating"


@dataclass(frozen=True)
class DynamicSweepSpec:
    """Immutable sweep geometry — shared by B2 active and B4 shadow."""

    start_xyz: tuple[float, float, float]
    end_xyz: tuple[float, float, float]
    duration_steps: int
    retreat_duration_steps: int = 50
    trigger_phase: str = "transit"
    proxy_radius: float = 0.40
    ee_radius: float = 0.08
    seed: int = 42

    def trajectory_hash_params(self) -> dict[str, Any]:
        """Canonical dict for ``disturbance_trajectory_id`` (no enforcement mode)."""

        def _xyz(t: tuple[float, float, float]) -> list[float]:
            return [round(float(t[0]), 6), round(float(t[1]), 6), round(float(t[2]), 6)]

        return {
            "seed": int(self.seed),
            "start_xyz": _xyz(self.start_xyz),
            "end_xyz": _xyz(self.end_xyz),
            "duration_steps": int(self.duration_steps),
            "retreat_duration_steps": int(self.retreat_duration_steps),
            "trigger_phase": str(self.trigger_phase).lower(),
            "proxy_radius": round(float(self.proxy_radius), 6),
            "ee_radius": round(float(self.ee_radius), 6),
            "kind": "dynamic_lateral_sweep_proxy",
        }


def compute_disturbance_trajectory_id(params: dict[str, Any]) -> str:
    """Stable SHA-256 over canonical JSON (never Python ``hash()``)."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_b2_proactive_trigger_rule(rule: str) -> bool:
    r = (rule or "").strip().lower()
    return r in B2_PROACTIVE_TRIGGER_RULES


def project_surface_toward_ee(
    center: np.ndarray,
    ee_pos: np.ndarray,
    proxy_radius: float,
) -> np.ndarray:
    """Surface point on proxy sphere closest toward EE (safety gating geometry)."""
    to_ee = np.asarray(ee_pos, dtype=np.float64).reshape(3) - np.asarray(
        center, dtype=np.float64
    ).reshape(3)
    dist = float(np.linalg.norm(to_ee))
    if dist > 1e-9:
        return (center + (to_ee / dist) * float(proxy_radius)).astype(np.float32)
    return np.asarray(center, dtype=np.float32).copy()


def surface_distance_to_ee(
    center: np.ndarray,
    ee_pos: np.ndarray,
    proxy_radius: float,
    ee_radius: float,
) -> float:
    center_dist = float(np.linalg.norm(np.asarray(center) - np.asarray(ee_pos)))
    return max(0.0, center_dist - float(proxy_radius) - float(ee_radius))


def time_to_risk_steps_from_ttc(ttc_seconds: float | None, control_dt: float) -> str:
    """``ceil(ttc / dt)`` when finite and > 0; else empty string."""
    if ttc_seconds is None:
        return ""
    try:
        ttc = float(ttc_seconds)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(ttc) or ttc <= 0.0:
        return ""
    dt = max(float(control_dt), 1e-9)
    return str(int(math.ceil(ttc / dt)))


@dataclass
class SweepStepOutput:
    center_xyz: np.ndarray
    surface_xyz: np.ndarray
    surface_vel_xyz: np.ndarray
    center_vel_xyz: np.ndarray
    sweep_attempt_id: int
    sweep_progress: float
    lifecycle: SweepLifecycle
    surface_distance: float
    active_proxy_radius: float
    attempt_started: bool = False
    retreat_started: bool = False


@dataclass
class DynamicLateralSweepProxy:
    """Phase-triggered world-coordinate sweep with replan-gated retreat."""

    spec: DynamicSweepSpec
    control_dt: float = 0.02
    _lifecycle: SweepLifecycle = field(default=SweepLifecycle.IDLE, init=False)
    _sweep_attempt_id: int = field(default=0, init=False)
    _step_in_segment: int = field(default=0, init=False)
    _prev_protocol_phase: str = field(default="", init=False)
    _prev_surface: Optional[np.ndarray] = field(default=None, init=False)
    _prev_center: Optional[np.ndarray] = field(default=None, init=False)
    _retreat_origin: Optional[np.ndarray] = field(default=None, init=False)
    _retreat_pending: bool = field(default=False, init=False)
    _center_now: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32), init=False)
    first_intervention_step: Optional[int] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._center_now = np.array(self.spec.start_xyz, dtype=np.float32)

    @property
    def disturbance_trajectory_id(self) -> str:
        return compute_disturbance_trajectory_id(self.spec.trajectory_hash_params())

    @property
    def sweep_attempt_id(self) -> int:
        return self._sweep_attempt_id

    @property
    def lifecycle(self) -> SweepLifecycle:
        return self._lifecycle

    def reset_episode(self) -> None:
        self._lifecycle = SweepLifecycle.IDLE
        self._sweep_attempt_id = 0
        self._step_in_segment = 0
        self._prev_protocol_phase = ""
        self._prev_surface = None
        self._prev_center = None
        self._retreat_origin = None
        self._retreat_pending = False
        self._center_now = np.array(self.spec.start_xyz, dtype=np.float32)
        self.first_intervention_step = None

    def _is_trigger_phase(self, phase: str) -> bool:
        return (phase or "").lower() == self.spec.trigger_phase.lower()

    def _transit_edge(self, phase: str) -> bool:
        cur = (phase or "").lower()
        prev = (self._prev_protocol_phase or "").lower()
        return self._is_trigger_phase(cur) and prev != cur

    def on_replan_applied_active(self) -> None:
        """Active B2 only — queue retreat after successful replan apply."""
        if self._lifecycle == SweepLifecycle.SWEEPING:
            self._retreat_pending = True

    def note_first_intervention(self, sim_step: int) -> None:
        if self.first_intervention_step is None:
            self.first_intervention_step = int(sim_step)

    def step(
        self,
        *,
        protocol_phase: str,
        ee_pos: np.ndarray,
        enforcement_mode: str = "active",
        replan_applied_this_step: bool = False,
        phase_radii: PhaseProxyRadii | None = None,
    ) -> SweepStepOutput:
        """Advance one control step.  Shadow never retreats on replan."""
        phase_l = (protocol_phase or "").lower()
        attempt_started = False
        retreat_started = False
        mode = (enforcement_mode or "active").lower()
        radii = phase_radii or PhaseProxyRadii()
        active_radius = radii.for_phase(phase_l)
        transit_edge = self._transit_edge(phase_l)

        if transit_edge and self._lifecycle == SweepLifecycle.IDLE:
            self._sweep_attempt_id += 1
            self._lifecycle = SweepLifecycle.SWEEPING
            self._step_in_segment = 0
            attempt_started = True
            # P0-7: fresh velocity baseline at TRANSIT entry.
            self._prev_surface = None
            self._prev_center = None

        if (
            mode == "active"
            and replan_applied_this_step
            and self._lifecycle == SweepLifecycle.SWEEPING
        ):
            self._retreat_pending = True

        if self._retreat_pending and self._lifecycle == SweepLifecycle.SWEEPING:
            if mode == "active":
                self._retreat_origin = self._center_now.copy()
                self._lifecycle = SweepLifecycle.RETREATING
                self._step_in_segment = 0
                retreat_started = True
            self._retreat_pending = False

        if not self._is_trigger_phase(phase_l):
            # Outside TRANSIT: hold at start (inactive).
            self._lifecycle = SweepLifecycle.IDLE
            self._step_in_segment = 0
            self._center_now = np.array(self.spec.start_xyz, dtype=np.float32)
        elif self._lifecycle == SweepLifecycle.SWEEPING:
            self._advance_sweep()
        elif self._lifecycle == SweepLifecycle.RETREATING:
            done = self._advance_retreat()
            if done:
                self._lifecycle = SweepLifecycle.IDLE
                self._step_in_segment = 0

        self._prev_protocol_phase = phase_l

        surface = project_surface_toward_ee(
            self._center_now, ee_pos, active_radius
        )
        in_transit_motion = self._is_trigger_phase(phase_l) and (
            self._lifecycle in (SweepLifecycle.SWEEPING, SweepLifecycle.RETREATING)
        )
        dt = max(float(self.control_dt), 1e-9)
        if not in_transit_motion:
            surface_vel = np.zeros(3, dtype=np.float32)
            center_vel = np.zeros(3, dtype=np.float32)
            self._prev_surface = None
            self._prev_center = None
        elif self._prev_surface is None or self._prev_center is None:
            surface_vel = np.zeros(3, dtype=np.float32)
            center_vel = np.zeros(3, dtype=np.float32)
            self._prev_surface = surface.copy()
            self._prev_center = self._center_now.copy()
        else:
            surface_vel = ((surface - self._prev_surface) / dt).astype(np.float32)
            center_vel = (
                (self._center_now - self._prev_center) / dt
            ).astype(np.float32)
            self._prev_surface = surface.copy()
            self._prev_center = self._center_now.copy()

        dur = max(int(self.spec.duration_steps), 1)
        progress = (
            min(1.0, float(self._step_in_segment) / float(dur))
            if self._lifecycle == SweepLifecycle.SWEEPING
            else 0.0
        )

        return SweepStepOutput(
            center_xyz=self._center_now.copy(),
            surface_xyz=surface,
            surface_vel_xyz=surface_vel,
            center_vel_xyz=center_vel,
            sweep_attempt_id=self._sweep_attempt_id,
            sweep_progress=progress,
            lifecycle=self._lifecycle,
            surface_distance=surface_distance_to_ee(
                self._center_now, ee_pos, active_radius, self.spec.ee_radius
            ),
            active_proxy_radius=float(active_radius),
            attempt_started=attempt_started,
            retreat_started=retreat_started,
        )

    def _advance_sweep(self) -> None:
        start = np.array(self.spec.start_xyz, dtype=np.float64)
        end = np.array(self.spec.end_xyz, dtype=np.float64)
        dur = max(int(self.spec.duration_steps), 1)
        alpha = min(1.0, float(self._step_in_segment) / float(dur))
        self._center_now = (start + alpha * (end - start)).astype(np.float32)
        self._step_in_segment += 1
        if self._step_in_segment >= dur:
            # Hold at end until phase ends or retreat.
            self._center_now = end.astype(np.float32)

    def _advance_retreat(self) -> bool:
        """Linear retreat from frozen origin back to start_xyz."""
        start = np.array(self.spec.start_xyz, dtype=np.float64)
        origin = (
            np.asarray(self._retreat_origin, dtype=np.float64)
            if self._retreat_origin is not None
            else np.asarray(self._center_now, dtype=np.float64)
        )
        dur = max(int(self.spec.retreat_duration_steps), 1)
        alpha = min(1.0, float(self._step_in_segment) / float(dur))
        pos = origin + alpha * (start - origin)
        self._center_now = pos.astype(np.float32)
        self._step_in_segment += 1
        return self._step_in_segment >= dur


# Minimum clearance above hard-stop for transit-start acceptance (P0-8).
TRANSIT_START_MARGIN_M = 0.04


@dataclass(frozen=True)
class PhaseProxyRadii:
    """Per-protocol-phase proxy radii (TRANSIT sweep uses spec.proxy_radius)."""

    transit: float = 0.40
    pick_place: float = 0.08
    reset: float = 0.30

    @classmethod
    def from_mapping(cls, mapping: dict[str, float]) -> PhaseProxyRadii:
        return cls(
            transit=float(
                mapping.get("transit_proxy_radius")
                or mapping.get("transit_radius")
                or 0.40
            ),
            pick_place=float(
                mapping.get("pick_place_proxy_radius")
                or mapping.get("pick_place_radius")
                or 0.08
            ),
            reset=float(
                mapping.get("reset_proxy_radius")
                or mapping.get("reset_radius")
                or 0.30
            ),
        )

    def for_phase(self, phase: str) -> float:
        return per_part_radius(
            phase,
            transit_proxy_radius=self.transit,
            pick_place_proxy_radius=self.pick_place,
            reset_proxy_radius=self.reset,
        )


@dataclass(frozen=True)
class GeometryAuditSample:
    """One EE pose audited at sweep start with a phase-specific proxy radius."""

    label: str
    phase: str
    ee_xyz: tuple[float, float, float]
    proxy_radius: float
    surface_distance_m: float
    gating_distance_m: float
    margin_m: float
    gating_margin_m: float
    is_non_disturbance: bool


@dataclass(frozen=True)
class SweepGeometryReport:
    """Offline diagnostic for sweep start vs representative EE poses."""

    hard_stop_m: float
    warn_m: float
    transit_start_margin_m: float
    gating_distance_offset_m: float
    start_xyz: tuple[float, float, float]
    end_xyz: tuple[float, float, float]
    samples: tuple[GeometryAuditSample, ...]
    transit_start_min_surface_m: float
    transit_start_min_gating_m: float
    non_disturbance_min_surface_m: float
    non_disturbance_min_gating_m: float
    any_non_disturbance_inside_hard_stop: bool
    transit_start_margin_ok: bool

    @property
    def any_start_inside_hard_stop(self) -> bool:
        return not self.transit_start_margin_ok

    def summary_lines(self) -> list[str]:
        lines = [
            f"hard_stop={self.hard_stop_m:.3f} warn={self.warn_m:.3f} "
            f"transit_margin_req={self.transit_start_margin_m:.3f} "
            f"gating_offset={self.gating_distance_offset_m:.3f}",
            f"start={self.start_xyz} end={self.end_xyz}",
            f"transit_start_min_surface={self.transit_start_min_surface_m:.4f} "
            f"transit_start_min_gating={self.transit_start_min_gating_m:.4f} "
            f"margin_ok={self.transit_start_margin_ok}",
            f"non_disturbance_min_surface={self.non_disturbance_min_surface_m:.4f} "
            f"non_disturbance_min_gating={self.non_disturbance_min_gating_m:.4f} "
            f"inside_hard_stop={self.any_non_disturbance_inside_hard_stop}",
        ]
        for s in self.samples:
            lines.append(
                f"  {s.phase}@{s.label}: r={s.proxy_radius:.2f} "
                f"surf={s.surface_distance_m:.4f} gating={s.gating_distance_m:.4f} "
                f"margin={s.margin_m:.4f} gating_margin={s.gating_margin_m:.4f} "
                f"ee={s.ee_xyz}"
            )
        return lines

    def startup_errors(self) -> list[str]:
        errors: list[str] = []
        if self.any_non_disturbance_inside_hard_stop:
            errors.append(
                "non-disturbance phase gating distance inside hard-stop at sweep start"
            )
        if not self.transit_start_margin_ok:
            errors.append(
                f"transit start min gating {self.transit_start_min_gating_m:.4f}m "
                f"< hard_stop+margin "
                f"{self.hard_stop_m + self.transit_start_margin_m:.4f}m"
            )
        return errors


def default_geometry_ee_samples() -> tuple[tuple[str, str, tuple[float, float, float]], ...]:
    """Representative EE poses for pick / place / transit audit."""
    return (
        ("pick_slot", "pick", (0.53, -0.35, 0.30)),
        ("place_slot", "place", (0.75, 0.25, 0.30)),
        ("transit_edge_observed", "transit", (0.5254, -0.3473, 0.5521)),
        ("transit_corridor_a", "transit", (0.75, -0.25, 0.45)),
        ("transit_corridor_mid", "transit", (0.75, 0.0, 0.45)),
        ("transit_corridor_b", "transit", (0.75, 0.25, 0.45)),
        ("transit_held_mid", "transit", (0.70, 0.0, 0.50)),
    )


def sweep_geometry_precheck(
    spec: DynamicSweepSpec,
    *,
    phase_radii: PhaseProxyRadii,
    ee_samples: Sequence[tuple[str, str, tuple[float, float, float]]] | None = None,
    hard_stop_m: float,
    warn_m: float,
    transit_start_margin_m: float = TRANSIT_START_MARGIN_M,
    gating_distance_offset_m: float = 0.065,
) -> SweepGeometryReport:
    """Audit sweep geometry against loaded safety thresholds (P0-8)."""
    if ee_samples is None:
        ee_samples = default_geometry_ee_samples()
    start = np.array(spec.start_xyz, dtype=np.float64)
    rows: list[GeometryAuditSample] = []
    for label, phase, ee in ee_samples:
        radius = phase_radii.for_phase(phase)
        surf = surface_distance_to_ee(start, np.array(ee), radius, spec.ee_radius)
        gating = max(0.0, float(surf) - float(gating_distance_offset_m))
        rows.append(GeometryAuditSample(
            label=label,
            phase=phase,
            ee_xyz=ee,
            proxy_radius=radius,
            surface_distance_m=float(surf),
            gating_distance_m=float(gating),
            margin_m=float(surf - hard_stop_m),
            gating_margin_m=float(gating - hard_stop_m),
            is_non_disturbance=phase.lower() in ("pick", "place", "reset"),
        ))
    transit_rows = [r for r in rows if r.phase.lower() == "transit"]
    non_disturb = [r for r in rows if r.is_non_disturbance]
    transit_min = min((r.surface_distance_m for r in transit_rows), default=float("inf"))
    transit_gating_min = min((r.gating_distance_m for r in transit_rows), default=float("inf"))
    non_disturb_min = min((r.surface_distance_m for r in non_disturb), default=float("inf"))
    non_disturb_gating_min = min((r.gating_distance_m for r in non_disturb), default=float("inf"))
    required = float(hard_stop_m) + float(transit_start_margin_m)
    return SweepGeometryReport(
        hard_stop_m=float(hard_stop_m),
        warn_m=float(warn_m),
        transit_start_margin_m=float(transit_start_margin_m),
        gating_distance_offset_m=float(gating_distance_offset_m),
        start_xyz=spec.start_xyz,
        end_xyz=spec.end_xyz,
        samples=tuple(rows),
        transit_start_min_surface_m=float(transit_min),
        transit_start_min_gating_m=float(transit_gating_min),
        non_disturbance_min_surface_m=float(non_disturb_min),
        non_disturbance_min_gating_m=float(non_disturb_gating_min),
        any_non_disturbance_inside_hard_stop=non_disturb_gating_min <= float(hard_stop_m),
        transit_start_margin_ok=transit_gating_min > required,
    )


def commanded_trajectory_row(
    *,
    sim_step: int,
    output: SweepStepOutput,
    disturbance_trajectory_id: str,
) -> dict[str, str]:
    """One row for B2/B4 pre-intervention trajectory comparison."""
    c = output.center_xyz
    s = output.surface_xyz
    v = output.surface_vel_xyz
    return {
        "sim_step": str(sim_step),
        "disturbance_trajectory_id": disturbance_trajectory_id,
        "sweep_attempt_id": str(output.sweep_attempt_id),
        "sweep_progress": f"{output.sweep_progress:.6f}",
        "proxy_center_x": f"{float(c[0]):.6f}",
        "proxy_center_y": f"{float(c[1]):.6f}",
        "proxy_center_z": f"{float(c[2]):.6f}",
        "proxy_surface_x": f"{float(s[0]):.6f}",
        "proxy_surface_y": f"{float(s[1]):.6f}",
        "proxy_surface_z": f"{float(s[2]):.6f}",
        "sweep_velocity_x": f"{float(v[0]):.6f}",
        "sweep_velocity_y": f"{float(v[1]):.6f}",
        "sweep_velocity_z": f"{float(v[2]):.6f}",
    }
