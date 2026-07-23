"""Runtime command/env guards for E01-Dyn-B Isaac preflight."""

from __future__ import annotations

from pathlib import Path


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


def canonical_dyn_b_smoke_shell(
    *,
    project_root: str = "/opt/projects/g1_ur10e_disturbance",
    output_csv: str = "/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1t/safety_logs/phase3.csv",
    numpy_origin_json: str = "/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1t/meta/numpy_origin.json",
) -> str:
    """Single-shell command: record NumPy origins then run AppLauncher smoke."""
    phase3 = run_phase3_command(project_root=project_root, output_csv=output_csv)
    return (
        "set -euo pipefail; "
        "/isaac-sim/python.sh -c "
        "\"import json,numpy as np; "
        "payload={'numpy_file':getattr(np,'__file__',''),"
        "'numpy_version':getattr(np,'__version__',''),"
        "'numpy_random_file':getattr(np.random,'__file__','')}; "
        f"open('{numpy_origin_json}','w',encoding='utf-8').write(json.dumps(payload,ensure_ascii=True,indent=2)+'\\\\n'); "
        "print(json.dumps(payload,ensure_ascii=True))\"; "
        f"{phase3}"
    )
