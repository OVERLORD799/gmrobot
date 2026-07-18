# GM-SafePick 任务迁移与架构解耦分析

> **定位**：评估 GM-SafePick 安全推理系统从 pick-and-place 任务迁移到其他机器人操作任务的可行性与工作量
> **面向**：项目成员与 AI 阅读者（迁移决策参考）
> **最后更新**：2026-06-30
> **分析基础**：代码库审计（`safety/`、`replan/`、`scripts/`、`configs/`）与耦合度量

---

## 1. 结论摘要

GM-SafePick 的安全核心（~2500–3000 行）**可零修改复用到任何具有「接近→操作→撤离」阶段结构的机器人操作任务**。任务特定耦合被严格控制在两个模块中，与安全核心之间通过薄接口（8 个 duck-typed 方法）连接。

迁移总成本约：
- **新任务策略**：~800 行（替代 `pick_and_place_policy.py`）
- **新环境配置**：~400 行（替代 `gmrobot_env_cfg.py`）
- **适配层微调**：~50 行（`replan/executor.py` 阶段名映射）
- **YAML 参数标定**：若干新配置文件

---

## 2. 模块可复用性矩阵

### 2.1 零修改复用（核心安全栈）

| 模块 | 路径 | 说明 |
|:------|:-----|:-----|
| 类型定义 | `safety/types.py` | `SafetyState`、`GateDecision`、`GateResult` — 纯运动学数据合约，无任务语义 |
| 配置 Schema | `safety/config.py` | `SafetyConfig` 及全部子数据类，所有参数 YAML 驱动 |
| 规则引擎 | `safety/rule_engine.py` | `RuleEngine.evaluate(SafetyState)` — 仅基于距离/TTC/工作空间做几何判定 |
| 安全门控 | `safety/gate.py` | `SafetyGate.apply()` — 8 维动作混合（`prev + α·(proposed−prev)`），泛用 |
| 包络评估 | `safety/envelope.py` | FK 计算臂段/指尖/携物碰撞原语 → 与手距离，链接名可配置 |
| 人类运动 | `safety/human_motion.py` | `HumanMotionController`：线性轨迹 + hold + retreat，全配置驱动 |
| Tier 融合 | `safety/fusion.py` | Tier0 硬止 / Tier1 ML 降级 / Tier2 减速，门控值驱动 |
| 距离法 GT | `safety/ground_truth.py` | 球体包络侵入判定，半径和阈值可配置 |
| GT 审计分支 | `safety/gt_branches.py` | FK 臂段距离 + PhysX contact stub，链接名从配置读取 |
| 卡尔曼滤波 | `safety/hand_trajectory_filter.py` | 人手轨迹 Kalman 滤波，零任务依赖 |
| 结构化日志 | `safety/logger.py` | CSV 流式写入 + Parquet 转存，字段可扩展 |
| 指标聚合 | `safety/metrics.py` | 干预率/误停率/漏判率/活锁比/replan成功率 |
| Layer 2 训练/推理 | `safety/layer2/` | ML 管道（特征提取→训练→预测），在数值特征向量上运行 |
| Replan 类型 | `safety/replan/types.py` | `ReplanRequest`/`ReplanResult`/`MotionReplanExecutor`（抽象基类） |
| Replan 触发 | `safety/replan/triggers.py` | 持续 SLOW/STOP 计数、TTC 门控、冷却期，触发逻辑任务无关 |
| VLM 客户端 | `vlm/` | `VLMClient` — HTTP → Qwen 推理，prompt 可替换 |
| 感知客户端 | `perception/` | GDINO+SAM2 → `/ground` + `/track`，text_prompt 可配置 |
| 夹爪监督 | `safety/vlm_grasp_supervisor.py` | VLM 周期检查持件状态，prompt 可替换 |
| 功能风控 | `safety/functional_risk.py` | 重抓上限 + 放置区检查，规则可配置 |

### 2.2 需配置调整（零代码改动）

