#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISTURB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DISTURB_ROOT}/.." && pwd)"
GM_ROOT="${REPO_ROOT}/GMRobot"

REQUIRED_HEAD="f361363"
TAG="gmdisturb:e01-func-c-empty-source-m1f7-20260723"
DOCKERFILE="${GM_ROOT}/docker/Dockerfile.e01-func-c-empty-source-m1f7"
RESULT_DIR="${DISTURB_ROOT}/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723"
DOC_BASENAME="vlm-v1m1f71-func-c-runtime-assertion-context-fix-2026-07-23"
DOC_MD="${DISTURB_ROOT}/docs/cross-project/${DOC_BASENAME}.md"
DOC_JSON="${DISTURB_ROOT}/docs/cross-project/${DOC_BASENAME}.json"

mkdir -p "${RESULT_DIR}/meta"

HEAD_SHORT="$(git -C "${REPO_ROOT}" rev-parse --short=7 HEAD)"
if [[ "${HEAD_SHORT}" != "${REQUIRED_HEAD}" ]]; then
  echo "STOP_NO_RETRY: HEAD mismatch (${HEAD_SHORT} != ${REQUIRED_HEAD})"
  exit 21
fi
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]]; then
  echo "STOP_NO_RETRY: worktree not clean"
  exit 22
fi

# Host-side prebuild checks: source/env/config contracts only (no pxr import).
python3 "${GM_ROOT}/scripts/test_e01_func_c_capture_unit.py"
python3 "${GM_ROOT}/scripts/test_runtime_scene_assertions_unit.py"
python3 "${DISTURB_ROOT}/scripts/test_v1m1f7_smoke_context_unit.py"
python3 "${DISTURB_ROOT}/scripts/test_v1e02_dataset_candidate_manifest_unit.py"
python3 "${DISTURB_ROOT}/scripts/validate_v1e02_dataset_candidate_manifest.py" \
  --manifest "${DISTURB_ROOT}/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json"

docker build -f "${DOCKERFILE}" -t "${TAG}" "${GM_ROOT}"

set +e
docker run --gpus all --rm \
  -e ACCEPT_EULA=Y \
  -e PRIVACY_CONSENT=Y \
  -e OMNI_KIT_ACCEPT_EULA=YES \
  -e GMROBOT_V1E01_TARGET_FULL=1 \
  -e GMROBOT_V1E01_VISUAL_ONLY=1 \
  -e GMROBOT_RUNTIME_SCENE_ASSERTIONS_PATH="/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723/meta/runtime_scene_assertions.json" \
  -v "${DISTURB_ROOT}/results:/opt/projects/g1_ur10e_disturbance/results" \
  -v "${GM_ROOT}/configs/ivj_v1e01_target_container_full.yaml:/opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/shadow/target_full_override.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/target_full_override.py:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/shadow/runtime_scene_assertions.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/runtime_scene_assertions.py:ro" \
  -v "${HOME}/.cache/gmdisturb-docker/kit:/isaac-sim/kit/cache" \
  -v "${HOME}/.cache/gmdisturb-docker/ov:/root/.cache/ov" \
  -v "${HOME}/.cache/gmdisturb-docker/pip:/root/.cache/pip" \
  -v "${HOME}/.cache/gmdisturb-docker/gl:/root/.cache/nvidia" \
  -v "${HOME}/.cache/gmdisturb-docker/logs:/root/.nvidia-omniverse/logs" \
  -v "${HOME}/.cache/gmdisturb-docker/data:/root/.local/share/ov/data" \
  -v "${HOME}/.cache/gmdisturb-docker/documents:/root/Documents" \
  "${TAG}" \
  bash -lc "set -euo pipefail
/isaac-sim/python.sh /opt/projects/GMRobot/scripts/gm_state_machine_agent.py --task gm --headless --enable_cameras --enable_safety --safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml --save_camera --camera_output_dir /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723/scene --camera_save_interval 1 --max_steps 1
" \
  > "${RESULT_DIR}/meta/smoke_stdout.txt" \
  2> "${RESULT_DIR}/meta/smoke_stderr.txt"
SMOKE_EC=$?
set -e
printf '%s\n' "${SMOKE_EC}" > "${RESULT_DIR}/meta/smoke_exit_code.txt"

python3 - <<'PY'
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/czz/GMrobot/g1_ur10e_disturbance/scripts")
from v1m1f7_smoke_context import load_runtime_scene_assertions_or_raise

repo = Path("/home/czz/GMrobot")
disturb = repo / "g1_ur10e_disturbance"
result_dir = disturb / "results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723"
doc_json = disturb / "docs/cross-project/vlm-v1m1f71-func-c-runtime-assertion-context-fix-2026-07-23.json"
doc_md = disturb / "docs/cross-project/vlm-v1m1f71-func-c-runtime-assertion-context-fix-2026-07-23.md"
frame = result_dir / "scene/frame_000000_env0.png"

smoke_ec = int((result_dir / "meta/smoke_exit_code.txt").read_text().strip())
runtime = None
runtime_err = None
try:
    runtime = load_runtime_scene_assertions_or_raise(result_dir)
except BaseException as exc:
    runtime_err = str(exc)

record = {
    "task": "V1-M1F7.1 runtime assertion context fix",
    "date": "2026-07-23",
    "status": "SMOKE_STARTUP_FAIL_FINAL" if (smoke_ec != 0 or not frame.is_file() or runtime is None) else "PASS",
    "next_gate": "FIX_VALIDATION_CONTEXT_ONLY" if (smoke_ec != 0 or not frame.is_file() or runtime is None) else "NONE",
    "raw_startup_failed": bool(smoke_ec != 0),
    "frame_absent": bool(not frame.is_file()),
    "runtime_scene_assertions_present": bool(runtime is not None),
    "runtime_scene_assertions_error": runtime_err,
    "runtime_scene_assertions": runtime,
    "smoke_exit_code": smoke_ec,
    "container_usd_sha256": hashlib.sha256((repo / "GMRobot/source/GMRobot/GMRobot/assets/container.usd").read_bytes()).hexdigest(),
}
doc_json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
doc_md.write_text(
    "# V1-M1F7.1 Func-C runtime assertion context fix（2026-07-23）\n\n"
    "- verdict: `SMOKE_STARTUP_FAIL_FINAL`\n"
    "- next_gate: `FIX_VALIDATION_CONTEXT_ONLY`\n"
    "- raw startup failed / frame absent facts preserved\n"
    "- runtime assertions must be produced in Kit context at `runtime_scene_assertions.json`\n"
    "- assertions cannot be deleted and cannot be downgraded to warning\n",
    encoding="utf-8",
)
if record["status"] != "PASS":
    raise SystemExit("STOP_NO_RETRY: smoke context gate failed")
PY

echo "DONE: ${TAG}"
