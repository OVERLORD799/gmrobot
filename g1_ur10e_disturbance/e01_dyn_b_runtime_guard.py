"""Runtime command/env guards for E01-Dyn-B Isaac preflight."""

from __future__ import annotations

from pathlib import Path

# Historical M1U2.3 tag (NumPy-dedup series; do not reuse for M1V).
M1U2_IMAGE_TAG = "gmdisturb:e01-dyn-b-m1u23-20260723"
M1U2_DOCKERFILE = "docker/Dockerfile.e01-dyn-b-m1u23"
M1U2_BAKE_FILES: tuple[str, ...] = (
    "scripts/run_phase3.py",
    "g1_disturbance_controller.py",
    "e01_dyn_b_runtime_guard.py",
    "e01_dyn_b_offline_readiness.py",
    "configs/e01_dyn_b_capture.yaml",
    "scripts/isaac_abi_import_preflight.py",
    "scripts/numpy_abi_guard.py",
    "scripts/pip_prebundle_numpy_dedup.py",
    "scripts/assert_numpy_dedup_report.py",
)

# V1-M1V clean physical baseline rebuild.
M1V_IMAGE_TAG = "gmdisturb:e01-dyn-b-clean-m1v-20260723"
M1V_DOCKERFILE = "docker/Dockerfile.e01-dyn-b-clean-m1v"
M1V_BASE_IMAGE = "gmdisturb:b4-p010-20260721"
M1V_BASE_IMAGE_SHA = "sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68"
M1V_BAKE_FILES: tuple[str, ...] = (
    "scripts/run_phase3.py",
    "g1_disturbance_controller.py",
    "e01_dyn_b_runtime_guard.py",
    "e01_dyn_b_offline_readiness.py",
    "configs/e01_dyn_b_capture.yaml",
    "scripts/isaac_abi_import_preflight.py",
    "scripts/numpy_abi_guard.py",
)

M1V_RESULT_ROOT = (
    "/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1v_dyn_b_clean_runtime_20260723"
)

# V1-M1V1 source-closure recovery (scene_camera_override and full local closure).
M1V1_IMAGE_TAG = "gmdisturb:e01-dyn-b-clean-m1v1-20260723"
M1V1_DOCKERFILE = "docker/Dockerfile.e01-dyn-b-clean-m1v1"
M1V1_RESULT_ROOT = (
    "/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1v1_dyn_b_clean_runtime_20260723"
)


def import_preflight_command(project_root: str = "/opt/projects/g1_ur10e_disturbance") -> str:
    preflight = Path(project_root) / "scripts" / "isaac_abi_import_preflight.py"
    return f"/isaac-sim/python.sh {preflight}"


def run_phase3_command(
    *,
    project_root: str = "/opt/projects/g1_ur10e_disturbance",
    output_csv: str = "/tmp/e01_dyn_b_preflight.csv",
    numpy_origin_pre_json: str = "",
    numpy_origin_post_json: str = "",
    typing_extensions_pre_json: str = "",
    typing_extensions_post_json: str = "",
) -> str:
    script = Path(project_root) / "scripts" / "run_phase3.py"
    cmd = (
        f"/isaac-sim/python.sh {script} "
        "--headless --seed 43 --scenario outer_lateral_patrol "
        "--max_steps 1 --progress_interval 1 "
        f"--output_csv {output_csv}"
    )
    if numpy_origin_pre_json:
        cmd += f" --numpy-origin-pre-json {numpy_origin_pre_json}"
    if numpy_origin_post_json:
        cmd += f" --numpy-origin-post-json {numpy_origin_post_json}"
    if typing_extensions_pre_json:
        cmd += f" --typing-extensions-pre-json {typing_extensions_pre_json}"
    if typing_extensions_post_json:
        cmd += f" --typing-extensions-post-json {typing_extensions_post_json}"
    return cmd


def canonical_dyn_b_smoke_shell(
    *,
    project_root: str = "/opt/projects/g1_ur10e_disturbance",
    output_csv: str = f"{M1V1_RESULT_ROOT}/safety_logs/phase3.csv",
    numpy_origin_pre_json: str = f"{M1V1_RESULT_ROOT}/meta/numpy_origin_pre.json",
    numpy_origin_post_json: str = f"{M1V1_RESULT_ROOT}/meta/numpy_origin_post.json",
    typing_extensions_pre_json: str = f"{M1V1_RESULT_ROOT}/meta/typing_extensions_pre.json",
    typing_extensions_post_json: str = f"{M1V1_RESULT_ROOT}/meta/typing_extensions_post.json",
) -> str:
    """Single-shell AppLauncher smoke with NumPy + typing_extensions pre/post guards."""
    phase3 = run_phase3_command(
        project_root=project_root,
        output_csv=output_csv,
        numpy_origin_pre_json=numpy_origin_pre_json,
        numpy_origin_post_json=numpy_origin_post_json,
        typing_extensions_pre_json=typing_extensions_pre_json,
        typing_extensions_post_json=typing_extensions_post_json,
    )
    return "set -euo pipefail; " + phase3


