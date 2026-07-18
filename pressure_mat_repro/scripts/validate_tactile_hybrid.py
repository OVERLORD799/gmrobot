#!/usr/bin/env python3
"""Validate the hybrid sequence-based velocity model live in sim.

Side-by-side video: sim viewport on the left, real-vs-predicted velocity plot
on the right. Uses:
  - PressureMat-Walk-G1-Deploy-v0 env (32x32 tactile, 4 m mat)
  - deploy_walk torchscript walking policy
  - SequentialTactileHybridRegressor velocity model (with weights from
    intelligentCarpet/.../g1_walk_deploy_v1_seqhybrid_..._best.path.tar)
"""
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
parser.add_argument("--task", type=str, default="PressureMat-Walk-G1-Deploy-v0")
parser.add_argument("--num_envs", type=int, default=1)
parser.add_argument("--num_steps", type=int, default=500)
parser.add_argument("--save_every_n", type=int, default=5,
                    help="Save+predict every Nth env step. 50 Hz / 5 = 10 Hz "
                         "matches the training data rate.")
parser.add_argument("--ckpt", type=str, required=True,
                    help="Hybrid velocity model checkpoint (.path.tar).")
parser.add_argument("--policy", type=str,
                    default="/home/isaac/deploy_backup/unitree_rl_gym_backup/deploy/pre_train/g1/0121_walk.pt",
                    help="Deploy_walk torchscript policy.")
parser.add_argument("--record_video", type=str, default=None,
                    help="Output video folder.")
parser.add_argument("--video_fps", type=int, default=30)
parser.add_argument("--position_scale", type=float, default=1.0)
parser.add_argument("--velocity_norm", type=float, default=1.0)
parser.add_argument("--head_idx", type=int, default=0)
parser.add_argument("--anchor_idx", type=int, default=8)
parser.add_argument("--lookahead", type=int, default=4,
                    help="Future-frame lookahead the hybrid model expects. "
                         "Predictions for the most recent `lookahead` frames "
                         "use sticky-edge padding (degraded accuracy) — the "
                         "reported prediction is taken `lookahead` frames "
                         "behind the latest collected frame for a clean comparison.")
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

if args.record_video is not None:
    args.enable_cameras = True

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

import omni.isaac.lab_tasks  # noqa: F401, E402


