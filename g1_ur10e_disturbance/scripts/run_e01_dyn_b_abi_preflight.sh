#!/usr/bin/env bash
# One-shot ABI import preflight for E01-Dyn-B (no formal capture).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS_ROOT="$(cd "${DIST_ROOT}/.." && pwd)"
TAG="${TAG:-gmdisturb:e01-func-c-m1j-20260723}"
OUT_DIR="${DIST_ROOT}/results/paper_demo/v1e01_dyn_b_preflight_m1r_20260723"
META_DIR="${OUT_DIR}/meta"
RUNNER="${WS_ROOT}/GMRobot/scripts/capture_one_shot_runner.py"

mkdir -p "${META_DIR}"

PY_GUARD="$(
python3 - <<'PY' "${DIST_ROOT}"
import sys
sys.path.insert(0, sys.argv[1])
from e01_dyn_b_runtime_guard import import_preflight_command
print(
    import_preflight_command()
    + " --json-out /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1r_20260723/meta/import_preflight_report.json"
)
PY
)"

python3 "${RUNNER}" \
  --result-dir "${OUT_DIR}" \
  --status-file "${META_DIR}/run_status.json" \
  --stdout-file "${META_DIR}/capture_stdout.txt" \
  --stderr-file "${META_DIR}/capture_stderr.txt" \
  --forbid-pattern "Traceback \\(most recent call last\\):" \
  --forbid-pattern "numpy\\.dtype size changed" \
  --forbid-pattern "cannot import name 'broadcast_to' from 'numpy\\.lib\\.stride_tricks'" \
  --require-path "${META_DIR}/import_preflight_report.json" \
  -- \
  docker run --rm --gpus all --network host --ipc=host \
    --ulimit memlock=-1 --ulimit stack=67108864 \
    -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y -e OMNI_KIT_ACCEPT_EULA=YES \
    -v "${DIST_ROOT}:/opt/projects/g1_ur10e_disturbance" \
    -v "${OUT_DIR}:/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1r_20260723" \
    -v "${HOME}/.cache/gmdisturb-docker/kit:/isaac-sim/kit/cache" \
    -v "${HOME}/.cache/gmdisturb-docker/ov:/root/.cache/ov" \
    -v "${HOME}/.cache/gmdisturb-docker/pip:/root/.cache/pip" \
    -v "${HOME}/.cache/gmdisturb-docker/gl:/root/.cache/nvidia" \
    -v "${HOME}/.cache/gmdisturb-docker/logs:/root/.nvidia-omniverse/logs" \
    -v "${HOME}/.cache/gmdisturb-docker/data:/root/.local/share/ov/data" \
    -v "${HOME}/.cache/gmdisturb-docker/documents:/root/Documents" \
    "${TAG}" \
    bash -lc "set -euo pipefail; ${PY_GUARD}"
