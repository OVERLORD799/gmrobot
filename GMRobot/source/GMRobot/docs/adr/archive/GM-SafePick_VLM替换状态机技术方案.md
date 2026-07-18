# GM-SafePick：VLM 替换状态机控制器技术方案（归档）

> **归档说明（2026-06-22）**：2026-06-15 早期「用 VLM 替换状态机任务规划」探索稿；**现行架构**为 Layer 1/2/3 安全推理 + 状态机保留作轨迹执行器。权威规范见 [架构总览](../../GM-SafePick_架构总览.md)、[Layer 3 VLM推理增强层](../../GM-SafePick_Layer3_VLM推理增强层.md)、[AI 服务器部署](../../GM-SafePick_AI服务器部署.md)。
>
> 项目路径：`/root/GMRobot`  
> 构建环境：**gpufree GPU 服务器**（Ubuntu 22.04，conda + pip 安装 Isaac Sim 5.1.0 / Isaac Lab）  
> 原目标：将脚本化状态机控制器替换为 VLM 驱动的决策系统（**未采用**；VLM 现为 Layer 3 非阻塞安全增强）

### 文档层级与对齐关系（历史）

| 优先级 | 文档 | 说明 |
|:------:|------|------|
| 1 | [`README.md`](../../../../README.md) | 项目初始说明（场景、控制接口、长期安全方向） |
| 2 | [`GM-SafePick_添加相机技术文档.md`](../../GM-SafePick_添加相机技术文档.md) | **相机与视觉观测接口的权威定义**（§5 接口契约） |
| 3 | **本文（归档）** | 早期 VLM 替换探索；部署细节已迁移至 AI 服务器部署文档 |

---

## 0. 当前部署前提（2026-06-15 已验证）

| 项 | 实际值 |
|----|--------|
| 项目根目录 | `/root/GMRobot` |
| 扩展包路径 | `/root/GMRobot/source/GMRobot` |
| Isaac Lab | `/root/gpufree-data/IsaacLab`（`/root/IsaacLab` 软链接） |
| Python 环境 | `/root/gpufree-data/conda/envs/env_isaaclab`（Python 3.11） |
| 激活脚本 | `source /root/activate_isaaclab.sh` |
| 注册任务 | `gm` / `Template-Gmrobot-v0` |
| 状态机 baseline | `python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras` 可完成环境初始化（相机已写入 env cfg，须传 `--enable_cameras`） |
| 连通性测试 | `python scripts/zero_agent.py --task=gm --headless --enable_cameras` 可 reset + step |

**资产加载（本地 USD，非占位方案）**：

| 资产 | 路径 |
|------|------|
| UR10e + 夹爪 | `source/GMRobot/GMRobot/assets/ur10e_2f/ur10e_gripper.usd` |
| 容器 | `assets/container.usd`（约 21 MB） |
| 隔板 | `assets/container/GM_Container_Slim_Divider_Sim.usd` |
| 零件 | `assets/part/part_5000.usd` |
| 工作台 | Nucleus `SeattleLabTable`（运行时缓存） |

USD 由 `.gitignore` 排除，不入 GitHub；VLM 开发须在本地保留完整 `assets/`。

---

## 1. 现状分析

当前控制器位于 `scripts/gm_state_machine_agent.py`，核心是 `SingleEnvPickAndPlacePolicy`：

| 维度 | 现状 |
|------|------|
| 决策依据 | **特权信息（privileged obs）**：`slot_A_1_T` 等 40 项静态槽位变换矩阵，不依赖视觉 |
| 控制方式 | reset 时预计算整条轨迹，按时间插值输出 8 维动作 |
| 动作空间 | `[x, y, z, qw, qx, qy, qz, gripper]`，经差分 IK 驱动 UR10e |
| 任务输入 | `DEFAULT_USER_COMMANDS` 硬编码 20 条：`A@1→B@1` … `A@20→B@20` |
| 感知 | 场景俯视相机 **已落地**（`obs["camera"]["scene_rgb"]`，见相机文档 §1）；状态机 **不消费** 视觉；`PolicyCfg` 仍提供位姿类特权观测（共 63 项） |
| 仿真参数 | `sim.dt = 1/200`，`decimation = 4` → 控制频率约 **50 Hz** |

**关键结论**：替换状态机不仅是换策略类，还要补齐 **视觉感知链路**，并重新定义 VLM 在控制栈中的职责边界。

### 当前控制流程

```
用户硬编码命令 → 读取特权 slot 变换矩阵 → 预计算 10 阶段轨迹 → 50Hz 插值输出 8 维动作
```

