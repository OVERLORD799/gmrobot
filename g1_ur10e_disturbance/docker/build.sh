#!/usr/bin/env bash
# Build GMDisturb Docker image.
#
# Usage:
#   ./build.sh                    # build with default tag
#   ./build.sh --tag v2.0         # custom tag
#   ./build.sh --push             # build + push to ghcr.io
#   ./build.sh --no-assets        # skip asset copy (CI: assets pre-staged)
#
# Env vars (override defaults for CI):
#   GMDISTURB_ROOT  — path to g1_ur10e_disturbance  (default: ../g1_ur10e_disturbance)
#   GMROBOT_ROOT    — path to GMRobot               (default: ../GMRobot)
#   PRESSURE_MAT    — path to pressure_mat_repro    (default: ../pressure_mat_repro)
#   GHCR_REPO       — ghcr.io target, e.g. overlord799/gmrobot
set -euo pipefail

TAG="gmdisturb:paper-demo-20260718"
SKIP_ASSETS=false
PUSH=false
BASE_IMAGE="nvcr.io/nvidia/isaac-sim:5.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONTEXT="${WORKSPACE_ROOT}/.docker_build_context"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)              TAG="$2"; shift 2 ;;
    --no-assets|--no-assets-copy) SKIP_ASSETS=true; shift ;;
    --push)             PUSH=true; shift ;;
    *)                  echo "Unknown: $1"; exit 1 ;;
  esac
done

# Paths — env var or workspace-relative default (CI overrides these)
GMDISTURB_ROOT="${GMDISTURB_ROOT:-${WORKSPACE_ROOT}/g1_ur10e_disturbance}"
GMROBOT_ROOT="${GMROBOT_ROOT:-${WORKSPACE_ROOT}/GMRobot}"
PRESSURE_MAT="${PRESSURE_MAT:-${WORKSPACE_ROOT}/pressure_mat_repro}"

echo "=== GMDisturb Docker Build ==="
echo "Tag:        ${TAG}"
echo "GMDisturb:  ${GMDISTURB_ROOT}"
echo "GMRobot:    ${GMROBOT_ROOT}"
echo "Pressure:   ${PRESSURE_MAT}"

# ── Prepare build context (assets only; projects via named build-contexts) ──
# Keep context outside the copied trees to avoid recursive inclusion.
CONTEXT="${WORKSPACE_ROOT}/.docker_build_context"
rm -rf "${CONTEXT}"
mkdir -p "${CONTEXT}"

