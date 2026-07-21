# GMDisturb -- G1 humanoid as an adversarial disturbance tester for UR10e safety systems

Dual-robot co-simulation framework: a Unitree G1 humanoid walks near a UR10e
pick-and-place arm, triggering the GMRobot safety layer (envelope gating,
motion replan, VLM guidance) to measure and improve grasp-knock-off defense.

## Architecture

```
                         ┌──────────────────────┐
                         │   Isaac Lab 2.3.2    │
                         │   (Isaac Sim 5.1.0)   │
                         └──────┬───────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              │      DualRobotSceneCfg             │
              │   (shared PhysX environment)       │
              └─────┬──────────────┬──────────────┘
                    │              │
        ┌───────────▼────┐  ┌─────▼──────────────┐
        │  G1 29-DOF     │  │  UR10e 12-DOF      │
        │  humanoid      │  │  + table/containers │
        │                │  │  + 20 parts         │
        └───────┬────────┘  └─────┬──────────────┘
                │                 │
   ┌────────────▼────────────┐    │
   │ G1DisturbanceController │    │
   │  ─ distance-gated speed │    │
   │  ─ arm PD poses         │    │
   │  ─ retreat commands     │    │
   └────────────┬────────────┘    │
                │                 │
   ┌────────────▼────────────┐    │
   │ G1VirtualHand           │    │
   │  ─ sphere at table ht   │    │
   │  ─ corridor-restricted  │    │
   │  ─ phase-driven radius  │    │
   └────────────┬────────────┘    │
                │                 │
   ┌────────────▼────────────┐    │
   │ DeadlockDetector        │    │
   │  ─ jitter → repel →     │    │
   │    G1 retreat (3-tier)  │    │
   └────────────┬────────────┘    │
                │                 │
   ┌────────────▼────────────┐    │
   │ G1EnvelopeAdapter       │    │
   │  ─ G1 body → sphere     │    │
   │    mapping              │    │
   └────────────┬────────────┘    │
                │                 │
   ┌────────────▼────────────┐    │
   │ GMRobot SafetyGate      │    │
   │  ─ envelope gating      │    │
   │  ─ STOP / SLOW_DOWN     │◄───┤ combined action
   │  ─ replan trigger       │    │
   └────────────┬────────────┘    │
                │                 │
   ┌────────────▼────────────┐    │
   │ UR10eController         │◄───┘
   │  ─ pick-and-place SM    │
   │  ─ grasp-knock recovery │
   └─────────────────────────┘

     ┌──────────────┐
     │ Pressure Mat │  ─ ground-truth force recording
     │ 32×32        │
     └──────────────┘
```

### Distance-gated behaviour

| Mode | Distance (m) | G1 speed | Behaviour |
|------|-------------|----------|-----------|
| CAUTIOUS | d < 0.15 | 0.0 | Retreat / stop |
| MODERATE | 0.15 <= d <= 0.55 | 0.10 | Slow + steer away |
| AGGRESSIVE | d > 0.55 | 0.20 | Full random wander |

### Action space: 20-D

- `[0:12]` -- G1 leg joint targets (12D walk policy output)
- `[12:19]` -- UR10e EE pose (7D) + gripper (1D)

## Prerequisites

