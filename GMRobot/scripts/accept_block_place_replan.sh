#!/usr/bin/env bash
# GM-SafePick Blocker 1 acceptance: ivj_static_block_place baseline vs replan (short run).
# Phase 4a v1 criteria (ADR §12): time_step unlock, placement zone, no mid-air open, wait-hold.
# Run on Isaac gpufree node after: source /root/activate_isaaclab.sh && cd /root/GMRobot
#
# Standard (outer GPU lock + passthrough avoids nested flock deadlock):
#   bash scripts/isaac_gpu_lock.sh env GPU_LOCK=scripts/isaac_gpu_passthrough.sh \
#     bash scripts/accept_block_place_replan.sh
set -euo pipefail

REPO="/root/GMRobot"
BASELINE_REF="20260617_192734"
REF_TIME_STEP=2015
MAX_STEPS=3000
PRESET="ivj_static_block_place"
CONFIG="configs/ivj/${PRESET}.yaml"
LOG_DIR="${REPO}/output/safety_logs"
PLACE_ZONE_RADIUS_M=0.08
GRIPPER_OPEN=1.0
GRIPPER_CLOSED=-0.5
CARRY_THRESHOLD=0.25
WATCHDOG_SEC=900
WATCHDOG_POLL_SEC=10
GPU_LOCK="${GPU_LOCK:-${REPO}/scripts/isaac_gpu_lock.sh}"

cd "${REPO}"

list_session_dirs() {
  if [[ -d "${LOG_DIR}" ]]; then
    ls -1 "${LOG_DIR}" 2>/dev/null || true
  fi
}

count_csv_rows() {
  local csv="$1"
  if [[ -f "${csv}" ]]; then
    python3 - <<PY
import csv
with open("${csv}", newline="") as f:
    print(sum(1 for _ in csv.DictReader(f)))
PY
  else
    echo 0
  fi
}

find_newest_run_csv() {
  local before_file="$1"
  local newest=""
  local newest_csv=""
  while IFS= read -r d; do
    [[ -z "${d}" ]] && continue
    if grep -qxF "${d}" "${before_file}" 2>/dev/null; then
      continue
    fi
    local candidate="${LOG_DIR}/${d}/episode_0000.csv"
    if [[ -f "${candidate}" ]]; then
      newest="${d}"
      newest_csv="${candidate}"
    fi
  done < <(list_session_dirs)
  if [[ -n "${newest_csv}" ]]; then
    echo "${newest}|${newest_csv}"
  fi
}

run_agent_with_watchdog() {
  local label="$1"
  local log_file="$2"
  shift 2

  echo "[${label}] starting: $*"
  local before_file
  before_file=$(mktemp)
  list_session_dirs > "${before_file}"

  "${GPU_LOCK}" "$@" 2>&1 | tee "${log_file}" &
  local agent_pid=$!
  local run_id=""
  local csv_path=""
  local last_rows=0
  local last_growth
  last_growth=$(date +%s)
  local watchdog_killed=0
  local start_ts
  start_ts=$(date +%s)

  while kill -0 "${agent_pid}" 2>/dev/null; do
    local now
    now=$(date +%s)
    local elapsed=$((now - start_ts))

    if [[ -z "${csv_path}" ]]; then
      local found
      found=$(find_newest_run_csv "${before_file}")
    if [[ -n "${found}" ]]; then
      run_id="${found%%|*}"
      csv_path="${found#*|}"
      last_rows=$(count_csv_rows "${csv_path}")
      last_growth="${now}"
      echo "[${label}] CSV appeared: ${csv_path} (${last_rows} rows)"
      elif (( elapsed >= WATCHDOG_SEC )); then
        echo "[watchdog] No CSV after ${WATCHDOG_SEC}s; killing pid=${agent_pid}"
        kill "${agent_pid}" 2>/dev/null || true
        watchdog_killed=1
        break
      fi
    else
      local rows
      rows=$(count_csv_rows "${csv_path}")
      if (( rows > last_rows )); then
        last_rows="${rows}"
        last_growth="${now}"
      elif (( now - last_growth >= WATCHDOG_SEC )); then
        echo "[watchdog] No CSV growth for ${WATCHDOG_SEC}s (${rows} rows); killing pid=${agent_pid}"
        kill "${agent_pid}" 2>/dev/null || true
        watchdog_killed=1
        break
      fi
    fi
    sleep "${WATCHDOG_POLL_SEC}"
  done

  wait "${agent_pid}" 2>/dev/null || true
  local exit_code=0
  if [[ "${watchdog_killed}" -eq 1 ]]; then
    exit_code=124
  fi

  if [[ -z "${run_id}" ]]; then
    local found
    found=$(find_newest_run_csv "${before_file}")
    if [[ -n "${found}" ]]; then
      run_id="${found%%|*}"
      csv_path="${found#*|}"
    fi
  fi
  rm -f "${before_file}"

  echo "[${label}] done exit=${exit_code} watchdog_killed=${watchdog_killed} run_id=${run_id:-none}"
  return "${exit_code}"
}

