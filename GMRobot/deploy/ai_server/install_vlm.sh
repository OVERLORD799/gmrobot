#!/bin/bash
# Install Qwen VLM service on gm-ai-server (Phase 3a). Run ON the AI server.
set -euo pipefail

VLM_DIR="${VLM_DIR:-/root/gm-safepick-vlm}"
VLM_PORT="${VLM_PORT:-8080}"
VLM_STUB="${VLM_STUB:-1}"

echo "[1/5] Creating conda env vlm (python 3.11)..."
source /opt/conda/etc/profile.d/conda.sh
conda create -n vlm python=3.11 -y 2>/dev/null || true
conda activate vlm

echo "[2/5] Installing PyTorch + FastAPI..."
pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -q fastapi uvicorn pydantic pillow transformers accelerate qwen-vl-utils

echo "[3/5] Setting up service directory ${VLM_DIR}..."
mkdir -p "${VLM_DIR}"
cp -f "$(dirname "$0")/vlm_service.py" "${VLM_DIR}/vlm_service.py"

echo "[4/5] Writing systemd-style start script..."
cat > "${VLM_DIR}/start_vlm.sh" <<EOF
#!/bin/bash
source /opt/conda/etc/profile.d/conda.sh
conda activate vlm
export VLM_PORT=${VLM_PORT}
export VLM_STUB=${VLM_STUB}
export VLM_MODEL_ID=Qwen2.5-VL-7B-Instruct-awq
cd ${VLM_DIR}
exec python vlm_service.py
EOF
chmod +x "${VLM_DIR}/start_vlm.sh"

echo "[5/5] Starting VLM service (stub=${VLM_STUB})..."
pkill -f "vlm_service.py" 2>/dev/null || true
nohup bash "${VLM_DIR}/start_vlm.sh" > "${VLM_DIR}/vlm.log" 2>&1 &
sleep 3
curl -s "http://127.0.0.1:${VLM_PORT}/health" || echo "health check pending..."

echo "Done. Service URL: http://$(hostname -I | awk '{print $1}'):${VLM_PORT}"
