#!/usr/bin/env python3
"""GMDisturb Phase 1 GUI demo: G1 walks on pressure mat, UR10e stays at home.

Expected behavior in GUI:
  - G1 starts at (-1.5, 0.8) on the left side of the mat
  - UR10e at (0, 0) mounted on table at (0.6, 0), gripper visible
  - Pressure mat (4m x 4m gray grid) under both robots
  - Two containers (A at y=-0.25, B at y=0.25) with 20 green parts
  - G1 walks forward at 0.5 m/s toward the table
  - G1 root_pos moves from x=-1.5 toward x=+0.5 over ~4 seconds
  - Then G1 stops (vx=0)

Usage:
    python scripts/gui_demo_phase1.py            # GUI mode
    python scripts/gui_demo_phase1.py --headless  # headless test (no visual)
"""
from __future__ import annotations
import argparse, sys, os

# Bootstrap: add project root to sys.path (__file__-relative, no hardcoded /root/)
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from paths import GMROBOT_ASSETS, GMROBOT_MDP, PRESSURE_MAT_POLICY

for p in [GMROBOT_ASSETS, GMROBOT_MDP]:
    if p not in sys.path:
        sys.path.insert(0, p)

from isaaclab.app import AppLauncher
parser = argparse.ArgumentParser(description="GMDisturb Phase 1 GUI demo")
AppLauncher.add_app_launcher_args(parser)
parser.add_argument("--policy", type=str, default=PRESSURE_MAT_POLICY)
parser.add_argument("--walk_steps", type=int, default=200,
                    help="Steps to walk forward at 0.5 m/s")
parser.add_argument("--stand_steps", type=int, default=100,
                    help="Steps to stand still after walking")
args_cli = parser.parse_args()
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import torch, gymnasium as gym
from dual_env_cfg import DualRobotDisturbanceEnvCfg
gym.register(id="G1-UR10e-Disturbance-v0",
             entry_point="isaaclab.envs:ManagerBasedRLEnv",
             disable_env_checker=True,
             kwargs={"env_cfg_entry_point": DualRobotDisturbanceEnvCfg})
from isaaclab_tasks.utils import parse_env_cfg


def main():
    task_id = "G1-UR10e-Disturbance-v0"
    print(f"[demo] Task: {task_id}")
    print(f"[demo] Isaac Sim running at http://localhost:8211 (check GUI window)")

    env_cfg = parse_env_cfg(task_id, num_envs=1)
    env = gym.make(task_id, cfg=env_cfg)
    obs, info = env.reset()
    scene = env.unwrapped.scene
    robot_g1 = scene["robot_g1"]
    robot_ur10e = scene["robot_ur10e"]

    # --- Load walking policy ---
    policy_path = args_cli.policy
    print(f"[demo] Loading walking policy: {policy_path}")
    if os.path.isfile(policy_path):
        policy = torch.jit.load(policy_path, map_location="cuda:0").eval()
        print("[demo] Policy loaded OK")
    else:
        policy = None
        print("[demo] WARNING: policy not found — G1 will NOT walk (zero actions only)")

    # --- Inject velocity command: walk forward ---
    vel_term = env.unwrapped.command_manager.get_term("g1_base_velocity")
    device = "cuda:0"

    print("\n[demo] === PHASE A: G1 stands still (50 steps) ===")
    vel_term.vel_command_b[:] = torch.tensor([[0.0, 0.0, 0.0]], device=device, dtype=torch.float32)
    for step in range(50):
        action = _get_action(policy, obs, env, device, robot_g1)
        obs, _, _, _, _ = env.step(action)
        if step % 10 == 0:
            print(f"  stand step {step}: G1@({robot_g1.data.root_pos_w[0,0]:.2f}, {robot_g1.data.root_pos_w[0,1]:.2f}), z={robot_g1.data.root_pos_w[0,2]:.2f}")

    print(f"\n[demo] === PHASE B: G1 walks forward at vx=0.5 m/s for {args_cli.walk_steps} steps ===")
    vel_term.vel_command_b[:] = torch.tensor([[0.5, 0.0, 0.0]], device=device, dtype=torch.float32)
    for step in range(args_cli.walk_steps):
        action = _get_action(policy, obs, env, device, robot_g1)
        obs, _, _, _, _ = env.step(action)
        if step % 25 == 0:
            g1 = robot_g1.data.root_pos_w[0]
            print(f"  walk step {step}: G1@({g1[0]:.2f}, {g1[1]:.2f}), z={g1[2]:.2f}")

    print(f"\n[demo] === PHASE C: G1 stands still ({args_cli.stand_steps} steps) ===")
    vel_term.vel_command_b[:] = torch.tensor([[0.0, 0.0, 0.0]], device=device, dtype=torch.float32)
    for step in range(args_cli.stand_steps):
        action = _get_action(policy, obs, env, device, robot_g1)
        obs, _, _, _, _ = env.step(action)
        if step % 25 == 0:
            g1 = robot_g1.data.root_pos_w[0]
            ur10e_ee = robot_ur10e.data.body_link_pos_w[0, 6]  # wrist_3_link
            print(f"  stand step {step}: G1@({g1[0]:.2f},{g1[1]:.2f}) EE@({ur10e_ee[0]:.2f},{ur10e_ee[1]:.2f})")

    # --- Final scene summary ---
    print("\n[demo] === SCENE SUMMARY ===")
    g1 = robot_g1.data.root_pos_w[0]
    ur10e_ee = robot_ur10e.data.body_link_pos_w[0, 6]
    print(f"  G1 final pos: ({g1[0]:.3f}, {g1[1]:.3f}, {g1[2]:.3f})")
    print(f"  UR10e EE pos: ({ur10e_ee[0]:.3f}, {ur10e_ee[1]:.3f}, {ur10e_ee[2]:.3f})")
    print(f"  G1 has {len(robot_g1.body_names)} bodies, {len(robot_g1.joint_names)} joints")
    print(f"  UR10e has {len(robot_ur10e.body_names)} bodies")
    print(f"  G1→EE distance: {torch.norm(g1[:2] - ur10e_ee[:2]):.3f} m")
    print("\n[demo] Demo complete. Close the Isaac Sim window to exit.")

    if args_cli.headless:
        env.close()
        simulation_app.close()
    else:
        print("[demo] GUI still running — close window or Ctrl+C to exit")
        try:
            while simulation_app.is_running():
                simulation_app.update()
        except KeyboardInterrupt:
            pass
        env.close()
        simulation_app.close()


def _get_action(policy, obs, env, device, robot_g1):
    """Build 20D action: G1 policy output (12D) + UR10e zero (8D)."""
    if policy is not None:
        g1_action = policy(obs["g1_walker"]).clip(-100, 100)
    else:
        # No policy: hold default leg positions
        g1_action = torch.zeros(1, 12, device=device)
    # UR10e stays at home (zero action via DiffIK = hold current)
    ur10e_ee_action = torch.zeros(1, 7, device=device)
    ur10e_grip_action = torch.zeros(1, 1, device=device)
    return torch.cat([g1_action, ur10e_ee_action, ur10e_grip_action], dim=-1)


if __name__ == "__main__":
    main()