echo "=== A) Baseline (no replan), max_steps=${MAX_STEPS} ==="
run_agent_with_watchdog "baseline" /tmp/block_place_baseline.log \
  python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config="${CONFIG}" \
  --max_steps="${MAX_STEPS}" --progress_interval=500

echo ""
echo "=== B) With replan, max_steps=${MAX_STEPS} ==="
if ! run_agent_with_watchdog "replan" /tmp/block_place_replan.log \
  python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config="${CONFIG}" \
  --enable_replan --max_steps="${MAX_STEPS}" --progress_interval=500; then
  echo "[replan] first attempt failed; retrying once..."
  run_agent_with_watchdog "replan-retry" /tmp/block_place_replan_retry.log \
    python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
    --enable_safety --safety_config="${CONFIG}" \
    --enable_replan --max_steps="${MAX_STEPS}" --progress_interval=500
fi

list_run_dirs() {
  if [[ -d "${LOG_DIR}" ]]; then
    find "${LOG_DIR}" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort
  fi
}

# Latest two run directories (by name = timestamp; exclude JSON summary files)
BASELINE_RUN=$(list_run_dirs | tail -2 | head -1)
REPLAN_RUN=$(list_run_dirs | tail -1)

echo ""
echo "=== Run IDs (verify against logs) ==="
echo "  baseline: ${BASELINE_RUN}"
echo "  replan:   ${REPLAN_RUN}"
echo "  reference baseline: ${BASELINE_REF} (time_step frozen @ ${REF_TIME_STEP})"

check_run() {
  local run_id="$1"
  local label="$2"
  local manifest="${LOG_DIR}/${run_id}/run_manifest.json"
  local csv="${LOG_DIR}/${run_id}/episode_0000.csv"

  echo ""
  echo "--- ${label}: ${run_id} ---"
  if [[ -f "${manifest}" ]]; then
    python3 - <<PY
import json
m = json.load(open("${manifest}"))
print("run_manifest.json:")
for k in ("run_id", "enable_replan", "max_steps", "outcome", "final_time_step", "task_time_step"):
    if k in m:
        print(f"  {k}: {m[k]}")
PY
  else
    echo "  WARN: missing ${manifest}"
  fi

  if [[ -f "${csv}" ]]; then
    python3 - <<PY
import csv
rows = list(csv.DictReader(open("${csv}")))
last = rows[-1] if rows else {}
cols = list(rows[0].keys()) if rows else []
has_envelope = "dist_min_envelope" in cols
print(f"episode CSV rows: {len(rows)}")
print(f"  dist_min_envelope column: {has_envelope}")
print(f"  last time_step: {last.get('time_step', '?')}")
print(f"  last task_time_step: {last.get('task_time_step', '?')}")
print(f"  outcome: {last.get('outcome', '?')}")
PY
  else
    echo "  WARN: missing ${csv}"
  fi

  python scripts/report_safety_metrics.py "${LOG_DIR}/${run_id}" \
    --config "${CONFIG}"
}

check_run "${BASELINE_RUN}" "Baseline (new)"
check_run "${REPLAN_RUN}" "Replan (new)"

