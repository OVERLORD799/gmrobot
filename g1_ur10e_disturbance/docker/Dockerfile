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

# ── System ────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget git git-lfs && rm -rf /var/lib/apt/lists/*

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
ARG ISAACLAB_REPO=https://github.com/isaac-sim/IsaacLab.git
ARG ISAACLAB_BRANCH=v2.3.2
RUN git clone --depth 1 -b ${ISAACLAB_BRANCH} ${ISAACLAB_REPO} /opt/IsaacLab
WORKDIR /opt/IsaacLab
# flatdict sdist needs pkg_resources; avoid isolated build with newest setuptools
RUN /isaac-sim/python.sh -m pip install --upgrade pip && \
    /isaac-sim/python.sh -m pip install 'setuptools>=69,<81' wheel && \
    /isaac-sim/python.sh -m pip install --no-build-isolation flatdict==4.0.1 && \
    /isaac-sim/python.sh -m pip install -e source/isaaclab

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

# ── Env ────────────────────────────────────────
ENV GMDISTURB_ROOT=/opt/projects/g1_ur10e_disturbance \
    GMROBOT_ROOT=/opt/projects/GMRobot \
    ISAACLAB_ROOT=/opt/IsaacLab \
    PRESSURE_MAT_ROOT=/opt/projects/pressure_mat_repro \
    PATH=/isaac-sim/python/bin:/opt/IsaacLab:${PATH}

WORKDIR /opt/projects/g1_ur10e_disturbance
ENTRYPOINT ["/isaac-sim/python.sh", "scripts/run_phase3.py"]
