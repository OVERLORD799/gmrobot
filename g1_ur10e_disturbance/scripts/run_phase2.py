#!/usr/bin/env python3
"""GMDisturb Phase 2: G1 wandering + UR10e pick-and-place co-simulation.

Usage:
    python scripts/run_phase2.py --headless
    python scripts/run_phase2.py                   # with GUI
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="GMDisturb Phase 2")
parser.add_argument("--max_steps", type=int, default=10000)
parser.add_argument("--progress_interval", type=int, default=200)
parser.add_argument("--output_csv", type=str, default="/tmp/gmdisturb_phase2.csv")
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

# Camera needs --enable_cameras — force it unconditionally
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import torch
import gymnasium as gym

from dual_env_cfg import DualRobotDisturbanceEnvCfg
gym.register(
    id="G1-UR10e-Disturbance-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": DualRobotDisturbanceEnvCfg},
)

from g1_walk_controller import G1WalkController
from ur10e_controller import UR10eController
from safety_adapter import G1EnvelopeAdapter
from mat_event_detector import MatEventDetector
from g1_disturbance_controller import G1DisturbanceController
from test_metrics import EpisodeMetrics, MetricsWriter


def main():
    from isaaclab_tasks.utils import parse_env_cfg

    task_id = "G1-UR10e-Disturbance-v0"
    print(f"[run] Creating env: {task_id}")
    env_cfg = parse_env_cfg(task_id, num_envs=1)
    env = gym.make(task_id, cfg=env_cfg)
    obs, info = env.reset()
    device = env.unwrapped.device

    # ── Controllers ──────────────────────────────────────────────────────
    g1_walk = G1WalkController().to(device)
    ur10e = UR10eController()
    adapter = G1EnvelopeAdapter()
    detector = MatEventDetector()
    disturb = G1DisturbanceController()
    metrics = EpisodeMetrics(episode_id=0)
    writer = MetricsWriter(args_cli.output_csv)

    print(f"[run] UR10e base_z={env.unwrapped.scene['robot_ur10e'].data.root_pos_w[0,2].item():.3f}  "
          f"G1 root_z={env.unwrapped.scene['robot_g1'].data.root_pos_w[0,2].item():.3f}")

    ur10e.reset(obs["ur10e_policy"])

    scene = env.unwrapped.scene
    g1 = scene["robot_g1"]
    ur10e_robot = scene["robot_ur10e"]

    ival = args_cli.progress_interval
    max_steps = args_cli.max_steps

    for step in range(max_steps):
        # ── 1. Read robot state ───────────────────────────────────────
        g1_root = g1.data.root_pos_w[0].cpu().numpy()
        ur10e_ee = ur10e_robot.data.body_link_pos_w[
            0, ur10e_robot.find_bodies("wrist_3_link")[0][0]
        ].cpu().numpy()

        # ── 2. G1 walking (random velocity from UniformVelocityCommandCfg) ──
        walker_obs = obs["g1_walker"][0].cpu().numpy().astype(np.float32)
        g1_leg_action = g1_walk.get_action(walker_obs)  # (12,)

        # ── 3. Disturbance tracking (velocity injection deferred to Phase 3) ──
        disturb.update(g1_root, ur10e_ee)

        # ── 4. UR10e pick-and-place ───────────────────────────────────
        ur10e_action = ur10e.get_action(obs["ur10e_policy"])  # (8,)

        # ── 5. Safety adapter ─────────────────────────────────────────
        adapter.update(g1, ur10e_ee)

        # ── 6. Mat event detection ────────────────────────────────────
        tactile_img = obs["tactile"]["tactile"][0].cpu().numpy() if isinstance(obs["tactile"], dict) else obs["tactile"][0].cpu().numpy()
        left_foot_pos = g1.data.body_link_pos_w[0, g1.find_bodies("left_ankle_roll_link")[0][0]].cpu().numpy()
        right_foot_pos = g1.data.body_link_pos_w[0, g1.find_bodies("right_ankle_roll_link")[0][0]].cpu().numpy()
        mat_events = detector.detect(tactile_img, left_foot_pos, right_foot_pos)

        # ── 7. Build combined action ──────────────────────────────────
        action = torch.zeros(1, 20, device=device)
        action[0, :12] = torch.from_numpy(g1_leg_action).to(device)
        action[0, 12:19] = torch.from_numpy(ur10e_action[:7].astype(np.float32)).to(device)
        action[0, 19] = torch.tensor(ur10e_action[7], dtype=torch.float32, device=device)

        # ── 7. Step simulation ────────────────────────────────────────
        obs, reward, terminated, truncated, info = env.step(action)

        # ── 8. Metrics ─────────────────────────────────────────────────
        g1_ur10e_dist = float(np.linalg.norm(g1_root[:2] - ur10e_ee[:2]))
        metrics.record_step(
            g1_root_z=float(g1_root[2]),
            g1_ur10e_distance=g1_ur10e_dist,
            surface_distance=float("inf"),  # Phase 2: no safety adapter
            mat_events=mat_events,
        )

        # ── 9. Progress ────────────────────────────────────────────────
        if step % ival == 0:
            print(f"  step {step:5d}  t={ur10e.time_step:5d}  "
                  f"{ur10e.stage_name:40s}  "
                  f"ee_z={ur10e_action[2]:.3f}  "
                  f"g1_z={g1_root[2]:.3f}  "
                  f"dist={g1_ur10e_dist:.2f}  "
                  f"events={len(mat_events)}")

        # ── 10. Termination ────────────────────────────────────────────
        metrics.policy_steps = ur10e.time_step
        metrics.parts_placed = ur10e.parts_placed

        if ur10e.success:
            print(f"\n[run] ALL PARTS PLACED at step {step}")
            break
        if terminated or truncated:
            print(f"\n[run] Episode ended at step {step}")
            break
        if g1_root[2] < -1.0:
            print(f"\n[run] G1 collapsed at step {step}")
            metrics.g1_fell = True
            break
    else:
        print(f"\n[run] Max steps ({max_steps})")

    # ── Finalise ───────────────────────────────────────────────────────
    metrics.policy_steps = ur10e.time_step
    metrics.parts_placed = ur10e.parts_placed
    writer.write(metrics)
    print(f"[run] Metrics written to {args_cli.output_csv}")
    print(f"[run] time_step={ur10e.time_step}  success={ur10e.success}  "
          f"parts={ur10e.parts_placed}/{ur10e.total_parts}")

    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