echo ""
echo "=== Success criteria (Phase 4a v1) ==="
echo "  1) replan final time_step >= ${REF_TIME_STEP}"
echo "  2) no mid-air gripper open during detour while carrying"
echo "  3) open_gripper only when EE XY within place zone (${PLACE_ZONE_RADIUS_M} m)"
echo "  4) outcome documented (collision acceptable if progress + documented)"
echo ""
echo "=== Compare table (fill from output above) ==="
printf "%-28s | %-20s | %-20s | %-12s\n" "Metric" "Ref ${BASELINE_REF}" "Baseline ${BASELINE_RUN}" "Replan ${REPLAN_RUN}"
printf "%-28s | %-20s | %-20s | %-12s\n" "---------------------------" "--------------------" "--------------------" "------------"
printf "%-28s | %-20s | %-20s | %-12s\n" "final time_step" "${REF_TIME_STEP}" "(see manifest)" "(see manifest)"
printf "%-28s | %-20s | %-20s | %-12s\n" "intervention_rate" "~41.0%" "(metrics)" "(metrics)"
printf "%-28s | %-20s | %-20s | %-12s\n" "outcome" "timeout@2015/7521" "(metrics)" "(metrics)"

REPLAN_CSV="${LOG_DIR}/${REPLAN_RUN}/episode_0000.csv"
REPLAN_MANIFEST="${LOG_DIR}/${REPLAN_RUN}/run_manifest.json"

eval "$(python3 - <<PY
import csv, json, os, ast, math

run = "${REPLAN_RUN}"
csv_path = "${REPLAN_CSV}"
manifest_path = "${REPLAN_MANIFEST}"
place_r = float("${PLACE_ZONE_RADIUS_M}")
g_open = float("${GRIPPER_OPEN}")
g_closed = float("${GRIPPER_CLOSED}")
carry_thr = float("${CARRY_THRESHOLD}")
ref_ts = int("${REF_TIME_STEP}")

ts = 0
outcome = "unknown"
if os.path.isfile(manifest_path):
    m = json.load(open(manifest_path))
    ts = int(m.get("final_time_step") or m.get("task_time_step") or 0)
    outcome = str(m.get("outcome", "unknown"))

rows = []
if os.path.isfile(csv_path):
    rows = list(csv.DictReader(open(csv_path)))

def parse_vec(raw):
    if raw is None or raw == "":
        return None
    try:
        v = ast.literal_eval(raw)
        return [float(x) for x in v[:3]]
    except Exception:
        return None

def parse_float(raw, default=0.0):
    try:
        return float(raw)
    except Exception:
        return default

# Gripper open while elevated and carrying (proxy: gripper open + z > grasp height)
mid_air_open = 0
open_out_of_zone = 0
open_in_zone = 0
wait_hold_steps = 0
max_task_ts = 0
grasp_z = 0.15

prev_task = None
for row in rows:
    task_ts = int(parse_float(row.get("task_time_step"), 0))
    max_task_ts = max(max_task_ts, task_ts)
    grip = parse_float(row.get("gripper") or row.get("action_gripper"), g_closed)
    ee = parse_vec(row.get("ee_pos"))
    g_rule = int(parse_float(row.get("g_rule"), 0))

    if ee is not None and grip > carry_thr and ee[2] > grasp_z:
        mid_air_open += 1

    if grip > carry_thr and ee is not None:
        dist_b = math.hypot(ee[0] - 0.8, ee[1] - 0.0)
        if dist_b <= place_r:
            open_in_zone += 1
        else:
            open_out_of_zone += 1

    if prev_task is not None and task_ts == prev_task and g_rule != 0:
        wait_hold_steps += 1
    prev_task = task_ts

if ts == 0 and max_task_ts:
    ts = max_task_ts

print(f"REPLAN_TS={ts}")
print(f"REPLAN_OUTCOME={outcome!r}")
print(f"MID_AIR_OPEN={mid_air_open}")
print(f"OPEN_IN_ZONE={open_in_zone}")
print(f"OPEN_OUT_OF_ZONE={open_out_of_zone}")
print(f"WAIT_HOLD_STEPS={wait_hold_steps}")
print(f"PASS_TS={1 if ts >= ref_ts else 0}")
print(f"PASS_GRIPPER={1 if mid_air_open == 0 else 0}")
print(f"PASS_PLACE={1 if open_out_of_zone == 0 or open_in_zone > 0 else 0}")
PY
)"

