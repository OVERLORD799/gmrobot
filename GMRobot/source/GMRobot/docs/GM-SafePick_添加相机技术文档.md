# GM-SafePick：场景相机技术文档

> **文档性质**：相机配置、观测接口与运行方式的**权威参考**（相机阶段已于 2026-06-15 完成并验收）
> **项目根目录**：`/root/GMRobot`
> **最后更新**：2026-06-15
> **状态**：✅ **已落地** — 俯视 `scene_rgb` 已写入 env cfg、验证脚本与帧导出可用；下一阶段见 §10

### 文档层级

| 优先级 | 文档 | 角色 |
|:------:|------|------|
| 1 | [`README.md`](../../../README.md) | 项目初始说明：场景、任务、控制接口、长期安全方向 |
| 2 | **本文** | 相机配置与 `obs["camera"]["scene_rgb"]` 的**权威定义** |
| 3 | `docs/` 其他文档（含 VLM 方案） | 视觉输入路径、分辨率、观测组命名**须与本文一致** |

> VLM 安全层文档应引用本文 §5 接口契约，不得自行定义冲突的相机接口。本文**不包含** VLM 推理或安全逻辑实现。

---

## 1. 项目现状速览

### 1.1 已实现能力

| 能力 | 实现位置 | 说明 |
|------|---------|------|
| 俯视场景相机 `scene_camera` | `gmrobot_env_cfg.py` → `UR10eGMSceneCfg` | `TiledCameraCfg`，640×480 RGB，10 Hz |
| 相机观测组 `camera.scene_rgb` | `gmrobot_env_cfg.py` → `ObservationsGMCfg` | 与 `policy` 组并列，独立输出 |
| 相机功能验证 | `scripts/test_camera.py` | 形状 / dtype / 非空断言 + 单帧 PNG |
| 仿真帧批量导出 | `scripts/gm_state_machine_agent.py` | `--save_camera` 及相关 CLI |

**运行时访问路径**（Gym `reset`/`step` 返回值）：

```python
rgb = obs["camera"]["scene_rgb"]  # torch.Tensor, (num_envs, 480, 640, 3), uint8
```

### 1.2 观测空间结构

`policy` 组（与 [`README.md`](../../../README.md) §5 一致，**未因相机改动而变更**）：

| 观测项 | 说明 |
|--------|------|
| `ee_pos` | 腕部 `wrist_3_link` 世界系位姿（`mdp.body_pose_w`，含位置 + 四元数） |
| `box_A_pos` / `box_B_pos` | 容器 A/B 静态 4×4 变换（键名带 `_pos`，实为变换矩阵） |
| `part_*_pos` | 20 个零件位姿 |
| `slot_*_T` | 40 个槽位变换矩阵（特权信息） |

`camera` 组（新增，供下游视觉模块消费）：

| 观测项 | 说明 |
|--------|------|
| `scene_rgb` | 俯视工作台 RGB，见 §5 |

状态机 baseline **不读取** `camera` 组；8 维动作接口不变。

### 1.3 场景参数（README §3）

| 项 | 值 |
|----|-----|
| 任务 ID | `gm` |
| 机器人 | UR10e + 夹爪，差分 IK 笛卡尔控制 |
| 容器 | A（源，20 零件）→ B（目标），各 5×4 槽位 |
| 成功标准 | 完成 `A@1→B@1` … `A@20→B@20` 全序列 |
| 控制频率 | ~50 Hz（`sim.dt=1/200`，`decimation=4`） |

### 1.4 README 滞后说明

[`README.md`](../../../README.md) §4 仍写「不使用视觉感知」，§2 Quick Start 未含 `--enable_cameras`。**以本文为准**：

- 相机已写入 `UR10eGMSceneCfg`；任何需要 `env.reset()` 成功的运行**必须**传 `--enable_cameras`。
- 带相机的命令见 §3；README 待后续统一更新时再同步。

---

## 2. 与论文参考文档的关系

对照 [Proactive Physical Safety Reasoning for Robot Manipulation 中文翻译与术语解析.md](./Proactive%20Physical%20Safety%20Reasoning%20for%20Robot%20Manipulation%20中文翻译与术语解析.md)（以下简称「论文参考文档」）：

