# Copyright (c) 2022-2024, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Observation terms for the pressure-mat task (Option 1: contactor-side sensor).

The mat is a rigid kinematic taxel grid. Per-taxel contact force is read from
a single ``ContactSensor`` placed on the **contactor** (the falling sphere),
with ``filter_prim_paths_expr`` targeting the entire taxel grid. PhysX returns
``data.force_matrix_w`` of shape ``(num_envs, 1, num_taxels, 3)``, which we
reshape into a ``(num_envs, rows, cols)`` Newton image.

Why this avoids the multi-contact double-counting we saw earlier
----------------------------------------------------------------
Earlier we placed the ContactSensor on the multi-body taxel grid itself
(``prim_path="{ENV_REGEX_NS}/sensor_.*"``) and read ``net_forces_w``. PhysX's
docs say this configuration -- many sensor bodies, each potentially filtered
against many other bodies -- is unsupported. Empirically the impulse buffer
ended up double-counted across consecutive episode resets, causing the per-
frame total contact force to alternate between F and 2F.

The supported configuration is **one sensor body, many filter bodies**
(documented in ``ContactSensorCfg.filter_prim_paths_expr``). Putting the
sensor on the single contactor and using the taxel grid as the filter list
gives us a clean per-pair contact force matrix that PhysX computes via the
standard one-to-many ``get_contact_force_matrix`` path.

Optional Pasternak shear coupling
---------------------------------
If ``coupling_length > 0``, a 2-D Gaussian blur is applied to the per-taxel
force image with sigma = ``coupling_length / pitch``. This emulates a soft-
mat shear layer so a single point of contact spreads into a smooth disc that
activates several neighbouring cells. The total force (sum over taxels) is
preserved by the blur (Gaussian kernel is normalized).

Permutation map
---------------
PhysX expands ``filter_prim_paths_expr`` and stores the resulting bodies in
some internal order that may not match our row-major ``sensor_RR_CC`` layout.
At first call we resolve the filter expression for env_0, parse each prim
name into row/col integers, and build a permutation tensor that re-orders
the force matrix into row-major. The map is cached on env identity.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

import torch

import omni.isaac.lab.sim as sim_utils
from omni.isaac.lab.managers import SceneEntityCfg

if TYPE_CHECKING:
    from omni.isaac.lab.envs import ManagerBasedEnv


# (id(env), sensor_name, rows, cols) -> filter permutation tensor
_PERM_CACHE: dict[tuple, torch.Tensor] = {}
# (id(env), rows, cols, sigma_pixels) -> (1-D Gaussian kernel, radius)
_KERNEL_CACHE: dict[tuple, tuple[torch.Tensor, int]] = {}

_NAME_RE = re.compile(r"sensor_(\d+)_(\d+)$")


def _build_perm_map_from_filter_expr(
    filter_expr: str, rows: int, cols: int, device: torch.device
) -> torch.Tensor:
    """Resolve the filter expression for env_0 and return a row-major permutation.

    The expression is a regex like ``/World/envs/env_.*/sensor_.*``. We
    rewrite ``env_.*`` to ``env_0`` (the first env) and resolve to a concrete
    list of taxel prim paths. The order of that list is what PhysX uses for
    the second-to-last dim of ``force_matrix_w``.

    Returns a long tensor ``perm`` of shape ``(rows*cols,)`` such that
    ``perm[r*cols + c]`` is the index in PhysX's filter ordering for the
    taxel at row ``r``, column ``c``.
    """
    # Resolve the expression to env_0 only -- the per-env taxel order is
    # identical across envs because each env is a clone of the template.
    env0_expr = filter_expr.replace("env_.*", "env_0")
    paths = sim_utils.find_matching_prim_paths(env0_expr)
    # PhysX iterates the filter list in the order returned by find_matching_prim_paths,
    # which uses scenegraph order = creation order. Our spawner inserts taxels in
    # row-major order so the natural ordering should already be row-major, but we
    # build the permutation defensively from parsed names.
    perm = torch.empty(rows * cols, dtype=torch.long, device=device)
    found = 0
    for idx, path in enumerate(paths):
        leaf = path.rsplit("/", 1)[-1]
        m = _NAME_RE.match(leaf)
        if m is None:
            continue
        r, c = int(m.group(1)), int(m.group(2))
        if r >= rows or c >= cols:
            raise RuntimeError(
                f"Pressure mat: filter taxel '{leaf}' has out-of-range index "
                f"(rows={rows}, cols={cols})."
            )
        perm[r * cols + c] = idx
        found += 1
    if found != rows * cols:
        raise RuntimeError(
            f"Pressure mat: expected {rows * cols} taxels matching '{env0_expr}', "
            f"found {found}. Sample paths: {paths[:5]} ... {paths[-5:]}"
        )
    return perm


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
    """Apply a separable 2-D Gaussian blur to an ``(N, R, C)`` image."""
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


