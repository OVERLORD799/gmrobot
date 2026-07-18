"""Config loader for G1-UR10e Disturbance.

Reads ``config/default.yaml`` and returns a frozen-ish dataclass tree.
Call ``load_config(path=None)`` to get the defaults; pass an explicit
``path`` to override the YAML source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Dict

import numpy as np
import yaml

from paths import DEFAULT_CONFIG_PATH as _DEFAULT_CONFIG_PATH


# ---------------------------------------------------------------------------
# Sub-configs (mirror default.yaml sections)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DisturbanceConfig:
    """Fields actually wired to G1DisturbanceController constructor.

    All other behaviour (velocity ranges, boundary steering, stuck
    detection, schedule generation) uses module-level constants in
    ``g1_disturbance_controller.py``.
    """
    cautious_threshold: float = 0.15
    moderate_threshold: float = 0.55  # synced with default.yaml (F1 fix: was 0.30)
    speed_aggressive: float = 0.20
    speed_moderate: float = 0.10
    speed_cautious: float = 0.0
    workspace_x: Tuple[float, float] = (0.0, 0.8)
    workspace_y: Tuple[float, float] = (-0.5, 0.5)
    vy_scale: float = 0.0       # 0 = disabled (safe); 0.05 = narrow lateral exploration
    resample_interval: int = 200


@dataclass(frozen=True)
class ArmConfig:
    length: float = 0.8             # m — nominal arm reach from head
    length_fixed: bool = True       # true = clamp to exactly length; false = variable
    length_min: float = 0.0         # m — min arm length (0 = no min, only used when length_fixed=False)
    length_max: float = 0.0         # m — max arm length (0 = no max, only used when length_fixed=False)


@dataclass(frozen=True)
class VirtualHandConfig:
    """Virtual hand tunables actually consumed by G1VirtualHand / run_phase3.py.

    All other behaviour (velocity persistence, attractor strength, corridor
    geometry, table obstacle margins, reflection damping) is controlled by
    module-level constants in ``g1_virtual_hand.py``.  Those constants are
    tuned for the standard GMDisturb scene and rarely need changing.
    """
    default_radius: float = 0.45
    height_mode: str = "table"


@dataclass(frozen=True)
class VLMSSHConfig:
    host: str = ""
    port: int = 30481
    user: str = "root"
    password: str = ""
    key: str = ""


@dataclass(frozen=True)
class VLMConfig:
    # SSH tunnel (optional — leave host empty to skip tunnel)
    ssh: VLMSSHConfig = field(default_factory=VLMSSHConfig)
    # VLM service endpoint
    host: str = "localhost"
    port: int = 8080
    # Query settings
    interval: int = 200
    scene_interval: int = 800   # R7: scene-camera strategic query interval (steps)
    min_interval_s: float = 2.0
    log_every_n: int = 5
    # Mapping from action name → (vx, vy, wz) list.  Callers convert to np.array.
    actions: Dict[str, Tuple[float, float, float]] = field(default_factory=lambda: {
        "circle_left":  (0.10, 0.0,  0.3),
        "circle_right": (0.10, 0.0, -0.3),
        "approach":     (0.25, 0.0,  0.0),
        "retreat":      (-0.20, 0.0, 0.0),
        "stand_wave":   (0.0,  0.0,  0.0),
    })
    blend_vlm_weight: float = 0.4
    blend_corridor_weight: float = 0.6
    corridor_pull_gain: float = 0.35
    corridor_activate_dist: float = 0.1
    boundary_max_dist: float = 2.0
    boundary_spring_gain: float = 0.2


@dataclass(frozen=True)
class ReplanConfig:
    trigger_threshold: int = 5   # synced with default.yaml (was 25 — stale GMRobot default)
    detour_lateral_m: float = 0.10
    detour_duration: int = 55
    # ponytail: cooldown_steps / slow_decay / detour_raise_m removed —
    # GMRobot ReplanTriggerConfig manages its own cooldown (200 steps),
    # sustained_slow decay is handled internally by the trigger, and
    # raise_approach_m lives on ReplanHint (default 0.05, wired via
    # triggers.py, not through GMDisturb config).


@dataclass(frozen=True)
class EETrackConfig:
    body: str = "wrist_3_link"
    offset: Tuple[float, float, float] = (0.0, 0.0, 0.02)


@dataclass(frozen=True)
class SafetyConfig:
    control_dt: float = 0.02
    tilt_threshold_rad: float = 0.35
    collapse_z: float = -1.0
    replan: ReplanConfig = field(default_factory=ReplanConfig)
    ee_track: EETrackConfig = field(default_factory=EETrackConfig)


@dataclass(frozen=True)
class BatchConfig:
    max_steps: int = 10000
    progress_interval: int = 200
    mode_default: str = "auto"
    repeats_default: int = 1
    output_csv: str = "/tmp/gmdisturb_phase3.csv"


@dataclass(frozen=True)
class Phase3Config:
    arm: ArmConfig = field(default_factory=ArmConfig)
    disturbance: DisturbanceConfig = field(default_factory=DisturbanceConfig)
    virtual_hand: VirtualHandConfig = field(default_factory=VirtualHandConfig)
    vlm: VLMConfig = field(default_factory=VLMConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)

    # ------------------------------------------------------------------
    # Convenience accessors that return np.array-ready values for
    # run_phase3.py hot paths.
    # ------------------------------------------------------------------

    @property
    def vlm_action_cmd(self) -> Dict[str, np.ndarray]:
        """VLM action names → numpy velocity vectors."""
        return {
            name: np.array(vec, dtype=np.float32)
            for name, vec in self.vlm.actions.items()
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _deep_update(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_update(merged[key], value)
        else:
            merged[key] = value
    return merged


def _build_config(raw: dict) -> Phase3Config:
    """Construct a Phase3Config from a raw (possibly partial) YAML dict."""

    # --- disturbance ---
    d_raw = raw.get("disturbance", {})
    disturbance = DisturbanceConfig(
        cautious_threshold=float(d_raw.get("cautious_threshold", 0.15)),
        moderate_threshold=float(d_raw.get("moderate_threshold", 0.55)),
        speed_aggressive=float(d_raw.get("speed_aggressive", 0.20)),
        speed_moderate=float(d_raw.get("speed_moderate", 0.10)),
        speed_cautious=float(d_raw.get("speed_cautious", 0.0)),
        workspace_x=tuple(d_raw.get("workspace_x", (0.0, 0.8))),
        workspace_y=tuple(d_raw.get("workspace_y", (-0.5, 0.5))),
        vy_scale=float(d_raw.get("vy_scale", 0.0)),
        resample_interval=int(d_raw.get("resample_interval", 200)),
    )

    # --- virtual_hand (only fields consumed by run_phase3.py / G1VirtualHand) ---
    vh_raw = raw.get("virtual_hand", {})
    virtual_hand = VirtualHandConfig(
        default_radius=float(vh_raw.get("default_radius", 0.45)),
        height_mode=str(vh_raw.get("height_mode", "table")),
    )

    # --- vlm ---
    vlm_raw = raw.get("vlm", {})
    vlm_actions = {}
    for name, vec in vlm_raw.get("actions", {}).items():
        vlm_actions[str(name)] = (float(vec[0]), float(vec[1]), float(vec[2]))
    # SSH sub-config
    ssh_raw = vlm_raw.get("ssh", {})
    vlm_ssh = VLMSSHConfig(
        host=str(ssh_raw.get("host", "")),
        port=int(ssh_raw.get("port", 30481)),
        user=str(ssh_raw.get("user", "root")),
        password=str(ssh_raw.get("password", "")),
        key=str(ssh_raw.get("key", "")),
    )
    vlm = VLMConfig(
        ssh=vlm_ssh,
        host=str(vlm_raw.get("host", "localhost")),
        port=int(vlm_raw.get("port", 8080)),
        interval=int(vlm_raw.get("interval", 200)),
        scene_interval=int(vlm_raw.get("scene_interval", 800)),
        min_interval_s=float(vlm_raw.get("min_interval_s", 2.0)),
        log_every_n=int(vlm_raw.get("log_every_n", 5)),
        actions=vlm_actions if vlm_actions else VLMConfig().actions,
        blend_vlm_weight=float(vlm_raw.get("blend_vlm_weight", 0.4)),
        blend_corridor_weight=float(vlm_raw.get("blend_corridor_weight", 0.6)),
        corridor_pull_gain=float(vlm_raw.get("corridor_pull_gain", 0.35)),
        corridor_activate_dist=float(vlm_raw.get("corridor_activate_dist", 0.1)),
        boundary_max_dist=float(vlm_raw.get("boundary_max_dist", 2.0)),
        boundary_spring_gain=float(vlm_raw.get("boundary_spring_gain", 0.2)),
    )

    # --- safety ---
    s_raw = raw.get("safety", {})
    # --- ee_track ---
    et_raw = raw.get("ee_track", {})
    ee_track = EETrackConfig(
        body=str(et_raw.get("ee_track_body", "wrist_3_link")),
        offset=tuple(et_raw.get("ee_track_offset", (0.0, 0.0, 0.02))),
    )
    r_raw = s_raw.get("replan", {})
    replan = ReplanConfig(
        trigger_threshold=int(r_raw.get("trigger_threshold", 5)),
        detour_lateral_m=float(r_raw.get("detour_lateral_m", 0.10)),
        detour_duration=int(r_raw.get("detour_duration", 55)),
    )
    safety = SafetyConfig(
        control_dt=float(s_raw.get("control_dt", 0.02)),
        tilt_threshold_rad=float(s_raw.get("tilt_threshold_rad", 0.35)),
        collapse_z=float(s_raw.get("collapse_z", -1.0)),
        replan=replan,
        ee_track=ee_track,
    )

    # --- batch ---
    b_raw = raw.get("batch", {})
    batch = BatchConfig(
        max_steps=int(b_raw.get("max_steps", 10000)),
        progress_interval=int(b_raw.get("progress_interval", 200)),
        mode_default=str(b_raw.get("mode_default", "auto")),
        repeats_default=int(b_raw.get("repeats_default", 1)),
        output_csv=str(b_raw.get("output_csv", "/tmp/gmdisturb_phase3.csv")),
    )

    # --- arm ---
    a_raw = raw.get("arm", {})
    arm = ArmConfig(
        length=float(a_raw.get("arm_length", 0.8)),
        length_fixed=bool(a_raw.get("arm_length_fixed", True)),
        length_min=float(a_raw.get("arm_length_min", 0.0)),
        length_max=float(a_raw.get("arm_length_max", 0.0)),
    )

    return Phase3Config(
        arm=arm,
        disturbance=disturbance,
        virtual_hand=virtual_hand,
        vlm=vlm,
        safety=safety,
        batch=batch,
    )


def load_config(path: Optional[str] = None) -> Phase3Config:
    """Load configuration from *path* (or the default YAML).

    Parameters
    ----------
    path : str or None
        Override path to a YAML file.  When ``None``, the default
        ``config/default.yaml`` is used.  The file may be a partial
        override — missing keys fall back to the dataclass defaults.

    Returns
    -------
    Phase3Config
        Frozen configuration object with attribute-style access.
    """
    yaml_path = Path(path) if path else Path(_DEFAULT_CONFIG_PATH)

    raw: dict = {}
    if yaml_path.is_file():
        with open(yaml_path, "r") as fh:
            raw = yaml.safe_load(fh) or {}

    return _build_config(raw)
