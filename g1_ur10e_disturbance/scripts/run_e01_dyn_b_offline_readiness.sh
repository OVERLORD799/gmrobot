#!/usr/bin/env bash
# E01-Dyn-B offline readiness/precheck runner. Default is non-executing precheck.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_JSON="${DIST_ROOT}/docs/cross-project/vlm-v1m1p-dyn-b-offline-readiness-2026-07-23.json"

ENABLE_CAPTURE="${ENABLE_CAPTURE:-0}"
EXECUTE_CAPTURE="${EXECUTE_CAPTURE:-0}"

python3 - <<'PY' "${DIST_ROOT}" "${OUT_JSON}" "${ENABLE_CAPTURE}" "${EXECUTE_CAPTURE}"
import json
import sys
from pathlib import Path

dist_root = Path(sys.argv[1])
out_json = Path(sys.argv[2])
enable_capture = str(sys.argv[3]).strip() in {"1", "true", "yes", "on"}
execute_capture = str(sys.argv[4]).strip() in {"1", "true", "yes", "on"}

sys.path.insert(0, str(dist_root))
from e01_dyn_b_offline_readiness import full_readiness_report, write_json  # noqa: E402

report = full_readiness_report(enable_capture=enable_capture, execute_capture=execute_capture)
write_json(out_json, report)
print(json.dumps({"verdict": report["verdict"], "json": str(out_json)}, ensure_ascii=True))
PY