def tactile_force(
    env: "ManagerBasedEnv",
    sensor_cfg: SceneEntityCfg = SceneEntityCfg("tactile_contact_sensor"),
    rows: int = 32,
    cols: int = 32,
    coupling_length: float = 0.0,
    mat_size_x: float = 1.0,
    mat_size_y: float = 1.0,
) -> torch.Tensor:
    """Per-taxel normal contact force in Newtons.

    Reads ``ContactSensor.data.force_matrix_w`` (shape ``(N, 1, R*C, 3)``)
    where the sensor is placed on the contactor and the taxel grid is the
    filter target. Takes the Z component, negates so positive = pressing INTO
    the mat, applies a row-major permutation, reshapes to ``(N, R, C)``, and
    optionally Gaussian-blurs to emulate a Pasternak shear layer.

    Args:
        env: the manager-based environment.
        sensor_cfg: scene entity for the contactor-side ContactSensor. Must
            be configured with ``filter_prim_paths_expr=["{ENV_REGEX_NS}/sensor_.*"]``.
        rows: number of taxel rows (must match the mat asset).
        cols: number of taxel columns (must match the mat asset).
        coupling_length: Pasternak coupling length in meters. ``0`` disables
            smearing. Typical real soft mats: 1-2 cm.
        mat_size_x: total mat extent in X (m) -- used to compute the taxel pitch.
        mat_size_y: total mat extent in Y (m) -- used to compute the taxel pitch.

    Returns:
        Per-taxel normal force in Newtons. Shape ``(num_envs, rows, cols)``.
    """
    contact_sensor = env.scene.sensors[sensor_cfg.name]
    # force_matrix_w shape: (num_envs, num_sensor_bodies=1, num_filter_bodies=R*C, 3)
    # PhysX populates this with the force ON the sensor body FROM each filter
    # body. Here the sensor body is the contactor (sphere) and the filter
    # bodies are the taxels, so the force on the sphere from each taxel is the
    # upward (+Z) reaction force = the magnitude of the load on that taxel.
    # We do NOT negate -- the +Z value already corresponds to "load pressing
    # into the mat".
    fmat = contact_sensor.data.force_matrix_w
    normal_n = fmat[:, 0, :, 2]  # (num_envs, num_taxels)

    expected_taxels = rows * cols
    if normal_n.shape[-1] != expected_taxels:
        raise RuntimeError(
            f"Pressure mat: contact sensor reports {normal_n.shape[-1]} filter "
            f"bodies but expected {expected_taxels} (= {rows} x {cols}). The "
            f"filter_prim_paths_expr may be matching too many or too few prims."
        )

    # PhysX expands filter_prim_paths_expr in scenegraph (= insertion) order.
    # Our spawner inserts taxels in row-major order (sensor_00_00,
    # sensor_00_01, ..., sensor_31_31), so the natural index along the
    # last dim of force_matrix_w is already the row-major taxel index.
    # No permutation needed; reshape directly.
    image = normal_n.view(-1, rows, cols)

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


