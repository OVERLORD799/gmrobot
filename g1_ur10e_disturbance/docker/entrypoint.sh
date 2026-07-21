#!/usr/bin/env bash
# Unified container entrypoint for GMDisturb.
#
# Usage (via docker run / docker/run.sh):
#   phase3 [args...]                 # scripts/run_phase3.py
#   batch <config_dir> [args...]     # batch_runner.py
#   smoke [args...]                  # short headless phase3 smoke
#   shell | bash                     # interactive shell
#   python <script> [args...]        # /isaac-sim/python.sh ...
#   run phase3|batch|smoke ...       # optional "run" prefix
#   --headless ...                   # backward compat: treat as phase3 flags
set -euo pipefail

ROOT="${GMDISTURB_ROOT:-/opt/projects/g1_ur10e_disturbance}"
ISAAC_RUN="${ISAAC_RUN:-/isaac-sim/python.sh}"
cd "${ROOT}"

usage() {
  cat <<'EOF'
GMDisturb Docker entrypoint

Commands:
  phase3 [args...]              Run scripts/run_phase3.py
  batch <config_dir> [args...]  Run batch_runner.py
  smoke [args...]               Headless 1-step smoke (override with SMOKE_STEPS)
  shell | bash [args...]        Interactive bash
  python <args...>              /isaac-sim/python.sh <args...>
  help                          Show this message

Examples:
  docker run --gpus all gmdisturb:paper-demo-20260718 phase3 --headless --max_steps 1
  docker run --gpus all gmdisturb:paper-demo-20260718 batch paper_scenarios/
  docker run --gpus all -it gmdisturb:paper-demo-20260718 shell
EOF
}

if [[ $# -eq 0 ]]; then
  set -- phase3 --help
fi

# Optional "run" prefix: `run phase3 ...` / `run batch ...`
if [[ "$1" == "run" ]]; then
  shift
  if [[ $# -eq 0 ]]; then
    usage
    exit 1
  fi
fi

cmd="$1"
shift || true

case "$cmd" in
  phase3|run-phase3|run_phase3)
    exec "${ISAAC_RUN}" "${ROOT}/scripts/run_phase3.py" "$@"
    ;;
  batch|run-batch|run_batch|batch_runner)
    exec "${ISAAC_RUN}" "${ROOT}/batch_runner.py" "$@"
    ;;
  smoke)
    steps="${SMOKE_STEPS:-1}"
    exec "${ISAAC_RUN}" "${ROOT}/scripts/run_phase3.py" \
      --headless --max_steps "${steps}" "$@"
    ;;
  shell|bash)
    exec bash "$@"
    ;;
  python|python3|isaac-python)
    exec "${ISAAC_RUN}" "$@"
    ;;
  help|-h|--help)
    usage
    exit 0
    ;;
  -*)
    # Backward compatible: previous ENTRYPOINT was run_phase3.py, so flags
    # passed directly to `docker run IMAGE --headless ...` still work.
    exec "${ISAAC_RUN}" "${ROOT}/scripts/run_phase3.py" "${cmd}" "$@"
    ;;
  *)
    # Allow `docker run --entrypoint ... IMAGE /path/to/script.py ...`
    if [[ -f "${cmd}" ]]; then
      exec "${ISAAC_RUN}" "${cmd}" "$@"
    fi
    echo "Unknown command: ${cmd}" >&2
    usage >&2
    exit 1
    ;;
esac
