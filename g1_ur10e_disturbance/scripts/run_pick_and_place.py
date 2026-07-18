#!/usr/bin/env python3
"""GMDisturb: UR10e pick-and-place with G1 stationary (z=0 GMRobot layout)."""

from __future__ import annotations
import argparse, sys, os
import numpy as np
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="GMDisturb pick-and-place demo")
parser.add_argument("--max_steps", type=int, default=10000)
parser.add_argument("--progress_interval", type=int, default=200)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import torch, gymnasium as gym
from dual_env_cfg import DualRobotDisturbanceEnvCfg
gym.register(id="G1-UR10e-Disturbance-v0", entry_point="isaaclab.envs:ManagerBasedRLEnv",
             disable_env_checker=True, kwargs={"env_cfg_entry_point": DualRobotDisturbanceEnvCfg})
from scripts.pick_and_place_policy import SingleEnvPickAndPlacePolicy

def _cpu_obs(d):
    r = {}
    for k, v in d.items():
        if hasattr(v, "cpu"): v = v.cpu().numpy()
        if isinstance(v, np.ndarray) and v.ndim >= 2 and v.shape[0] == 1: v = v[0]
        r[k] = v
    return r

def main():
    from isaaclab_tasks.utils import parse_env_cfg
    env_cfg = parse_env_cfg("G1-UR10e-Disturbance-v0", num_envs=1)
    env = gym.make("G1-UR10e-Disturbance-v0", cfg=env_cfg)
    obs, info = env.reset()
    dev = env.unwrapped.device
    policy = SingleEnvPickAndPlacePolicy()
    policy.reset(_cpu_obs(obs["ur10e_policy"]))
    ival = args_cli.progress_interval
    # Print actual world positions of key objects
    scene = env.unwrapped.scene
    ur10e_z = scene["robot_ur10e"].data.root_pos_w[0,2].item()
    g1_z = scene["robot_g1"].data.root_pos_w[0,2].item()
    print(f"[run] UR10e base_z={ur10e_z:.3f}  G1 root_z={g1_z:.3f}  "
          f"UR10e: {len(policy.user_commands)} parts A→B  |  max_steps={args_cli.max_steps}")

    for step in range(args_cli.max_steps):
        ua = policy.get_action(_cpu_obs(obs["ur10e_policy"]), advance=True)
        action = torch.zeros(1, 20, device=dev)
        action[0, 12:19] = torch.from_numpy(ua[:7].astype(np.float32)).to(dev)
        action[0, 19] = torch.tensor(ua[7], dtype=torch.float32, device=dev)
        obs, _, terminated, truncated, _ = env.step(action)

        if step % 50 == 0:
            gz = env.unwrapped.scene["robot_g1"].data.root_pos_w[0,2].item()
            ee = env.unwrapped.scene["robot_ur10e"].data.body_link_pos_w[0,
                env.unwrapped.scene["robot_ur10e"].find_bodies("wrist_3_link")[0][0]].cpu().numpy()
            base_z = env.unwrapped.scene["robot_ur10e"].data.root_pos_w[0,2].item()
            jpos = env.unwrapped.scene["robot_ur10e"].data.joint_pos[0,:6].cpu().numpy()
            print(f"[DATA] step={step:5d} t={policy.time_step:5d} "
                  f"base_z={base_z:.3f} target=({ua[0]:.3f},{ua[1]:.3f},{ua[2]:.3f}) "
                  f"ee=({ee[0]:.3f},{ee[1]:.3f},{ee[2]:.3f}) "
                  f"joints=[{jpos[0]:.2f},{jpos[1]:.2f},{jpos[2]:.2f},{jpos[3]:.2f},{jpos[4]:.2f},{jpos[5]:.2f}] "
                  f"stage={policy.stage_name_at_step(policy.time_step)} "
                  f"g1_z={gz:.3f}")

        # No data collection limit — run to completion

        if policy.success or terminated or truncated:
            break

    print(f"[run] time_step={policy.time_step}  success={policy.success}")
    env.close()
    simulation_app.close()

if __name__ == "__main__":
    main()
