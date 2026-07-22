# V0-B1 真实 RGB artifact 采集预检（2026-07-21）

## 状态

**仅预检与命令设计。未启动 Isaac，未采集，未连接 endpoint，未读凭据，未改冻结基准。**

等待人工批准后，再执行短采集。

---

## 1. 现有入口只读结论

| 入口 | 相机 | 落盘 | 适合 V0-B1？ |
|---|---|---|---|
| `GMRobot/scripts/gm_state_machine_agent.py` `--save_camera` | 仅 `obs["camera"]["scene_rgb"]`（640×480） | 已有 PNG 导出 | **是（零改代码，立即可跑）** |
| `GMRobot/scripts/test_camera.py` | 仅 scene | 只 dump **1** 帧 | 帧数不足（除非改脚本） |
| `g1_ur10e_disturbance/scripts/run_phase3.py` | 读取 `ur10e_camera.scene_rgb` + `g1_head_camera.head_rgb` | **无** PNG 保存 | 双相机有观测，缺落盘钩子 |
| `dual_env_cfg.py` | scene 640×480；head 320×240 | 配置已接线 | 双相机来源 |
| `docker/run.sh` + `gmdisturb:b4-p010-20260721` | — | `results/` bind-mount | 复用冻结镜像，**无需重建** |

证据：

- `gm_state_machine_agent.py:415–425`：`save_camera_frames` 只写 `camera/scene_rgb`
- `dual_env_cfg.py:385–422`：双相机定义；`618–621`：观测组 `ur10e_camera` / `g1_head_camera`
- `run_phase3.py:1390–1451`：读取双相机，但不写盘
- 冻结镜像内已含：`/opt/projects/GMRobot/scripts/gm_state_machine_agent.py` 与 `run_phase3.py`

---

## 2. 推荐采集路径

### 路径 A（推荐先跑）：GMRobot scene-only，零代码变更

- 镜像：`gmdisturb:b4-p010-20260721`（**不重建**）
- 入口：镜像内已有 `gm_state_machine_agent.py`
- 关闭：VLM / perception / five-stage shadow / safety / replan（均默认关）
- 不改任何冻结 YAML
- **限制**：只有 scene camera，无 G1 head

### 路径 B（双相机，需二次批准小脚本）：GMDisturb dual_env

- 同样冻结镜像，**bind-mount** 新增 `capture_rgb_v0b1.py`（不 bake、不重建镜像）
- 保存 `ur10e_camera/scene_rgb` + `g1_head_camera/head_rgb`
- 本预检**不创建该脚本**；批准路径 B 后再实现并采集

**建议顺序**：先批准路径 A 拿到有效 scene artifact 与门禁流程；需要 head 视角时再批准路径 B。

---

## 3. 精确命令（路径 A — 待批准后执行）

```bash
# Host prep
REPO=/home/czz/GMrobot
OUT_HOST="${REPO}/g1_ur10e_disturbance/results/paper_demo/v0b1_rgb_capture_20260721"
mkdir -p "${OUT_HOST}/scene" "${OUT_HOST}/manifest"

cd "${REPO}/g1_ur10e_disturbance/docker"

# Verify frozen image (do not rebuild)
docker image inspect gmdisturb:b4-p010-20260721 --format '{{.Id}}'
# expect: sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68

TAG=gmdisturb:b4-p010-20260721 \
RESULTS_DIR="${REPO}/g1_ur10e_disturbance/results" \
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

说明：

- `--max_steps=80` ≤ 100；`--camera_save_interval=10` → 约 **8–9** 帧（step 0 及 10…70，视 reset 额外帧而定），落在 3–10 目标内。
- 不传 `--enable_vlm` / `--enable_perception` / `--enable_five_stage_shadow` / `--enable_safety`。
- 产物经 `RESULTS_DIR` bind-mount 落在宿主机 `OUT_HOST`。

### 路径 B 命令草案（脚本尚未添加；批准后）

```bash
# AFTER approving a new host script scripts/capture_rgb_v0b1.py (not yet created)
TAG=gmdisturb:b4-p010-20260721 \
RESULTS_DIR="${REPO}/g1_ur10e_disturbance/results" \
DOCKER_EXTRA_ARGS="-v ${REPO}/g1_ur10e_disturbance/scripts/capture_rgb_v0b1.py:/tmp/capture_rgb_v0b1.py:ro" \
./run.sh python /tmp/capture_rgb_v0b1.py \
  --headless \
  --max_steps=50 \
  --save_interval=10 \
  --output_dir=/opt/projects/g1_ur10e_disturbance/results/paper_demo/v0b1_rgb_capture_20260721
