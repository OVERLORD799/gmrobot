#!/usr/bin/env bash
# One-click offline safety regression: unit tests + metrics on known run dirs.
# Isaac Sim runs are opt-in via --isaac (default off).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

RUN_ISAAC=0
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --isaac) RUN_ISAAC=1 ;;
    *) EXTRA_ARGS+=("$arg") ;;
  esac
done

echo "== GM-SafePick safety regression (offline) =="
echo "Repo: $REPO"
echo

echo "[1/3] Unit tests (safety + layer2)..."
python -m unittest discover -s tests -p 'test_*.py' -q

echo
echo "[2/3] Layer 1 metrics on known runs..."
python scripts/report_safety_metrics.py \
  output/safety_logs/20260617_193713 \
  output/safety_logs/20260617_193244 \
  output/safety_logs/20260617_211014 \
  --config configs/safety_layer1.yaml

echo
echo "[3/3] Shadow metrics (model 20260617_211615)..."
python scripts/report_shadow_metrics.py \
  output/safety_logs/20260617_193713 \
  output/safety_logs/20260617_211014 \
  --model-dir output/safety_models/20260617_211615 \
  --output-json output/shadow_metrics_regression_latest.json

if [[ "$RUN_ISAAC" -eq 1 ]]; then
  echo
  echo "[optional] Isaac short runs (--max_steps=500)..."
  python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
    --enable_safety --safety_config=configs/safety_layer1.yaml --max_steps=500 \
    --progress_interval=100
else
  echo
  echo "Isaac runs skipped (pass --isaac to enable short headless smoke test)."
fi

echo
echo "Regression complete."
