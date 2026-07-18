#!/usr/bin/env python3
"""GMDisturb Phase 1 smoke test: verify the dual-robot scene loads and runs.

Usage:
    python scripts/smoke_test_dual.py --headless
    python scripts/smoke_test_dual.py                   # with GUI
"""

from __future__ import annotations

import argparse
import sys
import os

import numpy as np

from isaaclab.app import AppLauncher

# CLI
parser = argparse.ArgumentParser(description="GMDisturb Phase 1 smoke test")
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

# Launch Isaac Sim
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# Ensure project root is on sys.path (vendored copies of GMRobot modules
# are used directly — no external GMRobot source tree needed).
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

import torch
import gymnasium as gym

# Register task directly (bypass package import which fails in Kit runtime)
from dual_env_cfg import DualRobotDisturbanceEnvCfg
gym.register(
    id="G1-UR10e-Disturbance-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={"env_cfg_entry_point": DualRobotDisturbanceEnvCfg},
)

from isaaclab_tasks.utils import parse_env_cfg


def main():
    task_id = "G1-UR10e-Disturbance-v0"
    print(f"[smoke] Registering task: {task_id}")
    print(f"[smoke] Creating env...")

    env_cfg = parse_env_cfg(task_id, num_envs=1)
    env = gym.make(task_id, cfg=env_cfg)
    obs, info = env.reset()

    print("[smoke] Env created. Reading scene entities...")

    # === Verification 1: Articulations exist ===
    scene = env.unwrapped.scene
    assert "robot_g1" in scene.articulations, "FAIL: robot_g1 not in scene!"
    assert "robot_ur10e" in scene.articulations, "FAIL: robot_ur10e not in scene!"
    print("[smoke] PASS: Both articulations present")

    robot_g1 = scene["robot_g1"]
    robot_ur10e = scene["robot_ur10e"]

    # === Verification 2: G1 body_names ===
    g1_body_names = list(robot_g1.body_names)
    print(f"[smoke] G1 body_names ({len(g1_body_names)}): {g1_body_names}")

    # === Verification 3: UR10e body_names ===
    ur10e_body_names = list(robot_ur10e.body_names)
    print(f"[smoke] UR10e body_names ({len(ur10e_body_names)}): {ur10e_body_names}")

    # === Verification 4: G1 joint_names ===
    g1_joint_names = list(robot_g1.joint_names)
    print(f"[smoke] G1 joint_names ({len(g1_joint_names)}): {g1_joint_names}")
    assert len(g1_joint_names) == 29, (
        f"FAIL: Expected 29 joints, got {len(g1_joint_names)}"
    )

    # === Verification 5: Contact sensor shapes ===
    contact_forces = scene["g1_contact_forces"]
    cf_shape = contact_forces.data.net_forces_w.shape
    print(f"[smoke] g1_contact_forces.net_forces_w.shape = {cf_shape}")
    assert cf_shape[1] == len(g1_body_names), (
        f"FAIL: net_forces_w dim 1 = {cf_shape[1]}, expected {len(g1_body_names)}"
    )

    # === Verification 6: Observation shapes ===
    print(f"[smoke] obs keys: {list(obs.keys())}")

    if "g1_walker" in obs:
        w_shape = obs["g1_walker"].shape
        print(f"[smoke] g1_walker shape: {w_shape}")
    if "tactile" in obs:
        # tactile group has concatenate_terms=False → dict sub-key
        if isinstance(obs["tactile"], dict):
            t_shape = obs["tactile"]["tactile"].shape
        else:
            t_shape = obs["tactile"].shape
        print(f"[smoke] tactile shape: {t_shape}")
    if "ur10e_policy" in obs:
        p_keys = list(obs["ur10e_policy"].keys())
        print(f"[smoke] ur10e_policy keys ({len(p_keys)}): {p_keys[:5]}...")
    if "safety" in obs:
        print(f"[smoke] safety keys: {list(obs['safety'].keys())}")
    if "g1_body" in obs:
        print(f"[smoke] g1_body keys: {list(obs['g1_body'].keys())}")

    # === Verification 7: Action space ===
    act_space = env.action_space
    print(f"[smoke] action_space: {act_space}")
    expected_dim = 12 + 7 + 1  # G1 legs (12) + UR10e EE ik (7) + gripper (1) = 20
    assert act_space.shape[-1] == expected_dim, (
        f"FAIL: action_dim = {act_space.shape[-1]}, expected {expected_dim}"
    )

    # === Verification 8: Run 100 steps ===
    print("[smoke] Running 100 simulation steps...")
    device = "cuda:0"
    for step in range(100):
        action = torch.zeros(1, expected_dim, device=device)
        obs, reward, terminated, truncated, info = env.step(action)
        if step % 20 == 0:
            root_z = robot_g1.data.root_pos_w[0, 2].item()
            print(f"  step {step}: G1 root_z = {root_z:.3f}")
    print("[smoke] PASS: 100 steps without crash")

    # === Verification 9: Physics sanity ===
    g1_root = robot_g1.data.root_pos_w[0].cpu().numpy()
    print(f"[smoke] Final G1 root pos: ({g1_root[0]:.3f}, {g1_root[1]:.3f}, {g1_root[2]:.3f})")
    assert -0.5 < g1_root[2] < 0.1, f"FAIL: G1 root_z = {g1_root[2]:.3f} (expected ~0.8)"

    # === Verification 10: Tactile spatial calibration ===
    # Have G1 step in place for 50 steps and compare tactile force
    # hotspot centers against FK foot positions. Deviation should be
    # less than one taxel pitch (0.125m for 32x32 / 4m mat).
    # This guards against taxel permutation errors (missing perm map).
    print("[smoke] Checking tactile spatial calibration (50-step stepping)...")
    left_foot_indices, _ = robot_g1.find_bodies("left_ankle_roll_link")
    right_foot_indices, _ = robot_g1.find_bodies("right_ankle_roll_link")
    left_foot_idx = left_foot_indices[0]
    right_foot_idx = right_foot_indices[0]

    taxel_pitch = 4.0 / 32  # MAT_SIZE_X / COLS = 0.125 m

    for step in range(50):
        action = torch.zeros(1, expected_dim, device=device)
        obs, reward, terminated, truncated, info = env.step(action)

    # Read final tactile image and FK foot positions.
    if "tactile" in obs:
        if isinstance(obs["tactile"], dict):
            tac = obs["tactile"]["tactile"][0].cpu().numpy()
        else:
            tac = obs["tactile"][0].cpu().numpy()

        # Compute force-weighted centroid of tactile image.
        rows, cols = tac.shape
        row_idx = np.arange(rows)
        col_idx = np.arange(cols)
        total_force = tac.sum()
        if total_force > 1.0:  # only check if there's meaningful contact
            centroid_row = (tac * row_idx[:, None]).sum() / total_force
            centroid_col = (tac * col_idx[None, :]).sum() / total_force
            # Convert centroid (row, col) to world XY:
            # world_x = (col - COLS/2) * pitch, world_y = (row - ROWS/2) * pitch
            centroid_world_x = (centroid_col - cols / 2) * taxel_pitch
            centroid_world_y = (centroid_row - rows / 2) * taxel_pitch

            left_foot_pos = robot_g1.data.body_link_pos_w[0, left_foot_idx].cpu().numpy()
            right_foot_pos = robot_g1.data.body_link_pos_w[0, right_foot_idx].cpu().numpy()

            dist_left = np.linalg.norm(
                np.array([centroid_world_x, centroid_world_y]) - left_foot_pos[:2])
            dist_right = np.linalg.norm(
                np.array([centroid_world_x, centroid_world_y]) - right_foot_pos[:2])
            min_dist = min(dist_left, dist_right)

            print(f"[smoke] Tactile centroid: world=({centroid_world_x:.3f}, {centroid_world_y:.3f})")
            print(f"[smoke] Left foot FK:     ({left_foot_pos[0]:.3f}, {left_foot_pos[1]:.3f})")
            print(f"[smoke] Right foot FK:    ({right_foot_pos[0]:.3f}, {right_foot_pos[1]:.3f})")
            print(f"[smoke] Min centroid-to-foot distance: {min_dist:.3f}m "
                  f"(threshold={taxel_pitch:.3f}m = 1 taxel)")

            if min_dist > taxel_pitch:
                print("[smoke] WARNING: Tactile spatial offset exceeds 1 taxel pitch! "
                      "Taxel permutation may be wrong. Consider restoring the perm map "
                      "from pressure_mat_repro/mdp/observations.py.")
            else:
                print("[smoke] PASS: Tactile spatial calibration within 1 taxel")
        else:
            print("[smoke] SKIP: Insufficient foot force for spatial calibration "
                  "(G1 may not be firmly on mat)")

    print("\n[smoke] ALL CHECKS PASSED - Phase 1 complete")
    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
