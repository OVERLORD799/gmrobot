#!/usr/bin/env python3
"""PPO training for GM pick-and-place (G6b).

Uses Isaac Lab skrl Runner.  Observation is flattened from Dict→Box
via the FlatObsWrapper defined below.

Usage::

    python scripts/train_ppo_pick_place.py --task=gm --headless \\
        --enable_cameras --num_envs 16 --max_iterations 200
"""

import argparse, sys
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Train PPO for GM pick-and-place.")
AppLauncher.add_app_launcher_args(parser)
parser.add_argument("--num_envs", type=int, default=16)
parser.add_argument("--max_iterations", type=int, default=200)
parser.add_argument("--task", type=str, default="gm")
parser.add_argument("--seed", type=int, default=42)
args_cli, hydra_args = parser.parse_known_args()
sys.argv = [sys.argv[0]] + hydra_args

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import GMRobot.tasks  # noqa: F401
import isaaclab_tasks  # noqa: F401

import gymnasium as gym
import numpy as np
import torch

from isaaclab_rl.skrl import SkrlVecEnvWrapper
from isaaclab_tasks.utils import parse_env_cfg
from skrl.utils.runner.torch import Runner




def _flatten_dict_obs(obs, obs_space):
    """Convert a Dict observation to a flat tensor."""
    if isinstance(obs, dict):
        parts = []
        for _, v in sorted(obs.items()):
            if v is None: continue
            t = torch.as_tensor(v, dtype=torch.float32)
            parts.append(t.reshape(t.shape[0], -1))
        if parts:
            return torch.cat(parts, dim=-1)
        return torch.zeros(torch.as_tensor(list(obs.values())[0]).shape[0], 0, dtype=torch.float32)
    t = torch.as_tensor(obs, dtype=torch.float32)
    return t.reshape(t.shape[0], -1)


def main():
    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device,
                            num_envs=args_cli.num_envs, use_fabric=False)
    env_cfg.seed = args_cli.seed
    # Use flat policy observations (1D vectors only, no 4×4 matrices).
    env_cfg.observations.policy = env_cfg.observations.flat_policy
    env_cfg.observations.camera = None
    env_cfg.observations.safety = None

    env = gym.make(args_cli.task, cfg=env_cfg)
    env = SkrlVecEnvWrapper(env)
    print(f"[TRAIN] obs_space={env.observation_space}")

    from isaaclab_tasks.utils.parse_cfg import load_cfg_from_registry
    agent_cfg = load_cfg_from_registry(args_cli.task, "skrl_cfg_entry_point")
    agent_cfg["agent"]["experiment"]["experiment_name"] = "ppo_pick_place"
    agent_cfg["trainer"]["timesteps"] = args_cli.max_iterations * agent_cfg["agent"]["rollouts"]

    runner = Runner(env, agent_cfg)
    runner.run()
    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()
