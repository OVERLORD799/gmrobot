# MANIFEST — where each file goes and why

> **📋 Archival copy** — This document is a snapshot from
> [`pressure_mat_repro`](https://github.com/OVERLORD799/pressure_mat)
> (Isaac Lab **1.3.0**, namespace `omni.isaac.lab.*`).
> The GMDisturb project has been migrated to Isaac Lab **2.x** (`isaaclab.*`).
> For GMDisturb's own architecture, see [`gmdisturb/ARCHITECTURE.md`](../gmdisturb/ARCHITECTURE.md).

`$ISAACLAB` = your stock Isaac Lab 1.3.0 checkout. `$REPRO` = this package.
`MB` = `$ISAACLAB/source/extensions/omni.isaac.lab_tasks/omni/isaac/lab_tasks/manager_based`.

## Isaac Lab task (the only thing that must be installed into the tree)

| File (in this package) | Install destination | Role |
|---|---|---|
| `isaac_lab_task/pressure_mat_deploy/` (whole folder) | `$MB/pressure_mat_deploy/` | Self-contained task package; auto-registers `PressureMat-Walk-G1-Deploy-v0` and `...-HiRes-v0`. |

Inside the package (no separate install — they travel with the folder):
| File | Role |
|---|---|
| `__init__.py` | `gym.register` for the two task ids. |
| `deploy_env_cfg.py` | 32×32 / 4 m env: scene, obs (tactile + 588-dim walker), 12-DOF leg action, commands, events, terminations. Self-contained. |
| `deploy_hires_env_cfg.py` | 64×64 / 4 m variant (ablation). |
| `robot_cfg.py` | `G1_927_WALK_CFG` (vendored from the project's `unitree.py` addition); USD path resolved package-relative. |
| `mdp/observations.py` | `tactile_force_multi_net` (per-taxel Newton image + Pasternak + calibration) + deploy-walk obs helpers (`velocity_commands_deploy`, `walk_sin_phase`, `walk_cos_phase`, `last_action_padded_29`). |
| `mdp/walk_action.py` | `WalkJointAction` / `WalkJointActionCfg` — 12-DOF leg-only action keeping a full 29-DOF target buffer (vendored; subclasses stock `JointAction`). |
| `mdp/terminations.py` | `root_out_of_mat_bounds` (walk-off-mat termination). |
| `mdp/__init__.py` | re-exports the above + `from omni.isaac.lab.envs.mdp import *`. |
| `data/g1_29dof_modified_new_91.usd` | G1 29-DOF robot USD (31 MB). |
| `data/tactile_mat_32x32_4m.usd` | 32×32 / 4 m mat USD. |
| `data/tactile_mat_64x64_4m.usd` | 64×64 / 4 m mat USD (HiRes task). |

> These vendored pieces (`robot_cfg`, `walk_action`, the deploy-walk obs
> helpers, the mat USDs) are why **no Isaac Lab core/asset-lib edits are
> needed** — the originals lived in modified core files; here they are local to
> the task package and use only stock Isaac Lab symbols.

## Scripts — run via `./isaaclab.sh -p $REPRO/scripts/<x>.py` (no install needed)

| File | Role |
|---|---|
| `scripts/play_deploy_walk_policy.py` | Walk the robot; optional sim + tactile-heatmap side-by-side video. |
| `scripts/collect_tactile_motion_deploy.py` | Collect a `(tactile, CoM)` dataset (intelligentCarpet schema). |
| `scripts/validate_tactile_hybrid.py` | Live demo: sim viewport + real-vs-predicted velocity (re-defines the model inline → only needs a checkpoint). |
| `scripts/smoke_test.py` | Isolated import/build/walk self-check (no tree install). |

> Pass `--policy $REPRO/policy/0121_walk.pt` to the first three (their built-in
> default path won't exist on your machine).

## Walking policy

| File | Role |
|---|---|
| `policy/0121_walk.pt` | G1 walking policy (torchscript). Input = 588-dim walker obs, output = 12-DOF leg action (clipped ±100). |

## Velocity network (Python 3.6 + torch 1.6 env)

| File | Role |
|---|---|
| `velocity_training/velocity_temporal_model.py` | `SequentialTactileHybridRegressor` + variants. |
| `velocity_training/velocity_train_seq.py` | Trainer (32×32). |
| `velocity_training/velocity_train_seq_64.py` | Trainer (64×64 hires). |
| `velocity_training/velocity_train_seq_noisy.py` | Trainer w/ `--noise_sigma` Gaussian tactile noise. |
| `velocity_training/velocity_dataLoader_seq_32.py` | Sequence dataloader, 32×32. |
| `velocity_training/velocity_dataLoader_seq_64.py` | Sequence dataloader, 64×64. |
| `velocity_training/velocity_dataLoader_seq_32_noisy.py` | 32×32 dataloader with noise injection. |
| `velocity_training/velocity_dataLoader_batch.py`, `..._batch_32.py` | dt / timestamp utilities used by the seq dataloaders. |
| `velocity_training/velocity_model_final.py` | `masked_mse_loss`. |
| `velocity_training/ckpts/...seqhybrid_0.0001_seq_best.path.tar` | DEMO checkpoint (32×32, no noise). |
| `velocity_training/ablation_ckpts/...{n5,n15,hires}...` | Ablation checkpoints (noise σ=5/15, 64×64). |

## NOT included (you provide / install separately)
- Stock **Isaac Sim 4.2.0** + **Isaac Lab 1.3.0**.
- Any **dataset** (collect one with `collect_tactile_motion_deploy.py`, or bring
  real mat data in the same schema).
