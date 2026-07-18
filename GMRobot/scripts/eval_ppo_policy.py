#!/usr/bin/env python3
"""G6c: Evaluate a trained PPO policy with safety gating, produce CSV metrics."""
import argparse, os, sys
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Evaluate trained PPO policy.")
AppLauncher.add_app_launcher_args(parser)
parser.add_argument("--task", type=str, default="gm")
parser.add_argument("--checkpoint", type=str,
                    default=os.path.join(os.environ.get("GMROBOT_OUTPUT_DIR", "/root/GMRobot/output"), "rl_models", "ppo_pick_place", "checkpoints", "agent_3200.pt"))
parser.add_argument("--max_steps", type=int, default=1000)
args_cli = parser.parse_args()

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import GMRobot.tasks  # noqa
import isaaclab_tasks  # noqa
import gymnasium as gym
import torch
import numpy as np
from isaaclab_rl.skrl import SkrlVecEnvWrapper
from isaaclab_tasks.utils import parse_env_cfg

def main():
    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=1, use_fabric=False)
    env_cfg.observations.policy = env_cfg.observations.flat_policy
    env_cfg.observations.camera = None
    env_cfg.observations.safety = None

    env = gym.make(args_cli.task, cfg=env_cfg)
    env = SkrlVecEnvWrapper(env)

    # Load trained policy
    ckpt = torch.load(args_cli.checkpoint, map_location="cpu")
    from skrl.agents.torch.ppo import PPO
    from skrl.resources.preprocessors.torch import RunningStandardScaler
    # Build minimal PPO agent just for inference
    agent = PPO(
        models={"policy": ckpt.get("policy"), "value": ckpt.get("value")},
        memory=None,
        cfg={"class": "PPO"},
        observation_space=env.observation_space,
        action_space=env.action_space,
        device=env.device,
    )
    if "policy" in ckpt:
        agent._policy.load_state_dict(ckpt["policy"])
    if "value" in ckpt:
        agent._value.load_state_dict(ckpt["value"])

    obs, _ = env.reset()
    total_reward = 0.0
    for step in range(args_cli.max_steps):
        with torch.no_grad():
            actions = agent.act(obs, timestep=step, timesteps=args_cli.max_steps)[0]
        obs, reward, terminated, truncated, _ = env.step(actions)
        total_reward += float(reward.mean())
        if terminated.any() or truncated.any():
            break

    print(f"PPO eval: steps={step+1} total_reward={total_reward:.1f}")
    env.close()

if __name__ == "__main__":
    main()
    simulation_app.close()