| 维度 | 论文 interim report（§IV G/H） | 当前 GM-SafePick |
|------|-------------------------------|------------------|
| 操作对象 | 3 个彩色方块 | 20 零件，双容器 5×4 槽位 |
| 任务 | 方块 → 单容器 | `A@1→B@1` … `A@20→B@20` |
| 行为策略 | PPO + 安全门控 $g_t$ | 确定性状态机 |
| 动作 | 4 维 `[x,y,z,ψ]` | 8 维（xyz + quat wxyz + 夹爪） |
| 控制频率 | 20 Hz | ~50 Hz |
| 视觉观测 | 该里程碑**无** | `camera.scene_rgb` 已提供 |
| 人类 agent | §IV J 下一里程碑 | 未实现（README §8） |

**含义**：`scene_rgb` 覆盖 GM-SafePick 双容器工作区，可支撑论文五阶段管线的**方法验证**；论文 Fig 2/3 的 3 方块场景与当前 demo **不等同**，不能假设 `output/camera_frames/` 帧内容与论文截图一致。

---

## 3. 运行方式

### 3.1 前置条件

- Isaac Sim **5.1.0**（`isaacsim[all,extscache]==5.1.0`，见部署文档）
- Isaac Lab（manager-based RL env）
- **必须**传 `--enable_cameras`（由 `AppLauncher` 解析）；漏传会在 `env.reset()` 报错：

```
RuntimeError: Camera could not be initialized. Please ensure --enable_cameras is used to enable rendering.
```

### 3.2 常用命令

```bash
# 相机单元验证（推荐首选）
python scripts/test_camera.py --task=gm --headless --enable_cameras

# 状态机 + 相机（不导出帧）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras

# 状态机 + 批量导出 RGB 帧
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --save_camera \
  --camera_output_dir=/root/GMRobot/output/camera_frames \
  --camera_save_interval=10

# 多环境（相机使用 TiledCameraCfg，推荐）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras --num_envs=16
```

### 3.3 `gm_state_machine_agent.py` 相机相关 CLI

| 参数 | 默认 | 说明 |
|------|------|------|
| `--enable_cameras` | 关 | 由 `AppLauncher` 提供；**启用相机所必需** |
| `--save_camera` | 关 | 将 `scene_rgb` 存为 PNG；**依赖** `--enable_cameras` |
| `--camera_output_dir` | `/root/GMRobot/output/camera_frames` | PNG 输出目录；启动时会清空已有目录 |
| `--camera_save_interval` | `10` | 每 N 个 env step 保存一帧；文件名 `frame_{step:06d}_env{idx}.png` |

`--save_camera` 未配合 `--enable_cameras` 时脚本会直接抛 `RuntimeError`。

### 3.4 输出路径

| 路径 | 说明 |
|------|------|
| `obs["camera"]["scene_rgb"]` | 运行时观测（权威接口） |
| `/tmp/camera_dump.png` | `test_camera.py` 单帧 dump |
| `/root/GMRobot/output/camera_frames/` | `--save_camera` 批量 PNG（gitignore） |
| `output/metadata.jsonl` | **待实现**（§10.4 A1）：帧–状态–阶段对齐 |

---

## 4. 相机配置（权威）

> **唯一权威来源**：`source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py` 中 `UR10eGMSceneCfg.scene_camera`。

### 4.1 类型选择

已部署 **`TiledCameraCfg`**（非单实例 `CameraCfg`）：

- 状态机支持 `--num_envs`（默认 1，可扩至 16+）
- 平铺渲染 API：一次 pass 输出所有环境视图，多 env 场景更高效

### 4.2 参数表

| 参数 | 值 | 说明 |
|------|-----|------|
| `prim_path` | `{ENV_REGEX_NS}/SceneCamera` | 每环境一个相机 prim |
| `width` × `height` | 640 × 480 | 4:3，`uint8` RGB |
| `data_types` | `["rgb"]` | 可扩展 `"depth"` → 键名 `scene_depth`（§5.3） |
| `update_period` | 0.1 s | 传感器 10 Hz；不必每 sim step 读取 |
| `focal_length` | 18.0 | 较宽 FOV，已验证覆盖工作区 |
| `focus_distance` | 400.0 | |
| `horizontal_aperture` | 20.955 | |
| `clipping_range` | (0.1, 1e5) | |
| `offset.pos` | (0.35, 0.0, 2.5) | world 系，工作台上方 |
| `offset.rot` | (0.7071, 0.0, 0.7071, 0.0) | world 系俯视，四元数 wxyz |
| `offset.convention` | `"world"` | |

