#!/usr/bin/env bash
# E01-Dyn-A one-shot formal capture (0 POST). Failures must not retune/rerun.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"
TAG="${TAG:-gmdisturb:e01-dyn-a-20260722}"
OUT_REL="results/paper_demo/v1e01_dyn_a_capture_20260722"
OUT_HOST="${WS_ROOT}/${OUT_REL}"
# Dual results bind-mount is g1_ur10e_disturbance/results
OUT_DISTURB="${REPO_ROOT}/results/paper_demo/v1e01_dyn_a_capture_20260722"
MODE="${1:-capture}"  # smoke|capture|analyze

mkdir -p "${OUT_DISTURB}"/{scene,manifest,safety_logs,meta}

export GMDISTURB_SCENE_CAMERA_OVERRIDE=1
export GMDISTURB_SCENE_CAMERA_POS="0.2,0.0,3.2"
export GMDISTURB_SCENE_CAMERA_ROT="0.7071,0.0,0.7071,0.0"

COMMON_ENV=(
  -e GMDISTURB_SCENE_CAMERA_OVERRIDE=1
  -e GMDISTURB_SCENE_CAMERA_POS=0.2,0.0,3.2
  -e GMDISTURB_SCENE_CAMERA_ROT=0.7071,0.0,0.7071,0.0
  -e ACCEPT_EULA=Y
  -e PRIVACY_CONSENT=Y
  -e OMNI_KIT_ACCEPT_EULA=YES
)

run_docker() {
  # shellcheck disable=SC2086
  docker run --gpus all --rm \
    "${COMMON_ENV[@]}" \
    -v "${REPO_ROOT}/results:/opt/projects/g1_ur10e_disturbance/results" \
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
  echo "${out}"
}

case "${MODE}" in
  smoke)
    xid_snapshot before_smoke
    run_docker bash -lc '
      set -e
      cd /opt/projects/g1_ur10e_disturbance
      /isaac-sim/python.sh -c "import scene_camera_override, e01_dyn_a_capture; print(\"canonical_import_ok\")"
      /isaac-sim/python.sh scripts/run_phase3.py --headless --seed 42 \
        --scenario arm_wave --max_steps 1 --progress_interval 1 \
        --motion_source_label scripted_g1_locomotion_arm_wave \
        --save_camera --camera_output_dir results/paper_demo/v1e01_dyn_a_capture_20260722/smoke_scene \
        --camera_save_steps 0 \
        --output_csv results/paper_demo/v1e01_dyn_a_capture_20260722/smoke_phase3.csv \
        2>&1 | tee results/paper_demo/v1e01_dyn_a_capture_20260722/meta/smoke_stdout.txt
    '
    xid_snapshot after_smoke
    ;;
  capture)
    if [[ -f "${OUT_DISTURB}/meta/formal_capture_done.flag" ]]; then
      echo "REFUSE: formal capture already marked done; no retune/rerun."
      exit 2
    fi
    xid_snapshot before_capture
    set +e
    run_docker bash -lc '
      set -e
      cd /opt/projects/g1_ur10e_disturbance
      /isaac-sim/python.sh scripts/run_phase3.py --headless --seed 42 \
        --scenario arm_wave --max_steps 500 --progress_interval 1 \
        --motion_source_label scripted_g1_locomotion_arm_wave \
        --save_camera \
        --camera_output_dir results/paper_demo/v1e01_dyn_a_capture_20260722/scene \
        --camera_save_steps 210,280 \
        --camera_pose_json results/paper_demo/v1e01_dyn_a_capture_20260722/meta/camera_pose.json \
        --body_pose_jsonl results/paper_demo/v1e01_dyn_a_capture_20260722/meta/body_poses.jsonl \
        --output_csv results/paper_demo/v1e01_dyn_a_capture_20260722/safety_logs/phase3.csv \
        2>&1 | tee results/paper_demo/v1e01_dyn_a_capture_20260722/meta/capture_stdout.txt
    '
    ec=$?
    set -e
    echo "${ec}" >"${OUT_DISTURB}/meta/isaac_exit_code.txt"
    xid_snapshot after_capture
    date -Is >"${OUT_DISTURB}/meta/formal_capture_done.flag"
    echo "capture_exit=${ec}"
    exit "${ec}"
    ;;
  analyze)
    python3 "${REPO_ROOT}/scripts/analyze_e01_dyn_a_capture.py" \
      --results-dir "${OUT_DISTURB}"
    ;;
  *)
    echo "usage: $0 smoke|capture|analyze"
    exit 1
    ;;
esac
