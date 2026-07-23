"""Runtime command/env guards for E01-Dyn-B Isaac preflight."""

from __future__ import annotations

from pathlib import Path

M1U0_IMAGE_TAG = "gmdisturb:e01-dyn-b-m1u0-20260723"
M1U0_DOCKERFILE = "docker/Dockerfile.e01-dyn-b-m1u0"
M1U0_BAKE_FILES: tuple[str, ...] = (
    "scripts/run_phase3.py",
    "g1_disturbance_controller.py",
    "e01_dyn_b_runtime_guard.py",
    "e01_dyn_b_offline_readiness.py",
    "configs/e01_dyn_b_capture.yaml",
    "scripts/isaac_abi_import_preflight.py",
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


def assert_no_host_code_bind_mount(docker_argv: list[str] | tuple[str, ...]) -> None:
    """Fail if argv mounts host project source over the baked image tree."""
    argv = list(docker_argv)
    for i, tok in enumerate(argv):
        if tok not in {"-v", "--volume"}:
            continue
        if i + 1 >= len(argv):
            continue
        spec = argv[i + 1]
        # results + cache mounts are allowed
        if ":/opt/projects/g1_ur10e_disturbance/results" in spec:
            continue
        if "/.cache/" in spec or ":/isaac-sim/kit/cache" in spec or ":/root/" in spec:
            continue
        # Full project tree or GMRobot source mounts are forbidden for M1U0 smoke.
        if ":/opt/projects/g1_ur10e_disturbance" in spec and "/results" not in spec.split(":")[-1]:
            # destination is exactly project root (not a results subpath)
            dest = spec.rsplit(":", 1)[-1]
            if dest.rstrip("/") == "/opt/projects/g1_ur10e_disturbance":
                raise AssertionError(f"host code bind-mount forbidden: {spec}")
        if ":/opt/projects/GMRobot" in spec:
            raise AssertionError(f"host code bind-mount forbidden: {spec}")


def smoke_enables_network_models(command: str) -> bool:
    low = command.lower()
    needles = (
        "enable_vlm",
        "enable_perception",
        "groundingdino",
        "grounding_dino",
        "sam2",
        "five_stage",
        "five-stage",
        "vlm_client",
        "perception_client",
        "--vlm",
        "post /analyze",
        "post /ground",
    )
    return any(n in low for n in needles)


def dockerfile_bake_mentions_outer_lateral(dockerfile_text: str) -> bool:
    """Dockerfile must COPY run_phase3 + controller (hosts of outer_lateral_patrol)."""
    return (
        "COPY scripts/run_phase3.py" in dockerfile_text
        and "COPY g1_disturbance_controller.py" in dockerfile_text
    )



def host_bake_sources_include_outer_lateral(repo_root: Path | str) -> dict[str, bool]:
    root = Path(repo_root)
    out: dict[str, bool] = {}
    for rel in M1U0_BAKE_FILES:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        out[rel] = ("outer_lateral_patrol" in text) or ("scripted_g1_outer_lateral_patrol" in text)
    return out