### 目标控制流程

```
自然语言任务 + RGB 图像 → VLM 规划/定位 → 低层运动执行器 → 50Hz 插值输出 8 维动作
```

---

## 2. 推荐总体架构

建议采用 **「VLM 高层决策 + 低层运动执行器」** 的分层方案，而不是让 VLM 直接每步输出 8 维连续动作。

**原因：**

1. 当前 8 维笛卡尔控制对 VLM 来说过于细粒度，推理延迟高、稳定性差
2. 现有差分 IK 与夹爪控制器已在 gpufree headless 环境验证可用，应复用
3. 与项目「未来人机协作安全评估」方向一致：VLM 负责理解场景与任务，底层负责安全运动

### 架构图

```mermaid
flowchart TB
    subgraph gpufree ["gpufree GPU 服务器"]
        sim["Isaac Sim 5.1 + Isaac Lab + GMRobot"]
        cam["场景相机 scene_rgb（已落地）/ 腕部相机（可选扩展）"]
        vlm["VLM 推理服务"]
        exec["低层执行器 MotionExecutor"]
    end

    userCmd["自然语言任务指令"]
    img["RGB 图像帧"]
    state["机器人状态摘要"]

    userCmd --> vlm
    cam -->|"obs[\"camera\"][\"scene_rgb\"]"| img --> vlm
    sim --> state --> vlm

    vlm -->|"结构化子任务"| exec
    exec -->|"8维 IK 动作"| sim
```

### VLM 输出格式（建议）

不让 VLM 直接输出连续轨迹，而是输出 **结构化子任务**，由低层执行器转成与现状态机等价的运动阶段：

```json
{
  "phase": "pick",
  "target_container": "A",
  "target_slot": 3,
  "confidence": 0.92,
  "reason": "容器A第3格有未搬运零件"
}
```

低层 `MotionExecutor` 将子任务展开为与现状态机等价的运动阶段序列：

```
MOVE_ABOVE(A@3) → DESCEND(A@3) → CLOSE_GRIPPER → LIFT
→ MOVE_ABOVE(B@3) → DESCEND(B@3) → OPEN_GRIPPER → LIFT
```

---

## 3. VLM 职责分层

### 方案 A：VLM 作任务规划器（首选，第一阶段）

- **输入**：用户自然语言 + `obs["camera"]["scene_rgb"]`（俯视工作台 RGB，见相机文档 §4.3 监控区域）
- **输出**：`pick` / `place` 命令序列（等价于 `DEFAULT_USER_COMMANDS`）
- **低层**：复用现有 `_build_stage_sequence` 逻辑，但槽位坐标来自 VLM 视觉定位

适合：快速替换硬编码命令，验证 VLM 是否理解场景与任务。

### 方案 B：VLM 作视觉定位器（第二阶段）

- **输入**：`obs["camera"]["scene_rgb"]` + 提示词（"找出容器A中所有待搬运零件的格子编号"）
- **输出**：`{(container, slot_id): bbox 或 2D 坐标}`
- **坐标映射**：2D 像素 → 通过相机内外参 + 桌面平面假设 → 世界坐标 `(x, y)`

替代当前对 `slot_*_T` 的直接依赖，使系统从 privileged 走向 vision-based。

### 方案 C：VLM 作阶段切换器（第三阶段，面向未来安全场景）

- **输入**：`obs["camera"]["scene_rgb"]` + 当前阶段 + 安全相关文本（"人靠近时暂停"）
- **输出**：`continue` / `pause` / `slow_down` / `replan`
- 为后续人机协作安全评估预留接口

**推荐实施顺序**：A → B → C，而不是一步到位端到端 VLM 控制。

---

## 4. 需要改动的模块

### 4.1 环境层（`source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py`）

**相机配置以 [`GM-SafePick_添加相机技术文档.md`](../../GM-SafePick_添加相机技术文档.md) 为准**（已于 2026-06-15 落地）。核心约定：

```python
# 已由相机文档定义 — 勿在本方案中重复改名
scene_camera: TiledCameraCfg  # prim_path="{ENV_REGEX_NS}/SceneCamera"
# 观测：obs["camera"]["scene_rgb"]  →  (num_envs, 480, 640, 3) uint8
```

| 观测组 | 内容 | 用途 |
|--------|------|------|
| `policy` | `ee_pos`、容器/零件/槽位变换等（与 README §5 一致） | 低层执行器、状态机 baseline |
| `camera` | `scene_rgb`（§5 契约） | VLM 安全层 / 视觉模块输入 |

