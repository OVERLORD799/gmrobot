#!/usr/bin/env bash
# E01-Func-C one-shot 0-POST capture (GMRobot agent). Failures must not retune/rerun.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"
TAG="${TAG:-gmdisturb:e01-func-c-20260722}"
OUT_DISTURB="${REPO_ROOT}/results/paper_demo/v1e01_func_c_capture_20260722"
MODE="${1:-capture}"

mkdir -p "${OUT_DISTURB}"/{scene,manifest,safety_logs,meta}

HOST_GM="${WS_ROOT}/GMRobot"

run_docker() {
  # shellcheck disable=SC2086
  docker run --gpus all --rm \
    -e ACCEPT_EULA=Y \
    -e PRIVACY_CONSENT=Y \
    -e OMNI_KIT_ACCEPT_EULA=YES \
    -e GMROBOT_V1E01_TARGET_FULL=1 \
    -v "${REPO_ROOT}/results:/opt/projects/g1_ur10e_disturbance/results" \
    -v "${HOST_GM}/configs/ivj_v1e01_target_container_full.yaml:/opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml:ro" \
    -v "${HOST_GM}/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py:ro" \
    -v "${HOST_GM}/source/GMRobot/GMRobot/shadow/target_full_override.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/target_full_override.py:ro" \
    -v "${HOST_GM}/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py:ro" \
    -v "${HOST_GM}/source/GMRobot/GMRobot/assets/container_full_visual.usd:/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_full_visual.usd:ro" \
    -v "${HOME}/.cache/gmdisturb-docker/kit:/isaac-sim/kit/cache" \
    -v "${HOME}/.cache/gmdisturb-docker/ov:/root/.cache/ov" \
    -v "${HOME}/.cache/gmdisturb-docker/pip:/root/.cache/pip" \
    -v "${HOME}/.cache/gmdisturb-docker/gl:/root/.cache/nvidia" \
    -v "${HOME}/.cache/gmdisturb-docker/logs:/root/.nvidia-omniverse/logs" \
    -v "${HOME}/.cache/gmdisturb-docker/data:/root/.local/share/ov/data" \
    -v "${HOME}/.cache/gmdisturb-docker/documents:/root/Documents" \
    ${DOCKER_EXTRA_ARGS:-} \
    "${TAG}" \
    "$@"
}

xid_snapshot() {
  local label="$1"
  local out="${OUT_DISTURB}/meta/xid_${label}.txt"
  {
    echo "label=${label}"
    echo "time=$(date -Is)"
    nvidia-smi -q -d XID 2>/dev/null | head -n 40 || echo "nvidia-smi_xid_unavailable"
    dmesg 2>/dev/null | grep -i "NVRM: Xid" | tail -n 20 || true
  } >"${out}" || true
}

case "${MODE}" in
  precheck)
    python3 "${HOST_GM}/scripts/analyze_e01_func_c_capture.py" --precheck-only \
      --assets-dir "${HOST_GM}/source/GMRobot/GMRobot/assets" \
      --results-dir "${OUT_DISTURB}"
    ;;
  smoke)
    xid_snapshot before_smoke
    set +e
    run_docker bash -lc "set -euo pipefail
/isaac-sim/python.sh -c 'from GMRobot.shadow.target_full_override import target_full_enabled; import os; assert os.environ.get(\"GMROBOT_V1E01_TARGET_FULL\")==\"1\"; print(\"canonical_import_ok\", target_full_enabled())'
/isaac-sim/python.sh /opt/projects/GMRobot/scripts/gm_state_machine_agent.py --task gm --headless --enable_cameras --enable_safety --safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml --save_camera --camera_output_dir /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/smoke_scene --camera_save_interval 1 --max_steps 1 2>&1 | tee /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/meta/smoke_stdout.txt
"
    ec=$?
    set -e
    echo "${ec}" >"${OUT_DISTURB}/meta/smoke_exit_code.txt"
    xid_snapshot after_smoke
    echo "smoke_exit=${ec}"
    exit "${ec}"
    ;;
  capture)
    if [[ -f "${OUT_DISTURB}/meta/formal_capture_done.flag" ]]; then
      echo "REFUSE: formal capture already marked done; no retune/rerun."
      exit 2
    fi
    printf '%s\n' '{"seed":51,"note":"agent CLI has no --seed; layout deterministic; recorded for manifest"}' \
      >"${OUT_DISTURB}/meta/seed_record.json"
    xid_snapshot before_capture
    set +e
    run_docker bash -lc "set -euo pipefail
/isaac-sim/python.sh /opt/projects/GMRobot/scripts/gm_state_machine_agent.py --task gm --headless --enable_cameras --enable_safety --safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml --save_camera --camera_output_dir /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/scene --camera_save_interval 100 --max_steps 300 2>&1 | tee /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/meta/capture_stdout.txt
"
    ec=$?
    set -e
    echo "${ec}" >"${OUT_DISTURB}/meta/isaac_exit_code.txt"
    xid_snapshot after_capture
    date -Is >"${OUT_DISTURB}/meta/formal_capture_done.flag"
    echo "capture_exit=${ec}"
    exit "${ec}"
    ;;
  analyze)
    python3 "${HOST_GM}/scripts/analyze_e01_func_c_capture.py" \
      --results-dir "${OUT_DISTURB}" \
      --assets-dir "${HOST_GM}/source/GMRobot/GMRobot/assets"
    ;;
  *)
    echo "usage: $0 precheck|smoke|capture|analyze"
    exit 1
    ;;
esac