# ── Git-ignored assets ─────────────────────────
if [ "${SKIP_ASSETS}" = false ]; then
  echo "Collecting git-ignored assets..."

  # GMRobot USD assets (~200 MB)
  GMROBOT_ASSETS="${GMROBOT_ROOT}/source/GMRobot/GMRobot/assets"
  if [ -d "${GMROBOT_ASSETS}" ]; then
    mkdir -p "${CONTEXT}/gmrobot_assets"
    cp -r "${GMROBOT_ASSETS}"/* "${CONTEXT}/gmrobot_assets/" 2>/dev/null || true
    echo "  GMRobot assets: $(find "${CONTEXT}/gmrobot_assets" -type f | wc -l) files"
  else
    echo "  WARNING: GMRobot assets not found at ${GMROBOT_ASSETS}"
  fi

  # G1 robot + walk policy + tactile mat from pressure_mat_repro
  mkdir -p "${CONTEXT}/g1_assets"
  for f in \
    "${PRESSURE_MAT}/isaac_lab_task/pressure_mat_deploy/data/g1_29dof_modified_new_91.usd" \
    "${PRESSURE_MAT}/policy/0121_walk.pt" \
    "${PRESSURE_MAT}/isaac_lab_task/pressure_mat_deploy/data/tactile_mat_32x32_4m.usd" \
    "${PRESSURE_MAT}/isaac_lab_task/pressure_mat_deploy/data/tactile_mat_64x64_4m.usd"
  do
    if [ -f "$f" ]; then
      cp "$f" "${CONTEXT}/g1_assets/"
      echo "  $(basename $f)"
    fi
  done
  echo "  g1_assets: $(find "${CONTEXT}/g1_assets" -type f | wc -l) files"
fi

# ── Resolve base image digest for reproducibility ──
BASE_IMAGE_DIGEST="unknown"
if docker image inspect "${BASE_IMAGE}" >/dev/null 2>&1; then
  BASE_IMAGE_DIGEST="$(docker image inspect --format='{{index .RepoDigests 0}}' "${BASE_IMAGE}" 2>/dev/null || true)"
  if [[ -z "${BASE_IMAGE_DIGEST}" || "${BASE_IMAGE_DIGEST}" == "<no value>" ]]; then
    BASE_IMAGE_DIGEST="$(docker image inspect --format='{{.Id}}' "${BASE_IMAGE}" 2>/dev/null || echo unknown)"
  fi
else
  echo "WARNING: base image ${BASE_IMAGE} not present locally; digest will be 'unknown'"
  echo "         Pull first: docker pull ${BASE_IMAGE}"
fi
echo "Base image: ${BASE_IMAGE}"
echo "Base digest/id: ${BASE_IMAGE_DIGEST}"

# ── Build ──────────────────────────────────────
echo "Building ${TAG}..."
# Named contexts avoid BuildKit refusing absolute symlinks outside the main context.
# Use host network so container can reach local HTTP proxy (e.g. 127.0.0.1:7897)
BUILD_NETWORK_ARGS=()
if ss -ltn 2>/dev/null | grep -q ':7897'; then
  export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}"
  export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"
  export http_proxy="${http_proxy:-$HTTP_PROXY}"
  export https_proxy="${https_proxy:-$HTTPS_PROXY}"
  BUILD_NETWORK_ARGS+=(--network=host)
  echo "Using host network + proxy ${HTTP_PROXY}"
fi
docker build \
  --tag "${TAG}" \
  --file "${SCRIPT_DIR}/Dockerfile" \
  --build-context gmrobot="${GMROBOT_ROOT}" \
  --build-context pressure="${PRESSURE_MAT}" \
  --build-context gmdisturb="${GMDISTURB_ROOT}" \
  ${BUILD_NETWORK_ARGS[@]+"${BUILD_NETWORK_ARGS[@]}"} \
  --build-arg HTTP_PROXY="${HTTP_PROXY:-}" \
  --build-arg HTTPS_PROXY="${HTTPS_PROXY:-}" \
  --build-arg http_proxy="${http_proxy:-}" \
  --build-arg https_proxy="${https_proxy:-}" \
  --build-arg BASE_IMAGE="${BASE_IMAGE}" \
  --build-arg BASE_IMAGE_DIGEST="${BASE_IMAGE_DIGEST}" \
  "${CONTEXT}"

# Persist host-side build metadata next to the image tag
META_DIR="${GMDISTURB_ROOT}/docker/image_meta"
mkdir -p "${META_DIR}"
IMAGE_ID="$(docker image inspect --format='{{.Id}}' "${TAG}" 2>/dev/null || echo unknown)"
{
  echo "tag=${TAG}"
  echo "image_id=${IMAGE_ID}"
  echo "base_image=${BASE_IMAGE}"
  echo "base_image_digest=${BASE_IMAGE_DIGEST}"
  echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${META_DIR}/${TAG##*:}.txt"
echo "Wrote build metadata: ${META_DIR}/${TAG##*:}.txt"

# ── Push (optional) ────────────────────────────
if [ "${PUSH}" = true ]; then
  GHCR_REPO="${GHCR_REPO:-overlord799/gmrobot}"
  if [ -z "${GHCR_REPO:-}" ]; then
    echo "ERROR: GHCR_REPO not set. Example: GHCR_REPO=overlord799/gmrobot"
    exit 1
  fi
  GHCR_TAG="ghcr.io/${GHCR_REPO}:${TAG##*:}"
  echo "Pushing ${GHCR_TAG}..."
  docker tag "${TAG}" "${GHCR_TAG}"
  docker push "${GHCR_TAG}"
  echo "Pushed: ${GHCR_TAG}"
fi

# ── Cleanup ────────────────────────────────────
rm -rf "${CONTEXT}"
echo "Done: ${TAG}"
