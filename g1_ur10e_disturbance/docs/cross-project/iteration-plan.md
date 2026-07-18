# GMDisturb 迭代改进方案

## 核心流程

```
AGGRESSIVE → 暴露弱点 → GMRobot修复 → MODERATE验证 → CAUTIOUS回归 → 循环
（发现模式）              （被测系统）   （验证模式）    （回归模式）
```

## 三档测试模式

### CAUTIOUS — 耐力测试（默认）

用于日常回归和长时耐力测试。G1 在 30cm 开始减速，15cm 强制后退。确保 `time_step` 始终推进，replan 可触发。

```yaml
proximity: "cautious"
proximity_decel_start_m: 0.30
proximity_retreat_m: 0.15
```

- 测什么：持续干扰下的任务推进能力、replan 成功率、零件完成数
- 预期 GMRobot 行为：SLOW_DOWN → replan → 绕行 → 任务继续
- 好指标：高 task_completion_rate、低 intervention_rate

### MODERATE — 验证测试

用于验证 GMRobot 改进效果。G1 允许进入 warn band，不强制后退。

```yaml
proximity: "moderate"
proximity_decel_start_m: 0.20
```

- 测什么：改进后的 GMRobot 在中等扰动下的表现
- 预期 GMRobot 行为：改进项生效（如 velocity-aware warn 提前触发）
- 好指标：replan_trigger_rate 提升、tier0_rate 下降

### AGGRESSIVE — 边界发现

用于发现 GMRobot 安全层的边界和弱点。G1 全速靠近，不减速不退让。Tier0 STOP 触发记录为测试通过。

```yaml
proximity: "aggressive"
```

- 测什么：安全门响应延迟、Tier0 触发距离、物理接触是否发生
- 预期 GMRobot 行为：Tier0 STOP 在物理接触前触发
- 好指标：safety_latency_steps < 5、tier0_trigger_distance_m > 0.08m

## 实现优先级

| 迭代轮次 | GMDisturb 阶段 | 自修 | 发现 GMRobot 弱点 | 验证 |
|---------|---------------|------|------------------|------|
| **第 1 轮** | Phase 2 | 自修 1-13（框架就绪） | — | smoke test |
| **第 2 轮** | Phase 3 | 三档模式实现 | W1（defense 解耦） | AGGRESSIVE → MODERATE |
| **第 3 轮** | Phase 4 | A/B 对比设施 | W2（velocity-aware warn）, W5（PartTracker） | MODERATE → CAUTIOUS |
| **第 4 轮** | Phase 5+ | 文档/路径对齐 | W3（多体过滤）, W4（Tier0 超时） | 全模式覆盖 |

## 进度 (2026-07-05)

### Phase 1 ✅ 完成

- 双机器人场景加载：G1 + UR10e + 压力垫
- UR10e 定位修正：`write_root_state_to_sim` 修正 USD 内置偏移 (-1.08, 2.35)→(0,0)
- GMRobot 原生 UR10E_CFG 导入，ImplicitActuatorCfg 保留 FK 链路
- GMRobot 坐标系复制：地面 z=-1.05，桌面/UR10e/容器 z=0
- 双容器布局：A（满 20 零件）→ B（空）
- 20 零件搬运周期：`success=True`, 7420 步
- 烟雾测试：`ALL CHECKS PASSED`
- 自修 1-13 完成：路径、碰撞、观测、文档修复

### Phase 2 ✅ 完成

- G1 行走控制器：加载 `0121_walk.pt`，588D→12D
- UR10e 控制器：封装 `SingleEnvPickAndPlacePolicy`
- 安全适配器：G1EnvelopeAdapter，8 体 FK→human_hand/torso
- 垫子事件检测器：32×32→连通分量→足迹/碰撞/掉落分类
- G1 扰动控制器：workspace 约束随机漫步（Phase 3 接入速度注入）
- 测试指标：EpisodeMetrics + CSV 输出
- 场景相机：TiledCameraCfg 启用
- 集成脚本：`scripts/run_phase2.py`

### Phase 3 ✅ 完成 (2026-07-06)

- 扰动速度注入：替换 UniformVelocityCommandCfg，每步写入 vel_command_b
- 三档距离行为：CAUTIOUS (<0.15m 后退) / MODERATE (0.15-0.30m 减速) / AGGRESSIVE (>0.30m 全速)
- 安全层联合测试：G1EnvelopeAdapter → SafetyState → RuleEngine → SafetyGate，50Hz 门控
- IntEnum 修复：GateDecision.ALLOW=0 → `if gate_decision is not None`
- 卡住检测：速度误差 >100 步 → 随机方向/接触力撤退
- 脚本化场景：`arm_collision`, `arm_wave`，ScriptedPhase + SCENARIOS 字典
- `--stress` 模式：手部 Z 投影到 EE 高度
- 集成脚本：`scripts/run_phase3.py`

### Phase 4 ✅ 完成 (2026-07-06)

