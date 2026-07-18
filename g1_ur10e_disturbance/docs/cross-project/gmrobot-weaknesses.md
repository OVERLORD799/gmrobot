# GMRobot 弱点报告

通过 GMDisturb 对抗性分析发现的 GMRobot 安全层弱点。每个弱点遵循模板：发现场景 → 根因分析 → 修复方案 → 验证标准。

## W1：Tier0 STOP 冻结传播到 Defense 计数器

**严重度**：🔴

**发现**：当 GMDisturb 触发 Tier0 STOP（`dist_min < 0.13m`），GMRobot 的 `pick_and_place_policy.py` 中 `advance_time_step()` 不被调用。grasp-knock-defense 的 cooldown（5 步）和 stabilization hold（60 步）计数器依赖 `time_step` 推进——Tier0 期间这些计数器也冻结。物体可能已从夹爪掉落，defense 永远不检测。

**根因**：`advance_time_step()` 同时控制轨迹时钟和 defense 计数器，两者的推进绑定在同一个 `advance` 条件上。

**修复方案**：将 defense 计数器从 `time_step` 驱动改为仿真步 `step_counter` 驱动。在 `maybe_rewind_for_failed_grasp()`、`note_grasp_disturbance()`、`advance_time_step()` 中增加独立 defense 时钟：

```python
# 在 advance_time_step 中：
self._defense_step_counter += 1  # 始终递增，不受 STOP 影响
if self._stabilize_hold_steps > 0:
    self._stabilize_hold_steps -= 1
```

安全底线：`time_step` 仍然冻结（轨迹不推进），仅 defense 计数器独立运行。

**GMDisturb 验证场景**：`tier0_defense_freeze`（AGGRESSIVE 模式）

**验收标准**：
- `grasp_lost_detection_delay` < 50 仿真步
- `time_step_frozen_duration` 仍 > 200（安全底线未破坏）
- CAUTIOUS 回归：正常场景 defense 行为不变

## W2：Replan 对高速障碍物触发过慢

**严重度**：🟠

**发现**：G1 以 0.8 m/s 靠近时穿过 6cm warn band 仅需 ~0.075 秒（<4 控制步），远低于 replan 触发所需的 30 步连续 SLOW_DOWN。GMRobot 的远场减速（`safe_dist_slow_far=0.35m`）是纯距离阈值，不感知靠近速度——距 EE 0.30m 但静止的 G1 和距 0.30m 但以 0.8m/s 冲过来的 G1 行为相同。

**根因**：远场减速规则仅基于距离，缺少速度感知维度。

**修复方案**：在 RuleEngine 中增加 velocity-aware early warning 规则：

```python
# 新增 YAML 配置项
velocity_warn_enabled: true
velocity_warn_threshold_mps: 0.5
velocity_warn_dist_threshold_m: 0.40

# RuleEngine.evaluate() 中：
approach_speed = _compute_radial_approach_speed(dist_min, prev_dist_min, control_dt)
if approach_speed > velocity_warn_threshold_mps and dist_min < velocity_warn_dist_threshold_m:
    return GateResult(g_t=SLOW_DOWN, reason="velocity_warn")
```

约束：不改变 Tier0 阈值（0.13m）、不改变 warn band（0.13-0.19m）、仅在远场增加速度感知层。

**GMDisturb 验证场景**：`fast_sweep_replan_window`（AGGRESSIVE 模式）

**验收标准**：
- `first_slow_down_distance_m` ≥ 0.30m
- `replan_triggered` = true
- `tier0_triggered` = false
- CAUTIOUS 回归：低速时 intervention_rate 不增加

## W3：多体障碍物使包络过度敏感

**严重度**：🟡

**发现**：GMRobot Phase 2.5 全包络系统对障碍物类型无区分。G1 全身 37 体同时靠近时，`dist_min` 常由体积最大的躯干决定——但躯干的碰撞风险远低于指尖。当前所有 body 一视同仁，躯干过早触发 SLOW_DOWN。

**根因**：包络系统缺少障碍物类型感知。

**修复方案（两阶段）**：

**阶段 1 — GMDisturb 侧（立即）**：`G1EnvelopeAdapter` 仅报告手部（left/right_wrist_pitch_link）和头部给安全层。躯干、大臂、前臂在 GMDisturb 侧过滤——不参与 closest-body 计算。记录单独日志（若躯干 < 0.05m，告警）。

**阶段 2 — GMRobot 侧（远期）**：`EnvelopeEvaluator` 增加障碍物尺寸感知，大物体自动使用更大的有效距离阈值。

**GMDisturb 验证场景**：`multi_body_envelope_sensitivity`（MODERATE 模式）

**验收标准**：
- 躯干触发 SLOW_DOWN 比例下降 >50%
- 手部仍正常触发 SLOW_DOWN
- 无新增 false_allows

## W4：Tier0 缺乏超时恢复机制

**严重度**：🟡

**发现**：Phase 3.5 ADR 规定 Tier0 永久 STOP。这在单人手的场景下合理（人手移开即恢复）。但 G1 是 1.3m 高的人形机器人，可能因步态误差或控制器滞后卡在 Tier0 区——自己退不出去，UR10e 也不让动，双向死锁。

**根因**：Tier0 没有超时退出策略。

**修复方案**：增加可选的 tier0 超时机制：

```python
# YAML 配置（默认关闭，保持向后兼容）
tier0_stop_timeout_steps: 500
tier0_timeout_action: "protected_retract"  # "hold" = 现行为
protected_retract_speed: 0.02              # m/s，极慢
protected_retract_target: "home"

# RuleEngine 中：
if g_t == STOP and dist_min < safe_dist_hard_stop:
    self._tier0_consecutive_steps += 1
    if self._tier0_consecutive_steps >= tier0_stop_timeout_steps:
        if tier0_timeout_action == "protected_retract":
            return GateResult(g_t=PROTECTED_RETRACT)
```

约束：撤退速度极低（2cm/s）、撤退中继续监控距离、默认关闭（旧 preset 行为不变）。

**GMDisturb 验证场景**：`tier0_bilateral_deadlock`（AGGRESSIVE 模式）

**验收标准**：
- 500 步后 UR10e 开始缓慢撤退
- 撤退中 dist_min 增大或保持
- 旧 preset（不配 timeout_action）行为不变

## W5：PartTracker 零件掉落检测未完整集成

**严重度**：🟡

**发现**：GMRobot 代码审计 F11 标注 PartTracker VLM 重试机制"永远触发不了"。GMDisturb 需要准确的物理零件计数来做 episode 汇总，但当前无此能力。

**根因**：PartTracker 未接入 agent 主循环。

**修复方案**：增加基于 FK 的 fallback 检测（不依赖 VLM 相机）：

```python
def detect_parts_on_floor(self):
    for part_id, part_pos in self.part_positions.items():
        if part_pos[2] < TABLE_HEIGHT - 0.05:  # Z < 桌面下 5cm
            if part_id not in self._dropped_parts:
                self._dropped_parts.add(part_id)
                self._on_part_dropped(part_id)
```

VLM 启用时，VLM 检测与 FK 检测交叉验证。

**GMDisturb 验证场景**：`object_push`

**验收标准**：
- FK 检测掉落零件数 ≥ 1（扰动场景中）
- VLM+FK 一致性 > 80%（VLM 启用时）
