#!/usr/bin/env python3
"""Unit tests for camera contract CLI/config -> env_cfg wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camera_contract import (  # noqa: E402
    apply_contract_to_env_cfg,
    pose_abs_error,
    read_env_cfg_pose,
    resolve_camera_contract,
)


@dataclass
class _Offset:
    pos: tuple[float, float, float]
    rot: tuple[float, float, float, float]


@dataclass
class _SceneCamera:
    offset: _Offset


@dataclass
class _Scene:
    scene_camera: _SceneCamera


@dataclass
class _EnvCfg:
    scene: _Scene


def _fake_env_cfg() -> _EnvCfg:
    return _EnvCfg(
        scene=_Scene(
            scene_camera=_SceneCamera(
                offset=_Offset(
                    pos=(1.0, 0.0, 3.0),
                    rot=(0.7071, 0.0, 0.7071, 0.0),
                )
            )
        )
    )


def test_config_contract_flows_to_env_cfg_offset() -> None:
    contract = resolve_camera_contract(
        config_camera={"override": True, "pos": [0.45, 0.0, 2.7], "rot": [0.7071, 0.0, 0.7071, 0.0]},
        cli_override=None,
        cli_pos="",
        cli_rot="",
    )
    cfg = _fake_env_cfg()
    apply_contract_to_env_cfg(cfg, contract)
    pos, rot = read_env_cfg_pose(cfg)
    assert pos == (0.45, 0.0, 2.7)
    assert rot == (0.7071, 0.0, 0.7071, 0.0)
    err = pose_abs_error(contract.requested_pos, contract.requested_rot, pos, rot)
    assert err["pos_max_abs"] == 0.0
    assert err["rot_max_abs"] == 0.0


def test_cli_contract_overrides_config() -> None:
    contract = resolve_camera_contract(
        config_camera={"override": True, "pos": [9.0, 9.0, 9.0], "rot": [1.0, 0.0, 0.0, 0.0]},
        cli_override=True,
        cli_pos="0.45,0.0,2.7",
        cli_rot="0.7071,0.0,0.7071,0.0",
    )
    cfg = _fake_env_cfg()
    apply_contract_to_env_cfg(cfg, contract)
    pos, _ = read_env_cfg_pose(cfg)
    assert pos == (0.45, 0.0, 2.7)
    assert contract.source == "cli"


if __name__ == "__main__":
    test_config_contract_flows_to_env_cfg_offset()
    test_cli_contract_overrides_config()
    print("PASS test_camera_contract_unit")
