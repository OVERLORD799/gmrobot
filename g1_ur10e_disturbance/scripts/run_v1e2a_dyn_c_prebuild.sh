#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

python3 "${DIST_ROOT}/scripts/v1e2a_dyn_c_mirrored_patrol_prebuild.py" --repo-root "${DIST_ROOT}/.."