| 配置项 | 文件 | 需调整内容 |
|:------|:-----|:-----|
| 工作空间边界 | `safety_layer1.yaml` | `workspace: {x, y, z}` — 新机器人可达范围 |
| 静态/TTC 阈值 | `safety_layer1.yaml` | `safe_dist_hard_stop`、`ttc_threshold` 等需根据新任务标定 |
| 减速系数 | `safety_layer1.yaml` | `slow_down_alpha`、`slow_down_alpha_ttc` — 新机器人动力学 |
| 人手轨迹 | `safety_layer1.yaml`、`ivj/*.yaml` | `human_trajectory: {start_pos, end_pos, ...}` — 新场景路径 |
| 包络臂段名 | `safety_layer1.yaml` | `envelope.arm_link_names` — 不同机械臂 FK 链接名 |
| 夹爪指尖名 | `safety_layer1.yaml` | `envelope.fingertip_link_names` — 不同末端执行器 |
| 夹持物尺寸 | `safety_layer1.yaml` | `envelope.held_box_dims_m` — 不同抓取物几何 |
| VLM prompt | `vlm_client.yaml` | 场景描述 prompt — 需包含新任务上下文 |
| 感知 prompt | `perception_client.yaml` | `text_prompt` — 新场景中需检测的物体关键词 |
| Replan 几何参数 | `safety_layer1.yaml` | `replan_lateral_offset_m`、`replan_detour_stage_duration` |
| 躯干尺寸 | `safety_layer1.yaml` | `human_torso_radius`、`human_torso_offset` |

### 2.3 需重写/新建的模块

| 模块 | 行数 | 内容 | 接口要求 |
|:------|:----:|:-----|:-----|
| **新任务策略** | ~800 行 | 替代 `pick_and_place_policy.py`：定义任务阶段机、路点序列、抓/放判定 | 需实现 §3 中的策略接口 |
| **新环境配置** | ~400 行 | 替代 `gmrobot_env_cfg.py`：Isaac Lab 场景（机器人、工具、物体、相机）、观测 schema | `obs["policy"]`、`obs["safety"]` 键名需保持一致 |
| **Replan 阶段映射** | ~30 行 | `replan/executor.py` `_phase_detour_params()`：将新任务阶段名映射到几何约束 | transit/approach/place 语义映射 |
| **Agent 入口** | ~20 行 | `gm_state_machine_agent.py`：更新策略类导入和观测键名 | — |
| **IV-J 场景库** | 若干 YAML | `configs/ivj/`：新任务的干预验证场景 preset | 遵循 `registry.yaml` schema |

---

## 3. 安全系统与任务策略的接口契约

安全系统通过 **8 个 duck-typed 方法/属性** 与任务策略交互。迁移到新任务时，策略类只需实现以下接口：

```python
class NewTaskPolicy:
    """安全系统期望的策略接口（duck-typed，非显式 ABC）。"""

    # ── 属性 ──────────────────────────────────

    time_step: int
    """当前轨迹路点索引。安全门控在 STOP/SLOW_DOWN 期间冻结，
    仅 ALLOW 时推进。"""

    time_stamps: np.ndarray
    """每个路点的时间戳 (N,) 数组。Replan 路线冲突检查用。"""

    pos_traj: np.ndarray
    """每个路点的 EE 位置 (N, 3) 数组。Replan 路线冲突检查用。"""

    # ── 方法 ──────────────────────────────────

    def transport_phase_at_step(self, step: int) -> str:
        """返回指定步的任务阶段，至少包含以下语义分类之一：
        - "transit"   — 运输段（横向余量大，可安全绕行）
        - "approach"  — 接近段（受限绕行，仅 EE-centric splice）
        - "place"     — 放置段（最小偏移，可能 defer splice → wait-hold）
        安全系统用此决定 replan 策略和 defer 行为。
        """

    def is_carrying_object(self, step: int) -> bool:
        """返回指定步是否夹持有物体。
        影响：held-box 包络原语是否激活；held-aware 绕行策略选择。
        """

    def splice_replan_detour(self, request: ReplanRequest,
                             executor: MotionReplanExecutor) -> bool:
        """在轨迹中插入绕行路点。
        Args:
            request: 触发原因 + 当前运动学 + 策略提示
            executor: 提供策略选择器和几何计算
        Returns:
            True 表示路点序列已修改（任务从新路点继续）。
        典型实现：executor.select_strategy(request) → executor.compute_detour(...)
        → 插入新路点 → 更新 time_stamps/pos_traj → 返回 True。
        """

    def maybe_rewind_for_failed_grasp(self, obs: dict) -> bool:
        """检查夹爪是否稳定持件，不稳定则回退路点。
        Returns: True 表示发生了回退。安全系统据此更新 functional_risk 元数据。
        若无抓取动作的任务，始终返回 False 即可。
        """

    def validate_placement_at_step(self, step: int) -> bool:
        """检查指定步的放置动作是否有效（物体已在目标区）。
        若无放置动作的任务，始终返回 True 即可。
        """
```

