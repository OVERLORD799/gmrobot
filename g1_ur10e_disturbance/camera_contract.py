"""Pure camera contract helpers for pre-launch wiring and fail-closed checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scene_camera_override import (
    DEFAULT_SCENE_CAMERA_POS,
    DEFAULT_SCENE_CAMERA_ROT,
    _parse_floats,
)


@dataclass(frozen=True)
class CameraContract:
    override_enabled: bool
    requested_pos: tuple[float, float, float]
    requested_rot: tuple[float, float, float, float]
    source: str


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_floats(raw: Any, *, n: int, label: str) -> tuple[float, ...]:
    if isinstance(raw, str):
        return _parse_floats(raw, n=n, label=label)
    if isinstance(raw, Sequence):
        if len(raw) != n:
            raise ValueError(f"{label} expects length={n}, got {len(raw)}")
        return tuple(float(v) for v in raw)
    raise ValueError(f"{label} expects csv string or sequence, got {type(raw).__name__}")


def resolve_camera_contract(
    *,
    config_camera: Mapping[str, Any] | None,
    cli_override: bool | None,
    cli_pos: str,
    cli_rot: str,
) -> CameraContract:
    """Resolve requested camera pose from CLI/config with deterministic precedence."""
    cfg = dict(config_camera or {})
    cfg_override = _as_bool(cfg.get("override", False))
    cfg_pos = cfg.get("pos", DEFAULT_SCENE_CAMERA_POS)
    cfg_rot = cfg.get("rot", DEFAULT_SCENE_CAMERA_ROT)

    override_enabled = bool(cfg_override if cli_override is None else cli_override)
    if not override_enabled:
        return CameraContract(
            override_enabled=False,
            requested_pos=tuple(float(v) for v in DEFAULT_SCENE_CAMERA_POS),
            requested_rot=tuple(float(v) for v in DEFAULT_SCENE_CAMERA_ROT),
            source="dual_default",
        )

    if cli_pos.strip() or cli_rot.strip():
        if not cli_pos.strip() or not cli_rot.strip():
            raise ValueError(
                "camera override enabled: --scene-camera-pos and --scene-camera-rot must both be set"
            )
        return CameraContract(
            override_enabled=True,
            requested_pos=_as_floats(cli_pos, n=3, label="--scene-camera-pos"),  # type: ignore[arg-type]
            requested_rot=_as_floats(cli_rot, n=4, label="--scene-camera-rot"),  # type: ignore[arg-type]
            source="cli",
        )

    return CameraContract(
        override_enabled=True,
        requested_pos=_as_floats(cfg_pos, n=3, label="camera.pos"),  # type: ignore[arg-type]
        requested_rot=_as_floats(cfg_rot, n=4, label="camera.rot"),  # type: ignore[arg-type]
        source="config",
    )


def apply_contract_envvars(contract: CameraContract, *, env: dict[str, str]) -> None:
    """Mutate process env so module-import camera reads deterministic values."""
    if contract.override_enabled:
        env["GMDISTURB_SCENE_CAMERA_OVERRIDE"] = "1"
        env["GMDISTURB_SCENE_CAMERA_POS"] = ",".join(str(float(v)) for v in contract.requested_pos)
        env["GMDISTURB_SCENE_CAMERA_ROT"] = ",".join(str(float(v)) for v in contract.requested_rot)
    else:
        env.pop("GMDISTURB_SCENE_CAMERA_OVERRIDE", None)
        env.pop("GMDISTURB_SCENE_CAMERA_POS", None)
        env.pop("GMDISTURB_SCENE_CAMERA_ROT", None)


def apply_contract_to_env_cfg(env_cfg: Any, contract: CameraContract) -> None:
    """Write requested camera pose to env_cfg scene camera offset (pre-make)."""
    env_cfg.scene.scene_camera.offset.pos = tuple(float(v) for v in contract.requested_pos)
    env_cfg.scene.scene_camera.offset.rot = tuple(float(v) for v in contract.requested_rot)


def read_env_cfg_pose(env_cfg: Any) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    pos = tuple(float(v) for v in env_cfg.scene.scene_camera.offset.pos)
    rot = tuple(float(v) for v in env_cfg.scene.scene_camera.offset.rot)
    if len(pos) != 3 or len(rot) != 4:
        raise ValueError(f"invalid env_cfg scene camera pose dimensions: pos={len(pos)} rot={len(rot)}")
    return pos, rot


def pose_abs_error(
    requested_pos: Sequence[float],
    requested_rot: Sequence[float],
    effective_pos: Sequence[float],
    effective_rot: Sequence[float],
) -> dict[str, float]:
    pos_err = max(abs(float(a) - float(b)) for a, b in zip(requested_pos, effective_pos))
    rot_err = max(abs(float(a) - float(b)) for a, b in zip(requested_rot, effective_rot))
    return {"pos_max_abs": float(pos_err), "rot_max_abs": float(rot_err)}
