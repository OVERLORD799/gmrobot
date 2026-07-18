#!/usr/bin/env python3
"""Isolated smoke test for the self-contained pressure_mat_deploy package.

Verifies the package imports + the env builds + the deploy_walk policy walks,
WITHOUT installing the package into the IsaacLab tree: it just puts the
package's parent dir on sys.path and registers from there.

Run:
    cd <IsaacLab>
    ./isaaclab.sh -p <repro>/scripts/smoke_test.py \
        --pkg_dir <repro>/isaac_lab_task \
        --policy <repro>/policy/0121_walk.pt \
        --headless
"""
import argparse
import os
import sys

from omni.isaac.lab.app import AppLauncher

parser = argparse.ArgumentParser()
parser.add_argument("--pkg_dir", required=True, help="dir containing pressure_mat_deploy/")
parser.add_argument("--policy", required=True)
parser.add_argument("--task", default="PressureMat-Walk-G1-Deploy-v0")
parser.add_argument("--num_steps", type=int, default=40)
parser.add_argument("--cmd_vx", type=float, default=0.5)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import gymnasium as gym
import numpy as np
import torch

# Register the self-contained task from the repro dir (no tree install).
sys.path.insert(0, os.path.abspath(args.pkg_dir))
import pressure_mat_deploy  # noqa: F401  -> fires gym.register
from pressure_mat_deploy.deploy_env_cfg import PressureMatWalkG1DeployEnvCfg


def main():
    cfg = PressureMatWalkG1DeployEnvCfg()
    cfg.scene.num_envs = 1
    env = gym.make(args.task, cfg=cfg)
    obs, _ = env.reset()
    dev = env.unwrapped.device

    walker = obs["walker"]
    tactile = obs["policy"]["tactile"]
    print(f"[smoke] walker obs shape = {tuple(walker.shape)}  (expect (1, 588))", flush=True)
    print(f"[smoke] tactile shape    = {tuple(tactile.shape)}  (expect (1, 32, 32))", flush=True)
    assert walker.shape[-1] == 588, f"walker obs {walker.shape[-1]} != 588"
    assert tuple(tactile.shape[-2:]) == (32, 32), f"tactile {tactile.shape}"

    policy = torch.jit.load(args.policy, map_location=dev).eval()
    vel = env.unwrapped.command_manager.get_term("base_velocity")
    fixed = torch.tensor([[args.cmd_vx, 0.0, 0.0]], device=dev).repeat(cfg.scene.num_envs, 1)

    any_fall = False
    peak = 0.0
    tac_peak = 0.0
    for step in range(args.num_steps):
        vel.vel_command_b[:] = fixed
        with torch.no_grad():
            action = policy(obs["walker"]).clip(min=-100.0, max=100.0)
        obs, _, term, trunc, _ = env.step(action)
        peak = max(peak, float(action.abs().max().item()))
        tac_peak = max(tac_peak, float(obs["policy"]["tactile"].max().item()))
        if bool((term | trunc).any().item()):
            any_fall = True
        if step % 10 == 0:
            print(f"[smoke] step {step:3d}  action_max={action.abs().max().item():.3f}  "
                  f"tactile_max={obs['policy']['tactile'].max().item():.1f} N", flush=True)

    print(f"[smoke] DONE {args.num_steps} steps | action peak {peak:.2f} | "
          f"tactile peak {tac_peak:.1f} N | early_done={any_fall}", flush=True)
    print("[smoke] PASS: package imports, env builds, policy runs, tactile non-zero."
          if tac_peak > 1.0 else "[smoke] WARN: tactile never registered force.", flush=True)
    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()
