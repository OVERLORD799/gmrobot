#!/usr/bin/env bash
# Prepare Isaac Sim 5.1 + Isaac Lab 2.3 for GMrobot (RTX 5090 / driver 580.x)
#
# Usage:
#   bash setup_isaac51.sh              # bare-metal conda (recommended for dev)
#   bash setup_isaac51.sh --docker-only   # only Docker toolkit + pull base image
#   bash setup_isaac51.sh --all        # conda + docker prep
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISAACLAB_ROOT="${ISAACLAB_ROOT:-${HOME}/IsaacLab}"
ISAACLAB_TAG="${ISAACLAB_TAG:-v2.3.2}"
CONDA_ENV="${CONDA_ENV:-env_isaaclab}"
ISAACSIM_VER="${ISAACSIM_VER:-5.1.0}"

MODE="${1:-bare-metal}"
if [[ "${MODE}" == "--docker-only" ]]; then MODE=docker; fi
if [[ "${MODE}" == "--all" ]]; then MODE=all; fi

log() { echo "[setup] $*"; }

require_sudo() {
  if ! sudo -n true 2>/dev/null; then
    log "需要 sudo 密码（安装 Docker GPU 支持 / hold 驱动）"
  fi
}

setup_driver_hold() {
  log "锁定 nvidia 580 驱动，防止升回 595..."
  sudo apt-mark hold nvidia-driver-580-open nvidia-dkms-580-open 2>/dev/null || true
  apt-mark showhold | grep nvidia || true
}

setup_docker_gpu() {
  log "安装 nvidia-container-toolkit..."
  if ! dpkg -l nvidia-container-toolkit 2>/dev/null | grep -q ^ii; then
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
  fi
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  log "验证 Docker GPU..."
  docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
}

pull_isaac_image() {
  log "拉取 Isaac Sim ${ISAACSIM_VER} 容器（约 15–20 GB，耗时较长）..."
  docker pull "nvcr.io/nvidia/isaac-sim:${ISAACSIM_VER}"
  log "快速验证 Isaac Sim 容器 GPU..."
  docker run --rm --gpus all -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y \
    "nvcr.io/nvidia/isaac-sim:${ISAACSIM_VER}" nvidia-smi
}

setup_conda_env() {
  log "创建 conda 环境 ${CONDA_ENV} (Python 3.11)..."
  # shellcheck source=/dev/null
  source "${HOME}/anaconda3/etc/profile.d/conda.sh"
  if conda env list | awk '{print $1}' | grep -qx "${CONDA_ENV}"; then
    log "环境 ${CONDA_ENV} 已存在，跳过 create"
  else
    conda create -n "${CONDA_ENV}" python=3.11 -y
  fi
  conda activate "${CONDA_ENV}"

  log "安装 Isaac Sim ${ISAACSIM_VER} pip 包（耗时较长）..."
  pip install --upgrade pip
  pip install "isaacsim[all,extscache]==${ISAACSIM_VER}" --extra-index-url https://pypi.nvidia.com

  log "安装 PyTorch (cu128, Blackwell)..."
  pip install -U torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128

  if [[ ! -d "${ISAACLAB_ROOT}/.git" ]]; then
    log "克隆 Isaac Lab ${ISAACLAB_TAG} -> ${ISAACLAB_ROOT}"
    git clone --depth 1 -b "${ISAACLAB_TAG}" https://github.com/isaac-sim/IsaacLab.git "${ISAACLAB_ROOT}"
  else
    log "Isaac Lab 已存在: ${ISAACLAB_ROOT}"
  fi

  log "安装 Isaac Lab 扩展..."
  pip install -e "${ISAACLAB_ROOT}/source/isaaclab"

  log "安装 GMRobot 扩展..."
  pip install -e "${WORKSPACE}/GMRobot/source/GMRobot"
  pip install scikit-learn joblib xgboost

  log "写入激活脚本..."
  cat > "${WORKSPACE}/activate_isaaclab.sh" <<EOF
#!/usr/bin/env bash
source "${HOME}/anaconda3/etc/profile.d/conda.sh"
conda activate ${CONDA_ENV}
source "${WORKSPACE}/env.sh"
export ISAACLAB_ROOT="${ISAACLAB_ROOT}"
export OMNI_KIT_ACCEPT_EULA=YES
export PATH="\${CONDA_PREFIX}/bin:\${PATH}"
echo "Isaac Sim ${ISAACSIM_VER} + Isaac Lab ${ISAACLAB_TAG}"
echo "  ISAACLAB_ROOT=\${ISAACLAB_ROOT}"
echo "  GMROBOT_ROOT=\${GMROBOT_ROOT}"
EOF
  chmod +x "${WORKSPACE}/activate_isaaclab.sh"

  log "conda 环境就绪。运行: source ${WORKSPACE}/activate_isaaclab.sh"
}

# ── main ──────────────────────────────────────
log "GMrobot Isaac Sim 5.1 准备 | mode=${MODE}"
log "工作区: ${WORKSPACE}"
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || true

case "${MODE}" in
  bare-metal)
    setup_driver_hold
    setup_conda_env
    ;;
  docker)
    require_sudo
    setup_driver_hold
    setup_docker_gpu
    pull_isaac_image
    log "Docker 路径就绪。构建项目镜像:"
    log "  cd ${WORKSPACE}/g1_ur10e_disturbance/docker && ./build.sh"
    ;;
  all)
    require_sudo
    setup_driver_hold
    setup_docker_gpu
    setup_conda_env
    pull_isaac_image &
    log "Isaac Sim 镜像在后台拉取中 (docker pull)"
    ;;
  *)
    echo "Unknown mode: ${MODE}"; exit 1 ;;
esac

log "完成。"
