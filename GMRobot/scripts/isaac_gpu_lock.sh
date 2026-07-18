#!/usr/bin/env bash
# Acquire exclusive GPU lock for Isaac Sim runs (one Sim process per machine).
# Usage: scripts/isaac_gpu_lock.sh <command> [args...]
# Waits up to 1 hour for the lock; exits with flock's status.
set -euo pipefail

LOCK_FILE="${ISAAC_GPU_LOCK:-/tmp/isaac_gpu.lock}"
WAIT_SEC="${ISAAC_GPU_LOCK_WAIT_SEC:-3600}"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <command> [args...]" >&2
  exit 2
fi

exec flock -w "${WAIT_SEC}" "${LOCK_FILE}" "$@"
