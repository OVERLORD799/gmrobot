"""Safety layer configuration."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# F10: single root for all output paths — override with GMROBOT_OUTPUT_DIR env var.
_DEFAULT_OUTPUT_ROOT = os.environ.get("GMROBOT_OUTPUT_DIR", "/root/GMRobot/output")


def resolve_output_path(rel_path: str) -> str:
    """Return ``{GMROBOT_OUTPUT_DIR}/{rel_path}``."""
    return os.path.join(_DEFAULT_OUTPUT_ROOT, rel_path)

# Canonical UR10e arm link names (shared across envelope, gt_branches, FK).
_DEFAULT_ARM_LINK_NAMES: list[str] = [
    "shoulder_link",
    "upper_arm_link",
    "forearm_link",
    "wrist_1_link",
    "wrist_2_link",
    "wrist_3_link",
]


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two dicts: override values win; nested dicts recurse (no list merging)."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge_dicts(merged[key], val)
        else:
            merged[key] = val
    return merged


@dataclass
class WorkspaceBounds:
    x_min: float = 0.1
    x_max: float = 1.1
    y_min: float = -0.5
    y_max: float = 0.5
    z_min: float = 0.0
    z_max: float = 0.8

    def contains(self, pos: Any) -> bool:
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        return (
            self.x_min <= x <= self.x_max
            and self.y_min <= y <= self.y_max
            and self.z_min <= z <= self.z_max
        )


@dataclass
class EnvelopeConfig:
    """Full-geometry envelope primitives (Phase 2.5a audit; 2.5b gating when enabled)."""

    gating_enabled: bool = False
    arm_link_names: list[str] = field(default_factory=lambda: list(_DEFAULT_ARM_LINK_NAMES))
    fingertip_link_names: list[str] = field(
        default_factory=lambda: [
            "left_outer_finger",
            "right_outer_finger",
        ]
    )
    arm_link_radius: float = 0.05
    fingertip_radius: float = 0.035
    held_box_dims_m: list[float] = field(
        default_factory=lambda: [0.05, 0.05, 0.17]
    )
    held_box_radius: float | None = None

    def effective_held_box_radius(self) -> float:
        if self.held_box_radius is not None:
            return float(self.held_box_radius)
        half = [float(d) * 0.5 for d in self.held_box_dims_m]
        return float(sum(h * h for h in half) ** 0.5)


@dataclass
class GtBranchesConfig:
    """Audit-only GT branches (log-only; never gate g_t)."""

    arm_links_enabled: bool = True
    contact_enabled: bool = True
    arm_link_names: list[str] = field(default_factory=lambda: list(_DEFAULT_ARM_LINK_NAMES))
    arm_link_radius: float = 0.05


@dataclass
class HumanTrajectoryConfig:
    type: str = "linear_approach"
    start_pos: list[float] = field(default_factory=lambda: [0.45, -0.35, 0.18])
    end_pos: list[float] = field(default_factory=lambda: [0.72, 0.0, 0.18])
    start_step: int = 150
    duration_steps: int = 100
    hold_far: bool = True
    # After approach: hold at end_pos (e.g. block placement opening), then optional retreat.
    hold_steps: int = 0
    retreat_pos: list[float] | None = None
    retreat_duration_steps: int = 55

    def approach_end_step(self) -> int:
        return self.start_step + self.duration_steps

    def hold_end_step(self) -> int:
        return self.approach_end_step() + self.hold_steps

    def retreat_end_step(self) -> int:
        if self.retreat_pos is None:
            return self.hold_end_step()
        return self.hold_end_step() + self.retreat_duration_steps

    def compute_pose(
        self, step_index: int, *, control_dt: float, eps: float = 1e-6
    ) -> tuple[Any, Any]:
        """Return (pos, vel) for this scripted trajectory at ``step_index``.

        Shared by ``HumanMotionController`` and proactive route replan so that
        changes to the trajectory model only need to be made in one place.
        """
        import numpy as np

        start = np.asarray(self.start_pos, dtype=np.float64)
        end = np.asarray(self.end_pos, dtype=np.float64)
        dt = max(control_dt, eps)
        approach_end = self.approach_end_step()
        hold_end = self.hold_end_step()
        retreat_end = self.retreat_end_step()

        if step_index < self.start_step:
            pos = start.copy()
            vel = np.zeros(3, dtype=np.float64)
        elif step_index < approach_end:
            alpha = (step_index - self.start_step) / max(self.duration_steps, 1)
            pos = start + alpha * (end - start)
            vel = (end - start) / max(self.duration_steps * dt, eps)
        elif step_index < hold_end:
            pos = end.copy()
            vel = np.zeros(3, dtype=np.float64)
        elif self.retreat_pos is not None and step_index < retreat_end:
            retreat = np.asarray(self.retreat_pos, dtype=np.float64)
            alpha = (step_index - hold_end) / max(self.retreat_duration_steps, 1)
            pos = end + alpha * (retreat - end)
            vel = (retreat - end) / max(self.retreat_duration_steps * dt, eps)
        elif self.retreat_pos is not None:
            pos = np.asarray(self.retreat_pos, dtype=np.float64)
            vel = np.zeros(3, dtype=np.float64)
        else:
            pos = end.copy()
            vel = np.zeros(3, dtype=np.float64)
        return pos, vel

    def is_approaching(self, step_index: int) -> bool:
        return self.start_step <= step_index < self.approach_end_step()

    def is_holding_at_end(self, step_index: int) -> bool:
        return self.approach_end_step() <= step_index < self.hold_end_step()

    def is_retreating(self, step_index: int) -> bool:
        if self.retreat_pos is None:
            return False
        return self.hold_end_step() <= step_index < self.retreat_end_step()


# ---------------------------------------------------------------------------
# Sub-config dataclasses — one responsibility per class (N2 refactor)
# ---------------------------------------------------------------------------

@dataclass
class StaticSafetySubConfig:
    """Static distance thresholds and slow-down blending."""
    safe_dist_static: float = 0.25
    safe_dist_hard_stop: float | None = 0.13
    safe_dist_warn: float | None = 0.16
    slow_down_alpha: float = 0.3
    slow_down_alpha_ttc: float | None = None
    slow_down_alpha_far: float = 0.55
    safe_dist_slow_far: float | None = None
    safe_dist_slow_far_envelope: float | None = None

    @property
    def effective_hard_stop(self) -> float:
        return self.safe_dist_hard_stop if self.safe_dist_hard_stop is not None else self.safe_dist_static

    @property
    def effective_warn(self) -> float:
        return self.safe_dist_warn if self.safe_dist_warn is not None else self.safe_dist_static


@dataclass
class TTCSubConfig:
    """Time-to-contact thresholds and replan triggering."""
    ttc_threshold: float = 0.5
    ttc_warn_threshold: float = 1.5
    ttc_dist_source: str = "envelope"
    ttc_replan_trigger_threshold: int = 6
    ttc_replan_hand_speed_min: float = 0.05
    ttc_forecast_replan_threshold: float | None = None
    # F3: how to handle dt≈0 in forecast approach-rate computation.
    # "skip" (default): do not compute a forecast rate when the sim time step
    #   is too small — physically honest, avoids underestimating the rate.
    # "control_dt": fall back to the nominal control period (legacy behaviour;
    #   may underestimate the approach rate when the real physics step is
    #   smaller than the control period, delaying forecast-triggered warnings).
    forecast_dt_fallback_mode: str = "skip"
    # F2: how to compute the velocity of the closest envelope primitive for
    # S7 Option C TTC (envelope-relative approach direction).
    # "ee_proxy" (default): use EE velocity for all primitives (legacy; fast,
    #   but kinematically inexact for arm-link primitives away from the wrist).
    # "finite_diff": compute the primitive's own velocity via forward-kinematics
    #   finite difference using joint velocities — physically correct to first
    #   order; requires joint_vel in SafetyState.
    ttc_primitive_vel_mode: str = "ee_proxy"


@dataclass
class ReplanSubConfig:
    """Motion replan geometry and trigger parameters."""
    lateral_offset_m: float = 0.10
    detour_stage_duration: int = 55
    trigger_threshold: int = 50
    use_perception_track_strategy: bool = False
    held_critical_replan_enabled: bool = False
    proactive_route_replan_enabled: bool = False
    proactive_route_horizon_steps: int = 80
    proactive_route_warn_gap_m: float = 0.19
    proactive_route_hard_gap_m: float = 0.13


@dataclass
class HumanModelSubConfig:
    """Human body model parameters."""
    hand_radius: float = 0.05
    ee_radius: float = 0.08
    torso_radius: float = 0.0
    torso_offset: list[float] = field(default_factory=lambda: [0.0, 0.0, -0.30])
    collision_threshold: float | None = None


@dataclass(init=False)
class SafetyConfig:
    # --- nested sub-configs ---
    static: StaticSafetySubConfig = field(default_factory=StaticSafetySubConfig)
    ttc: TTCSubConfig = field(default_factory=TTCSubConfig)
    replan: ReplanSubConfig = field(default_factory=ReplanSubConfig)
    human: HumanModelSubConfig = field(default_factory=HumanModelSubConfig)

    # --- top-level (no natural sub-group) ---
    workspace: WorkspaceBounds = field(default_factory=WorkspaceBounds)
    control_frequency: float = 50.0
    control_dt: float = 0.02
    gripper_boost_vel_threshold: float = 0.25
    gripper_boost_extra_closed: float = 0.15
    log_enabled: bool = True
    log_dir: str = field(default_factory=lambda: resolve_output_path("safety_logs"))
    human_enabled: bool = True
    human_trajectory: HumanTrajectoryConfig = field(default_factory=HumanTrajectoryConfig)
    eps: float = 1e-6
    gt_branches: GtBranchesConfig = field(default_factory=GtBranchesConfig)
    envelope: EnvelopeConfig = field(default_factory=EnvelopeConfig)
    expected_task_steps: int | None = None

    def __init__(
        self,
        *,
        # New-style sub-configs
        static: StaticSafetySubConfig | None = None,
        ttc: TTCSubConfig | None = None,
        replan: ReplanSubConfig | None = None,
        human: HumanModelSubConfig | None = None,
        # Top-level
        workspace: WorkspaceBounds | None = None,
        control_frequency: float = 50.0,
        control_dt: float = 0.02,
        gripper_boost_vel_threshold: float = 0.25,
        gripper_boost_extra_closed: float = 0.15,
        log_enabled: bool = True,
        log_dir: str | None = None,
        human_enabled: bool = True,
        human_trajectory: HumanTrajectoryConfig | None = None,
        eps: float = 1e-6,
        gt_branches: GtBranchesConfig | None = None,
        envelope: EnvelopeConfig | None = None,
        expected_task_steps: int | None = None,
        # Backward-compatible flat kwargs (populate sub-configs)
        safe_dist_static: float = 0.25,
        safe_dist_hard_stop: float | None = 0.13,
        safe_dist_warn: float | None = 0.16,
        slow_down_alpha: float = 0.3,
        slow_down_alpha_ttc: float | None = None,
        slow_down_alpha_far: float = 0.55,
        safe_dist_slow_far: float | None = None,
        safe_dist_slow_far_envelope: float | None = None,
        ttc_threshold: float = 0.5,
        ttc_warn_threshold: float = 1.5,
        ttc_dist_source: str = "envelope",
        ttc_replan_trigger_threshold: int = 6,
        ttc_replan_hand_speed_min: float = 0.05,
        ttc_forecast_replan_threshold: float | None = None,
        # F3 / F2: new TTC sub-config fields (see TTCSubConfig docstrings).
        ttc_forecast_dt_fallback_mode: str = "skip",
        ttc_primitive_vel_mode: str = "ee_proxy",
        replan_lateral_offset_m: float = 0.10,
        replan_detour_stage_duration: int = 55,
        replan_trigger_threshold: int = 50,
        use_perception_track_strategy: bool = False,
        held_critical_replan_enabled: bool = False,
        proactive_route_replan_enabled: bool = False,
        proactive_route_horizon_steps: int = 80,
        proactive_route_warn_gap_m: float = 0.19,
        proactive_route_hard_gap_m: float = 0.13,
        human_hand_radius: float = 0.05,
        human_torso_radius: float = 0.0,
        human_torso_offset: list[float] | None = None,
        ee_radius: float = 0.08,
        collision_threshold: float | None = None,
    ):
        self.static = static or StaticSafetySubConfig(
            safe_dist_static=safe_dist_static,
            safe_dist_hard_stop=safe_dist_hard_stop,
            safe_dist_warn=safe_dist_warn,
            slow_down_alpha=slow_down_alpha,
            slow_down_alpha_ttc=slow_down_alpha_ttc,
            slow_down_alpha_far=slow_down_alpha_far,
            safe_dist_slow_far=safe_dist_slow_far,
            safe_dist_slow_far_envelope=safe_dist_slow_far_envelope,
        )
        self.ttc = ttc or TTCSubConfig(
            ttc_threshold=ttc_threshold,
            ttc_warn_threshold=ttc_warn_threshold,
            ttc_dist_source=ttc_dist_source,
            ttc_replan_trigger_threshold=ttc_replan_trigger_threshold,
            ttc_replan_hand_speed_min=ttc_replan_hand_speed_min,
            ttc_forecast_replan_threshold=ttc_forecast_replan_threshold,
            forecast_dt_fallback_mode=ttc_forecast_dt_fallback_mode,
            ttc_primitive_vel_mode=ttc_primitive_vel_mode,
        )
        self.replan = replan or ReplanSubConfig(
            lateral_offset_m=replan_lateral_offset_m,
            detour_stage_duration=replan_detour_stage_duration,
            trigger_threshold=replan_trigger_threshold,
            use_perception_track_strategy=use_perception_track_strategy,
            held_critical_replan_enabled=held_critical_replan_enabled,
            proactive_route_replan_enabled=proactive_route_replan_enabled,
            proactive_route_horizon_steps=proactive_route_horizon_steps,
            proactive_route_warn_gap_m=proactive_route_warn_gap_m,
            proactive_route_hard_gap_m=proactive_route_hard_gap_m,
        )
        self.human = human or HumanModelSubConfig(
            hand_radius=human_hand_radius,
            ee_radius=ee_radius,
            torso_radius=human_torso_radius,
            torso_offset=human_torso_offset or [0.0, 0.0, -0.30],
            collision_threshold=collision_threshold,
        )
        self.workspace = workspace or WorkspaceBounds()
        self.control_frequency = control_frequency
        self.control_dt = control_dt
        self.gripper_boost_vel_threshold = gripper_boost_vel_threshold
        self.gripper_boost_extra_closed = gripper_boost_extra_closed
        self.log_enabled = log_enabled
        self.log_dir = log_dir if log_dir is not None else resolve_output_path("safety_logs")
        self.human_enabled = human_enabled
        self.human_trajectory = human_trajectory or HumanTrajectoryConfig()
        self.eps = eps
        self.gt_branches = gt_branches or GtBranchesConfig()
        self.envelope = envelope or EnvelopeConfig()
        self.expected_task_steps = expected_task_steps

    # ------------------------------------------------------------------
    # Backward-compatible flat accessors (delegate to sub-configs)
    # ------------------------------------------------------------------

    # -- static --
    @property
    def safe_dist_static(self) -> float: return self.static.safe_dist_static
    @safe_dist_static.setter
    def safe_dist_static(self, v: float): self.static.safe_dist_static = v

    @property
    def safe_dist_hard_stop(self) -> float | None: return self.static.safe_dist_hard_stop
    @safe_dist_hard_stop.setter
    def safe_dist_hard_stop(self, v: float | None): self.static.safe_dist_hard_stop = v

    @property
    def safe_dist_warn(self) -> float | None: return self.static.safe_dist_warn
    @safe_dist_warn.setter
    def safe_dist_warn(self, v: float | None): self.static.safe_dist_warn = v

    @property
    def slow_down_alpha(self) -> float: return self.static.slow_down_alpha
    @slow_down_alpha.setter
    def slow_down_alpha(self, v: float): self.static.slow_down_alpha = v

    @property
    def slow_down_alpha_ttc(self) -> float | None: return self.static.slow_down_alpha_ttc
    @slow_down_alpha_ttc.setter
    def slow_down_alpha_ttc(self, v: float | None): self.static.slow_down_alpha_ttc = v

    @property
    def slow_down_alpha_far(self) -> float: return self.static.slow_down_alpha_far
    @slow_down_alpha_far.setter
    def slow_down_alpha_far(self, v: float): self.static.slow_down_alpha_far = v

    @property
    def safe_dist_slow_far(self) -> float | None: return self.static.safe_dist_slow_far
    @safe_dist_slow_far.setter
    def safe_dist_slow_far(self, v: float | None): self.static.safe_dist_slow_far = v

    @property
    def safe_dist_slow_far_envelope(self) -> float | None: return self.static.safe_dist_slow_far_envelope
    @safe_dist_slow_far_envelope.setter
    def safe_dist_slow_far_envelope(self, v: float | None): self.static.safe_dist_slow_far_envelope = v

    @property
    def effective_hard_stop(self) -> float: return self.static.effective_hard_stop
    @property
    def effective_warn(self) -> float: return self.static.effective_warn

    # -- ttc --
    @property
    def ttc_threshold(self) -> float: return self.ttc.ttc_threshold
    @ttc_threshold.setter
    def ttc_threshold(self, v: float): self.ttc.ttc_threshold = v

    @property
    def ttc_warn_threshold(self) -> float: return self.ttc.ttc_warn_threshold
    @ttc_warn_threshold.setter
    def ttc_warn_threshold(self, v: float): self.ttc.ttc_warn_threshold = v

    @property
    def ttc_dist_source(self) -> str: return self.ttc.ttc_dist_source
    @ttc_dist_source.setter
    def ttc_dist_source(self, v: str): self.ttc.ttc_dist_source = v

    @property
    def ttc_replan_trigger_threshold(self) -> int: return self.ttc.ttc_replan_trigger_threshold
    @ttc_replan_trigger_threshold.setter
    def ttc_replan_trigger_threshold(self, v: int): self.ttc.ttc_replan_trigger_threshold = v

    @property
    def ttc_replan_hand_speed_min(self) -> float: return self.ttc.ttc_replan_hand_speed_min
    @ttc_replan_hand_speed_min.setter
    def ttc_replan_hand_speed_min(self, v: float): self.ttc.ttc_replan_hand_speed_min = v

    @property
    def ttc_forecast_replan_threshold(self) -> float | None: return self.ttc.ttc_forecast_replan_threshold
    @ttc_forecast_replan_threshold.setter
    def ttc_forecast_replan_threshold(self, v: float | None): self.ttc.ttc_forecast_replan_threshold = v

    @property
    def forecast_dt_fallback_mode(self) -> str: return self.ttc.forecast_dt_fallback_mode
    @forecast_dt_fallback_mode.setter
    def forecast_dt_fallback_mode(self, v: str): self.ttc.forecast_dt_fallback_mode = v

    @property
    def ttc_primitive_vel_mode(self) -> str: return self.ttc.ttc_primitive_vel_mode
    @ttc_primitive_vel_mode.setter
    def ttc_primitive_vel_mode(self, v: str): self.ttc.ttc_primitive_vel_mode = v

    # -- replan --
    @property
    def replan_lateral_offset_m(self) -> float: return self.replan.lateral_offset_m
    @replan_lateral_offset_m.setter
    def replan_lateral_offset_m(self, v: float): self.replan.lateral_offset_m = v

    @property
    def replan_detour_stage_duration(self) -> int: return self.replan.detour_stage_duration
    @replan_detour_stage_duration.setter
    def replan_detour_stage_duration(self, v: int): self.replan.detour_stage_duration = v

    @property
    def replan_trigger_threshold(self) -> int: return self.replan.trigger_threshold
    @replan_trigger_threshold.setter
    def replan_trigger_threshold(self, v: int): self.replan.trigger_threshold = v

    @property
    def use_perception_track_strategy(self) -> bool: return self.replan.use_perception_track_strategy
    @use_perception_track_strategy.setter
    def use_perception_track_strategy(self, v: bool): self.replan.use_perception_track_strategy = v

    @property
    def held_critical_replan_enabled(self) -> bool: return self.replan.held_critical_replan_enabled
    @held_critical_replan_enabled.setter
    def held_critical_replan_enabled(self, v: bool): self.replan.held_critical_replan_enabled = v

    @property
    def proactive_route_replan_enabled(self) -> bool: return self.replan.proactive_route_replan_enabled
    @proactive_route_replan_enabled.setter
    def proactive_route_replan_enabled(self, v: bool): self.replan.proactive_route_replan_enabled = v

    @property
    def proactive_route_horizon_steps(self) -> int: return self.replan.proactive_route_horizon_steps
    @proactive_route_horizon_steps.setter
    def proactive_route_horizon_steps(self, v: int): self.replan.proactive_route_horizon_steps = v

    @property
    def proactive_route_warn_gap_m(self) -> float: return self.replan.proactive_route_warn_gap_m
    @proactive_route_warn_gap_m.setter
    def proactive_route_warn_gap_m(self, v: float): self.replan.proactive_route_warn_gap_m = v

    @property
    def proactive_route_hard_gap_m(self) -> float: return self.replan.proactive_route_hard_gap_m
    @proactive_route_hard_gap_m.setter
    def proactive_route_hard_gap_m(self, v: float): self.replan.proactive_route_hard_gap_m = v

    # -- human --
    @property
    def human_hand_radius(self) -> float: return self.human.hand_radius
    @human_hand_radius.setter
    def human_hand_radius(self, v: float): self.human.hand_radius = v

    @property
    def human_torso_radius(self) -> float: return self.human.torso_radius
    @human_torso_radius.setter
    def human_torso_radius(self, v: float): self.human.torso_radius = v

    @property
    def human_torso_offset(self) -> list[float]: return self.human.torso_offset
    @human_torso_offset.setter
    def human_torso_offset(self, v: list[float]): self.human.torso_offset = v

    @property
    def ee_radius(self) -> float: return self.human.ee_radius
    @ee_radius.setter
    def ee_radius(self, v: float): self.human.ee_radius = v

    @property
    def collision_threshold(self) -> float | None: return self.human.collision_threshold
    @collision_threshold.setter
    def collision_threshold(self, v: float | None): self.human.collision_threshold = v

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafetyConfig:
        workspace_data = data.get("workspace", {})
        workspace = WorkspaceBounds(
            x_min=workspace_data.get("x", [0.1, 1.1])[0],
            x_max=workspace_data.get("x", [0.1, 1.1])[1],
            y_min=workspace_data.get("y", [-0.5, 0.5])[0],
            y_max=workspace_data.get("y", [-0.5, 0.5])[1],
            z_min=workspace_data.get("z", [0.0, 0.8])[0],
            z_max=workspace_data.get("z", [0.0, 0.8])[1],
        )
        traj_data = data.get("human_trajectory", {})
        retreat_raw = traj_data.get("retreat_pos")
        human_trajectory = HumanTrajectoryConfig(
            type=traj_data.get("type", "linear_approach"),
            start_pos=list(traj_data.get("start_pos", [0.45, -0.35, 0.18])),
            end_pos=list(traj_data.get("end_pos", [0.72, 0.0, 0.18])),
            start_step=int(traj_data.get("start_step", 150)),
            duration_steps=int(traj_data.get("duration_steps", 100)),
            hold_far=bool(traj_data.get("hold_far", True)),
            hold_steps=int(traj_data.get("hold_steps", 0)),
            retreat_pos=list(retreat_raw) if retreat_raw is not None else None,
            retreat_duration_steps=int(traj_data.get("retreat_duration_steps", 55)),
        )
        control_frequency = float(data.get("control_frequency", 50.0))
        control_dt = float(data.get("control_dt", 1.0 / control_frequency))

        safe_dist_static = float(data.get("safe_dist_static", 0.25))
        hard_stop_raw = data.get("safe_dist_hard_stop")
        warn_raw = data.get("safe_dist_warn")
        if hard_stop_raw is None and warn_raw is None and "safe_dist_static" in data:
            warnings.warn(
                "safe_dist_static is deprecated — set safe_dist_hard_stop and "
                "safe_dist_warn explicitly in your YAML config.  Falling back to "
                "STOP-only mode (no SLOW_DOWN warn band).",
                DeprecationWarning,
                stacklevel=2,
            )
            safe_dist_hard_stop = safe_dist_static
            safe_dist_warn = safe_dist_static
        else:
            ee_r = float(data.get("ee_radius", 0.08))
            hand_r = float(data.get("human_hand_radius", 0.05))
            default_collision = hand_r + ee_r
            safe_dist_hard_stop = (
                float(hard_stop_raw)
                if hard_stop_raw is not None
                else max(safe_dist_static, default_collision)
            )
            safe_dist_warn = (
                float(warn_raw) if warn_raw is not None
                else max(safe_dist_hard_stop + 0.03, 0.16)
            )

        # F4: validate warn >= hard_stop invariant (2026-07-01 review).
        # Without this, custom hard_stop > 0.16 would place the SLOW_DOWN band
        # inside the STOP zone — geometrically broken.
        if safe_dist_warn < safe_dist_hard_stop:
            warnings.warn(
                f"safe_dist_warn ({safe_dist_warn:.2f}m) < safe_dist_hard_stop "
                f"({safe_dist_hard_stop:.2f}m): SLOW_DOWN band is inverted. "
                f"Capping safe_dist_warn to safe_dist_hard_stop.",
                RuntimeWarning,
                stacklevel=2,
            )
            safe_dist_warn = safe_dist_hard_stop

        gt_data = data.get("gt_branches", {})
        gt_branches = GtBranchesConfig(
            arm_links_enabled=bool(gt_data.get("arm_links_enabled", True)),
            contact_enabled=bool(gt_data.get("contact_enabled", True)),
            arm_link_names=list(
                gt_data.get("arm_link_names", _DEFAULT_ARM_LINK_NAMES)
            ),
            arm_link_radius=float(gt_data.get("arm_link_radius", 0.05)),
        )

        envelope_data = data.get("envelope", {})
        held_radius_raw = envelope_data.get("held_box_radius")
        envelope = EnvelopeConfig(
            gating_enabled=bool(envelope_data.get("gating_enabled", False)),
            arm_link_names=list(
                envelope_data.get("arm_link_names", _DEFAULT_ARM_LINK_NAMES)
            ),
            fingertip_link_names=list(
                envelope_data.get(
                    "fingertip_link_names",
                    ["left_outer_finger", "right_outer_finger"],
                )
            ),
            arm_link_radius=float(envelope_data.get("arm_link_radius", 0.05)),
            fingertip_radius=float(envelope_data.get("fingertip_radius", 0.035)),
            held_box_dims_m=list(
                envelope_data.get("held_box_dims_m", [0.05, 0.05, 0.17])
            ),
            held_box_radius=(
                float(held_radius_raw) if held_radius_raw is not None else None
            ),
        )

        expected_task_steps_raw = data.get("expected_task_steps")
        expected_task_steps = (
            int(expected_task_steps_raw) if expected_task_steps_raw is not None else None
        )

        return cls(
            static=StaticSafetySubConfig(
                safe_dist_static=safe_dist_static,
                safe_dist_hard_stop=safe_dist_hard_stop,
                safe_dist_warn=safe_dist_warn,
                slow_down_alpha=float(data.get("slow_down_alpha", 0.3)),
                slow_down_alpha_ttc=(
                    float(data["slow_down_alpha_ttc"])
                    if data.get("slow_down_alpha_ttc") is not None else None
                ),
                slow_down_alpha_far=float(data.get("slow_down_alpha_far", 0.55)),
                safe_dist_slow_far=(
                    float(data["safe_dist_slow_far"])
                    if data.get("safe_dist_slow_far") is not None else None
                ),
                safe_dist_slow_far_envelope=(
                    float(data["safe_dist_slow_far_envelope"])
                    if data.get("safe_dist_slow_far_envelope") is not None else None
                ),
            ),
            ttc=TTCSubConfig(
                ttc_threshold=float(data.get("ttc_threshold", 0.5)),
                ttc_warn_threshold=float(data.get("ttc_warn_threshold", 1.5)),
                ttc_dist_source=str(data.get("ttc_dist_source", "envelope")),
                ttc_replan_trigger_threshold=int(data.get("ttc_replan_trigger_threshold", 6)),
                ttc_replan_hand_speed_min=float(data.get("ttc_replan_hand_speed_min", 0.05)),
                ttc_forecast_replan_threshold=(
                    float(data["ttc_forecast_replan_threshold"])
                    if data.get("ttc_forecast_replan_threshold") is not None else None
                ),
                forecast_dt_fallback_mode=str(data.get("forecast_dt_fallback_mode", "skip")),
                ttc_primitive_vel_mode=str(data.get("ttc_primitive_vel_mode", "ee_proxy")),
            ),
            replan=ReplanSubConfig(
                lateral_offset_m=float(data.get("replan_lateral_offset_m", 0.10)),
                detour_stage_duration=int(data.get("replan_detour_stage_duration", 55)),
                trigger_threshold=int(data.get("replan_trigger_threshold", 50)),
                use_perception_track_strategy=bool(data.get("use_perception_track_strategy", False)),
                held_critical_replan_enabled=bool(data.get("held_critical_replan_enabled", False)),
                proactive_route_replan_enabled=bool(data.get("proactive_route_replan_enabled", False)),
                proactive_route_horizon_steps=int(data.get("proactive_route_horizon_steps", 80)),
                proactive_route_warn_gap_m=float(data.get("proactive_route_warn_gap_m", 0.19)),
                proactive_route_hard_gap_m=float(data.get("proactive_route_hard_gap_m", 0.13)),
            ),
            human=HumanModelSubConfig(
                hand_radius=float(data.get("human_hand_radius", 0.05)),
                ee_radius=float(data.get("ee_radius", 0.08)),
                torso_radius=float(data.get("human_torso_radius", 0.0)),
                torso_offset=[float(x) for x in data.get("human_torso_offset", [0.0, 0.0, -0.30])],
                collision_threshold=(
                    float(data["collision_threshold"])
                    if data.get("collision_threshold") is not None else None
                ),
            ),
            workspace=workspace,
            control_frequency=control_frequency,
            control_dt=control_dt,
            gripper_boost_vel_threshold=float(data.get("gripper_boost_vel_threshold", 0.25)),
            gripper_boost_extra_closed=float(data.get("gripper_boost_extra_closed", 0.15)),
            log_enabled=bool(data.get("log_enabled", True)),
            log_dir=str(data.get("log_dir", resolve_output_path("safety_logs"))),
            human_enabled=bool(data.get("human_enabled", True)),
            human_trajectory=human_trajectory,
            eps=float(data.get("eps", 1e-6)),
            gt_branches=gt_branches,
            envelope=envelope,
            expected_task_steps=expected_task_steps,
        )


def _find_repo_root() -> Path | None:
    """Walk up from this file until we find .git or setup.py."""
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / ".git").exists() or (parent / "setup.py").exists():
            return parent
    return None


def _default_config_path(filename: str) -> Path | None:
    root = _find_repo_root()
    if root is None:
        return None
    candidate = root / "configs" / filename
    return candidate if candidate.is_file() else None


def load_safety_config(path: str | Path | None = None) -> SafetyConfig:
    if path is None:
        path = _default_config_path("safety_layer1.yaml")
    if path is None:
        return SafetyConfig()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # IV-J base inheritance: deep-merge base config before overrides.
    base_rel = data.pop("base", None)
    if base_rel is not None:
        base_path = Path(path).resolve().parent / base_rel
        if base_path.is_file():
            with open(base_path, encoding="utf-8") as bf:
                base_data = yaml.safe_load(bf) or {}
            data = _deep_merge_dicts(base_data, data)

    return SafetyConfig.from_dict(data)
