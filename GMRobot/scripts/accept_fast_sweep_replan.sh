#!/usr/bin/env bash
# GM-SafePick G4 acceptance: ivj_dynamic_fast_sweep + replan (full task completion).
# Criteria: replan run reaches task_ts >= 7520 (~7521 expected_task_steps) with detour=35.
# Run on Isaac gpufree node after: source /root/activate_isaaclab.sh && cd /root/GMRobot
#
# Standard (outer GPU lock + passthrough avoids nested flock deadlock):
#   bash scripts/isaac_gpu_lock.sh env GPU_LOCK=scripts/isaac_gpu_passthrough.sh \
#     bash scripts/accept_fast_sweep_replan.sh
set -euo pipefail

REPO="/root/GMRobot"
REF_TIME_STEP=7520
EXPECTED_TASK_STEPS=7521
MAX_STEPS=8000
PRESET="ivj_dynamic_fast_sweep"
CONFIG="configs/ivj/${PRESET}.yaml"
LOG_DIR="${REPO}/output/safety_logs"
WATCHDOG_SEC=3600
WATCHDOG_POLL_SEC=15
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

echo "=== G4 fast_sweep replan acceptance (max_steps=${MAX_STEPS}, ref task_ts>=${REF_TIME_STEP}) ==="
echo "  preset: ${PRESET}"
echo "  config: ${CONFIG}"

if ! run_agent_with_watchdog "replan" /tmp/fast_sweep_replan.log \
  python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config="${CONFIG}" \
  --enable_replan --max_steps="${MAX_STEPS}" --progress_interval=500; then
  echo "[replan] first attempt failed; retrying once..."
  run_agent_with_watchdog "replan-retry" /tmp/fast_sweep_replan_retry.log \
    python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
    --enable_safety --safety_config="${CONFIG}" \
    --enable_replan --max_steps="${MAX_STEPS}" --progress_interval=500
fi

REPLAN_RUN=$(find "${LOG_DIR}" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort | tail -1)
REPLAN_CSV="${LOG_DIR}/${REPLAN_RUN}/episode_0000.csv"
REPLAN_MANIFEST="${LOG_DIR}/${REPLAN_RUN}/run_manifest.json"

echo ""
echo "=== Run ID ==="
echo "  replan: ${REPLAN_RUN}"

if [[ -f "${REPLAN_MANIFEST}" ]]; then
  python3 - <<PY
import json
m = json.load(open("${REPLAN_MANIFEST}"))
print("run_manifest.json:")
for k in ("run_id", "enable_replan", "max_steps", "outcome", "final_time_step", "task_time_step"):
    if k in m:
        print(f"  {k}: {m[k]}")
PY
fi

if [[ -f "${REPLAN_CSV}" ]]; then
  python scripts/report_safety_metrics.py "${LOG_DIR}/${REPLAN_RUN}" --config "${CONFIG}" || true
fi

eval "$(python3 - <<PY
import csv, json, os

run = "${REPLAN_RUN}"
csv_path = "${REPLAN_CSV}"
manifest_path = "${REPLAN_MANIFEST}"
ref_ts = int("${REF_TIME_STEP}")
expected = int("${EXPECTED_TASK_STEPS}")

ts = 0
outcome = "unknown"
replan_applied = 0
if os.path.isfile(manifest_path):
    m = json.load(open(manifest_path))
    ts = int(m.get("final_time_step") or m.get("task_time_step") or 0)
    outcome = str(m.get("outcome", "unknown"))

rows = []
if os.path.isfile(csv_path):
    rows = list(csv.DictReader(open(csv_path)))

max_task_ts = 0
for row in rows:
    try:
        max_task_ts = max(max_task_ts, int(float(row.get("task_time_step") or 0)))
    except Exception:
        pass
    if row.get("replan_event") == "applied":
        replan_applied += 1

if ts == 0 and max_task_ts:
    ts = max_task_ts

print(f"REPLAN_TS={ts}")
print(f"MAX_TASK_TS={max_task_ts}")
print(f"REPLAN_OUTCOME={outcome!r}")
print(f"REPLAN_APPLIED={replan_applied}")
print(f"PASS_TS={1 if ts >= ref_ts else 0}")
print(f"PASS_COMPLETE={1 if ts >= expected - 1 else 0}")
PY
)"

echo ""
echo "=== G4 success criteria ==="
echo "  1) replan final task_ts >= ${REF_TIME_STEP} (task completes ~${EXPECTED_TASK_STEPS})"
echo "  2) replan_event=applied at least once (dynamic dodge triggered)"
echo ""
echo "=== Replan metrics (${REPLAN_RUN}) ==="
echo "  final_task_ts: ${REPLAN_TS}"
echo "  max_task_ts: ${MAX_TASK_TS}"
echo "  outcome: ${REPLAN_OUTCOME}"
echo "  replan_applied_count: ${REPLAN_APPLIED}"

FAIL=0
if [[ "${REPLAN_TS}" -lt "${REF_TIME_STEP}" ]]; then
  echo "FAIL: task_ts=${REPLAN_TS} < ${REF_TIME_STEP}"
  FAIL=1
else
  echo "PASS: task_ts=${REPLAN_TS} >= ${REF_TIME_STEP}"
fi

if [[ "${REPLAN_APPLIED}" -lt 1 ]]; then
  echo "WARN: no replan_event=applied rows (detour may not have triggered)"
else
  echo "PASS: replan applied (${REPLAN_APPLIED} rows)"
fi

if [[ "${FAIL}" -eq 0 ]]; then
  echo ""
  echo "OVERALL PASS (G4 fast_sweep replan acceptance)"
  exit 0
else
  echo ""
  echo "OVERALL FAIL — see metrics above"
  exit 1
fi
