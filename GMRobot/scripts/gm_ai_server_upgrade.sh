#!/bin/bash
# GM-SafePick: upgrade perception models + restart (Phase 4b F/G)
# Run on gm-ai-server: ssh -p 30481 root@120.209.70.195

set -euo pipefail

source /opt/conda/etc/profile.d/conda.sh
conda activate /root/gpufree-data/conda-envs/vlm
export HF_HOME=/root/gpufree-data/huggingface
export HF_ENDPOINT=https://hf-mirror.com

echo "=== F: Download SAM2-hiera-small (if missing) ==="
python3 -c '
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id="facebook/sam2.1-hiera-small",
    filename="sam2.1_hiera_small.pt",
    local_dir="/root/gpufree-data/perception-service/checkpoints",
)
print("SAM2-small: OK")
'

echo "=== F: Update start.sh with new model env vars ==="
START_SH=/root/gpufree-data/perception-service/start.sh
# Only add if not already present
if ! grep -q 'GDINO_MODEL_ID' "$START_SH"; then
    sed -i "s|export PERCEPTION_HOST|export GDINO_MODEL_ID=IDEA-Research/grounding-dino-base\nexport SAM2_CONFIG=configs/sam2.1/sam2.1_hiera_s.yaml\nexport SAM2_CHECKPOINT=/root/gpufree-data/perception-service/checkpoints/sam2.1_hiera_small.pt\nexport PERCEPTION_HOST|" "$START_SH"
    echo "start.sh updated"
else
    echo "start.sh already has model env vars"
fi

echo "=== Restart perception-service ==="
OLD_PID=$(pgrep -f "gpufree-data/perception-service/app.py" | head -1 || echo "")
if [ -n "$OLD_PID" ]; then
    echo "Killing old PID=$OLD_PID (supervisord will auto-restart)..."
    kill "$OLD_PID"
    sleep 5
fi

echo "=== Waiting for new models to load (up to 60s) ==="
for i in $(seq 1 12); do
    sleep 5
    HEALTH=$(curl -s http://127.0.0.1:8082/health 2>/dev/null || echo '{}')
    LOADED=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('models_loaded', False))" 2>/dev/null || echo "False")
    GDINO=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gdino_model_id', ''))" 2>/dev/null || echo "")
    echo "  [$i] loaded=$LOADED gdino=$GDINO"
    if [ "$LOADED" = "True" ] && [ "$GDINO" = "IDEA-Research/grounding-dino-base" ]; then
        echo "=== F: Upgrade SUCCESS ==="
        curl -s http://127.0.0.1:8082/health | python3 -m json.tool
        exit 0
    fi
done

echo "=== F: Upgrade TIMEOUT — check supervisor.err.log ==="
tail -20 /root/gpufree-data/perception-service/supervisor.err.log
exit 1