### 4.3 监控区域与 FOV 验证

| 区域 | 世界坐标（`gmrobot_env_cfg.py`） | 用途 |
|------|----------------------------------|------|
| 工作台 + UR10e 基座 | 桌子 `(0.6, 0.0, 0.0)` | 机械臂运动 |
| 容器 A（源） | `(0.75, -0.25, 0.0)` | 拣选 |
| 容器 B（目标） | `(0.75, 0.25, 0.0)` | 放置 |
| 人机共享区（预留） | 容器与机器人间桌面通道 | README §8 / 论文 §IV J |

**2026-06-15 验收**：`output/camera_frames/` 114 帧（step 0–1130，间隔 10）人工确认 UR10e、SeattleLabTable、双容器及共享通道均可见。加入人类 agent 后须复验共享区 FOV。

---

## 5. 观测接口契约

以下约定为**稳定接口**；VLM / 检测模块**只能消费、不得重命名**已有键（扩展项除外）。

| 契约项 | 约定值 |
|--------|--------|
| 观测组 | `"camera"` |
| 观测项 | `"scene_rgb"` |
| 访问路径 | `obs["camera"]["scene_rgb"]` |
| 类型 | `torch.Tensor` |
| 形状 | `(num_envs, 480, 640, 3)` |
| dtype | `uint8`（依赖 `normalize=False`，见 §6.2） |
| 传感器实体 | `"scene_camera"` |
| 更新频率 | 10 Hz（`update_period=0.1`） |
| VLM 建议采样 | 1–2 Hz（不必每 control step 调用） |

**预留扩展**（同一 `camera` 组内追加，不改 `scene_rgb`）：

| 扩展项 | 建议键名 | 触发条件 |
|--------|----------|----------|
| 深度图 | `scene_depth` | 需要距离判据 / SAM2 精细 mask |
| 腕部 RGB | `wrist_rgb` | 挂载 `wrist_3_link`；近场遮挡严重时的 Stage 2 |
| 侧视 RGB | `side_rgb` | 人机共域需补高度、减遮挡 |

**内参 / 外参（Phase 3+）**：

- 内参：`env.unwrapped.scene.sensors["scene_camera"].data.intrinsic_matrices`
- 外参：§4.2 `offset` + world 系

**本阶段不提供**：VLM 推理、安全判决 JSON、`pause/slow_down/replan`、特权观测移除。

---

## 6. 代码实现参考

### 6.1 变更文件清单

| 文件 | 变更 |
|------|------|
| `gmrobot_env_cfg.py` | `TiledCameraCfg` 场景相机 + `ObservationsGMCfg.CameraCfg` 观测组 |
| `scripts/test_camera.py` | 相机验证脚本（新增） |
| `scripts/gm_state_machine_agent.py` | `--save_camera` / `--camera_output_dir` / `--camera_save_interval` + `save_camera_frames()` |
| `mdp/observation.py` | **无变更**（虽有 Camera 导入，env cfg 未引用；观测用 `isaaclab.envs.mdp.image`） |

### 6.2 场景相机（`gmrobot_env_cfg.py`）

```python
from isaaclab.sensors.camera.camera_cfg import CameraCfg
from isaaclab.sensors.camera.tiled_camera_cfg import TiledCameraCfg

# UR10eGMSceneCfg 内：
scene_camera: TiledCameraCfg = TiledCameraCfg(
    prim_path="{ENV_REGEX_NS}/SceneCamera",
    update_period=0.1,
    height=480,
    width=640,
    data_types=["rgb"],
    spawn=sim_utils.PinholeCameraCfg(
        focal_length=18.0,
        focus_distance=400.0,
        horizontal_aperture=20.955,
        clipping_range=(0.1, 1.0e5),
    ),
    offset=CameraCfg.OffsetCfg(
        pos=(0.35, 0.0, 2.5),
        rot=(0.7071, 0.0, 0.7071, 0.0),
        convention="world",
    ),
)
```

