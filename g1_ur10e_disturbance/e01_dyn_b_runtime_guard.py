"""Runtime command/env guards for E01-Dyn-B Isaac preflight."""

from __future__ import annotations

from pathlib import Path


def pythonpath_guard_prologue() -> str:
    return (
        "USD_LIBS=$(ls -d /isaac-sim/extscache/omni.usd.libs-* | head -n1); "
        "test -n \"$USD_LIBS\"; "
        "export PYTHONPATH=\"$USD_LIBS:${PYTHONPATH:-}\"; "
        "export LD_LIBRARY_PATH=\"$USD_LIBS/bin:${LD_LIBRARY_PATH:-}\"; "
        "PIP_ARCHIVE=$(ls -d /isaac-sim/extscache/omni.kit.pip_archive-*.lx64.cp311/pip_prebundle | head -n1); "
        "test -n \"$PIP_ARCHIVE\"; "
        "export PYTHONPATH=\"$PIP_ARCHIVE:${PYTHONPATH:-}\""
    )


def import_preflight_command(project_root: str = "/opt/projects/g1_ur10e_disturbance") -> str:
    preflight = Path(project_root) / "scripts" / "isaac_abi_import_preflight.py"
    return f"/isaac-sim/python.sh {preflight}"


def run_phase3_command(
    *,
    project_root: str = "/opt/projects/g1_ur10e_disturbance",
    output_csv: str = "/tmp/e01_dyn_b_preflight.csv",
) -> str:
    script = Path(project_root) / "scripts" / "run_phase3.py"
    return (
        f"/isaac-sim/python.sh {script} "
        "--headless --seed 43 --scenario outer_lateral_patrol "
        "--max_steps 1 --progress_interval 1 "
        f"--output_csv {output_csv}"
    )