---

## 4. 观测接口契约

安全系统从 Isaac Lab 环境中读取以下观测组，迁移时保持键名一致即可无缝接入：

```python
obs = {
    "policy": {
        "ee_pos": np.ndarray  # shape (7,) — xyz + quat(wxyz)，世界坐标系
    },
    "safety": {
        "ee_vel": np.ndarray,           # shape (3,) — EE 线速度
        "human_hand_pos": np.ndarray,   # shape (3,) — 人手球心世界坐标
        "human_hand_vel": np.ndarray,   # shape (3,) — 人手球体线速度
        "joint_pos": np.ndarray,        # shape (6,) — 臂关节位置
        "joint_vel": np.ndarray,        # shape (6,) — 臂关节速度
    },
    # "camera": {"scene_rgb": ...} — 可选，Layer 3 VLM/Perception 需要
}
```

---

## 5. 迁移步骤清单

### 5.1 第一步：新环境配置（~400 行）

1. 创建 `NewTaskEnvCfg`，遵循 Isaac Lab `DirectRLEnvCfg` 或 `ManagerBasedRLEnvCfg`
2. 在场景中加入 `human_hand`（球体 r=0.05 m, kinematic）和可选 `human_torso`
3. 配置观测组 `policy` 和 `safety`，保持 §4 中的键名
4. 如果需 Layer 3 VLM/Perception，加入 `TiledCameraCfg`（参考 [`GM-SafePick_添加相机技术文档.md`](./GM-SafePick_添加相机技术文档.md)）
5. 设置 `sim.dt=1/200`，`decimation=4` → `control_dt=0.02 s` → 50 Hz

### 5.2 第二步：新任务策略（~800 行）

1. 实现 §3 中的完整策略接口
2. 定义任务阶段机（如焊接：`move_to_weld → descend → arc_on → hold → lift → move_to_next`）
3. 将阶段映射到安全系统能理解的三种运输阶段语义：
   - `"transit"` — 焊接任务中焊枪在焊点间移动
   - `"approach"` — 焊枪下降接近工件
   - `"place"` — 焊枪接触工件执行焊接（最小偏移）
4. 实现 `splice_replan_detour()` — 可用 `GeometryReplanV0.select_strategy()` 和 `compute_detour()`
5. `maybe_rewind_for_failed_grasp()` 和 `validate_placement_at_step()` 可根据任务语义实现或返回 False/True

### 5.3 第三步：安全配置标定（YAML）

1. **工作空间边界**：根据新机器人 reach 和新桌面/工作区尺寸设定
2. **静态距离阈值**：在安全场景中跑几次校准运行，确定 `safe_dist_hard_stop` 和 `safe_dist_warn`
3. **TTC 阈值**：根据新机器人的最大速度和典型人手接近速度标定
4. **包络参数**：更新 `arm_link_names`、`fingertip_link_names`、`held_box_dims_m`
5. **人手轨迹**：设计新的干预验证场景（替代 IV-J preset）

### 5.4 第四步：Replan 适配（~50 行）

1. 在 `replan/executor.py` `_phase_detour_params()` 中更新阶段名映射
2. 在 `replan/strategy.py` 中，如果新任务有完全不同的避障需求，可扩展策略选择器
3. 如果新任务没有「夹持物」概念，`held_critical` 条件永远不会触发，不影响运行

### 5.5 第五步：Layer 3 适配（可选）