### 6.3 相机观测组（`gmrobot_env_cfg.py`）

```python
@configclass
class CameraCfg(ObsGroup):
    """Camera observations. Reserved for downstream vision modules."""

    scene_rgb = ObsTerm(
        func=mdp.image,
        params={
            "sensor_cfg": SceneEntityCfg("scene_camera"),
            "data_type": "rgb",
            "normalize": False,  # 必须 False，否则 float 而非 uint8
        },
    )

    def __post_init__(self):
        self.concatenate_terms = False

camera: CameraCfg = CameraCfg()
```

> **注意**：内部类名 `CameraCfg` 与传感器 import `CameraCfg` 同名；阅读时区分 ObsGroup 与传感器配置类。`mdp.image` 默认 `normalize=True` 会减 batch 均值并转 float，下游与验证均需要原始 `uint8`。

### 6.4 帧导出（`gm_state_machine_agent.py`）

```python
def save_camera_frames(obs, output_dir: str, step: int) -> None:
    rgb = to_numpy(obs["camera"]["scene_rgb"])
    for env_idx in range(rgb.shape[0]):
        frame_path = os.path.join(output_dir, f"frame_{step:06d}_env{env_idx}.png")
        Image.fromarray(rgb[env_idx]).save(frame_path)
```

在 `reset` 后及每 `camera_save_interval` step 调用；episode 成功重置时额外保存一帧。

---

## 7. 验证与验收记录

相机阶段已于 **2026-06-15** 完成验收。与 README §3「20 次全序列成功」区分：后者为项目级 demo 回归，**不是**相机阶段门槛。

### 7.1 必验项（全部通过 ✅）

| # | 类别 | 预期 | 结果 | 验证方式 |
|---|------|------|:----:|----------|
| E1 | 环境启动 | `test_camera.py` 退出码 0 | ✅ | 2026-06-15 运行 |
| E2 | 形状 | `(num_envs, 480, 640, 3)` | ✅ | §6.1 断言 |
| E3 | dtype | `uint8`，max > 0 | ✅ | §6.1 断言 |
| E4 | 视野 | UR10e、SeattleLabTable、容器 A/B 可见 | ✅ | 114 帧 PNG 人工检查 |
| E6 | 接口不变 | `policy` 组与 8 维动作未改 | ✅ | 代码审查 |

### 7.2 建议验项

| # | 类别 | 说明 | 结果 |
|---|------|------|:----:|
| E5 | 状态机兼容 | `--enable_cameras` 下 reset + step 无 Camera 报错 | ✅ 已跑通 |
| E7 | 性能 | 单 env + 相机 ~150–180 Hz（相对无相机 ~200 Hz） | 参考值，非硬性 |

### 7.3 验证脚本

完整实现见仓库 `scripts/test_camera.py`。核心逻辑：

```python
obs, _ = env.reset()
rgb = obs["camera"]["scene_rgb"].detach().cpu().numpy()
assert rgb.shape == (num_envs, 480, 640, 3)
assert rgb.dtype == np.uint8 and rgb.max() > 0
```

运行：`python scripts/test_camera.py --task=gm --headless --enable_cameras`

单帧人工检查输出：`/tmp/camera_dump.png`（脚本会先清理同目录旧 PNG）。

### 7.4 不在相机阶段验收范围内

- 状态机 20 次 `A@i→B@i` 全序列 + `is_success()==True`
- VLM 推理延迟、人机距离、`pause/slow_down` 干预

---

## 8. 性能与注意事项

| 配置 | 预估 sim 帧率 | 说明 |
|------|:-----------:|------|
| 无相机（回退 env cfg 后） | ~200 Hz | 仅物理，无 RGB 渲染 |
| + 1 相机 640×480 | ~150–180 Hz | 需 `--enable_cameras` |
| 多相机 / 多 env | ~100–150 Hz | 随 GPU 与 `--num_envs` 变化 |

**经验值为 gpufree 单机 headless 参考，非必验。**

| 风险 | 对策 |
|------|------|
| 漏传 `--enable_cameras` | 所有需 reset 的命令显式传入 |
| 相机写入 cfg 后无相机无法 reset | 性能对照需 git 回退相机改动 |
| sim 帧率下降 | 增大 `update_period` 或降低 `--num_envs` |
| FOV 不足 | GUI 调 `offset` / `focal_length` 后更新 §4.2 |

