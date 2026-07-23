"""Offline command/preflight guards for V1-M1F12.1 Dual-reference Func-C smoke."""

from __future__ import annotations

from typing import Iterable


CAMERA_FLAG = "--enable_cameras"
PYTHON_LAUNCHER = "/isaac-sim/python.sh"
ENTRYPOINT = "/opt/projects/GMRobot/scripts/gm_state_machine_agent.py"


def _count_token(command: str, token: str) -> int:
    return command.split().count(token)


def build_dual_reference_smoke_inner_command(
    *,
    camera_output_dir: str,
    runtime_assertions_json: str,
    visual_env: str = "1",
    camera_pos: tuple[float, float, float] = (0.45, 0.0, 2.7),
    camera_rot: tuple[float, float, float, float] = (0.7071, 0.0, 0.7071, 0.0),
) -> str:
    """Build canonical one-step AppLauncher command with camera enabled."""
    cpos = ",".join(str(float(x)) for x in camera_pos)
    crot = ",".join(str(float(x)) for x in camera_rot)
    return (
        "set -euo pipefail; "
        f"export GMDISTURB_V1E01_FUNC_C_VISUAL={visual_env}; "
        "export GMDISTURB_SCENE_CAMERA_OVERRIDE=1; "
        f"export GMDISTURB_SCENE_CAMERA_POS={cpos}; "
        f"export GMDISTURB_SCENE_CAMERA_ROT={crot}; "
        f"export GMROBOT_RUNTIME_SCENE_ASSERTIONS_PATH={runtime_assertions_json}; "
        f"{PYTHON_LAUNCHER} {ENTRYPOINT} "
        "--task gm --headless --enable_cameras --enable_safety "
        "--safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml "
        "--save_camera "
        f"--camera_output_dir {camera_output_dir} "
        "--camera_save_interval 1 --max_steps 1"
    )


def assert_single_camera_flag(command: str) -> None:
    count = _count_token(command, CAMERA_FLAG)
    if count != 1:
        raise AssertionError(f"camera flag count must be 1, got {count}")


def assert_single_launcher_and_entrypoint(command: str) -> None:
    launcher_count = _count_token(command, PYTHON_LAUNCHER)
    if launcher_count != 1:
        raise AssertionError(f"python launcher count must be 1, got {launcher_count}")
    entrypoint_count = _count_token(command, ENTRYPOINT)
    if entrypoint_count != 1:
        raise AssertionError(f"entrypoint count must be 1, got {entrypoint_count}")


def assert_required_switches(command: str, required: Iterable[str] | None = None) -> None:
    required_tokens = tuple(required) if required is not None else (
        "--headless",
        "--save_camera",
        "--camera_output_dir",
        "--max_steps",
    )
    missing = [tok for tok in required_tokens if tok not in command]
    if missing:
        raise AssertionError(f"missing required switches: {missing}")


def preflight_camera_flag_or_fail(command: str) -> None:
    """Fail-closed preflight for missing camera flag before AppLauncher starts."""
    if CAMERA_FLAG not in command.split():
        raise SystemExit("SMOKE_STARTUP_FAIL_FINAL: camera_flag_missing")