- G1ArmController：5 种动作原语，缓启动斜坡，倾斜保护回缩（当前阶段因行走策略限制不启用）
- G1VirtualHand：平滑随机游走虚拟手，桌边障碍，EE 吸引器，杆子可视化
- `--virtual-hand 0.8` CLI：STOP=8, SLOW=79（600 步随机漫步验证）
- 全局策略调研：H1 不换（全维度 G1 优），AMO 不用（遥操作），无可用全身策略
- 文档统一：`gmdisturb_docs/` 合并进 `docs/`，新增 `ROBOT_SELECTION.md` + `AMO_ANALYSIS.md`
- WalkJointAction 修复：仅写腿部关节，保留手臂/腰部目标

### 已知限制

- G1 行走策略 (0121_walk.pt) 未训练手臂运动 → 物理 arm_motion 会破坏平衡
- 当前无开箱即用的 G1 全身（手臂+腿）策略
- 8 个预定义场景中仅 `arm_collision`/`arm_wave` 可通过 CLI 运行
- 5 个 GMRobot 弱点 (W1-W5) 均定义了验证场景但未执行

### Phase 5 A/B 对比初步 (2026-07-07)

首次安全门 A/B 对比（虚拟手 0.8m，2000 步各一次）：

| 指标 | 无安全门 (baseline) | 有安全门 | 差异 |
|------|-------------------|---------|------|
| parts_placed | 4/20 | 4/20 | 相同 — 安全门不影响任务进度 |
| policy_steps | 1850 | 1850 | 相同 — 无冻结延迟 |
| STOP | 0 | **19** | 安全门有效拦截危险动作 |
| SLOW_DOWN | 0 | **64** | 安全门主动减速 |
| min_distance | 0.872m | 0.872m | — |

**初步结论**：安全门触发 83 次干预，但 UR10e 任务未被阻塞（零件数相同）。无 false positive 导致任务停滞。

### Phase 6 规划：导航 + 摄像头

基于 ARCHITECTURE.md §"辅助感知方案" 已有设计：

- **方案 9** (G1 头部相机)：在 `Bd435` body 上挂载 `TiledCamera`，输出 RGB (320×240)。用途：G1 第一人称视角，VLM 决策输入
- **方案 10** (G1 头部 LiDAR)：❌ 已评估，不采用。RayCasterCfg 不支持动态挂载到关节体（需要 USD 中预存 prim，创建方式与 TiledCamera 不同）。且仿真中 FK 全知（0ms 延迟、100% 准确）严格优于 LiDAR 点云（±2cm 噪声、100ms 延迟）。LiDAR 价值在真机部署阶段，仿真不需要。
- **方案 3** (VLM 全局推理)：复用现有 `scene_camera` RGB → VLM → 自适应扰动决策。已有 `vlm_explore` 场景定义
- **导航目标**：突破 G1 当前"工作台正面一侧"的活动限制，实现绕桌行走、跨工作区移动

### Phase 6 实际进度 (2026-07-07)

| 组件 | 状态 | 备注 |
|------|------|------|
| G1 头部相机 (D435, 320×240 RGB) | ✅ 已激活 | `obs["g1_head_camera"]["head_rgb"]`, 挂载在 d435_link |
| G1 头部 LiDAR (MID-360) | ❌ 不采用 | 见方案 10 分析 |
| VLM 导航决策 | 🔲 待接入 | 需要 VLM 服务端点 |
| 绕桌行走 | 🔲 待实现 | 依赖 VLM 决策输出

每个测试场景应标注它瞄准的 GMRobot 弱点：

| 场景 | 模式 | 瞄准弱点 | 关键指标 |
|------|------|---------|---------|
| `constrained_wander` | CAUTIOUS（默认） | 耐力基准 | task_completion_rate, replan_success_rate |
| `tier0_defense_freeze` | AGGRESSIVE | W1 | grasp_lost_detected, defense_detection_delay |
| `fast_sweep_replan_window` | AGGRESSIVE | W2 | first_slow_down_distance_m, replan_triggered, tier0_triggered |
| `multi_body_envelope_sensitivity` | MODERATE | W3 | intervention_rate_by_body, closest_body_distribution |
| `tier0_bilateral_deadlock` | AGGRESSIVE | W4 | tier0_duration_steps, protected_retract_triggered |
| `object_push` | MODERATE | W5 | parts_on_floor, part_tracker_detection_rate |
| `arm_collision` | MODERATE | W1+W2 | defense_cooldown_while_stopped, replan_triggered |
| `table_bump` | CAUTIOUS | 回归 | intervention_rate（应不增加） |

## GMRobot 文档修正

在整理文档过程中发现的 GMRobot 文档问题，已同步修正：

1. **架构总览控制频率**：多处 "20 Hz" → "50 Hz"，与 Layer1 §0 权威值对齐。详见 [gmrobot/架构总览.md](../gmrobot/架构总览.md)（已直接在副本中标注）
