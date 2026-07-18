# Tactile observation + deploy-walk observation helpers
# Migrated from pressure_mat_repro/mdp/observations.py for Isaac Lab 2.x.
#
# Import paths rewired: omni.isaac.lab.* → isaaclab.*
# Functions carried over: tactile_force_multi_net, Pasternak helpers,
# velocity_commands_deploy, walk_sin/cos_phase, last_action_padded_29.
# Logic and calibration formulas UNCHANGED.

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv


# ===========================================================================
# Pasternak shear coupling helpers (cache + Gaussian blur)
# ===========================================================================

_KERNEL_CACHE: dict[tuple, tuple[torch.Tensor, int]] = {}
"""Cache of 1-D Gaussian kernels keyed by (id(env), rows, cols, sigma_pixels)."""


def _build_gaussian_kernel(
    sigma_pixels: float, device: torch.device
) -> tuple[torch.Tensor, int]:
    """Return a 1-D normalized Gaussian kernel and its half-width."""
    if sigma_pixels <= 0.0:
        return torch.tensor([1.0], device=device), 0
    radius = max(1, int(math.ceil(3.0 * sigma_pixels)))
    xs = torch.arange(-radius, radius + 1, device=device, dtype=torch.float32)
    kernel = torch.exp(-0.5 * (xs / sigma_pixels) ** 2)
    kernel = kernel / kernel.sum()
    return kernel, radius


def _gaussian_blur_2d(
    image: torch.Tensor, kernel_1d: torch.Tensor, radius: int
) -> torch.Tensor:
    """Apply a separable 2-D Gaussian blur to an (N, R, C) image."""
    if radius == 0:
        return image
    x = image.unsqueeze(1)  # (N, 1, R, C)
    k_h = kernel_1d.view(1, 1, -1, 1)
    k_w = kernel_1d.view(1, 1, 1, -1)
    x = torch.nn.functional.pad(x, (0, 0, radius, radius), mode="reflect")
    x = torch.nn.functional.conv2d(x, k_h)
    x = torch.nn.functional.pad(x, (radius, radius, 0, 0), mode="reflect")
    x = torch.nn.functional.conv2d(x, k_w)
    return x.squeeze(1)


def _apply_pasternak(
    summed: torch.Tensor,
    rows: int,
    cols: int,
    coupling_length: float,
    mat_size_x: float,
    mat_size_y: float,
    env: "ManagerBasedEnv",
) -> torch.Tensor:
    """Reshape flat taxel vector to (N, R, C) and optionally Pasternak-smear."""
    image = summed.view(-1, rows, cols)
    if coupling_length > 0.0:
        pitch_x = mat_size_x / cols
        pitch_y = mat_size_y / rows
        sigma_pixels = coupling_length / min(pitch_x, pitch_y)
        kern_key = (id(env), rows, cols, round(sigma_pixels, 4))
        cached = _KERNEL_CACHE.get(kern_key)
        if cached is None:
            cached = _build_gaussian_kernel(sigma_pixels, image.device)
            _KERNEL_CACHE[kern_key] = cached
        kernel_1d, radius = cached
        image = _gaussian_blur_2d(image, kernel_1d, radius)
    return image


# ===========================================================================
# Main tactile observation function
# ===========================================================================

def tactile_force_multi_net(
    env: "ManagerBasedEnv",
    sensor_names: list[str],
    rows: int = 32,
    cols: int = 32,
    coupling_length: float = 0.0,
    mat_size_x: float = 1.0,
    mat_size_y: float = 1.0,
    physics_calibrate: bool = True,
) -> torch.Tensor:
    """Per-taxel Newton image calibrated via ``net_forces_w``.

    Reads ``ContactSensor.data.force_matrix_w`` from each named sensor,
    extracts the Z-component (normal force), optionally calibrates the
    magnitude against ``sensor.data.net_forces_w[..., 2]`` (the PhysX
    impulse-buffer ground reaction force — correct for articulated feet),
    sums across sensors, reshapes to ``(num_envs, rows, cols)``, and
    optionally applies Pasternak Gaussian smearing.

    Args:
        env: Manager-based environment.
        sensor_names: Scene-entity names of per-foot ContactSensors.
        rows, cols: Taxel grid dimensions.
        coupling_length: Pasternak coupling length in meters (0 = disabled).
        mat_size_x, mat_size_y: Total mat extent in meters.
        physics_calibrate: Enable per-sensor scaling via net_forces_w.

    Returns:
        ``(num_envs, rows, cols)`` Newton image, summed across sensors.
    """
    expected_taxels = rows * cols
    summed: torch.Tensor | None = None
    eps = 1e-3

    for sname in sensor_names:
        sensor = env.scene.sensors[sname]
        fmat = sensor.data.force_matrix_w
        if fmat is None:
            continue
        if fmat.shape[-2] != expected_taxels:
            raise RuntimeError(
                f"Pressure mat sensor '{sname}' reports {fmat.shape[-2]} filter "
                f"bodies, expected {expected_taxels} (= {rows}x{cols})."
            )
        per_taxel = fmat[:, 0, :, 2]  # (N, R*C)
        reported_total = per_taxel.sum(dim=-1)  # (N,)

        if physics_calibrate:
            expected_total = sensor.data.net_forces_w[:, 0, 2]  # (N,)
            expected_total = torch.clamp(expected_total, min=0.0)
            in_contact = reported_total > eps
            scale = torch.where(
                in_contact,
                torch.clamp(
                    expected_total / torch.clamp(reported_total, min=eps),
                    max=10.0,  # R3 M2 fix: cap calibration to prevent single-frame explosion
                ),
                torch.ones_like(reported_total),
            )
            per_taxel = per_taxel * scale.unsqueeze(-1)

        if summed is None:
            summed = per_taxel.clone()
        else:
            summed = summed + per_taxel

    if summed is None:
        device = env.scene.env_origins.device
        summed = torch.zeros(env.num_envs, expected_taxels, device=device)

    return _apply_pasternak(summed, rows, cols, coupling_length, mat_size_x, mat_size_y, env)