# ---------------------------------------------------------------------------
# Re-define the hybrid model here so the validate script doesn't depend on the
# p36 conda env / intelligentCarpet on PYTHONPATH.
# ---------------------------------------------------------------------------
class SequentialTactileHybridRegressor(nn.Module):
    def __init__(self, local_window=1, lookahead=4, cnn_feat=1024,
                 gru_hidden=256, num_gru_layers=1, dropout=0.2):
        super().__init__()
        self.local_window = int(local_window)
        self.lookahead = int(lookahead)
        in_ch = 2 * self.local_window + 1
        self.cnn = nn.Sequential(
            nn.Conv2d(in_ch, 32, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(32),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(64), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(128),
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(256), nn.MaxPool2d(2),
            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(512),
            nn.Conv2d(512, 1024, kernel_size=5),
            nn.LeakyReLU(), nn.BatchNorm2d(1024),
            nn.Conv2d(1024, cnn_feat, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(cnn_feat), nn.MaxPool2d(2),
            nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten(),
        )
        self.gru = nn.GRU(
            input_size=(self.lookahead + 1) * cnn_feat,
            hidden_size=gru_hidden, num_layers=num_gru_layers,
            batch_first=True,
            dropout=dropout if num_gru_layers > 1 else 0.0,
            bidirectional=False,
        )
        self.head = nn.Sequential(
            nn.Linear(gru_hidden, 128), nn.LeakyReLU(), nn.Dropout(p=dropout),
            nn.Linear(128, 3),
        )

    @staticmethod
    def _shift_dim1_clamp(x, k):
        if k == 0:
            return x
        if k > 0:
            pad = x[:, -1:].expand(-1, k, *([-1] * (x.dim() - 2)))
            return torch.cat([x[:, k:], pad], dim=1)
        kk = -k
        pad = x[:, :1].expand(-1, kk, *([-1] * (x.dim() - 2)))
        return torch.cat([pad, x[:, :-kk]], dim=1)

    def forward(self, x):
        B, T, H, W = x.shape
        local = [self._shift_dim1_clamp(x, k)
                 for k in range(-self.local_window, self.local_window + 1)]
        local_stack = torch.stack(local, dim=2)
        in_ch = local_stack.shape[2]
        cnn_in = local_stack.reshape(B * T, in_ch, H, W)
        feat = self.cnn(cnn_in).reshape(B, T, -1)
        shifted = [self._shift_dim1_clamp(feat, k)
                   for k in range(self.lookahead + 1)]
        gru_in = torch.cat(shifted, dim=-1)
        seq, _ = self.gru(gru_in)
        out = self.head(seq.reshape(B * T, -1))
        return out.reshape(B, T, 3)


def _plot_to_rgb(time_s, real_vel, pred_vel, target_hw):
    """3-panel plot of vx/vy/vz, real vs predicted."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    target_h, target_w = target_hw
    dpi = 100
    fig, axes = plt.subplots(3, 1, figsize=(target_w / dpi, target_h / dpi),
                              dpi=dpi, facecolor="black", sharex=True)
    axis_names = ["vx", "vy", "vz"]
    for ax, name, i_ax in zip(axes, axis_names, range(3)):
        ax.set_facecolor("black")
        for spine in ax.spines.values():
            spine.set_color("white")
        ax.tick_params(colors="white", labelsize=8)
        ax.set_ylabel(f"{name} (m/s)", color="white", fontsize=9)
        ax.grid(True, alpha=0.2, color="gray")
        if len(time_s) > 0:
            ax.plot(time_s, real_vel[:, i_ax], color="#00c8ff", linewidth=1.5, label="real")
            ax.plot(time_s, pred_vel[:, i_ax], color="#ff4040", linewidth=1.5,
                    linestyle="--", label="pred (hybrid)")
        ax.set_ylim(-1.2, 1.2)
        if i_ax == 0:
            ax.legend(loc="upper right", facecolor="black",
                      edgecolor="white", labelcolor="white", fontsize=8)
    axes[-1].set_xlabel("time (s)", color="white", fontsize=9)
    plt.tight_layout()
    fig.canvas.draw()
    rgba = np.asarray(fig.canvas.buffer_rgba())
    plt.close(fig)
    return rgba[..., :3].copy()


def _compose_side_by_side(sim_mp4, plot_frames, out_mp4, fps):
    import imageio.v2 as imageio
    reader = imageio.get_reader(sim_mp4)
    sim_frames = [f for f in reader]
    reader.close()
    if not sim_frames:
        raise RuntimeError(f"no frames in {sim_mp4}")
    sim_h, sim_w = sim_frames[0].shape[:2]
    indices = np.linspace(0, len(plot_frames) - 1, len(sim_frames)).astype(np.int64)
    writer = imageio.get_writer(out_mp4, fps=fps, codec="libx264", quality=7)
    try:
        for sim_frame, plot_idx in zip(sim_frames, indices):
            plot_rgb = plot_frames[plot_idx]
            composite = np.concatenate([sim_frame, plot_rgb], axis=1)
            if composite.shape[0] % 2:
                composite = composite[:-1]
            if composite.shape[1] % 2:
                composite = composite[:, :-1]
            writer.append_data(composite)
    finally:
        writer.close()
    return out_mp4


def main():
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    # ---- Load hybrid velocity model ----
    model = SequentialTactileHybridRegressor().to(device)
    ckpt = torch.load(args.ckpt, map_location=device)
    state = ckpt.get("model_state_dict",
                     ckpt.get("state_dict",
                              ckpt.get("model", ckpt)))
    state = {k.replace("module.", ""): v for k, v in state.items()}
    model.load_state_dict(state)
    model.eval()
    print(f"[validate] loaded velocity model from {args.ckpt}", flush=True)

    # ---- Build env ----
    from omni.isaac.lab_tasks.utils import parse_env_cfg
    env_cfg = parse_env_cfg(args.task, num_envs=args.num_envs)
    env_cfg.viewer.eye = (-4.0, 4.0, 3.0)
    env_cfg.viewer.lookat = (0.0, 0.0, 0.5)
    render_mode = "rgb_array" if args.record_video else None
    env = gym.make(args.task, cfg=env_cfg, render_mode=render_mode)

    if args.record_video is not None:
        os.makedirs(args.record_video, exist_ok=True)
        sim_video_dir = os.path.join(args.record_video, "sim")
        os.makedirs(sim_video_dir, exist_ok=True)
        env = gym.wrappers.RecordVideo(
            env, video_folder=sim_video_dir, step_trigger=lambda step: step == 0,
            video_length=args.num_steps, disable_logger=True, name_prefix="sim_viewport_hybrid")
        print(f"[validate] recording sim to {sim_video_dir}", flush=True)

    obs, _ = env.reset()
    robot = env.unwrapped.scene["robot"]
    dev = env.unwrapped.device

    # ---- Load deploy_walk torchscript walking policy ----
    walk_policy = torch.jit.load(args.policy, map_location=device).eval()
    print(f"[validate] loaded walking policy: {args.policy}", flush=True)

    dt = args.save_every_n * env_cfg.sim.dt * env_cfg.decimation  # save period
    print(f"[validate] save dt = {dt:.3f} s ({1/dt:.0f} Hz)", flush=True)

    # Per-episode buffers (cleared on reset)
    tactile_buf: list[np.ndarray] = []   # (32, 32) per save-step
    com_buf: list[np.ndarray] = []       # (3,) per save-step
    # Output streams (across all episodes)
    times_out: list[float] = []
    real_vels_out: list[np.ndarray] = []
    pred_vels_out: list[np.ndarray] = []
    plot_frames: list[np.ndarray] = []

    LOOK = args.lookahead  # report prediction LOOK frames behind the latest

    for step in range(args.num_steps):
        walker_obs = obs["walker"]
        with torch.no_grad():
            action = walk_policy(walker_obs).clip(min=-100.0, max=100.0)
        obs, _, terminated, truncated, _ = env.step(action)

        # Reset per-episode buffers on env-0 termination/truncation.
        env0_done = bool((terminated[0] | truncated[0]).item())
        if env0_done:
            tactile_buf.clear()
            com_buf.clear()

        if step % args.save_every_n == 0:
            tac = obs["policy"]["tactile"][0].detach().cpu().numpy()  # (32, 32)
            com_world = robot.data.root_pos_w[0].detach().cpu().numpy()
            origin = env.unwrapped.scene.env_origins[0].detach().cpu().numpy()
            com_local = com_world - origin

            tactile_buf.append(tac.astype(np.float32))
            com_buf.append(com_local.astype(np.float32))

            # Need at least 2 frames to compute real velocity.
            # For the prediction we want LOOK frames of "future" beyond the
            # query, so we produce a delayed prediction at index t-LOOK once
            # the buffer has > LOOK + 1 frames.
            if len(tactile_buf) >= LOOK + 2:
                # ---- Run model on the entire episode buffer so far ----
                seq = torch.from_numpy(np.stack(tactile_buf, axis=0)).unsqueeze(0).to(device)
                with torch.no_grad():
                    pred_seq = model(seq)[0].cpu().numpy() * args.velocity_norm  # (T, 3)
                # Use prediction at index `len-1-LOOK` (LOOK frames lag for clean lookahead)
                idx = len(tactile_buf) - 1 - LOOK
                pred = pred_seq[idx]
                # Real velocity at the SAME idx via centered finite-diff
                if 1 <= idx < len(com_buf) - 1:
                    com_a = com_buf[idx - 1] * args.position_scale
                    com_b = com_buf[idx + 1] * args.position_scale
                    real = (com_b - com_a) / (2.0 * dt)
                else:
                    real = np.zeros(3, dtype=np.float32)

                # Append to output stream — time = (step // save_every_n - LOOK) * dt
                t_out = (step // args.save_every_n - LOOK) * dt
                times_out.append(float(t_out))
                real_vels_out.append(real)
                pred_vels_out.append(pred)

        if args.record_video is not None and step % args.save_every_n == 0:
            time_arr = np.array(times_out, dtype=np.float32)
            real_arr = np.array(real_vels_out, dtype=np.float32).reshape(-1, 3) if real_vels_out else np.zeros((0, 3))
            pred_arr = np.array(pred_vels_out, dtype=np.float32).reshape(-1, 3) if pred_vels_out else np.zeros((0, 3))
            plot_rgb = _plot_to_rgb(time_arr, real_arr, pred_arr, target_hw=(540, 540))
            plot_frames.append(plot_rgb)

        if step % 50 == 0 and times_out:
            print(f"step {step:4d}  t={times_out[-1]:.2f}s  "
                  f"real=[{real_vels_out[-1][0]:+.2f},{real_vels_out[-1][1]:+.2f},{real_vels_out[-1][2]:+.2f}]"
                  f"  pred=[{pred_vels_out[-1][0]:+.2f},{pred_vels_out[-1][1]:+.2f},{pred_vels_out[-1][2]:+.2f}]",
                  flush=True)

    print(f"[validate] finished {args.num_steps} steps, {len(times_out)} predictions",
          flush=True)
    env.close()

    # ---- Metrics ----
    if real_vels_out:
        real_arr = np.array(real_vels_out, dtype=np.float32)
        pred_arr = np.array(pred_vels_out, dtype=np.float32)
        mae = np.mean(np.abs(real_arr - pred_arr), axis=0)
        speed_mae = np.mean(np.abs(np.linalg.norm(real_arr, axis=1) -
                                    np.linalg.norm(pred_arr, axis=1)))
        print(f"[validate] MAE xyz = [{mae[0]:.3f}, {mae[1]:.3f}, {mae[2]:.3f}] m/s",
              flush=True)
        print(f"[validate] Speed MAE = {speed_mae:.3f} m/s", flush=True)

    # ---- Compose side-by-side ----
    if args.record_video is not None and plot_frames:
        try:
            sim_video_dir = os.path.join(args.record_video, "sim")
            sim_mp4s = sorted([f for f in os.listdir(sim_video_dir) if f.endswith(".mp4")])
            if sim_mp4s:
                import imageio.v2 as imageio
                reader = imageio.get_reader(os.path.join(sim_video_dir, sim_mp4s[-1]))
                sim_h = reader.get_data(0).shape[0]
                reader.close()
                plot_frames_sized = []
                for i in range(len(plot_frames)):
                    idx = int(i * len(times_out) / max(len(plot_frames), 1))
                    idx = min(idx, len(times_out))
                    time_arr = np.array(times_out[:idx + 1], dtype=np.float32)
                    real_arr = np.array(real_vels_out[:idx + 1], dtype=np.float32).reshape(-1, 3)
                    pred_arr = np.array(pred_vels_out[:idx + 1], dtype=np.float32).reshape(-1, 3)
                    plot_frames_sized.append(_plot_to_rgb(time_arr, real_arr, pred_arr,
                                                          target_hw=(sim_h, sim_h)))
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                out_mp4 = os.path.join(args.record_video, f"validate_hybrid_{ts}.mp4")
                _compose_side_by_side(os.path.join(sim_video_dir, sim_mp4s[-1]),
                                       plot_frames_sized, out_mp4, args.video_fps)
                print(f"[validate] saved video to {out_mp4}", flush=True)
        except Exception as exc:
            print(f"[validate] video composition failed: {exc}", flush=True)
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
    simulation_app.close()