def assert_canonical_run_sh_payload(argv: list[str] | tuple[str, ...]) -> None:
    """Require run.sh payload to be `bash -lc INNER`, never direct python.sh."""
    tokens = list(argv)
    if len(tokens) < 2:
        raise AssertionError("run.sh payload missing")
    if tokens[0] == "/isaac-sim/python.sh":
        raise AssertionError("forbidden payload: direct /isaac-sim/python.sh")
    if tokens[0] != "bash" or tokens[1] != "-lc":
        raise AssertionError("run.sh payload must begin with: bash -lc")


def build_m1v1_dyn_b_preflight_inner_command(*, result_root_in_container: str) -> str:
    """Build the proven M1V1 one-shot inner shell for Dyn-B preflight capture."""
    rr = result_root_in_container.rstrip("/")
    return (
        "set -euo pipefail; "
        "/isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py "
        "--headless --seed 43 --scenario outer_lateral_patrol "
        "--motion_source_label scripted_g1_outer_lateral_patrol "
        "--max_steps 341 --progress_interval 50 "
        f"--output_csv {rr}/safety_logs/phase3.csv "
        "--save_camera "
        f"--camera_output_dir {rr}/scene "
        "--camera_save_steps 219,220,221,329,330,331 "
        f"--camera_pose_json {rr}/meta/camera_pose.json "
        f"--body_pose_jsonl {rr}/meta/body_poses.jsonl "
        f"--numpy-origin-pre-json {rr}/meta/numpy_origin_pre.json "
        f"--numpy-origin-post-json {rr}/meta/numpy_origin_post.json "
        f"--typing-extensions-pre-json {rr}/meta/typing_extensions_pre.json "
        f"--typing-extensions-post-json {rr}/meta/typing_extensions_post.json"
    )


def build_m1v1_dyn_b_preflight_outer_argv(
    *,
    run_sh_path: str,
    image_tag: str,
    host_results_dir: str,
    result_root_in_container: str,
) -> list[str]:
    """Build canonical outer command: run.sh --tag IMAGE --results RESULTS bash -lc INNER."""
    inner = build_m1v1_dyn_b_preflight_inner_command(
        result_root_in_container=result_root_in_container
    )
    payload = ["bash", "-lc", inner]
    assert_canonical_run_sh_payload(payload)
    return [
        run_sh_path,
        "--tag",
        image_tag,
        "--results",
        host_results_dir,
        *payload,
    ]


def assert_no_host_code_bind_mount(docker_argv: list[str] | tuple[str, ...]) -> None:
    """Fail if argv mounts host project source over the baked image tree."""
    argv = list(docker_argv)
    for i, tok in enumerate(argv):
        if tok not in {"-v", "--volume"}:
            continue
        if i + 1 >= len(argv):
            continue
        spec = argv[i + 1]
        if ":/opt/projects/g1_ur10e_disturbance/results" in spec:
            continue
        if "/.cache/" in spec or ":/isaac-sim/kit/cache" in spec or ":/root/" in spec:
            continue
        if ":/opt/projects/g1_ur10e_disturbance" in spec and "/results" not in spec.split(":")[-1]:
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


def dockerfile_is_clean_m1v(dockerfile_text: str) -> dict[str, bool]:
    """Static policy checks for the clean-base Dockerfile."""
    low = dockerfile_text.lower()
    return {
        "from_b4": "FROM gmdisturb:b4-p010-20260721" in dockerfile_text,
        "copies_run_phase3": "COPY scripts/run_phase3.py" in dockerfile_text,
        "copies_controller": "COPY g1_disturbance_controller.py" in dockerfile_text,
        "no_pip_install": "pip install" not in low and "pip uninstall" not in low and "pip upgrade" not in low,
        "no_conda": "conda " not in low and "conda\n" not in low,
        "no_apt": "apt-get" not in low and "apt install" not in low,
        "no_numpy_quarantine": "quarantine" not in low and "pip_prebundle_numpy_dedup" not in dockerfile_text,
        "no_site_packages_copy": "site-packages" not in low,
        "no_prebundle_pythonpath": "PYTHONPATH" not in dockerfile_text and "pip_prebundle" not in low,
    }


def dockerfile_bake_mentions_outer_lateral(dockerfile_text: str) -> bool:
    return (
        "COPY scripts/run_phase3.py" in dockerfile_text
        and "COPY g1_disturbance_controller.py" in dockerfile_text
    )


def host_bake_sources_include_outer_lateral(
    repo_root: Path | str,
    *,
    bake_files: tuple[str, ...] | None = None,
) -> dict[str, bool]:
    root = Path(repo_root)
    files = bake_files if bake_files is not None else M1V_BAKE_FILES
    out: dict[str, bool] = {}
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        out[rel] = ("outer_lateral_patrol" in text) or ("scripted_g1_outer_lateral_patrol" in text)
    return out
