# M1G 视觉验证记录（2026-07-23）

- 里程碑：`M1G`
- 结论：`M1G_VISUAL_GATE_FAIL`
- 本次是否为正式 Func-C 正样本：否（本记录仅用于 M1G 调用与视觉门禁验证）
- 是否允许进入正式 Func-C 单次重采集：否

## 一次运行证明

- 单次运行约束：已遵守（仅执行 1 次 `docker run`）
- 镜像：`gmdisturb:e01-func-c-m1e-20260723`
- 镜像完整 SHA：`sha256:3364f5165f35136ccbd93d3a7b46ca67f5e106b862c852f7167322572850feee`
- 镜像 `Config.Entrypoint`：`['/opt/projects/g1_ur10e_disturbance/docker/entrypoint.sh']`
- 镜像 `Config.Cmd`：`['phase3', '--help']`
- 实际运行入口：`/isaac-sim/python.sh`（通过 `--entrypoint` 指定）
- `meta/command.txt` 静态检查：`/isaac-sim/python.sh` 出现次数 = `1`（无重复）
- 运行命令：

```bash
docker run --rm --gpus all --network host --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 --entrypoint /isaac-sim/python.sh -e GMROBOT_V1E01_TARGET_FULL=1 -e ACCEPT_EULA=Y -e PRIVACY_CONSENT=Y -e OMNI_KIT_ACCEPT_EULA=YES -v /home/czz/GMrobot/g1_ur10e_disturbance/results:/opt/projects/g1_ur10e_disturbance/results -v /home/czz/.cache/gmdisturb-docker/kit:/isaac-sim/kit/cache -v /home/czz/.cache/gmdisturb-docker/ov:/root/.cache/ov -v /home/czz/.cache/gmdisturb-docker/pip:/root/.cache/pip -v /home/czz/.cache/gmdisturb-docker/gl:/root/.cache/nvidia -v /home/czz/.cache/gmdisturb-docker/logs:/root/.nvidia-omniverse/logs -v /home/czz/.cache/gmdisturb-docker/data:/root/.local/share/ov/data -v /home/czz/.cache/gmdisturb-docker/documents:/root/Documents gmdisturb:e01-func-c-m1e-20260723 /opt/projects/GMRobot/scripts/gm_state_machine_agent.py --task gm --headless --enable_cameras --enable_safety --safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml --save_camera --camera_output_dir /opt/projects/g1_ur10e_disturbance/results/paper_demo/m1g_visual_validation_20260723/scene --camera_save_interval 1 --max_steps 1
```

## 运行结果

- 退出码：`0`
- 耗时：`27` 秒
- stdout：`g1_ur10e_disturbance/results/paper_demo/m1g_visual_validation_20260723/meta/stdout.txt`
- stderr：`g1_ur10e_disturbance/results/paper_demo/m1g_visual_validation_20260723/meta/stderr.txt`
- 关键错误：`FileNotFoundError: USD file not found at path at: '/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_fixed.usd'.`

## 日志与安全检查

- `Traceback`：是
- `DEVICE_LOST`：否
- `nested RigidBodyAPI`：否
- 新增 Xid：无
- 运行前后信息：
  - `meta/xid_pre.txt`
  - `meta/xid_post.txt`
  - `meta/xid_diff.txt`
  - `meta/nvidia_smi_pre.txt`
  - `meta/nvidia_smi_post.txt`

## 视觉门禁逐项结论

- PNG 有效性（`480x640x3`）：失败（未生成 `frame_000000_env0.png`）
- 白色扇形消失：无法验证（无帧）
- 两个箱体尺度正常：无法验证（无帧）
- ContainerA 及 20 source parts 正常：无法验证（无帧）
- ContainerB 完整且 filled contents 清晰：无法验证（无帧）

## Frame 信息

- 路径：`g1_ur10e_disturbance/results/paper_demo/m1g_visual_validation_20260723/scene/frame_000000_env0.png`
- 是否存在：`False`
- SHA256：`None`
- Shape：`None`

## 结论说明

本次 M1G 仅一次运行，虽进程退出码为 0，但出现 `Traceback/FileNotFoundError` 且未产出门禁所需 PNG，无法完成真实场景视觉核验，故判定为 `M1G_VISUAL_GATE_FAIL`。
