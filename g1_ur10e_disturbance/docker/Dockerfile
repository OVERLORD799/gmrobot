FROM nvcr.io/nvidia/isaac-sim:5.1.0

# RTX 50-series (Blackwell) requires Isaac Sim >= 5.1
ENV ACCEPT_EULA=Y \
    PRIVACY_CONSENT=Y \
    OMNI_KIT_ACCEPT_EULA=YES

# Base image defaults to non-root user isaac-sim; need root for apt/conda/installs
USER root

# BuildKit proxy (optional; passed from build.sh when local proxy is up)
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG http_proxy
ARG https_proxy

# Record base image identity for reproducibility (digest passed from build.sh)
ARG BASE_IMAGE=nvcr.io/nvidia/isaac-sim:5.1.0
ARG BASE_IMAGE_DIGEST=unknown
ARG H5PY_VERSION=3.13.0
ARG ISAACLAB_REPO=https://github.com/isaac-sim/IsaacLab.git
ARG ISAACLAB_BRANCH=v2.3.2

# ── System ────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget git git-lfs && rm -rf /var/lib/apt/lists/*

# ── Fix Torch vendor packaging symlink (Isaac Sim 5.1.0) ──
# torch/_vendor/packaging/_structures.py is a relative symlink into
# omni.isaac.core_archive. Replace it with a real file so import stays
# robust if the archive layout changes (known ModuleNotFoundError otherwise).
RUN TORCH_STRUCT="/isaac-sim/exts/omni.isaac.ml_archive/pip_prebundle/torch/_vendor/packaging/_structures.py" && \
    for src in \
      /isaac-sim/exts/omni.isaac.core_archive/pip_prebundle/packaging/_structures.py \
      /isaac-sim/kit/python/lib/python3.11/site-packages/packaging/_structures.py \
      /isaac-sim/kit/python/lib/python3.11/site-packages/pip/_vendor/packaging/_structures.py \
    ; do \
      if [ -f "${src}" ]; then \
        rm -f "${TORCH_STRUCT}" && \
        cp "${src}" "${TORCH_STRUCT}" && \
        echo "torch packaging _structures.py <- ${src}" && \
        break; \
      fi; \
    done && \
    test -f "${TORCH_STRUCT}" && \
    /isaac-sim/python.sh -c "import torch; print('torch', torch.__version__)"

# ── Miniconda (for pressure_mat velocity training Python 3.6) ──
RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
    -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && rm /tmp/miniconda.sh
ENV PATH=/opt/conda/bin:$PATH

# Newer Miniconda requires accepting Anaconda ToS non-interactively
# Prefer Tsinghua PyPI (direct files.pythonhosted.org is often slow/hung)
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda create -n vel python=3.6 -y && \
    conda run -n vel pip install --progress-bar off torch==1.6.0 numpy progressbar2

# ── Isaac Lab 2.3.x (for Isaac Sim 5.1) ─────
RUN git clone --depth 1 -b ${ISAACLAB_BRANCH} ${ISAACLAB_REPO} /opt/IsaacLab
WORKDIR /opt/IsaacLab
# flatdict sdist needs pkg_resources; avoid isolated build with newest setuptools
RUN /isaac-sim/python.sh -m pip install --upgrade pip && \
    /isaac-sim/python.sh -m pip install 'setuptools>=69,<81' wheel && \
    /isaac-sim/python.sh -m pip install --no-build-isolation flatdict==4.0.1 && \
    /isaac-sim/python.sh -m pip install -e source/isaaclab && \
    /isaac-sim/python.sh -m pip install \
        -e source/isaaclab_assets \
        -e source/isaaclab_tasks

# ── Isaac Python runtime deps (must use /isaac-sim/python.sh, not conda) ──
# Note: do not `import isaaclab_assets` here — it pulls pxr/USD which needs a
# running Kit process. Verify install via importlib.metadata instead.
RUN /isaac-sim/python.sh -m pip install "h5py==${H5PY_VERSION}" && \
    /isaac-sim/python.sh -c "import h5py; print('h5py', h5py.__version__)" && \
    /isaac-sim/python.sh -c "import importlib.metadata as m; \
pkgs=('isaaclab','isaaclab_assets','isaaclab_tasks'); \
[print(p, m.version(p)) for p in pkgs]"

# ── GMRobot (editable install + training deps) ──
COPY --from=gmrobot . /opt/projects/GMRobot/
RUN /isaac-sim/python.sh -m pip install -e /opt/projects/GMRobot/source/GMRobot && \
    /isaac-sim/python.sh -m pip install scikit-learn joblib xgboost

# ── pressure_mat_repro ────────────────────────
COPY --from=pressure . /opt/projects/pressure_mat_repro/

# ── g1_ur10e_disturbance (main project) ───────
COPY --from=gmdisturb . /opt/projects/g1_ur10e_disturbance/

# ── USD assets (gitignored, copied from host) ──
COPY gmrobot_assets/ /opt/projects/GMRobot/source/GMRobot/GMRobot/assets/
COPY g1_assets/ /opt/projects/g1_ur10e_disturbance/assets/

# ── Locked dependency manifest (Isaac Python only) ──
RUN mkdir -p /opt/locks && \
    /isaac-sim/python.sh -m pip freeze > /opt/locks/isaac-python-requirements.txt && \
    printf '%s\n' \
      "base_image=${BASE_IMAGE}" \
      "base_image_digest=${BASE_IMAGE_DIGEST}" \
      "isaaclab_branch=${ISAACLAB_BRANCH}" \
      "h5py=${H5PY_VERSION}" \
      "isaac_python=/isaac-sim/kit/python/bin/python3" \
      > /opt/locks/image-build-info.txt

# ── Env ────────────────────────────────────────
ENV GMDISTURB_ROOT=/opt/projects/g1_ur10e_disturbance \
    GMROBOT_ROOT=/opt/projects/GMRobot \
    ISAACLAB_ROOT=/opt/IsaacLab \
    PRESSURE_MAT_ROOT=/opt/projects/pressure_mat_repro \
    ISAAC_PYTHON=/isaac-sim/kit/python/bin/python3 \
    GMDISTURB_BASE_IMAGE=${BASE_IMAGE} \
    GMDISTURB_BASE_DIGEST=${BASE_IMAGE_DIGEST} \
    PATH=/isaac-sim/python/bin:/opt/IsaacLab:${PATH}

WORKDIR /opt/projects/g1_ur10e_disturbance
RUN chmod +x /opt/projects/g1_ur10e_disturbance/docker/entrypoint.sh \
             /opt/projects/g1_ur10e_disturbance/docker/run.sh

ENTRYPOINT ["/opt/projects/g1_ur10e_disturbance/docker/entrypoint.sh"]
CMD ["phase3", "--help"]