**后续扩展（相机文档 §5 允许项，本方案引用但不实现）**：

```python
# 未来可在同一 camera 组追加，键名以相机文档为准
# wrist_rgb   — 腕部相机（wrist_3_link 挂载）
# scene_depth — 深度图
```

**非特权环境（Phase 3）**：建议新增 `UR10eGMVisionEnvCfg`，关闭 `OBS_SLOTS` 等 ground-truth 槽位观测；在 `__init__.py` 注册为 `gm-vision` 任务。**不改变** `camera.scene_rgb` 接口。

**可复用资产**：`assets/` 中已有 `MAN C testbed Multi Cameras.usd`、`ZED_X.usdc` 等相机相关 USD，可作腕部相机 prim 参考；场景俯视相机配置见相机文档 §4.3。

### 4.2 策略层（新建 `scripts/gm_vlm_agent.py`）

抽象统一接口，替换 `MultiEnvPickAndPlacePolicy`：

```python
class VLMPickPlacePolicy:
    def __init__(self, vlm_client, motion_executor, num_envs):
        ...

    def reset(self, obs, user_instruction: str):
        # VLM 规划任务序列 + 视觉定位
        ...

    def get_action(self, obs):
        # 低层执行器按当前子阶段输出 8 维动作
        # 必要时周期性调用 VLM 重规划
        ...
```

保留 `MultiEnvPickAndPlacePolicy` 作为 baseline，便于 A/B 对比。

### 4.3 VLM 推理层（新建 `source/GMRobot/GMRobot/vlm/`）

```
source/GMRobot/GMRobot/
  vlm/
    client.py          # 统一推理接口
    prompts.py         # 任务/定位 prompt 模板
    parsers.py         # 结构化输出解析与校验
    backends/
      openai_api.py    # GPT-4o / 兼容 API
      qwen_vl.py       # 本地 Qwen2.5-VL
      openvla.py       # 机器人专用 VLM（可选）
```

### 4.4 低层执行层（新建 `source/GMRobot/GMRobot/control/motion_executor.py`）

从 `SingleEnvPickAndPlacePolicy` 抽取以下逻辑：

- `_build_stage_sequence`
- `_build_trajectory`
- `get_action`

改为接受 **VLM 提供的 `(container, slot, world_pose)`**，而非 `obs["slot_*_T"]` 特权观测。

常量可直接复用状态机脚本中的定义：

| 常量 | 值 | 说明 |
|------|-----|------|
| `HOME_POSITION` | `(0.9, 0.0, 0.4)` | 起始/home 位姿 |
| `APPROACH_HEIGHT` | `0.40` | 接近/抬升高度 |
| `GRASP_HEIGHT` | `0.13` | 抓取/放置高度 |
| `GRIPPER_OPEN` / `GRIPPER_CLOSED` | `1.0` / `-0.5` | 夹爪动作标量 |

---

## 5. VLM 模型选型建议

| 场景 | 推荐模型 | 说明 |
|------|----------|------|
| 快速原型 / 任务理解 | GPT-4o / Qwen2.5-VL-7B | 结构化 JSON 输出能力强，prompt 工程成本低 |
| 本地离线推理 | Qwen2.5-VL-7B-Instruct | 7B 可在单卡 24GB 跑通；gpufree RTX 4090 可同机或分进程 |
| 端到端机器人动作（后期） | OpenVLA / Octo | 需大量仿真数据微调，不适合第一期 |
| 槽位/物体定位 | Grounding DINO + VLM | 检测 bbox，再由 VLM 做语义关联，比纯 VLM 坐标回归更稳 |

**第一期建议**：`Qwen2.5-VL-7B`（本地）或 `GPT-4o`（API），做 **任务规划 + 槽位识别**，低层运动仍走现有 IK 管线。

---

## 6. 部署方案

### 6.1 当前推荐：gpufree conda/pip 环境（已跑通 baseline）

与 [GM-SafePick_远程运行指南.md](../../GM-SafePick_远程运行指南.md) 一致，VLM 第一期应优先在此环境迭代：

```bash
source /root/activate_isaaclab.sh
pip install -e /root/GMRobot/source/GMRobot

# baseline 验证
python scripts/list_envs.py
python scripts/gm_state_machine_agent.py --task=gm --headless

# VLM 依赖（示例）
pip install transformers accelerate qwen-vl-utils pillow
```

| 项目 | 要求 |
|------|------|
| GPU | NVIDIA RTX 4090（本机示例） |
| 驱动 | 容器内 `nvidia-smi` 可见 |
| Isaac Sim | `isaacsim[all,extscache]==5.1.0`（pip） |
| 磁盘 | ≥ 50GB（Sim 缓存 + 本地 USD + VLM 权重） |
| 显示模式 | headless（`--headless`）或 VNC 带界面 |

