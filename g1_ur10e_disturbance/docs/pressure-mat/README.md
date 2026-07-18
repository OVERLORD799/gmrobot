# Pressure-Mat Tactile → CoM-Velocity — Reproduction Package

> **📋 Archival copy** — This document is a snapshot from
> [`pressure_mat_repro`](https://github.com/OVERLORD799/pressure_mat)
> (Isaac Lab **1.3.0**, namespace `omni.isaac.lab.*`).
> The GMDisturb project has been migrated to Isaac Lab **2.x** (`isaaclab.*`).
> For GMDisturb's own architecture, see [`gmdisturb/ARCHITECTURE.md`](../gmdisturb/ARCHITECTURE.md).

A Unitree **G1 (29-DOF)** humanoid walks on a simulated **tactile pressure mat**
in Isaac Lab. The per-taxel contact-force image is fed to a CNN+GRU network that
predicts the robot's center-of-mass velocity `(vx, vy, vz)`. This package lets
you reproduce the **demo** (walking + live velocity prediction video) and
**train / evaluate** the velocity network on tactile data.

The Isaac Lab task is **fully self-contained**: it depends only on a *stock*
Isaac Lab install plus the files in this package. **No edits to Isaac Lab core
or asset libraries are required.**

---

## 1. Versions we used

| Component | Version |
|---|---|
| Isaac Sim | **4.2.0** |
| Isaac Lab | **1.3.0** (namespace `omni.isaac.lab.*`) |
| Python (sim) | 3.10 |
| Python (velocity training) | 3.6 |
| PyTorch (velocity training) | 1.6.0 + CUDA 10.2 |
| GPU used | NVIDIA RTX 2080 Ti (11 GB) — 1 GPU is enough |

> Install stock Isaac Sim 4.2.0 + Isaac Lab 1.3.0 first, following
> https://isaac-sim.github.io/IsaacLab/ (v1.3.0 docs). Everything below assumes
> `./isaaclab.sh` works in your Isaac Lab checkout.

There are **two Python environments**:
- the **Isaac Lab** env (Python 3.10) — runs the sim, walking demo, data
  collection, and the live-validation video. Invoked via `./isaaclab.sh -p`.
- a **velocity-training** env (Python 3.6, torch 1.6) — trains/evaluates the
  CNN+GRU velocity model. Only needs `torch`, `numpy`, `progressbar2`.

---

## 2. What's in the box

```
pressure_mat_repro/
├── README.md                      ← this file
├── MANIFEST.md                    ← every file + where it goes + why
├── isaac_lab_task/
│   └── pressure_mat_deploy/       ← THE TASK PACKAGE (drop into Isaac Lab, see install)
│       ├── __init__.py            ← registers PressureMat-Walk-G1-Deploy-v0 (+ HiRes)
│       ├── deploy_env_cfg.py      ← 32×32 / 4 m mat env (the demo task)
│       ├── deploy_hires_env_cfg.py← 64×64 / 4 m mat env (ablation)
│       ├── robot_cfg.py           ← G1 29-DOF walk robot config (vendored)
│       ├── mdp/
│       │   ├── __init__.py
│       │   ├── observations.py    ← tactile force image + deploy-walk obs helpers
│       │   ├── terminations.py    ← walk-off-mat termination
│       │   └── walk_action.py     ← 12-DOF leg-only action term (vendored)
│       └── data/
│           ├── g1_29dof_modified_new_91.usd   ← robot USD (31 MB)
│           ├── tactile_mat_32x32_4m.usd        ← 32×32 mat USD
│           └── tactile_mat_64x64_4m.usd        ← 64×64 mat USD (HiRes)
├── policy/
│   └── 0121_walk.pt               ← G1 walking policy (torchscript, 1.9 MB)
├── scripts/                       ← run via ./isaaclab.sh -p
│   ├── play_deploy_walk_policy.py ← walk the robot, optional sim+tactile video
│   ├── collect_tactile_motion_deploy.py ← collect (tactile, CoM) dataset
│   ├── validate_tactile_hybrid.py ← live demo: sim + real-vs-predicted velocity
│   └── smoke_test.py              ← quick self-check (no tree install needed)
└── velocity_training/             ← CNN+GRU train/eval (Python 3.6 + torch 1.6)
    ├── velocity_temporal_model.py ← SequentialTactileHybridRegressor
    ├── velocity_train_seq.py      ← trainer (32×32)
    ├── velocity_train_seq_64.py   ← trainer (64×64 hires)
    ├── velocity_train_seq_noisy.py← trainer w/ Gaussian tactile noise
    ├── velocity_dataLoader_*.py   ← sequence dataloaders (32 / 64 / noisy + base utils)
    ├── velocity_model_final.py    ← masked-MSE loss helper
    ├── ckpts/
    │   └── g1_walk_deploy_v1_seqhybrid_0.0001_seq_best.path.tar  ← DEMO checkpoint
    └── ablation_ckpts/            ← noise σ=5, σ=15, and 64×64-hires checkpoints
```

---

## 3. Install

### 3a. The Isaac Lab task package
Copy the task folder into your Isaac Lab checkout's task tree, then it
auto-registers on `import omni.isaac.lab_tasks`:

```bash
ISAACLAB=/path/to/IsaacLab          # your stock Isaac Lab 1.3.0 checkout
REPRO=/path/to/pressure_mat_repro   # this package

cp -r "$REPRO/isaac_lab_task/pressure_mat_deploy" \
      "$ISAACLAB/source/extensions/omni.isaac.lab_tasks/omni/isaac/lab_tasks/manager_based/"
```

That's the **only** install step for the sim side — no core files are touched.
(The robot + mat USDs travel inside `pressure_mat_deploy/data/`, so the package
is relocatable.)

Quick check it imports + the policy walks (does NOT modify your tree):
```bash
cd "$ISAACLAB"
./isaaclab.sh -p "$REPRO/scripts/smoke_test.py" \
    --pkg_dir "$REPRO/isaac_lab_task" \
    --policy  "$REPRO/policy/0121_walk.pt" \
    --headless
# expect: walker obs (1,588), tactile (1,32,32), policy walks, "[smoke] PASS"
```

### 3b. The velocity-training environment (Python 3.6)
```bash
conda create -n vel python=3.6 -y && conda activate vel
pip install torch==1.6.0 numpy progressbar2
```

---

## 4. Reproduce the demo

Run all of these from your Isaac Lab root (`cd "$ISAACLAB"`). Always pass
`--policy "$REPRO/policy/0121_walk.pt"` (the script default points elsewhere).

> **Headless vs windowed:** keep `--headless` for a no-GUI run that just writes
> the mp4 (what we used). **Drop `--headless`** to watch it live in the Isaac Sim
> GUI window. All demo commands use **`--num_envs 1`** (single robot).

**(a) Walk the robot + record sim-viewport + tactile heatmap side-by-side:**
```bash
./isaaclab.sh -p "$REPRO/scripts/play_deploy_walk_policy.py" \
    --task PressureMat-Walk-G1-Deploy-v0 \
    --num_envs 1 \
    --policy "$REPRO/policy/0121_walk.pt" \
    --cmd_seq "0.5,0,0;-0.4,0,0;0,0.3,0;0,-0.3,0;0,0,1.0;0,0,-1.0;0.3,0.3,0" \
    --steps_per_cmd 60 \
    --record_video "$REPRO/out" --side_by_side_tactile --headless
```
`--cmd_seq` is a list of `vx,vy,wz` commands (m/s, m/s, rad/s); each is held for
`--steps_per_cmd` env steps. Command envelope: `vx∈[-0.8,0.8]`,
`vy∈[-0.5,0.5]`, `wz∈[-1.57,1.57]`.

**(b) Live velocity-prediction demo (THE headline video — sim on the left,
real vs predicted velocity on the right):**
```bash
./isaaclab.sh -p "$REPRO/scripts/validate_tactile_hybrid.py" \
    --task PressureMat-Walk-G1-Deploy-v0 \
    --num_envs 1 \
    --policy "$REPRO/policy/0121_walk.pt" \
    --ckpt  "$REPRO/velocity_training/ckpts/g1_walk_deploy_v1_seqhybrid_0.0001_seq_best.path.tar" \
    --num_steps 500 --record_video "$REPRO/out" --headless
# prints live MAE; saves out/validate_hybrid_<ts>.mp4  (≈0.08 m/s Speed MAE)
```

---

## 5. Collect data + train / evaluate the velocity network

**(a) Collect a synthetic (tactile, CoM) dataset** (40 parallel envs, 10 Hz,
intelligentCarpet schema = `log.p` + per-sequence dirs of frame pickles
`[tactile(R,C), None, keypoint(21,3)]` with CoM at keypoint 0 & 8):
```bash
./isaaclab.sh -p "$REPRO/scripts/collect_tactile_motion_deploy.py" \
    --task PressureMat-Walk-G1-Deploy-v0 \
    --policy "$REPRO/policy/0121_walk.pt" \
    --num_envs 40 --target_frames 60000 --tactile_out_size 0 \
    --out_dir /path/to/dataset --headless
```
> To train/evaluate on **real** mat data instead, arrange it in the same schema
> (32×32 tactile per frame, CoM in keypoints 0 & 8, `log.p` listing sequence
> start indices) and point `--train_dir/--val_dir` at it below.

**(b) Train the CNN+GRU velocity model** (Python 3.6 env, from
`velocity_training/`):
```bash
conda activate vel
cd "$REPRO/velocity_training"
python velocity_train_seq.py \
    --epoch 30 --batch_size 4 --num_workers 4 \
    --train_dir /path/to/dataset/ --val_dir /path/to/dataset/ \
    --exp my_run --fps_default 10 --smooth_radius 1 \
    --head_idx 0 --anchor_idx 8 --position_scale 1.0 --velocity_norm 1.0
# best checkpoint -> ./train/ckpts/my_run_0.0001_seq_best.path.tar
```
Variants: `velocity_train_seq_64.py` (64×64 data), `velocity_train_seq_noisy.py
--noise_sigma 5` (Gaussian tactile-noise augmentation, in Newtons).

**(c) Evaluate** = run the live-validation demo (§4b) with `--ckpt` pointing at
your trained `*_seq_best.path.tar`, optionally `--task
PressureMat-Walk-G1-Deploy-HiRes-v0` for the 64×64 checkpoint.

---

## 6. Checkpoints provided

| File | Mat | Train noise | Live Speed MAE |
|---|---|---|---|
| `ckpts/...seqhybrid_0.0001_seq_best.path.tar` | 32×32 | none | **0.078 m/s** ← demo |
| `ablation_ckpts/...n5...` | 32×32 | σ=5 N | 0.082 m/s |
| `ablation_ckpts/...n15...` | 32×32 | σ=15 N | 0.132 m/s |
| `ablation_ckpts/...hires...` | 64×64 | none | 0.105 m/s |

Model = `SequentialTactileHybridRegressor` (per-frame CNN over a 3-frame local
stack → causal GRU with 4-frame future lookahead → per-timestep `(vx,vy,vz)`).
`validate_tactile_hybrid.py` re-defines this class inline, so evaluation needs
no `velocity_training/` import — just a checkpoint.

---

## 7. Notes / gotchas

- **Mat resolution:** 32×32 over a 4 m mat (≈12.9 cm pitch) was the sweet spot.
  Finer mats (64×64) give noisier walking + lower per-cell force SNR; the
  `HiRes` task + `...hires...` checkpoint reproduce that ablation.
- **Why it walks cleanly on the mat:** the mat USD bakes in ground-plane-matched
  friction (0.5/0.5 + patch friction) and high taxel mass; the robot foot
  friction is set to 0.8/0.6 via a reset event. These already live in the
  shipped USDs / env config — nothing to tune.
- **Tactile image** is the per-taxel normal force in Newtons, calibrated so each
  foot's image sums to that foot's net ground-reaction force, then
  Pasternak-smeared (`coupling_length=0.01 m`).
- The two extra tasks the scripts can target: `PressureMat-Walk-G1-Deploy-v0`
  (32×32) and `PressureMat-Walk-G1-Deploy-HiRes-v0` (64×64).