| Requirement | Version / Path |
|-------------|---------------|
| NVIDIA GPU | RTX 4090+ recommended; RTX 5090 (Blackwell) supported via Isaac Sim ≥ 5.1 |
| NVIDIA driver | ≥ 535 (RTX 50-series: use a driver that supports the installed CUDA runtime, e.g. 580.x) |
| Isaac Sim | **5.1.0** (Docker: `nvcr.io/nvidia/isaac-sim:5.1.0`) |
| Isaac Lab | **2.3.2** (`isaaclab`, `isaaclab_assets`, `isaaclab_tasks`) |
| [GMRobot](https://github.com/example/GMRobot) | sibling checkout — safety layer, UR10e assets, pick-and-place |
| [pressure_mat_repro](https://github.com/example/pressure_mat_repro) | sibling checkout — G1 USD, walk policy, tactile mat |
| Python (sim) | Isaac Kit Python 3.11 via `/isaac-sim/python.sh` (set `ISAAC_PYTHON`) |

### Environment variables

Set these or rely on `paths.py` defaults:

```bash
export GMDISTURB_ROOT=/path/to/g1_ur10e_disturbance
export GMROBOT_ROOT=/path/to/GMRobot
export ISAACLAB_ROOT=/path/to/IsaacLab
export PRESSURE_MAT_ROOT=/path/to/pressure_mat_repro
# Docker / Isaac Kit interpreter (preferred over conda fallback)
export ISAAC_PYTHON=/isaac-sim/kit/python/bin/python3
```

## Quick Start (Docker — recommended)

### Prerequisites

- **Docker** ≥ 24.x with `nvidia-container-toolkit` (`docker run --gpus all` must work)
- **≥ 80 GB** free disk space for build (image ≈ 41 GB + build cache)
- **nvcr.io** accessible (Isaac Sim base image)
- **NVIDIA GPU** with a driver compatible with Isaac Sim 5.1

> **If you don't want to build**, skip to [Pull pre-built image](#pull-pre-built-image) below.

### Build

The build fetches `nvcr.io/nvidia/isaac-sim:5.1.0`, repairs the Torch vendor packaging
symlink, installs Isaac Lab 2.3.2 (`isaaclab` + `isaaclab_assets` + `isaaclab_tasks`),
pins `h5py` into Isaac Python, and copies all three projects + USD assets.

Default image tag: **`gmdisturb:paper-demo-20260718`**.

```bash
cd g1_ur10e_disturbance/docker

# Full build (30–60 min depending on network); records base-image digest
./build.sh

# Custom tag
./build.sh --tag gmdisturb:dev

# Build + push to ghcr.io in one step
GHCR_REPO=overlord799/gmdisturb ./build.sh --push
```

**What the build script does:**

1. Sets up a build context with USD / policy assets from the sibling repos
2. Resolves the base image digest (not just the `5.1.0` tag) into build metadata
3. Runs `docker build` from the Dockerfile — layers cached on rebuild
4. Writes host-side metadata under `docker/image_meta/`

Locked dependency lists inside the image:

- `/opt/locks/isaac-python-requirements.txt`
- `/opt/locks/image-build-info.txt`

**Environment variables for CI / custom paths:**

| Variable | Default | Description |
|----------|---------|-------------|
| `GMDISTURB_ROOT` | `<workspace>/g1_ur10e_disturbance` | Path to this repo |
| `GMROBOT_ROOT` | `<workspace>/GMRobot` | Path to GMRobot checkout |
| `PRESSURE_MAT` | `<workspace>/pressure_mat_repro` | Path to pressure_mat_repro checkout |
| `GHCR_REPO` | (none) | `owner/repo` to push to ghcr.io |

### Run

Prefer `docker/run.sh` so `results/` and Isaac caches persist on the host:

```bash
cd g1_ur10e_disturbance/docker

# Interactive shell
./run.sh shell

# 1-step headless smoke
./run.sh smoke
# or:
./run.sh phase3 --headless --max_steps 1

# Batch paper scenarios (results → ./results on host)
./run.sh batch paper_scenarios/

# Equivalent raw docker (must mount results/)
docker run --gpus all --rm \
  -v "$(pwd)/../results:/opt/projects/g1_ur10e_disturbance/results" \
  gmdisturb:paper-demo-20260718 \
  phase3 --headless --max_steps 1
```

Entrypoint commands: `phase3`, `batch`, `smoke`, `shell`, `python`.
Passing flags directly (e.g. `--headless ...`) still runs `run_phase3.py` for backward compatibility.

Override entrypoint only when needed:

```bash
docker run --gpus all --rm \
  --entrypoint /isaac-sim/python.sh \
  -v "$(pwd)/../results:/opt/projects/g1_ur10e_disturbance/results" \
  gmdisturb:paper-demo-20260718 \
  /opt/projects/g1_ur10e_disturbance/batch_runner.py \
  /opt/projects/g1_ur10e_disturbance/paper_scenarios/
```

### Pull pre-built image

If an image has been pushed to **GitHub Container Registry** (ghcr.io):

```bash
docker pull ghcr.io/OVERLORD799/gmdisturb:paper-demo-20260718
docker tag ghcr.io/OVERLORD799/gmdisturb:paper-demo-20260718 gmdisturb:paper-demo-20260718
```

### Export / import (offline machines)

```bash
# On the build machine — export as tar (~41 GB)
./docker/export.sh --tag gmdisturb:paper-demo-20260718

# Transfer
scp gmdisturb_gmdisturb_paper-demo-20260718.tar user@offline-machine:/path/

# On the offline machine — load directly
docker load < /path/to/gmdisturb_gmdisturb_paper-demo-20260718.tar
./docker/run.sh smoke
```

### CI / GitHub Actions

`.github/workflows/docker-build.yml` — builds and pushes to ghcr.io on every push to
`master`. Requires a **self-hosted runner** with the label `self-hosted, linux, x64, gpu`.
Set the following secrets on the repo:

| Secret | Description |
|--------|-------------|
| `NVCR_USERNAME` | nvcr.io login (usually `$oauthtoken`) |
| `NVCR_PASSWORD` | nvcr.io API key |

## Quick Start (bare-metal -- alternative)

```bash
# Use Isaac Lab / Isaac Sim Python (prefer ISAAC_PYTHON over conda fallback)
export ISAAC_PYTHON=/path/to/isaac-sim/kit/python/bin/python3

# Smoke test (single episode, 2000 steps)
bash scripts/smoke_test.sh

# Single episode, headless, with replan + virtual hand
python scripts/run_phase3.py \
    --headless \
    --max_steps 10000 \
    --replan \
    --virtual-hand \
    --output_csv /tmp/run.csv

# Batch sweep (3 radii x 3 repeats)
python scripts/run_batch.py \
    --radii 0.5,0.8,1.0 \
    --repeats 3 \
    --max-steps 3000

# Analyze results
python scripts/analyze_run.py /tmp/run.csv

# Plot 3D trajectory
python scripts/plot_trajectory.py /tmp/run.csv
```

## CLI Reference -- `run_phase3.py`

### Core

| Flag | Default | Description |
|------|---------|-------------|
| `--max_steps` | 10000 | Sim steps per episode |
| `--progress_interval` | 200 | Steps between progress prints |
| `--output_csv PATH` | `/tmp/gmdisturb_phase3.csv` | Per-step CSV output |
| `--config PATH` | `config/default.yaml` | YAML config path |

### Disturbance mode

| Flag | Default | Description |
|------|---------|-------------|
| `--mode {auto,AGGRESSIVE,MODERATE,CAUTIOUS}` | `auto` | Force behaviour mode (auto = distance-gated) |
| `--scenario {arm_collision,arm_wave,constrained_wander,vlm_explore}` | random wander | Scripted disturbance scenario |

### Virtual hand

| Flag | Default | Description |
|------|---------|-------------|
| `--virtual-hand [RADIUS]` | off, 0.3m if no arg | Enable virtual hand sphere at table height |
| `--virtual-hand-speed SPEED` | 0.12 | Hand drift speed (m/s) |
| `--vhand-lag FLOAT` | 0.0 | Attractor lag 0-1 (higher = smoother trailing) |
| `--vhand-retreat STEPS` | 200 | Retreat duration after replan/STOP (0 = never) |
| `--vhand-remove-after STEPS` | 0 | Remove hand after N steps (0 = never) |

### Safety + replan

| Flag | Default | Description |
|------|---------|-------------|
| `--safety-config PATH` | GMRobot defaults | Path to GMRobot safety YAML |
| `--no-safety` | off | Disable safety gating (pass-through) |
| `--replan` | off | Enable motion replan on sustained SLOW_DOWN |
| `--stress` | off | Project hand to table height for forced triggers |

### Per-part protocol (requires `--virtual-hand`)

| Flag | Default | Description |
|------|---------|-------------|
| `--per-part-protocol` | off | Pick->Transit->Place->Reset per part |
| `--scenario-hand {empty_box,fast_approach,transit_block,knock_off}` | off | Time-based hand scenario |

### VLM (requires `--vlm`)

| Flag | Default | Description |
|------|---------|-------------|
| `--vlm` | off | Enable VLM navigation (head camera -> remote VLM) |
| `--vlm-scene` | off | Strategic scene reasoning (overhead camera) |
| `--vlm-monitor` | off | Part/slot occupancy monitoring |
| `--vlm-coordinate` | off | VLM advises both hand + UR10e replan |

### Approach

| Flag | Default | Description |
|------|---------|-------------|
| `--g1-bias-y FLOAT` | 0.0 | Constant y-offset on G1 velocity (steer) |
| `--approach-side {front,back,left,right}` | front | Preset workspace/velocity bias |

## CLI Reference -- `run_batch.py`

| Flag | Default | Description |
|------|---------|-------------|
| `--radii` | `0.5,0.8,1.0` | Comma-separated virtual hand radii |
| `--repeats` | 3 | Episodes per radius |
| `--max-steps` | 3000 | Steps per episode |
| `--speed` | 0.08 | Virtual hand speed |
| `--replan` | off | Enable replan across all episodes |
| `--output-dir` | `/tmp/gmdisturb_batch` | Output directory |

## Other Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_phase2.py` | Phase 2 (G1 walk + UR10e pick-and-place, no disturbance) |
| `scripts/run_pick_and_place.py` | Standalone UR10e pick-and-place |
| `scripts/smoke_test.sh` | Single-episode integration test (replan + per-part + vhand-remove) |
| `scripts/smoke_test_dual.py` | Dual-robot load test (100 steps, env smoke) |
| `scripts/gui_demo_phase1.py` | Isaac Sim GUI demo |
| `scripts/run_batch.sh` | Bash wrapper for batch runs |
| `scripts/analyze_run.py` | CSV analytics (`python analyze_run.py <steps.csv>`) |
| `scripts/plot_trajectory.py` | 3D trajectory plot (`python plot_trajectory.py <steps.csv>`) |

## Configuration (`config/default.yaml`)

All tunable parameters are externalized to a single YAML file. The `--config` flag overrides the default path.

### `disturbance` -- G1 behaviour

| Key | Default | Description |
|-----|---------|-------------|
| `cautious_threshold` | 0.15 | Distance below which G1 retreats (m) |
| `moderate_threshold` | 0.55 | Distance below which G1 slows + steers (m) |
| `speed_aggressive` | 0.20 | Wander speed multiplier for AGGRESSIVE |
| `speed_moderate` | 0.10 | Speed multiplier for MODERATE |
| `speed_cautious` | 0.0 | Speed multiplier for CAUTIOUS |
| `workspace_x` | `[0.0, 0.8]` | G1 wander bounds X (m) |
| `workspace_y` | `[-0.5, 0.5]` | G1 wander bounds Y (m) |
| `vy_scale` | 0.05 | Lateral velocity noise scale (0 = disabled) |
| `resample_interval` | 200 | Steps between velocity resamples |

### `virtual_hand` -- Proxy hand sphere

| Key | Default | Description |
|-----|---------|-------------|
| `default_radius` | 0.45 | Max sphere radius (m) |
| `height_mode` | `"table"` | Height reference (`"table"` or `"head"`) |

### `arm` -- G1 arm model

| Key | Default | Description |
|-----|---------|-------------|
| `arm_length` | 0.8 | Simulated arm length (m) |
| `arm_length_fixed` | false | Clamp to exactly `arm_length` |
| `arm_length_min` | 0.6 | Min variable length (m) |
| `arm_length_max` | 0.9 | Max variable length (m) |

### `ee_track` -- UR10e tracking target

| Key | Default | Description |
|-----|---------|-------------|
| `ee_track_body` | `"wrist_3_link"` | UR10e body to track |
| `ee_track_offset` | `[0.0, 0.0, 0.02]` | Offset from body centre (m) |

### `vlm` -- Remote VLM navigation

| Key | Default | Description |
|-----|---------|-------------|
| `ssh.host` | `120.209.70.195` | Jump host (temporary dev infra) |
| `ssh.port` | 30481 | SSH port |
| `host` | `localhost` | VLM service host (after tunnel) |
| `port` | 8080 | VLM service port |
| `interval` | 200 | Steps between tactical queries |
| `scene_interval` | 800 | Steps between strategic queries |
| `blend_vlm_weight` | 0.4 | VLM fraction in hybrid drive |
| `blend_corridor_weight` | 0.6 | Corridor-attractor fraction |
| `boundary_max_dist` | 2.0 | Spring trigger distance (m) |

### `safety` -- GMRobot safety adapter

| Key | Default | Description |
|-----|---------|-------------|
| `control_dt` | 0.02 | Safety adapter timestep (s) |
| `tilt_threshold_rad` | 0.35 | Arm retract tilt (~20 deg) |
| `collapse_z` | -1.0 | Episode end if G1 root drops below (m) |
| `replan.trigger_threshold` | 3 | Consecutive SLOW_DOWN steps to trigger |
| `replan.detour_lateral_m` | 0.10 | Lateral replan offset (m) |
| `replan.detour_duration` | 55 | Detour segment length (steps) |

### `batch` -- Episode defaults

| Key | Default | Description |
|-----|---------|-------------|
| `max_steps` | 10000 | Max steps per episode |
| `progress_interval` | 200 | Steps between progress prints |
| `mode_default` | `"auto"` | Default behaviour mode |
| `repeats_default` | 1 | Episodes per radius |
| `output_csv` | `/tmp/gmdisturb_phase3.csv` | Default CSV path |

## Project Structure

```
g1_ur10e_disturbance/
├── config/
│   └── default.yaml              # All tunable parameters (single source of truth)
├── batch_test_configs/           # Minimal YAML configs for batch runs (5 scenarios)
│   ├── arm_collision_safety.yaml
│   ├── arm_wave_safety.yaml
│   ├── wander_no_safety.yaml
│   ├── wander_safety_fusion.yaml
│   └── wander_vhand_replan.yaml
├── docker/                       # Docker build, export, and run tooling
│   ├── Dockerfile                # Isaac Sim 4.5.0 + Isaac Lab 2.x + GMRobot
│   ├── build.sh                  # Symlink-based build context + asset collection
│   └── export.sh                 # docker save to .tar
├── docs/                         # Full documentation (7 core + 27 sub-docs)
│   ├── README.md                 # Doc index + navigation by role/phase
│   ├── ARCHITECTURE.md           # System design, scene layout, control loop
│   ├── DATA_FLOW.md              # Per-step data lifecycle
│   ├── INTERFACES.md             # All module class/method signatures
│   ├── SCENARIOS.md              # YAML schema + scenario reference
│   ├── VARIABLES.md              # Full variable reference (groups A-H)
│   └── ROBOT_SELECTION.md        # G1 vs H1 architecture decision
├── scripts/
│   ├── run_phase3.py             # PRIMARY -- single-episode runner (all features)
│   ├── run_batch.py              # Multi-episode radius sweep
│   ├── run_phase2.py             # Phase 2 (G1 walk, no disturbance)
│   ├── run_pick_and_place.py     # Standalone UR10e pick-and-place
│   ├── smoke_test.sh             # Integration smoke test
│   ├── smoke_test_dual.py        # Dual-robot env load test
│   ├── gui_demo_phase1.py        # Isaac Sim GUI demo
│   ├── run_batch.sh              # Bash batch wrapper
│   ├── analyze_run.py            # CSV analytics
│   └── plot_trajectory.py        # 3D trajectory plot (requires matplotlib)
├── dual_env_cfg.py               # DualRobotDisturbanceEnvCfg -- merged env config
├── g1_walk_controller.py         # G1 walking policy wrapper (TorchScript)
├── g1_disturbance_controller.py  # Distance-gated velocity + arm PD + retreat
├── g1_arm_controller.py          # G1 arm joint PD control
├── g1_virtual_hand.py            # Safety proxy sphere (drifts near G1 head)
├── g1_vlm_client.py              # Remote VLM client (SSH tunnel + HTTP)
├── ur10e_controller.py           # UR10e pick-and-place state machine
├── safety_adapter.py             # G1EnvelopeAdapter -- G1 bodies -> safety spheres
├── deadlock_escape.py            # DeadlockDetector -- 3-tier escape (jitter/repel/retreat)
├── scenarios.py                  # Time-based hand scenarios (knock_off, transit_block, etc.)
├── per_part_state.py             # PerPartTester -- PICK/TRANSIT/PLACE/RESET protocol
├── batch_runner.py               # Batch orchestration (subprocess per episode)
├── mat_event_detector.py         # Pressure mat event detection
├── test_metrics.py               # EpisodeMetrics dataclass + MetricsWriter
├── config_loader.py              # YAML config loading + Phase3Config dataclass
├── paths.py                      # Centralized path constants (env vars with fallbacks)
└── mdp/                          # GMRobot safety MDP modules
```

## Development Notes

### Project dependencies

GMDisturb **references but does not copy** the two upstream projects:

```
/root/GMRobot/          -- read-only: UR10e USD, table/container/part assets,
                            safety layer (RuleEngine + SafetyGate), VLM server
/root/pressure_mat_repro/ -- read-only: G1 USD, walk policy .pt,
                             tactile mat .usd, MDP modules
```

GMDisturb imports GMRobot's `safety` and `mdp` modules via `importlib` at
runtime (lazy-loaded to avoid GMRobot's `isaaclab`-dependent `__init__.py`).
All path resolution goes through `paths.py`.

### Symlink-based Docker build

The Docker build context uses symlinks (set by `docker/build.sh`). Docker COPY
dereferences symlinks to their targets. This works when the target paths are on
the same filesystem as the build context. If `/root/GMRobot` or
`/root/pressure_mat_repro` are on a different filesystem, COPY will fail --
copy the directories into the context manually as a workaround.

### Adding a new scenario

1. Copy an existing YAML from `batch_test_configs/`
2. Set `name`, `mode`, and `safety` fields
3. Run: `python scripts/run_batch.py --radii 0.5 --repeats 1`

### Adding a new module

1. New Python file in project root
2. Import it in `scripts/run_phase3.py` where needed
3. Document the interface in `docs/INTERFACES.md`
4. Add the module to the architecture diagram in `docs/ARCHITECTURE.md`

### Testing

```bash
# Fastest integration test (2 min)
bash scripts/smoke_test.sh

# Load env without running a full episode
python scripts/smoke_test_dual.py

# Analyze output
python scripts/analyze_run.py /tmp/smoke_test_phase3.csv
```

## Docs

Full documentation is in `docs/`. Start with:

- New to the project: `docs/ARCHITECTURE.md` + `docs/DATA_FLOW.md`
- Testing scenarios: `docs/SCENARIOS.md`
- Module APIs: `docs/INTERFACES.md`
- Variable reference: `docs/VARIABLES.md`
- Doc index: `docs/README.md`