### 6.2 显存与进程布局

| 布局 | 适用 | 说明 |
|------|------|------|
| 同进程 / 同机 | RTX 4090 24GB | Sim headless 约占 8–12GB；7B VLM 4-bit 量化后可同卡 |
| 双进程 | 显存紧张 | Sim 占 GPU0，VLM 推理服务占 GPU1 或 CPU offload |
| Docker（可选） | 需可复现交付时 | 仓库有 `.dockerignore`，但**尚无** `docker/Dockerfile`；可参考 Isaac Lab 官方 Docker 扩展 |

### 6.3 Docker 方案（可选，非当前主路径）

若后续需要容器化交付，建议基于 Isaac Lab 官方 Ubuntu 22.04 镜像扩展，而非从零写镜像。构建前须将本地 `assets/*.usd` 挂载或 COPY 进镜像（USD 不在 git 中）。

```bash
# 示意（Dockerfile 待新建）
docker run --gpus all --rm -it \
  -v /root/GMRobot:/workspace/GMRobot \
  -e ACCEPT_EULA=Y \
  gmrobot-vlm:latest \
  python scripts/gm_vlm_agent.py --task=gm --headless
```

### 6.4 VLM 服务通信（双进程时）

```mermaid
flowchart LR
    simProc["进程1: Isaac Sim + GMRobot"]
    vlmProc["进程2: VLM 推理服务"]
    simProc -->|"HTTP/gRPC 图像+prompt"| vlmProc
    vlmProc -->|"JSON 子任务"| simProc
```

---

## 7. 控制循环设计

当前仿真参数：`dt = 1/200`，`decimation = 4` → 控制频率约 **50 Hz**。

VLM 推理通常 **0.5–3 s/次**，不能每步调用。

| 层级 | 频率 | 职责 |
|------|------|------|
| VLM 规划器 | 每 episode 1 次，或子任务失败时重规划 | 生成 pick/place 序列、视觉定位 |
| VLM 监控器（可选） | 每 1–2 s | 检测异常（零件掉落、目标格已占用） |
| MotionExecutor | 50 Hz | 轨迹插值、输出 8 维动作 |
| Isaac Sim | 200 Hz | 物理仿真 |

这与现状态机「reset 时规划、step 时执行」的节奏一致，只是把规划来源从特权 obs 换成 VLM。

---

## 8. 数据与评估

### 8.1 训练数据（若走微调路线）

1. **仿真自动标注**：用现状态机跑 episodes，同步保存 `(RGB, privileged slot pose, command)` 三元组
2. **Replicator SDG**：随机光照、相机位姿、零件初始位置，扩充视觉多样性
3. **格式**：COCO 风格 bbox + 任务 JSON，或 VQA 问答对

### 8.2 评估指标

| 指标 | 说明 |
|------|------|
| Task Success Rate | 20 个零件全部搬运完成 |
| Slot Identification Accuracy | VLM 识别的槽位与 GT 一致率 |
| Plan Validity | 输出的 pick/place 序列语法合法 |
| Motion Completion Time | 对比状态机 baseline |
| Vision-only vs Privileged Gap | 关闭 `slot_*_T` 后的性能下降 |

### 8.3 A/B 对比基线