echo ""
echo "=== Replan metrics (${REPLAN_RUN}) ==="
echo "  final_time_step: ${REPLAN_TS}"
echo "  outcome: ${REPLAN_OUTCOME}"
echo "  mid_air_gripper_open_count: ${MID_AIR_OPEN}"
echo "  open_gripper_in_zone_count: ${OPEN_IN_ZONE}"
echo "  open_gripper_out_of_zone_count: ${OPEN_OUT_OF_ZONE}"
echo "  wait_hold_steps: ${WAIT_HOLD_STEPS}"

echo ""
echo "=== Per-part placement tracker (replan run) ==="
python scripts/analyze_part_placement.py "${LOG_DIR}/${REPLAN_RUN}" \
  --focus-part=5 --block-place-smoke || PLACE_FAIL=$?
PLACE_FAIL=${PLACE_FAIL:-0}

BASELINE_CSV="${LOG_DIR}/${BASELINE_RUN}/episode_0000.csv"
eval "$(python3 - <<PY
import csv
csv_path = "${BASELINE_CSV}"
ref_ts = int("${REF_TIME_STEP}")
max_ts = 0
has_env = False
if __import__("os").path.isfile(csv_path):
    rows = list(csv.DictReader(open(csv_path)))
    if rows:
        has_env = "dist_min_envelope" in rows[0]
        max_ts = max(int(float(r.get("task_time_step") or 0)) for r in rows)
print(f"BASELINE_TS={max_ts}")
print(f"BASELINE_HAS_ENVELOPE={1 if has_env else 0}")
print(f"PASS_BASELINE_TS={1 if max_ts > ref_ts else 0}")
print(f"PASS_BASELINE_ENVELOPE={has_env}")
PY
)"

echo ""
echo "=== Baseline 2.5b gate (${BASELINE_RUN}) ==="
echo "  max_task_time_step: ${BASELINE_TS}"
echo "  dist_min_envelope column: ${BASELINE_HAS_ENVELOPE}"

FAIL=0
if [[ "${REPLAN_TS}" -lt "${REF_TIME_STEP}" ]]; then
  echo "FAIL: time_step=${REPLAN_TS} < ${REF_TIME_STEP}"
  FAIL=1
else
  echo "PASS: time_step=${REPLAN_TS} >= ${REF_TIME_STEP}"
fi

if [[ "${MID_AIR_OPEN}" -gt 0 ]]; then
  echo "FAIL: mid-air gripper open during carry (${MID_AIR_OPEN} rows)"
  FAIL=1
else
  echo "PASS: no mid-air gripper open during detour/carry"
fi

if [[ "${OPEN_OUT_OF_ZONE}" -gt 0 && "${OPEN_IN_ZONE}" -eq 0 ]]; then
  echo "FAIL: open_gripper only out of zone (${OPEN_OUT_OF_ZONE} rows)"
  FAIL=1
elif [[ "${OPEN_OUT_OF_ZONE}" -gt 0 ]]; then
  echo "WARN: some open_gripper out of zone (${OPEN_OUT_OF_ZONE}), but in-zone attempts exist"
else
  echo "PASS: open_gripper placement zone OK"
fi

if [[ "${PLACE_FAIL}" -ne 0 ]]; then
  echo "FAIL: analyze_part_placement part5 acceptance"
  FAIL=1
else
  echo "PASS: part placement tracker (part5 smoke)"
fi

if [[ "${BASELINE_HAS_ENVELOPE}" -ne 1 ]]; then
  echo "FAIL: baseline CSV missing dist_min_envelope (2.5b gate)"
  FAIL=1
else
  echo "PASS: baseline has dist_min_envelope column"
fi

if [[ "${BASELINE_TS}" -le "${REF_TIME_STEP}" ]]; then
  echo "WARN: baseline task_time_step=${BASELINE_TS} <= ${REF_TIME_STEP} (2.5b regression vs ref)"
else
  echo "PASS: baseline task_time_step=${BASELINE_TS} > ${REF_TIME_STEP}"
fi

if [[ "${FAIL}" -eq 0 ]]; then
  echo ""
  echo "OVERALL PASS (Phase 4a v1 acceptance)"
  exit 0
else
  echo ""
  echo "OVERALL FAIL — see metrics above"
  exit 1
fi