---

## 9. 范围外内容

- VLM 部署与五阶段推理管线 → [Layer 3 VLM推理增强层](./GM-SafePick_Layer3_VLM推理增强层.md)、[AI 服务器部署](./GM-SafePick_AI服务器部署.md)
- Grounding DINO / SAM2 集成
- 安全门控 $g_t$、PPO 策略
- 特权观测（`slot_*_T`）移除
- 仿真人类 agent → 论文 §IV J / README §8

下游模块通过 **`obs["camera"]["scene_rgb"]`** 消费，无需修改 scene cfg。

---

## 10. 下一阶段规划

> 来源：2026-06-15 对 `output/camera_frames/` 与论文参考文档的对照评审。

### 10.1 当前交付物评估

| 交付物 | 现状 | 意义 |
|--------|:----:|------|
| `obs["camera"]["scene_rgb"]` | ✅ | VLM Stage 1/3/4 合格第一版输入 |
| `output/camera_frames/*.png` | ✅ 114 帧 | 验收素材；**非**完整 benchmark |
| 帧级元数据 | ❌ | 无法对齐 approach/grasp/transit/place |
| VLM JSON 输出 | ❌ | Stage 1–5 未落地 |
| Grounding DINO / SAM2 | ❌ | Stage 2 未落地 |
| 仿真人类运动 | ❌ | 论文 §IV J |
| 安全门控日志 $g_t$ | ❌ | 平台闭环未建立 |

相机阶段完成；全链路约 **5–10%** 视觉采集就绪，**不足以**单独支撑论文完整安全评估。

### 10.2 单路俯视相机适用性

| 能力 | 单路 `scene_rgb`（VLM 原型） | 说明 |
|------|:----------------------------:|------|
| 全局布局、臂 XY 轨迹 | ✅ | 工作台、双容器、UR10e 已覆盖 |
| 静态区域级冲突 | ✅ | |
| 粗粒度动态风险 | ⚠️ | 10 Hz 相机 + 秒级 VLM 延迟 |
| 高度 / 深度歧义 | ❌ | 俯视 Z 轴不可分 |
| 连杆遮挡下人手–夹爪 | ❌ | |
| 人体细节（防护、注意力） | ❌ | 分辨率与角度不足 |

Stage 2 像素定位由 Grounding DINO + SAM2 负责，非 VLM；俯视 bbox 可作第一版，遮挡 case 记为已知局限。

### 10.3 相机扩展决策

**场景相机 `scene_rgb`**：

| 阶段 | 另加相机？ |
|------|:----------:|
| VLM 原型（Stage 1/3/4） | 否 |
| Grounding DINO 第一版（Stage 2） | 否（俯视 bbox 起步） |
| 可靠安全门控 + 人机共域 | **建议**侧视 RGB |
| 距离判据 / 精细 mask | **建议** `scene_depth` |

**腕部相机 `wrist_rgb`**（`wrist_3_link`）：

| | 俯视 `scene_rgb` | 腕部 `wrist_rgb` |
|--|------------------|------------------|
| 擅长 | 全局布局、区域风险 | 抓取细节、手–夹爪近距 |
| 弱点 | 遮挡、高度歧义 | 无全局（侧面闯入可能漏检） |

- **暂不追加**：VLM 原型、无人类 agent、先跑通 `scene_rgb` + JSON 管线
- **建议追加**：需可靠判断人手进入抓取区；俯视 Stage 2 因遮挡不稳定

### 10.4 路线图

```
scene_rgb（已完成）
  → 帧元数据 sidecar（A1）
  → VLM JSON 输出（B）
  → 仿真人类运动（D）
  → 按需侧视 / depth / wrist（§10.3）
  → 安全门控联调（C）
```

| 阶段 | 任务 | 优先级 |
|------|------|:------:|
| **A** 视觉数据 | A1：`--save_camera` 同步 `metadata.jsonl`；A3：人类 agent 前复验 FOV | P1 |
| **B** VLM + Stage 2 | B1–B3：VLM JSON + DINO bbox + SAM2 mask；B4：评估俯视 Stage 2 失败率 | P0–P1 |
| **C** 安全门控 | C1–C2：`g_t` 日志与帧时间戳对齐、干预指标 | P1 |
| **D** 人机协作 | D1–D3：人类场景库、rollout、扩展相机评估 | P0–P1 |