```

---

## 4. 镜像 SHA

| 字段 | 值 |
|---|---|
| Tag | `gmdisturb:b4-p010-20260721` |
| Image ID | `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68` |
| 是否需重建 | **否** |

---

## 5. 预计耗时

| 阶段 | 估计 |
|---|---|
| 容器冷启动 + Kit/场景 | 1–3 min（GPU/缓存状态相关） |
| 80 step + 相机渲染 | 约 0.5–2 min |
| **合计** | **约 2–5 min**（冷启动偏上限） |

参考：历史短 smoke 量级约数十秒仿真段；加相机渲染会更慢。

---

## 6. 预计产物

```text
results/paper_demo/v0b1_rgb_capture_20260721/
  scene/
    frame_000000_env0.png
    frame_000010_env0.png
    ...
  manifest/
    artifacts.jsonl          # 每帧一条
    capture_summary.json     # 命令、镜像 SHA、门禁结果
  (path B only) head/
    frame_000000_env0.png
    ...
```

**不**写入 B0/B1/B2/B4 正式结果树；**不**当作论文统计。

---

## 7. Artifact manifest 设计

每帧 JSONL 字段：

```json
{
  "artifact_id": "v0b1_<camera>_<sim_step>_<sha12>",
  "image_path": "scene/frame_000010_env0.png",
  "sha256": "...",
  "camera_name": "scene_camera",
  "sim_step": 10,
  "width": 640,
  "height": 480,
  "channels": 3,
  "dtype": "uint8",
  "min": 0,
  "max": 255,
  "mean": 87.3,
  "nonzero_ratio": 0.992,
  "captured_at": "2026-07-21T...Z",
  "image_id": "sha256:defe95e7...",
  "container_tag": "gmdisturb:b4-p010-20260721",
  "command": "<exact argv>",
  "source_entry": "GMRobot/scripts/gm_state_machine_agent.py"
}
```

采集后由**离线**校验脚本生成（批准采集后再写；本轮不实现）。

---

## 8. 有效帧门禁

全部通过才算 P0-7 关闭候选：

1. PNG 可被 Pillow/OpenCV 正常解码
2. shape = `H×W×3`（scene：480×640×3；head：240×320×3）
3. dtype = `uint8`（若源为 float，必须记录转换并证明来自仿真观测）
4. 非全黑：`max > 0` 且 `mean` 不极端接近 0
5. 非全白：`min < 255` 且 `mean` 不极端接近 255
6. `nonzero_ratio` 合理（经验阈：`> 0.01`）
7. 同相机不同 `sim_step` 的内容 hash **不得全部相同**（允许相邻帧相似，但 8 帧全同 → FAIL）
8. 禁止随机 `np.random` / 纯色占位图冒充
9. manifest 中 `image_id` 必须等于冻结镜像 SHA

---

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 漏 `--enable_cameras` → Camera init FAIL | 命令已显式包含 |
| 全黑帧（渲染/GPU） | 门禁拒绝；检查 GPU/`--headless` |
| 路径 A 无 head 相机 | 先 A 后 B；五阶段可先用 scene |
| 镜像内 GMRobot 与宿主机源码可能不一致 | 采集只用镜像内脚本；不依赖 V0-A 新代码 |
| 误触 VLM/safety | 不传相关 flag；默认关闭 |
| 写错目录污染冻结结果 | 专用 `v0b1_rgb_capture_20260721/` |
| 超时过长 | `max_steps=80` 硬上限 |

---

## 10. 是否需要构建新镜像

**否。** 路径 A 完全使用冻结 `defe95e…`。路径 B 仅 bind-mount 宿主机脚本，仍不重建。

---

## 11. 停止点

预检完成。**不得自行启动采集。** 等待批准路径 A（和/或路径 B 脚本实现）。
