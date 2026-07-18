"""Verify camera sensor produces valid RGB output."""

import argparse
import os

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Verify GMRobot scene camera output.")
parser.add_argument("--task", type=str, default="gm")
parser.add_argument("--num_envs", type=int, default=1)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import gymnasium as gym
import numpy as np
from PIL import Image

import GMRobot.tasks  # noqa: F401
import isaaclab_tasks  # noqa: F401
from isaaclab_tasks.utils import parse_env_cfg


def _to_numpy(tensor) -> np.ndarray:
    if hasattr(tensor, "detach"):
        tensor = tensor.detach().cpu().numpy()
    return np.asarray(tensor)


def test_camera_output(env):
    """验证相机 RGB 输出的形状、类型和内容非空。"""
    obs, _ = env.reset()

    rgb = _to_numpy(obs["camera"]["scene_rgb"])
    num_envs = env.unwrapped.num_envs

    assert rgb.shape == (num_envs, 480, 640, 3), \
        f"Expected ({num_envs}, 480, 640, 3), got {rgb.shape}"

    assert rgb.dtype == np.uint8, f"Expected uint8, got {rgb.dtype}"

    assert rgb.max() > 0, "Camera output is all zeros — rendering may be broken"

    print(f"[PASS] Camera RGB: shape={rgb.shape}, dtype={rgb.dtype}, "
          f"range=[{rgb.min()}, {rgb.max()}]")


def dump_camera_frame(env, output_path="/tmp/camera_dump.png"):
    """将第一帧相机输出保存为 PNG 供人工检查。"""
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        for name in os.listdir(output_dir):
            if name.endswith(".png"):
                os.remove(os.path.join(output_dir, name))

    obs, _ = env.reset()
    rgb = _to_numpy(obs["camera"]["scene_rgb"][0])
    img = Image.fromarray(rgb)
    img.save(output_path)
    print(f"[INFO] Camera frame saved to {output_path}")


def main():
    env_cfg = parse_env_cfg(
        args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs
    )
    env = gym.make(args_cli.task, cfg=env_cfg)
    try:
        test_camera_output(env)
        dump_camera_frame(env)
    finally:
        env.close()
        simulation_app.close()


if __name__ == "__main__":
    main()
