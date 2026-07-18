#!/usr/bin/env bash
# GMDisturb batch runner — multi-episode sweep via run_phase3.py.
#
# Usage:
#   bash scripts/run_batch.sh
#   bash scripts/run_batch.sh "0.5,0.8,1.0" 3 3000

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../env.sh
source "$(cd "${SCRIPT_DIR}/../.." && pwd)/env.sh"

RADII="${1:-0.5,0.8,1.0}"
REPEATS="${2:-3}"
MAX_STEPS="${3:-3000}"
SPEED="${4:-0.08}"
OUTDIR="${5:-/tmp/gmdisturb_batch}"

IFS=',' read -ra RADIUS_LIST <<< "$RADII"
TOTAL=$((${#RADIUS_LIST[@]} * REPEATS))

PYTHON="${CONDA_PREFIX}/bin/python3"
SCRIPT="${GMDISTURB_ROOT}/scripts/run_phase3.py"
ISAAC_LAB="${ISAACLAB_ROOT}"

export OMNI_KIT_ACCEPT_EULA=YES
export DISPLAY="${DISPLAY:-:0}"
export CONDA_PREFIX

mkdir -p "$OUTDIR"
SUMMARY="$OUTDIR/batch_summary.csv"
echo "radius,repeat,success,fell,stop,slow,replan,stuck,parts,min_dist,elapsed_s" > "$SUMMARY"

echo "[batch] ${#RADIUS_LIST[@]} radii x $REPEATS repeats = $TOTAL episodes"
echo "[batch] Output: $OUTDIR"
echo ""

EP=0
for R in "${RADIUS_LIST[@]}"; do
    for ((REP=1; REP<=REPEATS; REP++)); do
        EP=$((EP + 1))
        CSV="$OUTDIR/r${R}_run${REP}.csv"
        TAG="r=${R} #${REP}/${REPEATS}"
        echo "=== Episode $EP/$TOTAL: $TAG ==="
        echo "[batch] Start: $(date +%H:%M:%S)"

        T0=$(date +%s)
        cd "$ISAAC_LAB" && "$PYTHON" -u "$SCRIPT" \
            --virtual-hand "$R" \
            --virtual-hand-speed "$SPEED" \
            --max_steps "$MAX_STEPS" \
            --progress_interval 500 \
            --output_csv "$CSV" \
            --replan \
            > "$OUTDIR/ep${EP}_stdout.txt" 2> "$OUTDIR/ep${EP}_stderr.txt"
        grep -E 'phase3|PARTS|Safety|replan|tilt|fell|Error|Traceback' \
            "$OUTDIR/ep${EP}_stdout.txt" "$OUTDIR/ep${EP}_stderr.txt" || true
        T1=$(date +%s)
        ELAPSED=$((T1 - T0))

        # Parse result from CSV
        SUCCESS="False"; FELL="False"; STOP=0; SLOW=0; REPLAN_COUNT=0; STUCK=0; PARTS=0; MIND=0

        # Read CSV for actual metrics
        if [ -f "$CSV" ]; then
            LINE=$(tail -1 "$CSV" 2>/dev/null || echo "")
            if [ -n "$LINE" ]; then
                IFS=',' read -ra FIELDS <<< "$LINE"
                # fields: episode_id,total_steps,policy_steps,parts_placed,parts_total,
                #         task_completed,g1_fell,...,tier0_stop_count,slowdown_count,
                #         replan_count,stuck_count,...,min_g1_ur10e_distance_m,...
                PARTS="${FIELDS[3]:-0}"
                SUCCESS="${FIELDS[5]:-False}"
                FELL="${FIELDS[6]:-False}"
                STOP="${FIELDS[9]:-0}"
                SLOW="${FIELDS[10]:-0}"
                REPLAN_COUNT="${FIELDS[11]:-0}"
                STUCK="${FIELDS[12]:-0}"
                # Find min_dist (3rd from last or specific column)
                MIND="${FIELDS[15]:-0}"
            fi
        fi

        echo "$R,$REP,$SUCCESS,$FELL,$STOP,$SLOW,$REPLAN_COUNT,$STUCK,$PARTS,$MIND,$ELAPSED" >> "$SUMMARY"
        STATUS="?"
        [ "$SUCCESS" = "True" ] && STATUS="OK"
        [ "$FELL" = "True" ] && STATUS="FELL"
        echo "[batch] $STATUS STOP=$STOP SLOW=$SLOW REPLAN=$REPLAN_COUNT parts=$PARTS time=${ELAPSED}s"
        echo ""
    done
done

echo "=== Batch complete ==="
echo "Summary: $SUMMARY"
echo "Episodes: $TOTAL"
cat "$SUMMARY"
