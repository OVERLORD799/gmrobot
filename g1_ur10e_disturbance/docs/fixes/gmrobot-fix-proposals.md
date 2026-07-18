# GMRobot 修复提案

基于 GMDisturb 对抗分析，向 GMRobot 提出的改进建议。每个提案遵循：弱点描述 → 修复方案 → 验收标准。

> **GMDisturb 验证状态 (2026-07-06)**: 所有 5 个弱点的验证场景 (W1: tier0_defense_freeze, W2: fast_sweep_replan_window, W3: multi_body_envelope_sensitivity, W4: tier0_bilateral_deadlock, W5: object_push) 均已定义但**尚未执行**。提案中的定量证据需要 Phase 5 场景批量运行后采集。当前安全门功能已通过 `--virtual-hand` 模式验证（STOP=8, SLOW=79 at 0.8m radius）。

## 迭代流程

```
GMDisturb AGGRESSIVE 模式发现问题
  → 记录到本文档（新提案或更新已有提案）
  → GMRobot 团队评估 + 实现修复
  → GMDisturb MODERATE 模式验证
  → GMDisturb CAUTIOUS 模式回归
  → 关闭提案
```

## W1：Defense 计数器与 time_step 解耦

- **严重度**：🔴
- **状态**：open
- **影响文件**：`scripts/pick_and_place_policy.py`
- **GMDisturb 发现场景**：`tier0_defense_freeze`

**修复方案**：在 `advance_time_step()` 和相关 defense 方法中，将 cooldown 和 stabilization hold 计数器改为基于仿真步 `step_counter` 而非轨迹步 `time_step`。详见 [gmrobot-weaknesses.md](../cross-project/gmrobot-weaknesses.md#w1tier0-stop-冻结传播到-defense-计数器)。

## W2：Velocity-Aware Early Warning

- **严重度**：🟠
- **状态**：open
- **影响文件**：`safety/rule_engine.py`, `configs/safety_layer1.yaml`
- **GMDisturb 发现场景**：`fast_sweep_replan_window`

**修复方案**：在 RuleEngine 中增加速度感知规则——当 `dist_min` 变化率 > 0.5 m/s 且距离 < 0.40m 时提前进入 SLOW_DOWN。详见 [gmrobot-weaknesses.md](../cross-project/gmrobot-weaknesses.md#w2replan-对高速障碍物触发过慢)。

**与现有功能关系**：Phase 2.5 已有 `safe_dist_slow_far=0.35m`（纯距离阈值）。W2 在此基础上增加速度维度——同一距离下，高速靠近的障碍物比静止的障碍物更早触发 SLOW_DOWN。

## W3：包络障碍物类型感知

- **严重度**：🟡
- **状态**：open（GMDisturb 侧先做过滤）
- **影响文件**：`safety/envelope.py`, `safety/rule_engine.py`
- **GMDisturb 发现场景**：`multi_body_envelope_sensitivity`

**修复方案**：远期在 `EnvelopeEvaluator` 中增加障碍物尺寸/类型感知。详见 [gmrobot-weaknesses.md](../cross-project/gmrobot-weaknesses.md#w3多体障碍物使包络过度敏感)。

## W4：Tier0 超时恢复

- **严重度**：🟡
- **状态**：open
- **影响文件**：`safety/gate.py`, `configs/safety_layer1.yaml`
- **GMDisturb 发现场景**：`tier0_bilateral_deadlock`

**修复方案**：增加可选 `tier0_stop_timeout` 配置（默认关闭）。详见 [gmrobot-weaknesses.md](../cross-project/gmrobot-weaknesses.md#w4tier0-缺乏超时恢复机制)。

**关键约束**：默认关闭（`tier0_timeout_action: "hold"`），旧 preset 行为完全不变。仅在明确需要超时退出的场景中显式启用。

## W5：PartTracker FK Fallback

- **严重度**：🟡
- **状态**：open
- **影响文件**：`safety/part_tracker.py`
- **GMDisturb 发现场景**：`object_push`

**修复方案**：增加基于 Z 轴阈值的 FK 掉落检测，不依赖 VLM 相机。详见 [gmrobot-weaknesses.md](../cross-project/gmrobot-weaknesses.md#w5parttracker-零件掉落检测未完整集成)。
