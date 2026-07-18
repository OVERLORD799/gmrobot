#!/usr/bin/env python3
"""Run the unitree_rl_gym deploy_walk torchscript policy inside Isaac Lab.

Loads:
    /home/isaac/deploy_backup/unitree_rl_gym_backup/deploy/pre_train/g1/0121_walk.pt

Drives the new env:
    Isaac-Walk-G1-Deploy-Play-v0

Verifies the obs shape (expected 588 = 6 * 98), then runs the policy for
`--num_steps` steps. Optionally records a video of the sim viewport so we can
eyeball whether the gait looks natural.

Usage:
    ./isaaclab.sh -p scripts/play_deploy_walk_policy.py --num_steps 500 --headless --record_video /home/isaac/pressure_mat_video
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from omni.isaac.lab.app import AppLauncher

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

parser = argparse.ArgumentParser()
parser.add_argument("--task", type=str, default="Isaac-Walk-G1-Deploy-Play-v0")
parser.add_argument("--num_envs", type=int, default=1)
parser.add_argument("--num_steps", type=int, default=500)
parser.add_argument(
    "--policy",
    type=str,
    default="/home/isaac/deploy_backup/unitree_rl_gym_backup/deploy/pre_train/g1/0121_walk.pt",
)
parser.add_argument("--cmd_vx", type=float, default=0.5)
parser.add_argument("--cmd_vy", type=float, default=0.0)
parser.add_argument("--cmd_wz", type=float, default=0.0)
parser.add_argument(
    "--cmd_seq", type=str, default=None,
    help='Semicolon-separated command list, "vx,vy,wz;vx,vy,wz;...". '
         'Each cmd is held for `--steps_per_cmd` env steps. Overrides --cmd_*.',
)
parser.add_argument("--steps_per_cmd", type=int, default=100)
parser.add_argument("--init_x", type=float, default=None,
                    help="If set, override the robot reset x-position.")
parser.add_argument("--init_y", type=float, default=None,
                    help="If set, override the robot reset y-position.")
parser.add_argument("--disable_out_of_mat", action="store_true",
                    help="Remove the out_of_mat termination (lets robot walk anywhere).")
parser.add_argument("--episode_length_s", type=float, default=None,
                    help="If set, override env episode length (sec). Long values "
                         "let us see steady-state gait without reset-transient bias.")
parser.add_argument("--side_by_side_tactile", action="store_true",
                    help="After recording, compose a side-by-side video: sim "
                         "viewport on the left, tactile heatmap on the right.")
parser.add_argument("--record_video", type=str, default=None,
                    help="If set, output video folder.")
parser.add_argument("--video_length", type=int, default=None)
parser.add_argument("--video_fps", type=int, default=30)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

if args.record_video is not None:
    args.enable_cameras = True

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

# isaac sim-dependent imports below
import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402

import omni.isaac.lab_tasks  # noqa: F401, E402  ← triggers gym.register
from omni.isaac.lab_tasks.utils import parse_env_cfg  # noqa: E402


def main():
    # ---- Build env ----
    env_cfg = parse_env_cfg(args.task, num_envs=args.num_envs)

    # Optional overrides for off-mat / no-mat-bound testing.
    if args.init_x is not None or args.init_y is not None:
        x = args.init_x if args.init_x is not None else 0.0
        y = args.init_y if args.init_y is not None else 0.0
        # Pressure-mat env: reset_base uses pose_range; pin to a single point.
        if hasattr(env_cfg.events, "reset_base"):
            env_cfg.events.reset_base.params["pose_range"] = {
                "x": (x, x), "y": (y, y), "yaw": (0.0, 0.0),
            }
        print(f"[play] reset pos override: x={x}, y={y}", flush=True)
    if args.disable_out_of_mat:
        if hasattr(env_cfg.terminations, "out_of_mat"):
            env_cfg.terminations.out_of_mat = None
            print("[play] disabled out_of_mat termination", flush=True)
    if args.episode_length_s is not None:
        env_cfg.episode_length_s = args.episode_length_s
        print(f"[play] episode_length_s = {args.episode_length_s}", flush=True)

    render_mode = "rgb_array" if args.record_video is not None else None
    env = gym.make(args.task, cfg=env_cfg, render_mode=render_mode)

    # Determine total step count up-front so RecordVideo gets the right length.
    if args.cmd_seq is not None:
        n_cmds = len([c for c in args.cmd_seq.split(";") if c.strip()])
        planned_total = n_cmds * args.steps_per_cmd
    else:
        planned_total = args.num_steps

    if args.record_video is not None:
        os.makedirs(args.record_video, exist_ok=True)
        env = gym.wrappers.RecordVideo(
            env,
            video_folder=args.record_video,
            step_trigger=lambda step: step == 0,
            video_length=args.video_length or planned_total,
            disable_logger=True,
            name_prefix=f"deploy_walk_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        print(f"[play] recording sim to {args.record_video}", flush=True)

    # Joint-order sanity check — must match deploy yaml's `isaaclab_joint` list.
    expected_joint_order = [
        "left_hip_pitch_joint", "right_hip_pitch_joint", "waist_yaw_joint",
        "left_hip_roll_joint", "right_hip_roll_joint", "waist_roll_joint",
        "left_hip_yaw_joint", "right_hip_yaw_joint", "waist_pitch_joint",
        "left_knee_joint", "right_knee_joint",
        "left_shoulder_pitch_joint", "right_shoulder_pitch_joint",
        "left_ankle_pitch_joint", "right_ankle_pitch_joint",
        "left_shoulder_roll_joint", "right_shoulder_roll_joint",
        "left_ankle_roll_joint", "right_ankle_roll_joint",
        "left_shoulder_yaw_joint", "right_shoulder_yaw_joint",
        "left_elbow_joint", "right_elbow_joint",
        "left_wrist_roll_joint", "right_wrist_roll_joint",
        "left_wrist_pitch_joint", "right_wrist_pitch_joint",
        "left_wrist_yaw_joint", "right_wrist_yaw_joint",
    ]
    actual = list(env.unwrapped.scene["robot"].joint_names)
    if actual != expected_joint_order:
        print("[play] WARNING: joint order mismatch!", flush=True)
        for i, (a, e) in enumerate(zip(actual, expected_joint_order)):
            if a != e:
                print(f"  slot {i}: got {a!r} expected {e!r}", flush=True)

    obs_dict, _ = env.reset()
    # The walker observation key differs between envs:
    #   - standalone walking env: obs_dict["policy"]  (walker is the only group)
    #   - pressure-mat env:       obs_dict["walker"]  (policy = tactile)
    walker_key = "walker" if "walker" in obs_dict else "policy"
    obs = obs_dict[walker_key]
    print(f"[play] walker obs key='{walker_key}' shape={tuple(obs.shape)}  "
          f"(expected (N, 588))", flush=True)
    assert obs.shape[-1] == 588, (
        f"obs shape mismatch: got {obs.shape[-1]}, expected 588 "
        "(6 history * 98 per-step)"
    )

    # ---- Load policy ----
    device = env.unwrapped.device
    policy = torch.jit.load(args.policy, map_location=device).eval()
    print(f"[play] loaded policy: {args.policy}", flush=True)

    # ---- Build command schedule ----
    # If --cmd_seq is given, parse a list of (vx, vy, wz) tuples; otherwise use
    # the single --cmd_* triple for the whole run.
    if args.cmd_seq is not None:
        cmd_list = []
        for chunk in args.cmd_seq.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            vx, vy, wz = (float(x) for x in chunk.split(","))
            cmd_list.append((vx, vy, wz))
        total_steps = len(cmd_list) * args.steps_per_cmd
        print(f"[play] cmd schedule: {cmd_list}  ({args.steps_per_cmd} steps each, "
              f"total {total_steps})", flush=True)
    else:
        cmd_list = [(args.cmd_vx, args.cmd_vy, args.cmd_wz)]
        total_steps = args.num_steps
        print(f"[play] single cmd: {cmd_list[0]}  ({total_steps} steps)", flush=True)

    vel_term = env.unwrapped.command_manager.get_term("base_velocity")

    def set_cmd(vxvywz):
        t = torch.tensor([vxvywz], device=device, dtype=torch.float32).repeat(args.num_envs, 1)
        vel_term.vel_command_b[:] = t
        return t

    # ---- Run policy ----
    tactile_frames: list[np.ndarray] = []
    record_tactile = args.side_by_side_tactile and "policy" in obs_dict and isinstance(obs_dict["policy"], dict)
    for step in range(total_steps):
        if args.cmd_seq is not None:
            cmd_idx = min(step // args.steps_per_cmd, len(cmd_list) - 1)
        else:
            cmd_idx = 0
        set_cmd(cmd_list[cmd_idx])

        with torch.no_grad():
            action = policy(obs).clip(min=-100.0, max=100.0)

        obs_dict, _, terminated, truncated, _ = env.step(action)
        obs = obs_dict[walker_key]

        if record_tactile and "tactile" in obs_dict["policy"]:
            tactile_frames.append(obs_dict["policy"]["tactile"][0].detach().cpu().numpy())

        if step % 25 == 0:
            done = (terminated | truncated)
            try:
                robot = env.unwrapped.scene["robot"]
                root_w = robot.data.root_pos_w[0]
                origin = env.unwrapped.scene.env_origins[0]
                local_x = float((root_w[0] - origin[0]).item())
                local_y = float((root_w[1] - origin[1]).item())
                pos_str = f"x={local_x:+.2f} y={local_y:+.2f}"
            except Exception:
                pos_str = "x=?"
            print(f"step {step:4d}  cmd={cmd_list[cmd_idx]}  "
                  f"{pos_str}  "
                  f"action_max={action.abs().max().item():.3f}  "
                  f"any_done={bool(done.any().item())}", flush=True)

    print(f"[play] finished {total_steps} steps", flush=True)
    env.close()

    # ---- Compose side-by-side sim + tactile video ----
    if args.side_by_side_tactile and args.record_video and tactile_frames:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import imageio.v2 as imageio
            import os as _os

            # Find the recorded sim mp4 (RecordVideo saves it inside record_video).
            sim_mp4s = sorted([
                f for f in _os.listdir(args.record_video)
                if f.startswith("deploy_walk_") and f.endswith(".mp4")
            ])
            if not sim_mp4s:
                print("[play] no sim mp4 found for side-by-side", flush=True)
            else:
                sim_path = _os.path.join(args.record_video, sim_mp4s[-1])
                print(f"[play] composing side-by-side from {sim_path}", flush=True)
                sim_reader = imageio.get_reader(sim_path)
                sim_h, sim_w = sim_reader.get_data(0).shape[:2]
                sim_count = sim_reader.count_frames()

                # Render each tactile frame to an RGB image of size (sim_h, sim_h)
                # so the composite is square-friendly. Compute vmax from the
                # NON-ZERO cells only — averaging in the ~99% empty cells of a
                # 32x32 tactile image collapses any percentile to ~0.
                _stack = np.stack(tactile_frames)
                _active = _stack[_stack > 0.05]
                if _active.size > 0:
                    vmax = float(np.percentile(_active, 95))
                else:
                    vmax = 1.0
                vmax = max(vmax, 1.0)
                rendered = []
                dpi = 100
                for arr in tactile_frames:
                    fig, ax = plt.subplots(
                        figsize=(sim_h / dpi, sim_h / dpi), dpi=dpi, facecolor="black"
                    )
                    ax.imshow(arr, origin="lower", cmap="hot", vmin=0, vmax=vmax,
                              interpolation="nearest")
                    ax.set_title(f"Tactile (max {vmax:.0f} N)", color="white")
                    ax.set_xticks([]); ax.set_yticks([])
                    fig.tight_layout()
                    fig.canvas.draw()
                    rgba = np.asarray(fig.canvas.buffer_rgba())
                    rendered.append(rgba[..., :3].copy())
                    plt.close(fig)

                # Map sim frames to tactile frames (sim is rendered every
                # render_interval steps; just resample evenly).
                idxs = np.linspace(0, len(rendered) - 1, sim_count).astype(np.int64)

                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = _os.path.join(args.record_video,
                                         f"sxs_tactile_{ts}.mp4")
                writer = imageio.get_writer(out_path, fps=args.video_fps,
                                            codec="libx264", quality=7)
                for i, sim_frame in enumerate(sim_reader):
                    tac = rendered[idxs[i]]
                    if tac.shape[0] != sim_h:
                        # quick resize via matplotlib if needed
                        from PIL import Image
                        tac = np.asarray(Image.fromarray(tac).resize((sim_h, sim_h)))
                    composite = np.concatenate([sim_frame, tac], axis=1)
                    if composite.shape[0] % 2:
                        composite = composite[:-1]
                    if composite.shape[1] % 2:
                        composite = composite[:, :-1]
                    writer.append_data(composite)
                writer.close()
                sim_reader.close()
                print(f"[play] saved side-by-side to {out_path}", flush=True)
        except Exception as exc:
            print(f"[play] side-by-side compose failed: {exc}", flush=True)
            import traceback as _tb
            _tb.print_exc()


if __name__ == "__main__":
    main()
    simulation_app.close()
