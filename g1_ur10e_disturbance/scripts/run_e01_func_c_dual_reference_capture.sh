#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${REPO_ROOT}/results/paper_demo/v1e01_func_c_dual_reference_m1f11"
ASSERT_JSON="${OUT_DIR}/meta/runtime_scene_assertions.json"

mkdir -p "${OUT_DIR}/meta"
export GMDISTURB_V1E01_FUNC_C_VISUAL="${GMDISTURB_V1E01_FUNC_C_VISUAL:-1}"

python3 "${SCRIPT_DIR}/run_e01_func_c_dual_reference_capture.py" \
  --runtime-assertions-json "${ASSERT_JSON}"

echo "runtime_assertions=${ASSERT_JSON}"
