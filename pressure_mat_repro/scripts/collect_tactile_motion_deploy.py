#!/usr/bin/env python3
"""Parallel tactile/CoM data collection driven by the deploy_walk torchscript
policy on the new ``PressureMat-Walk-G1-Deploy-v0`` env.

Same output format as ``collect_tactile_motion.py`` (intelligentCarpet schema:
log.p + per-sequence dirs of frame pickles), so the existing velocity-regressor
training pipeline can read the dataset unchanged.

Differences vs ``collect_tactile_motion.py``:
  - Default task: PressureMat-Walk-G1-Deploy-v0 (588-dim walker obs, 12-DOF
    leg-only action).
  - Policy: torchscript .pt, batch-call (no per-env loop).
  - Action shape that the env consumes is (N, 12) instead of (N, 29).
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import time

from omni.isaac.lab.app import AppLauncher

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

parser = argparse.ArgumentParser(description="G1 deploy_walk tactile/CoM data collection.")
parser.add_argument("--task", type=str, default="PressureMat-Walk-G1-Deploy-v0")
parser.add_argument("--num_envs", type=int, default=16)
parser.add_argument("--target_frames", type=int, default=15000)
parser.add_argument("--min_seq_len", type=int, default=20)
parser.add_argument("--save_every_n", type=int, default=5,
                    help="Env runs at 50 Hz, save_every_n=5 -> 10 Hz dataset.")
parser.add_argument("--trim_start_frames", type=int, default=5)
parser.add_argument("--trim_end_frames", type=int, default=1)
parser.add_argument("--skip_fall_terminations", action="store_true", default=True)
parser.add_argument("--tactile_out_size", type=int, default=96,
                    help="Resize tactile to this dim (intelligentCarpet expects 96x96).")
parser.add_argument(
    "--policy", type=str,
    default="/home/isaac/deploy_backup/unitree_rl_gym_backup/deploy/pre_train/g1/0121_walk.pt",
)
parser.add_argument("--out_dir", type=str, required=True)
parser.add_argument("--seed", type=int, default=0)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

import omni.isaac.lab_tasks  # noqa: F401, E402
from omni.isaac.lab_tasks.utils import parse_env_cfg  # noqa: E402


def main():
    os.makedirs(args.out_dir, exist_ok=True)

    # ---- Build env ----
    env_cfg = parse_env_cfg(args.task, num_envs=args.num_envs)
    env = gym.make(args.task, cfg=env_cfg)
    obs, _ = env.reset()
    device = env.unwrapped.device
    robot = env.unwrapped.scene["robot"]
    print(f"[collect] task={args.task} num_envs={args.num_envs}", flush=True)
    print(f"[collect] walker obs shape: {tuple(obs['walker'].shape)}", flush=True)
    print(f"[collect] tactile shape:    {tuple(obs['policy']['tactile'].shape)}", flush=True)

    # ---- Load torchscript policy (batch-friendly) ----
    policy = torch.jit.load(args.policy, map_location=device).eval()
    print(f"[collect] loaded policy: {args.policy}", flush=True)

    # ---- Per-env frame buffers ----
    buffers: list[list[dict]] = [[] for _ in range(args.num_envs)]
    sequence_start_indices: list[int] = []
    total_frames_saved = 0

    t_start = time.time()
    step = 0
    while total_frames_saved < args.target_frames:
        # ---- Policy inference (batched) ----
        with torch.no_grad():
            action = policy(obs["walker"]).clip(min=-100.0, max=100.0)

        # ---- Step env ----
        obs, _, terminated, truncated, info = env.step(action)
        done = terminated | truncated  # (num_envs,) bool

        # ---- Capture per-env frame at the chosen sample rate ----
        if step % args.save_every_n == 0:
            tactile = obs["policy"]["tactile"].detach().cpu().numpy()  # (N, R, C)
            com_world = robot.data.root_pos_w.detach().cpu().numpy()
            env_origin = env.unwrapped.scene.env_origins.detach().cpu().numpy()
            com_local = com_world - env_origin

            if args.tactile_out_size > 0 and tactile.shape[-1] != args.tactile_out_size:
                t_in = torch.from_numpy(tactile).unsqueeze(1).float()
                t_resized = torch.nn.functional.interpolate(
                    t_in, size=(args.tactile_out_size, args.tactile_out_size),
                    mode="bilinear", align_corners=False,
                ).squeeze(1)
                tactile = t_resized.numpy()

            for i in range(args.num_envs):
                buffers[i].append({
                    "tactile": tactile[i].astype(np.float32),
                    "com": com_local[i].astype(np.float32),
                })

        # ---- Flush sequences whose episode just ended ----
        done_envs = torch.nonzero(done).squeeze(-1).tolist()
        if isinstance(done_envs, int):
            done_envs = [done_envs]

        fell_by_env = {}
        if args.skip_fall_terminations and done_envs:
            term_mgr = env.unwrapped.termination_manager
            if "base_height" in term_mgr.active_terms:
                fell_flags = term_mgr.get_term("base_height")
                for i in done_envs:
                    fell_by_env[i] = bool(fell_flags[i].item())

        for i in done_envs:
            if fell_by_env.get(i, False):
                buffers[i] = []
                continue

            seq = buffers[i]
            if args.trim_start_frames > 0:
                seq = seq[args.trim_start_frames:]
            if args.trim_end_frames > 0:
                seq = seq[:-args.trim_end_frames] if args.trim_end_frames < len(seq) else []

            if len(seq) >= args.min_seq_len:
                seq_start = total_frames_saved
                seq_dir = os.path.join(args.out_dir, str(seq_start))
                os.makedirs(seq_dir, exist_ok=True)
                for f_idx, frame in enumerate(seq):
                    kp = np.zeros((21, 3), dtype=np.float32)
                    kp[0] = frame["com"]
                    kp[8] = frame["com"]
                    data = [frame["tactile"], None, kp]
                    global_idx = seq_start + f_idx
                    with open(os.path.join(seq_dir, f"{global_idx}.p"), "wb") as f:
                        pickle.dump(data, f)

                sequence_start_indices.append(seq_start)
                total_frames_saved += len(seq)
                with open(os.path.join(args.out_dir, "log.p"), "wb") as f:
                    pickle.dump(
                        np.array(sequence_start_indices + [total_frames_saved], dtype=np.int64),
                        f,
                    )
            buffers[i] = []

        step += 1
        if step % 50 == 0:
            elapsed = time.time() - t_start
            fps = (total_frames_saved + sum(len(b) for b in buffers)) / max(elapsed, 1e-6)
            print(
                f"[collect] step={step:5d}  saved={total_frames_saved:6d}/{args.target_frames}"
                f"  seqs={len(sequence_start_indices)}  "
                f"buffered={sum(len(b) for b in buffers):4d}  fps={fps:.1f}",
                flush=True,
            )

    with open(os.path.join(args.out_dir, "log.p"), "wb") as f:
        pickle.dump(np.array(sequence_start_indices + [total_frames_saved], dtype=np.int64), f)
    print(
        f"[collect] DONE. {total_frames_saved} frames in {len(sequence_start_indices)} sequences.",
        flush=True,
    )
    print(f"[collect] out_dir: {args.out_dir}", flush=True)
    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()