# ===========================================================================
# Deploy-walk observation helpers
# ===========================================================================

_LEG_INDICES_IN_29 = [0, 1, 3, 4, 6, 7, 9, 10, 13, 14, 17, 18]
_MAX_CMD = (0.8, 0.5, 1.57)
_STAND_THRESHOLD = 0.1
PHASE_PERIOD: float = 0.65
"""Walk gait phase period in seconds. Exported as mdp.PHASE_PERIOD."""


def _is_standing_still(env, command_name: str) -> torch.Tensor:
    """(N,1) bool: True when all joystick-equivalent cmd magnitudes < threshold."""
    cmd = env.command_manager.get_command(command_name)
    max_cmd = torch.tensor(_MAX_CMD, device=cmd.device, dtype=cmd.dtype)
    joystick = cmd / max_cmd
    return joystick.abs().amax(dim=-1, keepdim=True) < _STAND_THRESHOLD


def velocity_commands_deploy(
    env, command_name: str, lin_scale: float, ang_scale: float
) -> torch.Tensor:
    """cmd * [lin_scale, lin_scale, ang_scale], zero-gated on stand-still."""
    cmd = env.command_manager.get_command(command_name).clone()
    is_standing = _is_standing_still(env, command_name)
    cmd = torch.where(is_standing, torch.zeros_like(cmd), cmd)
    out = torch.empty_like(cmd)
    out[:, 0] = cmd[:, 0] * lin_scale
    out[:, 1] = cmd[:, 1] * lin_scale
    out[:, 2] = cmd[:, 2] * ang_scale
    return out


def _phase_radians(env, period: float) -> torch.Tensor:
    if hasattr(env, "episode_length_buf"):
        sim_time = env.episode_length_buf.float() * env.step_dt
    else:
        sim_time = torch.zeros(env.num_envs, device=env.device)
    phase = (sim_time % period) / period
    return (2.0 * math.pi * phase).unsqueeze(-1)


def walk_sin_phase(
    env, command_name: str = "base_velocity", period: float = PHASE_PERIOD
) -> torch.Tensor:
    val = torch.sin(_phase_radians(env, period))
    return torch.where(
        _is_standing_still(env, command_name), torch.zeros_like(val), val
    )


def walk_cos_phase(
    env, command_name: str = "base_velocity", period: float = PHASE_PERIOD
) -> torch.Tensor:
    val = torch.cos(_phase_radians(env, period))
    return torch.where(
        _is_standing_still(env, command_name), torch.zeros_like(val), val
    )


def last_action_padded_29(
    env, action_name: str = "joint_pos"
) -> torch.Tensor:
    """29-dim last-action obs: leg slots hold processed targets, rest zeroed."""
    pa = env.action_manager.get_term(action_name).processed_actions  # (N, 29)
    out = torch.zeros_like(pa)
    # R3 H2 fix: assert the hardcoded leg indices match the WalkJointAction
    # term's dynamically-resolved joint_ids.  If the G1 USD is re-exported
    # with a different joint order, this catches the drift immediately instead
    # of silently feeding corrupted 6-step history to the walker policy.
    _term_joint_ids = env.action_manager.get_term(action_name)._joint_ids
    if set(_LEG_INDICES_IN_29) != set(_term_joint_ids):
        raise RuntimeError(
            f"_LEG_INDICES_IN_29 ({sorted(_LEG_INDICES_IN_29)}) does not match "
            f"WalkJointAction._joint_ids ({sorted(_term_joint_ids)}). "
            f"The G1 USD joint order has changed — update _LEG_INDICES_IN_29 "
            f"in mdp/tactile_obs.py to match."
        )
    out[:, _LEG_INDICES_IN_29] = pa[:, _LEG_INDICES_IN_29]
    return out