1. **VLM prompt**：更新 `SAFETY_SYSTEM_PROMPT`（在 `vlm_client.yaml` 或代码中），描述新任务的正常/异常状态
2. **Perception prompt**：更新 `text_prompt`，从 `"gloved hand . robot gripper"` 改为新场景中需检测的物体关键词
3. **VLM Grasp Supervisor**：更新 prompt，描述新任务中「正常持件」的视觉特征

### 5.6 第六步：场景库（可选）

按 `configs/ivj/registry.yaml` schema 创建新 IV-J preset，覆盖：
- `far_observer` — 基线低干预（人手远离）
- `shoulder_pass` — 人手挡通道
- `block_place` — 人手挡操作位
- `fast_sweep` — 快速扫过
- `intrusion_positive` — 侵入正样本

---

## 6. 架构分层图

```
 ┌─────────────────────────────────────────────────────────┐
 │              安全核心 (~2500 行，零修改复用)                │
 │                                                         │
 │  SafetyState  ←  RuleEngine  →  GateDecision            │
 │       ↑              ↑              ↓                   │
 │  [ee, hand,     [static/TTC/    [ALLOW/STOP/            │
 │   joints]        workspace]       SLOW_DOWN]            │
 │                                                         │
 │  SafetyGate  ·  EnvelopeEvaluator  ·  SafetyFusion      │
 │  GroundTruth  ·  GtBranches  ·  SafetyLogger  ·  Metrics│
 │  HumanMotionController  ·  KalmanFilter                 │
 │  ReplanRequest/Result  ·  L1WarnReplanTrigger            │
 │                                                         │
 └──────────────────────┬──────────────────────────────────┘
                        │
         薄接口 (8 个 duck-typed 方法)
         transport_phase_at_step() / is_carrying_object()
         splice_replan_detour() / pos_traj / ...
                        │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
    ▼                   ▼                   ▼
┌───────────┐    ┌───────────┐    ┌───────────┐
│ Pick &    │    │ 焊接任务    │    │ 装配任务    │
│ Place     │    │            │    │            │
│ (当前)    │    │ 策略 ~800行 │    │ 策略 ~800行 │
│ 策略 800行│    │ 环境 ~400行 │    │ 环境 ~400行 │
│ 环境 400行│    │            │    │            │
└───────────┘    └───────────┘    └───────────┘
```

---

## 7. 不适合直接迁移的场景

| 场景特征 | 原因 | 需要的额外工作 |
|:------|:-----|:-----|
| 非手臂式机器人（移动底盘、无人机） | 包络系统基于机械臂 FK 链接；工作空间边界语义不同 | 替换包络评估器（`envelope.py`），实现新的碰撞距离计算 |
| 无明确阶段结构的连续操作 | 安全系统的 STOP/hold + replan 机制依赖「路点→冻结→恢复」模型 | 需设计新的安全介入与恢复语义 |
| 多机器人协调 | 当前 `SafetyState` 仅建模单个 EE 和单个人手 | 扩展 `SafetyState` 支持多 EE/多障碍物 |
| 纯视觉任务（无特权观测） | L1 TTC/距离计算依赖 `human_hand_pos`（仿真特权观测） | 需在 Layer 3 感知输出上构建距离估计（SAM2 `/track` + 深度），替换特权观测依赖 |

---

## 8. 与相关文档的链接

| 文档 | 角色 |
|:------|:-----|
| [GM-SafePick_架构总览.md](./GM-SafePick_架构总览.md) | 三层安全架构定义 |
| [GM-SafePick_Layer1_规则安全层.md](./GM-SafePick_Layer1_规则安全层.md) | 核心规则引擎契约 |
| [GM-SafePick_添加相机技术文档.md](./GM-SafePick_添加相机技术文档.md) | 相机观测接口 |
| [GM-SafePick_AI服务器部署.md](./GM-SafePick_AI服务器部署.md) | VLM/Perception 服务端部署 |
| [adr/GM-SafePick_Phase3.5_MotionReplan契约.md](./adr/GM-SafePick_Phase3.5_MotionReplan契约.md) | MotionReplan 接口契约 ADR |