### 10.5 跨模块缺口

| 优先级 | 缺失项 | 负责模块 |
|:------:|--------|---------|
| P0 | 仿真人类运动 | 仿真 / 场景 |
| P0 | VLM Stage 1+3 JSON | VLM 方案 |
| P0 | DINO bbox + SAM2 mask | VLM 方案 |
| P1 | 安全门控 $g_t$ | 平台 |
| P1 | 帧元数据 sidecar | 导出脚本 |
| P2 | 视频序列（SAM2） | 导出脚本 |
| P2 | 侧视 / 深度 / 腕部相机 | 本文 §5 扩展 |

---

## 11. 已确认决策

| # | 决策 | 结论 |
|---|------|------|
| D1 | 相机阶段是否要求 20 次全序列？ | **否**；必验 E1–E4、E6 |
| D2 | 是否同步更新 README？ | **暂缓**；带相机命令以本文 §3 为准 |
| D3 | 单路俯视是否够 VLM 原型？ | **是**（Stage 1/3/4）；Stage 2 / 门控见 §10 |
| D4 | 原型是否必须腕部/侧视？ | **否**；人机共域阶段再评估 |

---

## 12. 相关参考

### 项目文档

- [`README.md`](../../../README.md)
- [`GM-SafePick_Layer3_VLM推理增强层.md`](./GM-SafePick_Layer3_VLM推理增强层.md)
- [`GM-SafePick_AI服务器部署.md`](./GM-SafePick_AI服务器部署.md)
- [归档：VLM 模型选型讨论](./adr/archive/GM-SafePick_VLM模型选型讨论.md)
- [论文中文翻译与术语解析](./Proactive%20Physical%20Safety%20Reasoning%20for%20Robot%20Manipulation%20中文翻译与术语解析.md)

### 外部参考

- [Isaac Lab Camera API](https://isaac-sim.github.io/IsaacLab/main/_modules/isaaclab/sensors/camera/camera_cfg.html)
- [Isaac Lab Discussions #1054](https://github.com/isaac-sim/IsaacLab/discussions/1054)
- [Isaac Sim 5.1 相机传感器](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/gui/tutorial_gui_camera_sensors.html)（项目版本 5.1.0；旧版 4.5 教程 API 大体兼容）

---

## 附录 A：GUI 调参参考（非已部署值）

初稿曾建议较低高度、较长焦距；**勿覆盖** §4.2 已验证配置，仅供 GUI 实验：

| 参数 | 初稿参考 | 已部署（权威） |
|------|----------|---------------|
| `offset.pos` | (0.6, 0.0, 0.8) | (0.35, 0.0, 2.5) |
| `offset.rot` | (0.707, 0.0, 0.0, 0.707) | (0.7071, 0.0, 0.7071, 0.0) |
| `focal_length` | 24.0 | 18.0 |

调参后须重跑 §7 必验项并更新 §4.2。

---

## 附录 B：目录结构

```
source/GMRobot/GMRobot/tasks/manager_based/gmrobot/
├── gmrobot_env_cfg.py          ← scene_camera + camera 观测组
├── mdp/
│   ├── observation.py          ← 无变更
│   └── ...
└── __init__.py                 ← 注册任务 id="gm"

scripts/
├── test_camera.py              ← 相机验证
└── gm_state_machine_agent.py   ← --save_camera 帧导出

output/camera_frames/           ← --save_camera 输出（gitignore）
```

---

## 附录 C：术语说明

| 项 | 说明 |
|----|------|
| `ee_pos` | 键名沿用历史；实现为 `mdp.body_pose_w`（7 维：xyz + quat） |
| `box_*_pos` | 键名带 `_pos`；实际返回 4×4 变换矩阵 |
| ObsGroup `CameraCfg` vs import `CameraCfg` | 前者为观测组类，后者为传感器配置 import |
| Isaac Sim 版本 | 5.1.0 为本机部署版本；其他版本未系统验证 |
| E7 帧率 | gpufree 经验值，非必验 |
