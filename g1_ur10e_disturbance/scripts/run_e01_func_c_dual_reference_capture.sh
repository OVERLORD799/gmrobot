#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${REPO_ROOT}/results/paper_demo/v1e01_func_c_dual_reference_m1f11"
ASSERT_JSON="${OUT_DIR}/meta/runtime_scene_assertions.json"
SCENE_DIR="${OUT_DIR}/scene"
CMD_TXT="${OUT_DIR}/meta/canonical_app_launcher_inner_command.txt"

mkdir -p "${OUT_DIR}/meta"
export GMDISTURB_V1E01_FUNC_C_VISUAL="${GMDISTURB_V1E01_FUNC_C_VISUAL:-1}"
python3 - <<'PY' "${REPO_ROOT}" "${SCENE_DIR}" "${ASSERT_JSON}" "${CMD_TXT}"
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
scene_dir = sys.argv[2]
assert_json = sys.argv[3]
cmd_txt = Path(sys.argv[4])

sys.path.insert(0, str(repo_root))
from func_c_dual_reference_smoke_guard import (  # noqa: E402
    assert_required_switches,
    assert_single_camera_flag,
    assert_single_launcher_and_entrypoint,
    build_dual_reference_smoke_inner_command,
    preflight_camera_flag_or_fail,
)

inner = build_dual_reference_smoke_inner_command(
    camera_output_dir=scene_dir,
    runtime_assertions_json=assert_json,
)
preflight_camera_flag_or_fail(inner)
assert_single_camera_flag(inner)
assert_single_launcher_and_entrypoint(inner)
assert_required_switches(inner)
cmd_txt.write_text(inner + "\n", encoding="utf-8")
print(f"canonical_inner_command={cmd_txt}")
PY

python3 "${SCRIPT_DIR}/run_e01_func_c_dual_reference_capture.py" \
  --runtime-assertions-json "${ASSERT_JSON}"

echo "runtime_assertions=${ASSERT_JSON}"
