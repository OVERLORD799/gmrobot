#!/usr/bin/env bash
# ponytail: smoke test for phase3 — replan + per-part-protocol + vhand-remove
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../../env.sh
source "$(cd "${PROJECT_ROOT}/.." && pwd)/env.sh"
cd "${PROJECT_ROOT}"

CSV="/tmp/smoke_test_phase3.csv"
export PATH="${CONDA_PREFIX}/bin:$PATH"

echo "[smoke] Running phase3..."
python scripts/run_phase3.py \
    --per-part-protocol --replan \
    --max_steps 2000 --vhand-remove-after 2000 --progress_interval 500 \
    --output_csv "$CSV"

echo "[smoke] Analyzing..."
ANALYSIS=$(python scripts/analyze_run.py "$CSV")
echo "$ANALYSIS"

REPLAN=$(echo "$ANALYSIS" | awk '/Replan count:/{print $NF}')
PLACED=$(echo "$ANALYSIS" | awk '/Parts placed:/{print $NF}')

if [ "${REPLAN:-0}" -gt 0 ] && [ "${PLACED:-0}" -gt 0 ]; then
    echo "PASS: replan_count=$REPLAN parts_placed=$PLACED"
else
    echo "FAIL: replan_count=$REPLAN parts_placed=$PLACED (need both >0)"
fi

rm -f "$CSV"