| 配置 | 控制器 | 观测 |
|------|--------|------|
| Baseline | `gm_state_machine_agent.py` | 特权 `slot_*_T` |
| VLM-Plan | `gm_vlm_agent.py` | 特权 `slot_*_T` + 图像 |
| VLM-Vision | `gm_vlm_agent.py` | 仅图像（`gm-vision` 环境） |

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| VLM 坐标不准 | 不直接回归 3D 坐标；用 bbox + 相机标定 + 桌面平面投影 |
| 推理延迟高 | VLM 仅在 episode/子任务级调用，低层保持 50Hz 执行 |
| headless 长时间 Mutex 崩溃 | 缩短任务、减 `--num_envs`、或 VNC 带界面（见远程运行指南 Q2） |
| 显存不足 | Sim 与 VLM 分进程；或 VLM 用 4-bit 量化 |
| VLM 幻觉（错误槽位） | 输出 schema 校验 + 执行前碰撞/可达性检查 |
| 与 privileged obs 混用 | 分两个 env cfg：`gm`（baseline）与 `gm-vision`（评估用） |
| USD 缺失导致无法复现 | 克隆后须恢复本地 `assets/`；路径见 [远程运行指南 §6](../../GM-SafePick_远程运行指南.md#6-资产与-usd-路径) |
| 容器刚体 xformstack 告警 | 非致命，不影响 VLM 开发；见资产清单第六节 |

---

## 10. 实施分期

### Phase 0 — 环境确认（已完成）

- [x] gpufree conda 环境跑通 Isaac Lab + GMRobot
- [x] 完整本地 USD 资产加载
- [x] 状态机 baseline headless 环境初始化成功
- [x] `zero_agent.py` reset + step 连通性验证

### Phase 1 — 视觉基础设施（已完成 2026-06-15）

- [x] 按 [`GM-SafePick_添加相机技术文档.md`](../../GM-SafePick_添加相机技术文档.md) 落地场景相机，满足 §7 **必验** E1–E4、E6
- [x] （建议验）状态机 baseline 在 `--enable_cameras` 下持续仿真无 Camera 报错（§7 建议验 E5）
- [ ] 帧元数据 sidecar（`metadata.jsonl`，相机文档 §10.4 A1）
- [ ] （可选）Docker 镜像，用于交付复现

### Phase 2 — VLM 任务规划（1–2 周）

- [ ] VLM 替代 `DEFAULT_USER_COMMANDS`，输出 pick/place 序列
- [ ] 低层仍用特权 `slot_*_T` 做运动（验证 VLM 任务理解）
- [ ] 新建 `scripts/gm_vlm_agent.py` 与 `GMRobot/vlm/` 模块

### Phase 3 — VLM 视觉定位（2–3 周）

- [ ] VLM/检测模型定位槽位与零件
- [ ] 新建 `gm-vision` 环境，移除特权槽位观测
- [ ] 端到端 vision-based pick-and-place

### Phase 4 — 安全扩展（后续）

- [ ] VLM 监控人机距离、触发 pause/slow_down
- [ ] 对接人机协作安全评估方向

---

## 11. 待确认的关键决策

| # | 决策项 | 选项 |
|---|--------|------|
| 1 | VLM 部署方式 | 本地模型（Qwen2.5-VL）/ 云端 API（GPT-4o） |
| 2 | 替换深度 | 仅任务规划 / 连同视觉定位一起替换特权 obs |
| 3 | GPU 资源 | 单卡 24GB 同进程 / Sim+VLM 双进程 |
| 4 | 是否需训练 | 零样本 prompt 工程 / 基于仿真数据微调 |
| 5 | 并行环境 | 是否保留 `--num_envs=16`（VLM 并行会显著增加推理负载） |
| 6 | 运行形态 | gpufree 直接开发（推荐）/ Docker 交付 |

---

## 12. 相关文件索引

| 文件 | 说明 |
|------|------|
| `scripts/gm_state_machine_agent.py` | 当前状态机控制器（baseline，待抽取逻辑） |
| `source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py` | 环境与观测配置 |
| `source/GMRobot/GMRobot/tasks/manager_based/gmrobot/mdp/observation.py` | 自定义观测项 |
| `source/GMRobot/GMRobot/assets/ur10e_cfg.py` | UR10e 本地 USD 路径 |
| `scripts/gm_vlm_agent.py` | VLM 控制器（待新建） |
| `source/GMRobot/GMRobot/vlm/` | VLM 推理模块（待新建） |
| `source/GMRobot/GMRobot/control/motion_executor.py` | 低层运动执行器（待新建） |
| `docker/Dockerfile` | 容器构建（待新建，非当前主路径） |

---

## 13. 相关文档

- [`README.md`](../../../../README.md) — 项目初始说明（最高优先级）
- [`GM-SafePick_添加相机技术文档.md`](../../GM-SafePick_添加相机技术文档.md) — 相机配置与 §5 接口契约（视觉层权威）
- [GM-SafePick_远程运行指南.md](../../GM-SafePick_远程运行指南.md) — headless/VNC 运行与 §6 资产路径
- [GM-SafePick_Layer3_VLM推理增强层.md](../../GM-SafePick_Layer3_VLM推理增强层.md) — 现行 VLM 五阶段规范
- [GM-SafePick_AI服务器部署.md](../../GM-SafePick_AI服务器部署.md) — gm-ai-server 部署与隧道

---

## 14. 参考链接

- [Isaac Lab 安装指南](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/index.html)
- [Isaac Sim 5.1 系统要求](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html)
- [Isaac Lab Docker 方案](https://isaac-sim.github.io/IsaacLab/main/source/deployment/docker.html)
- [Qwen2.5-VL 模型](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)
