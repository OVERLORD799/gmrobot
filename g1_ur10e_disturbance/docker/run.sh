#!/usr/bin/env bash
# Host-side helper to run the GMDisturb image with GPU, persistent caches,
# and a bind-mounted results/ directory (survives container deletion).
#
# Usage:
#   ./run.sh phase3 --headless --max_steps 1
#   ./run.sh batch paper_scenarios/
#   ./run.sh smoke
#   ./run.sh shell
#   ./run.sh --tag gmdisturb:latest phase3 --help
#
# Env overrides:
#   TAG / IMAGE_TAG   image tag (default: gmdisturb:paper-demo-20260718)
#   CACHE_ROOT        host cache root (default: ~/.cache/gmdisturb-docker)
#   RESULTS_DIR       host results dir (default: <repo>/results)
#   DOCKER_EXTRA_ARGS extra docker run args (quoted string)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TAG="${TAG:-${IMAGE_TAG:-gmdisturb:paper-demo-20260718}}"
CACHE_ROOT="${CACHE_ROOT:-${HOME}/.cache/gmdisturb-docker}"
RESULTS_DIR="${RESULTS_DIR:-${REPO_ROOT}/results}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      TAG="$2"
      shift 2
      ;;
    --results)
      RESULTS_DIR="$2"
      shift 2
      ;;
    --cache-root)
      CACHE_ROOT="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

mkdir -p \
  "${RESULTS_DIR}" \
  "${CACHE_ROOT}/kit" \
  "${CACHE_ROOT}/ov" \
  "${CACHE_ROOT}/pip" \
  "${CACHE_ROOT}/gl" \
  "${CACHE_ROOT}/logs" \
  "${CACHE_ROOT}/data" \
  "${CACHE_ROOT}/documents"

# Interactive TTY when stdout is a terminal (shell / debugging)
DOCKER_TTY_ARGS=()
if [[ -t 0 && -t 1 ]]; then
  DOCKER_TTY_ARGS+=(-it)
fi

FORWARD_ENV_VARS=(
  GMDISTURB_SCENE_CAMERA_OVERRIDE
  GMDISTURB_SCENE_CAMERA_POS
  GMDISTURB_SCENE_CAMERA_ROT
)
FORWARD_ENV_ARGS=()
for _var in "${FORWARD_ENV_VARS[@]}"; do
  if [[ -n "${!_var-}" ]]; then
    FORWARD_ENV_ARGS+=(-e "${_var}=${!_var}")
  fi
done

# shellcheck disable=SC2086
exec docker run --gpus all --rm \
  "${DOCKER_TTY_ARGS[@]}" \
  -e ACCEPT_EULA=Y \
  -e PRIVACY_CONSENT=Y \
  -e OMNI_KIT_ACCEPT_EULA=YES \
  -e ISAAC_PYTHON=/isaac-sim/kit/python/bin/python3 \
  -v "${RESULTS_DIR}:/opt/projects/g1_ur10e_disturbance/results" \
  -v "${CACHE_ROOT}/kit:/isaac-sim/kit/cache" \
  -v "${CACHE_ROOT}/ov:/root/.cache/ov" \
  -v "${CACHE_ROOT}/pip:/root/.cache/pip" \
  -v "${CACHE_ROOT}/gl:/root/.cache/nvidia" \
  -v "${CACHE_ROOT}/logs:/root/.nvidia-omniverse/logs" \
  -v "${CACHE_ROOT}/data:/root/.local/share/ov/data" \
  -v "${CACHE_ROOT}/documents:/root/Documents" \
  "${FORWARD_ENV_ARGS[@]}" \
  ${DOCKER_EXTRA_ARGS:-} \
  "${TAG}" \
  "$@"
