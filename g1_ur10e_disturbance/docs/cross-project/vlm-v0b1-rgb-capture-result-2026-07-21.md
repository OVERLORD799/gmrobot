# V0-B1 路径 A：scene RGB 短采集结果（2026-07-21）

## 结论

**Artifact 门禁：PASS**  
**P0-7：`closed_for_scene_camera_replay`**

不声称：G1 head camera 已验证；模型推理已验证。未进入 V0-B2。

---

## 执行摘要

| 项 | 值 |
|---|---|
| 镜像 tag | `gmdisturb:b4-p010-20260721` |
| 镜像 SHA | `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68` |
| 是否重建镜像 | 否 |
| capture exit code | `0` |
| 耗时 | ~36 s |
| 帧数 | 8（3–10 合格） |
| 分辨率 | 480×640×3 |
| dtype（盘上 PNG） | `uint8` |
| camera_name | `scene_camera` |
| 唯一 SHA-256 | 8 / 8（帧间 hash 全部不同） |
| min 范围 | 0.0 – 0.0 |
| max 范围 | 247.0 – 248.0 |
| mean 范围 | ~83.41 – ~91.07 |
| nonzero_ratio 范围 | ~0.9981 – ~0.9999 |
| 网络 / endpoint / 凭据 / 模型下载 | **无** |
| 冻结 B0–B4 资产修改 | **无** |

---

## 命令（已执行一次）

```bash
TAG=gmdisturb:b4-p010-20260721 \
RESULTS_DIR=/home/czz/GMrobot/g1_ur10e_disturbance/results \
./run.sh python /opt/projects/GMRobot/scripts/gm_state_machine_agent.py \
  --task=gm \
  --headless \
  --enable_cameras \
  --num_envs=1 \
  --max_steps=80 \
  --save_camera \
  --camera_output_dir=/opt/projects/g1_ur10e_disturbance/results/paper_demo/v0b1_rgb_capture_20260721/scene \
  --camera_save_interval=10 \
  --progress_interval=10
```

未传：`--enable_safety` / `--enable_vlm` / `--enable_perception` / `--enable_five_stage_shadow`。

---

## 产物路径

```text
g1_ur10e_disturbance/results/paper_demo/v0b1_rgb_capture_20260721/
  scene/frame_000000_env0.png … frame_000070_env0.png   # 8 帧
  manifest/artifacts.jsonl
  manifest/capture_summary.json
  capture_exit_code.txt          # 0
  capture_elapsed_sec.txt        # 36
  capture.log                    # 宿主机 tee 初失败备注（见下）
```

文档：

- 本文件：`docs/cross-project/vlm-v0b1-rgb-capture-result-2026-07-21.md`
- 预检：`docs/cross-project/vlm-v0b1-rgb-capture-preflight-2026-07-21.md`

---

## dtype 说明

Gym 观测空间将 `camera/scene_rgb` 声明为 `float32`。  
`save_camera_frames` 通过 `Image.fromarray(...).save(...)` 写出 PNG；盘上解码为 **uint8 H×W×3**。采集后未做额外 rescale。

---

## 门禁核对

1. PNG 数量 8 ∈ [3,10] — PASS
2. 均可解码 — PASS
3. shape H×W×3 — PASS
4. dtype uint8（盘上）— PASS（转换见上）
5. 非全黑 / 非全白 — PASS
6. nonzero_ratio > 0.01 — PASS
7. SHA-256 不全相同 — PASS（8 个互异）
8–10. manifest 字段 / image_id / camera_name — PASS  
11. 非随机/占位 — PASS（Isaac 仿真写出）

---

## 操作备注

- 宿主机首次 `mkdir`/`tee` 因 `results/paper_demo` 为 root 属主失败；容器以 root 创建输出目录并成功写帧；之后用 `docker run alpine chown` 将目录交还用户 `czz`，再写 manifest。
- **仅运行一次**；未调参、未重跑。
- 未连接 VLM/perception endpoint；未读 `.github_token`；未下载模型。

---

## P0-7 范围

`closed_for_scene_camera_replay`：仅 scene camera 真实 RGB artifact，可供五阶段离线回放使用。  
**不含** G1 head camera；**不含** 真实模型推理（P0-8 仍开）。