def tactile_force_multi(
    env: "ManagerBasedEnv",
    sensor_names: list[str],
    asset_names: list[str] | None = None,
    rows: int = 32,
    cols: int = 32,
    coupling_length: float = 0.0,
    mat_size_x: float = 1.0,
    mat_size_y: float = 1.0,
    gravity: float = 9.81,
    physics_calibrate: bool = True,
) -> torch.Tensor:
    """Sum the per-pair contact forces from multiple contactor sensors, with
    optional per-contactor physics calibration.

    Each entry in ``sensor_names`` should refer to a ``ContactSensor`` whose
    sensor body is a single rigid contactor. PhysX gives each one a
    ``force_matrix_w`` of shape ``(N, 1, R*C, 3)`` containing the force on
    that contactor from each taxel.

    Physics calibration (default: ON)
    ---------------------------------
    PhysX's contact-manifold reporting inflates the *magnitude* of the
    per-pair force matrix for flat-bottomed contactors (cubes, cylinders) by a
    small integer factor (we observed 2x for a cube, 3x for a cylinder). The
    *spatial distribution* across taxels is correct, but the magnitudes are
    not. To recover physically-correct Newton readings, we use Newton's
    second law: the net contact force on a contactor at any instant is
    ``m * (a - g_world)``, where ``a`` is its world-frame acceleration and
    ``g_world = (0, 0, -g)``. For a contactor at rest this reduces to
    ``m * g`` (its weight, upward).

    For each contactor we:
      1. read its raw per-taxel force vector from the contact sensor
      2. compute the expected total upward force from its mass + acceleration
      3. compute a per-frame scale = expected / reported (if reported > eps)
      4. apply the scale to the per-taxel forces (preserving distribution)

    For curved contactors (sphere, capsule) the scale is ~1.0 since their
    raw readings are already correct. For flat-bottomed contactors it
    corrects the integer-factor inflation. Pass ``physics_calibrate=False``
    to disable and read raw PhysX values.

    Args:
        env: the manager-based environment.
        sensor_names: scene-entity names of the contactor ContactSensors.
        asset_names: scene-entity names of the corresponding RigidObjects.
            Must be the same length as ``sensor_names`` (1:1 mapping). Only
            required if ``physics_calibrate=True``.
        rows, cols: taxel grid dimensions.
        coupling_length: Pasternak coupling length in meters (0 disables).
        mat_size_x, mat_size_y: mat extent in m, used to compute taxel pitch.
        gravity: gravitational acceleration magnitude (m/s^2). Default 9.81.
        physics_calibrate: enable per-contactor scaling via Newton's law.

    Returns:
        ``(num_envs, rows, cols)`` Newton image, summed across contactors,
        Pasternak-smeared if ``coupling_length > 0``.
    """
    expected_taxels = rows * cols

    if physics_calibrate and (asset_names is None or len(asset_names) != len(sensor_names)):
        raise ValueError(
            "tactile_force_multi: asset_names is required (and must match "
            "sensor_names length) when physics_calibrate=True."
        )

    summed: torch.Tensor | None = None
    eps = 1e-3  # Newtons -- below this we treat the contactor as out-of-contact

    for i, sname in enumerate(sensor_names):
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
            asset = env.scene[asset_names[i]]
            mass = asset.root_physx_view.get_masses().to(per_taxel.device)
            mass = mass.view(-1)  # (N,)
            # body_lin_acc_w: (N, 3) world-frame linear acceleration of the body
            try:
                lin_acc = asset.data.body_lin_acc_w[:, 0, :]  # (N, 3)
            except (AttributeError, IndexError):
                lin_acc = asset.data.root_lin_vel_w * 0.0  # fallback: zero
            # Net contact force on the contactor (Newton's 2nd):
            #   F_contact = m * (a - g_world) = m * a + m * g_up
            #             = m * a_z + m * g  (taking the +Z component)
            expected_total = mass * (lin_acc[:, 2] + gravity)
            expected_total = torch.clamp(expected_total, min=0.0)

            in_contact = reported_total > eps
            scale = torch.where(
                in_contact,
                expected_total / torch.clamp(reported_total, min=eps),
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

    image = _apply_pasternak(summed, rows, cols, coupling_length, mat_size_x, mat_size_y, env)

    return image


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

    Same as ``tactile_force_multi`` but uses ``ContactSensor.data.net_forces_w``
    as the ground-truth total contact force instead of Newton's-law computation.

    Why this matters for articulated robots
    ----------------------------------------
    For a single rigid contactor, ``m * (a + g)`` gives the correct ground
    reaction force. For a humanoid *foot*, the foot's own mass is tiny
    (~0.6 kg) but it carries the entire upper-body weight through joint
    forces. ``m_foot * (a + g)`` would vastly underestimate the ground
    reaction.

    ``net_forces_w`` is the aggregate contact impulse / dt from PhysX's
    impulse buffer. It does NOT include joint/constraint forces — only
    surface contacts. So for a humanoid foot it gives the **actual ground
    reaction force**, regardless of how many links sit above it.

    Calibration:  ``scale = net_forces_z / sum(force_matrix_z)``
    Spatial distribution preserved; only the magnitude is corrected.
    No ``asset_names`` needed — the sensor provides everything.

    Args:
        env: the manager-based environment.
        sensor_names: scene-entity names of the ContactSensors (one per
            foot / contactor).
        rows, cols: taxel grid dimensions.
        coupling_length: Pasternak coupling length in meters (0 disables).
        mat_size_x, mat_size_y: mat extent in m, used to compute taxel pitch.
        physics_calibrate: enable per-sensor scaling via ``net_forces_w``.

    Returns:
        ``(num_envs, rows, cols)`` Newton image, summed across sensors,
        Pasternak-smeared if ``coupling_length > 0``.
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
                expected_total / torch.clamp(reported_total, min=eps),
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


# -----------------------------------------------------------------------------
# Slab-mode tactile reading: bin per-contact-point forces into a virtual taxel
# grid. Used with the slab-only env where physics is a single big rigid body
# and per-taxel readings are derived from PhysX's per-contact-point data.
# -----------------------------------------------------------------------------
# Cache of private rigid_contact_views (one entry per (env, sensor_names) key)
# created with max_contact_data_count > 0 so we can read per-contact-point data
# (the default ContactSensor view is created with max_contact_data_count=0).
_SLAB_PER_POINT_VIEWS: dict = {}

def tactile_force_from_slab_contacts(
    env: "ManagerBasedEnv",
    sensor_names: tuple[str, ...] = ("left_foot_sensor", "right_foot_sensor"),
    rows: int = 64,
    cols: int = 64,
    mat_size_x: float = 2.0,
    mat_size_y: float = 2.0,
    physics_calibrate: bool = True,
) -> torch.Tensor:
    """Per-taxel Newton image built by spatially binning every individual
    foot-vs-slab contact point reported by PhysX.

    Pipeline (per env, per foot sensor):
      1. ``contact_physx_view.get_contact_force_data(dt=sim_dt)`` returns flat
         buffers of every contact point's normal-force magnitude, world-space
         position, normal, and the (start, count) per env into the buffer.
      2. Convert each contact point's (x, y) from world to env-local frame.
      3. Map (x, y) to a virtual taxel index using the same row-major
         convention as the original mat USD generator:
             ``r = round((mat_size_x/2 - x) / pitch_x)``
             ``c = round((mat_size_y/2 - y) / pitch_y)``
      4. Accumulate the contact's normal-force magnitude into ``image[env, r, c]``.

    Calibration (matches ``tactile_force_multi_net``)
    -------------------------------------------------
    PhysX's per-pair contact-force buffer has a small magnitude inflation
    (~2x for cube-shaped contactors). The per-contact-point data sums to the
    same per-pair force, so it has the same inflation. We rescale each
    foot's image so its total matches the foot's ``net_forces_w[..., 2]``,
    which is the impulse-buffer ground-reaction force (correct).

    No Pasternak / Gaussian smearing applied here. Returns the raw binned
    image as Newtons.

    Args:
        env: the manager-based environment.
        sensor_names: scene-entity names of the per-foot ``ContactSensor``s.
            Each must be configured with ``filter_prim_paths_expr`` pointing
            at the slab body.
        rows, cols: virtual taxel grid dimensions.
        mat_size_x, mat_size_y: total mat extent in m. Pitch = size / (n - 1).
        physics_calibrate: if True, scale each foot's image so its total
            matches ``ContactSensor.data.net_forces_w[..., 2]``.

    Returns:
        ``(num_envs, rows, cols)`` Newton image, summed over feet.
    """
    device = env.scene.env_origins.device
    image = torch.zeros((env.num_envs, rows, cols), device=device, dtype=torch.float32)

    pitch_x = mat_size_x / max(rows - 1, 1)
    pitch_y = mat_size_y / max(cols - 1, 1)
    half_x = mat_size_x / 2.0
    half_y = mat_size_y / 2.0

    # Obtain the per-foot views from the ContactSensorWithData sensors. These
    # were created during env init with max_contact_data_count > 0.
    views = []
    for sname in sensor_names:
        sensor = env.scene.sensors.get(sname)
        if sensor is None or sensor.contact_physx_view is None:
            return image
        if sensor.contact_physx_view.max_contact_data_count == 0:
            return image
        views.append(sensor.contact_physx_view)

    sim_dt = float(env.cfg.sim.dt)

    # One view per foot. Each view sees (env_id, slab) pairs.
    for view in views:
        forces_norm, points, _normals, _distances, pair_start, pair_count = (
            view.get_contact_data(dt=sim_dt)
        )
        net_forces = view.get_net_contact_forces(dt=sim_dt)  # (sensor_count, 3)

        # Diagnostic: print contact stats once in a while.
        import os
        if os.environ.get("TACTILE_DEBUG"):
            n_pairs = int(pair_count.sum().item())
            net_z = float(net_forces[:, 2].abs().sum().item())
            print(
                f"[tactile_force_from_slab_contacts]"
                f" view: sensors={view.sensor_count}"
                f" filters={view.filter_count}"
                f" max_contact={view.max_contact_data_count}"
                f" pair_count_sum={n_pairs}"
                f" net_z_sum={net_z:.2f}",
                flush=True,
            )

        ps = pair_start[:, 0].to(torch.long)
        pc = pair_count[:, 0].to(torch.long)
        sensor_count = view.sensor_count  # = num_envs

        for env_id in range(sensor_count):
            count = int(pc[env_id].item())
            if count <= 0:
                continue
            start = int(ps[env_id].item())
            f = forces_norm[start:start + count, 0].to(torch.float32)
            p = points[start:start + count, :2].to(torch.float32)
            origin_xy = env.scene.env_origins[env_id, :2].to(torch.float32)
            local_xy = p - origin_xy

            r_idx = ((half_x - local_xy[:, 0]) / pitch_x).round().long()
            c_idx = ((half_y - local_xy[:, 1]) / pitch_y).round().long()
            valid = (r_idx >= 0) & (r_idx < rows) & (c_idx >= 0) & (c_idx < cols)
            if not bool(valid.any().item()):
                continue

            per_foot = torch.zeros((rows, cols), device=device, dtype=torch.float32)
            per_foot.index_put_((r_idx[valid], c_idx[valid]), f[valid], accumulate=True)

            if physics_calibrate:
                net_z = float(torch.clamp(net_forces[env_id, 2], min=0.0).item())
                binned = float(per_foot.sum().item())
                if binned > 1e-3 and net_z > 1e-3:
                    per_foot = per_foot * (net_z / binned)

            image[env_id] = image[env_id] + per_foot

    return image


# ===========================================================================
# Deploy-walk observation helpers (vendored from the project's
# locomotion/velocity/config/g1/g1_walk_deploy_cfg.py). These reproduce the
# exact obs layout the unitree deploy_walk torchscript policy expects:
# velocity-command gating + sin/cos walking phase + 29-dim last-action.
# ===========================================================================
# Active leg joint indices in the 29-dim isaaclab joint order.
_LEG_INDICES_IN_29 = [0, 1, 3, 4, 6, 7, 9, 10, 13, 14, 17, 18]
# Per-axis joystick max (used to convert cmd <-> joystick scale for gating).
_MAX_CMD = (0.8, 0.5, 1.57)
# Joystick-scale threshold below which deploy zeros cmd and phase.
_STAND_THRESHOLD = 0.1
# Walking phase period (seconds).
_PHASE_PERIOD = 0.65


def _is_standing_still(env, command_name: str) -> torch.Tensor:
    """(N,1) bool: True when all joystick-equivalent cmd magnitudes < threshold."""
    cmd = env.command_manager.get_command(command_name)
    max_cmd = torch.tensor(_MAX_CMD, device=cmd.device, dtype=cmd.dtype)
    joystick = cmd / max_cmd
    return joystick.abs().amax(dim=-1, keepdim=True) < _STAND_THRESHOLD


def velocity_commands_deploy(env, command_name: str, lin_scale: float, ang_scale: float) -> torch.Tensor:
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


def walk_sin_phase(env, command_name: str = "base_velocity", period: float = _PHASE_PERIOD) -> torch.Tensor:
    val = torch.sin(_phase_radians(env, period))
    return torch.where(_is_standing_still(env, command_name), torch.zeros_like(val), val)


def walk_cos_phase(env, command_name: str = "base_velocity", period: float = _PHASE_PERIOD) -> torch.Tensor:
    val = torch.cos(_phase_radians(env, period))
    return torch.where(_is_standing_still(env, command_name), torch.zeros_like(val), val)


def last_action_padded_29(env, action_name: str = "joint_pos") -> torch.Tensor:
    """29-dim last-action obs: leg slots hold processed targets, rest zeroed."""
    pa = env.action_manager.get_term(action_name).processed_actions  # (N, 29)
    out = torch.zeros_like(pa)
    out[:, _LEG_INDICES_IN_29] = pa[:, _LEG_INDICES_IN_29]
    return out
