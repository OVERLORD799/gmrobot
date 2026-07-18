# GMDisturb 多角度对抗性审查 (2026-07-10) — 第 2 次

> **范围**: 全量源码 + 全量文档。前次审查 (2026-07-01, 26 issues) 及修复 (2026-07-10, 11 issues) 已闭合。
> **角度**: 正确性 · 鲁棒性 · 安全性 · 性能 · 架构 · 测试覆盖 · 文档一致性
> **方法**: 逐文件对照文档声称行为 vs 代码实际行为。
>
> **后续审查**: [adversarial-review-ponytail-2026-07-10.md](adversarial-review-ponytail-2026-07-10.md) — 第 3 次 (ponytail 深度版)，发现 2 CRITICAL (SSH 凭据泄露 + VLM prompt 错位) 及修复验证。

---

## 发现汇总

| 严重度 | 数量 | 关键主题 |
|--------|------|---------|
| 🔴 CRITICAL | 0 | — (前次 C1-C4 已修复) |
| 🟠 HIGH | 3 | vy=0 单轴游走、表面距离可负、碰撞过滤静默失败 |
| 🟡 MEDIUM | 10 | W3 修复不完整、drop 匹配缺失、dt 硬编码、batch 模式 _done 泄漏 等 |
| 🟢 LOW | 4 | 文档过时、指标口径不一致、死代码 等 |

---

## 🔴 CRITICAL — 无新发现

前次审查的 C1-C4 (表面距离、速度跳变、桌边不等式、阶段计数) 已全部修复，本轮未发现新的 CRITICAL 问题。

---

## 🟠 HIGH

### H1. `_generate_schedule` vy=0 导致单轴游走，与文档矛盾

**位置**: [g1_disturbance_controller.py:447-456](../../g1_disturbance_controller.py#L447-L456)

**问题**: 代码中 `vy = 0.0  # lateral movement disabled` 硬编码。ARCHITECTURE.md 描述的随机游走行为是 `vy∈[-0.2, 0.2]`，DATA_FLOW.md 也是 `vy∈[-0.2, 0.2]`。实际运行时 G1 仅在 x 轴上前进/后退，y 轴变化仅来自 `_boundary_steer` 和 `_steer_away` 的修正偏置——不是随机探索。

**影响**: 
- 游走覆盖面积从 0.8×1.0 m² 降为 0.8×0.02 m² (仅边界反弹产生 y 偏移)
- UR10e 工作空间 y∈[-0.5, 0.5]，G1 绝大部分时间在 y=0 线上——容器 A (y=-0.25) 和容器 B (y=+0.25) 几乎不会被随机触达
- 10k 步测试中 min distance=0.861m (从未进入 moderate zone) 的可能根因：G1 实际从未偏离 y=0 中线，距离 UR10e EE 始终 >0.8m

**修复**: 恢复 vy 随机采样，或至少用 ±0.05 的窄带（注释中写"most stable for walking policy"但 0.0 过于保守）。如果横向移动确实导致摔倒，应在配置参数中暴露而非硬编码为 0。

```
# 最小修复: 窄带横向游走
vy = rng.uniform(-0.05, 0.05)
```

---

### H2. 表面距离可为负值——RuleEngine 可能收到负距离

**位置**: [safety_adapter.py:267-269](../../safety_adapter.py#L267-L269)

**问题**: 
```python
surface_dist = center_dist - radius - self._ee_radius
```
当躯干 (radius=0.20) 和 EE (radius=0.08) 半径之和 (0.28m) 大于中心距时，`surface_dist < 0`。GMRobot RuleEngine 的 `hard_stop=0.13m` 是正阈值——如果收到负值，`dist < 0.13` 恒为 True，但 RuleEngine 内部可能有 `max(0, dist)` 或直接崩溃，取决于其实现。

**触发条件**: G1 躯干中心距 UR10e EE < 0.28m 时 (AGGRESSIVE 模式下的碰撞场景)。

**修复**: 对 surface_dist 做下限裁剪:
```python
surface_dist = max(0.0, center_dist - radius - self._ee_radius)
```
或改为传递原始 `center_dist` 并在 `build_safety_state` 文档中说明距离语义。

---

### H3. 碰撞过滤 ImportError 静默 pass——AGGRESSIVE 模式有 PhysX 崩溃风险

**位置**: [dual_env_cfg.py:810-811](../../dual_env_cfg.py#L810-L811)

**问题**:
```python
except ImportError:
    pass
```
如果 `omni.physx` 不可用 (比如 Isaac Lab 版本升级改了包名)，碰撞过滤静默失败。此时 G1↔UR10e 物理碰撞响应保持激活。在 AGGRESSIVE 模式下，两个复杂 articulation 碰撞会产生巨大接触力，可能导致:
- PhysX 求解器发散 (NaN velocities)
- 仿真崩溃 (segfault)
- 接触缓冲区溢出 (即使已设为 2^24)

后两个尤其隐蔽——不是立即崩溃而是运行一段时间后随机崩溃。

**修复**: ImportError 时不应静默 pass，应:
1. 检查 `gpu_max_rigid_contact_count` 是否已设置
2. 打印 **红色** 警告 (不是普通 print)
3. 如果用户指定了 AGGRESSIVE 模式且碰撞过滤不可用 → 报错退出，不要继续
4. 如果是 MODERATE/CAUTIOUS 模式 → 允许继续但打印警告

---

## 🟡 MEDIUM

### M1. W3 修复不完整——仍追踪肩膀和肘部

**位置**: [safety_adapter.py:23-32](../../safety_adapter.py#L23-L32)

**问题**: W3 (多体包络过度敏感) 的 GMDisturb 侧修复方案明确要求"仅报告手部 (left/right_wrist_pitch_link) 和头部"。但 `TRACKED_BODIES` 实际包含 8 个 body:
- torso_link (radius=0.20) — 仅用于 human_torso，不参与 closest-body
- head_link (0.12)
- left/right_shoulder_pitch_link (0.07 each)
- left/right_elbow_link (0.07 each)
- left/right_wrist_pitch_link (0.05 each)

肩膀和肘部的半径 (0.07) 是手腕 (0.05) 的 1.4 倍。在密集靠近场景中，肩膀/肘部会先于手腕触发 closest-body 计算，导致安全门对"手臂靠近"而非"手靠近"做出反应——这正是 W3 要解决的问题。GM-SafePick 的补抓恢复是针对末端夹爪掉落设计的，肩膀碰撞不需要触发 STOP。

**修复**: 将 `TRACKED_BODIES` 缩减为 `["head_link", "left_wrist_pitch_link", "right_wrist_pitch_link"]`，或新增 `SAFETY_BODIES` 变量与 `TRACKED_BODIES` 分离——后者保留 8 体用于日志/监控，前者仅 3 体用于安全门。

---

### M2. 掉落检测缺零件匹配——ARCHITECTURE.md 描述的功能未实现

**位置**: [mat_event_detector.py:188-224](../../mat_event_detector.py#L188-L224)

**问题**: ARCHITECTURE.md §MatEventDetector 步骤 3 明确描述:
```python
part_id = argmin(dist(c.world_xy, part_positions))
```
但 `_detect_drops` **不接受 `part_positions` 参数**，也不做任何零件匹配。`MatEvent` 数据类没有 `part_id` 字段。这意味着:
- 无法区分"零件 3 掉落"和"零件 7 掉落"
- Episode 汇总中 `knock_off_part_ids` (D06) 永远为空
- 无法统计哪些零件更容易被撞落

**修复**: 
1. `MatEvent` 增加 `part_id: int = -1` 字段
2. `detect()` 增加 `part_positions: dict[str, np.ndarray]` 参数
3. 在 `_detect_drops` 中对每个 drop 做最近邻匹配

---

### M3. 掉落检测无 workspace 空间过滤

**位置**: [mat_event_detector.py:188-224](../../mat_event_detector.py#L188-L224)

**问题**: `_detect_drops` 对整个 4m×4m 垫子做帧差检测，包括 G1 起始位置 (x=-1.5)。G1 脚步在砂砾/碎石地面上可能产生 >10N 的瞬态力变化，满足 `DROP_THRESHOLD`。这些脚步瞬态会被误分类为 `object_drop`。

对比 `_classify` 方法——它正确地加了 `WORKSPACE_X_RANGE` 过滤。但 `_detect_drops` 没有等价过滤。

**修复**: 在 `_detect_drops` 中增加: 仅当 `wx` 在 `WORKSPACE_X_RANGE` 内时才分类为 `object_drop`。

---

### M4. `_classify` collision_impact 缺 y 轴过滤

**位置**: [mat_event_detector.py:183](../../mat_event_detector.py#L183)

**问题**:
```python
if total_force >= COLLISION_FORCE and (WORKSPACE_X_RANGE[0] <= wx <= WORKSPACE_X_RANGE[1]):
    return "collision_impact"
```
只检查 x∈[0.3, 1.0]，不检查 y。UR10e 工作空间 y∈[-0.5, 0.5]。垫子边缘 (y≈±2.0) 的高力事件 (如 G1 脚步) 会被误标为 collision_impact。

**修复**: 增加 y 轴范围检查，或使用 `WORKSPACE_Y_RANGE = (-0.5, 0.5)`。

---

### M5. `_detect_and_handle_stuck` 硬编码 dt=0.02

**位置**: [g1_disturbance_controller.py:558](../../g1_disturbance_controller.py#L558)

**问题**:
```python
actual_speed = actual_disp / 0.02  # approximate instantaneous speed
```
`dual_env_cfg.py` 中 `decimation = 4` 且 `sim.dt = 0.005` → 控制 dt = 0.02。但如果有人改了 decimation (如改为 2 → dt=0.01)，实际速度会被低估一半，导致 stuck detection 漏报 (应该检测到的卡住被 `STUCK_ACTUAL_SPEED_MAX` 放过)。

**修复**: 将 `dt` 作为构造函数参数传入，或从 env 的 `physics_dt * decimation` 读取。

---

### M6. `_scripted_command` 强制报告 AGGRESSIVE mode

**位置**: [g1_disturbance_controller.py:652](../../g1_disturbance_controller.py#L652)

**问题**:
```python
self._mode = DisturbanceMode.AGGRESSIVE
```
在 `_scripted_command` 中无条件设置。当 G1 在 MODERATE 距离带 (0.15-0.30m) 时，主循环在 scripted command 后应用 `self._cmd[:2] *= self.speed_moderate` 降速——行为正确。但 `self._mode` 已被覆盖为 AGGRESSIVE，导致:
- `controller.mode` 属性返回 AGGRESSIVE (错误)
- CSV 中记录的 mode 永远是 AGGRESSIVE (即使实际运行在 MODERATE 速度)
- 无法从日志区分"任务在 AGGRESSIVE 带完成"和"任务在 MODERATE 带完成"

**修复**: `_scripted_command` 不覆盖 `self._mode`，保留主循环中 distance-gated 的 mode。

---

### M7. `_fix_ur10e_position._done` 跨 episode 泄漏

**位置**: [dual_env_cfg.py:729-746](../../dual_env_cfg.py#L729-L746)

**问题**: `_done` 标志作为函数属性存储。在单 episode 场景下正确——第一次 reset 修正 UR10e 位置，后续 reset 跳过。但在 batch runner 场景下:
1. Env 被销毁 → 创建新 env → 新 env 调用 reset → `_fix_ur10e_position` 已标记 `_done=True` → 跳过
2. 新 env 的 UR10e 在 USD 默认偏移位置 (-1.08, 2.35, 0) 而非 (0, 0, 0)
3. IK 目标不可达，所有零件操作失败

**修复**: 使用 env 实例属性而非模块级函数属性，或在 `env.reset()` 的完整 teardown/setup 路径中重置标志。更根本的方案：修改 UR10e USD 文件消除内置偏移。

---

### M8. ARM_JOINT_INDICES 无运行时名称校验

**位置**: [g1_arm_controller.py:23](../../g1_arm_controller.py#L23)

**问题**: `ARM_JOINT_INDICES = [11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]` 是硬编码的索引，假设 G1 的 29-DOF 关节顺序不变。如果:
- G1 USD 更新 (关节增删/重排)
- 使用不同的 G1 变体 (如 G1_927_WALK_CFG 升级)
这些索引会静默指向错误关节。写错关节可能: 无效果 (浪费计算)、破坏平衡 (写腰部关节)、损坏仿真 (写超出物理限制的值)。

**修复**: 在 `apply()` 中增加断言:
```python
assert all(robot_g1.joint_names[idx] in G1_ARM_JOINT_NAMES for idx in ARM_JOINT_INDICES)
```

---

### M9. `_stuck_retreat_command` fallback 使用全局 np.random

**位置**: [g1_disturbance_controller.py:607-610](../../g1_disturbance_controller.py#L607-L610)

**问题**: 游走 schedule 使用 `np.random.RandomState(42)` 确保可复现，但 stuck recovery 的 fallback 路径使用全局 `np.random`:
```python
angle = np.random.uniform(-np.pi * 0.6, np.pi * 0.6)
```
这导致 stuck recovery 行为不可复现——同一个 seed 的同一次运行，stuck 时的撤退方向不同。对于调试卡住问题，不可复现 = 无法定位。

**修复**: 在 `__init__` 中创建 `self._rng = np.random.RandomState(seed)`，所有随机调用统一使用。

---

### M10. 4 个脚本化场景是死代码

**位置**: [g1_disturbance_controller.py:103-137](../../g1_disturbance_controller.py#L103-L137)

**问题**: `TABLE_BUMP_PHASES`、`OBJECT_PUSH_PHASES`、`CIRCULATE_PHASES`、`COMBINED_PHASES` 在代码中定义完整，且注册在 `SCENARIOS` 字典中。但 SCENARIOS.md 标明了这些场景:
- `table_bump`: ❌ 无执行路径
- `object_push`: ❌ 需要手臂控制 (G1 行走策略不支持)
- `circulate`: ❌ 无执行路径
- `combined`: ❌ 需要手臂控制

**影响**: 
- ~100 行死代码
- `SCENARIOS` dict 中 `constrained_wander: None` 和 `vlm_explore: None` 语义不明确 (None 表示"用默认随机游走"还是"未定义"?)
- 如果有人通过 CLI `--scenario table_bump` 调用，controller 会加载 phases 但 scenario 实际效果取决于 G1 能否物理撞到桌子 (未验证)

**修复**: 要么补齐执行路径使这些场景可用，要么删除死代码，保留 SCENARIOS.md 中的 YAML 定义作为"计划"即可。

---

## 🟢 LOW

### L1. INTERFACES.md 过时——VLM 状态标记错误

**位置**: [INTERFACES.md:19](../../docs/INTERFACES.md#L19)

**问题**: `g1_vlm_disturbance.py` 标记为 `🔲 SPEC_ONLY`。但 project-delivery.md §3.4 确认 VLM 导航 "Working End-to-End"，实际实现在 `g1_vlm_client.py`。接口文档与实际代码不一致。

**修复**: 更新 INTERFACES.md 反映实际状态。

---

### L2. EpisodeMetrics 距离口径不一致

**位置**: [test_metrics.py:49-50](../../test_metrics.py#L49-L50) vs [safety_adapter.py:269](../../safety_adapter.py#L269)

**问题**: `EpisodeMetrics` 记录 `g1_ur10e_distance` 来自 `G1DisturbanceController.distance`——根中心到 EE 中心的 XY 距离。但安全门实际使用的是 `G1EnvelopeAdapter.closest_body_distance`——最近身体部件表面到 EE 表面的距离。两者语义不同:
- Controller: root_xy ↔ ee_xy (中心距, 仅 XY 平面, >0.8m for AGGRESSIVE)
- Adapter: body_surface ↔ ee_surface (表面距, 3D, 可 <0.13m)

CSV 中 `min_g1_ur10e_distance_m: 0.861` 看起来"G1 从未靠近 UR10e"，但实际可能是 adapter 的表面距已经触发过 STOP。无法从 CSV 验证安全门的实际触发距离。

**修复**: CSV 增加 `min_surface_distance_m` 列 (来自 adapter)。

---

### L3. 虚拟手 attractor 硬编码

**位置**: [g1_virtual_hand.py:53,104-108](../../g1_virtual_hand.py#L53)

**问题**: `attractor=(0.8, 0.0)` 和 `corridor_x=0.75` 硬编码。如果容器布局改变 (如 A/B 位置调整)，虚拟手仍向旧位置漂移，可能在无 UR10e 活动的区域产生干扰。

**修复**: 从 `CONTAINER_POSES` 读取或作为构造参数传入。

---

### L4. `_PHASE_PERIOD` 命名不一致

**位置**: [dual_env_cfg.py:56](../../dual_env_cfg.py#L56)

**问题**: 从 mdp 公开导出为 `PHASE_PERIOD`，但导入为 `_PHASE_PERIOD` (带下划线)。带下划线的命名约定通常表示模块私有——但它在 dual_env_cfg.py 的观测配置中被使用，不是私有场景。

**修复**: 统一为 `PHASE_PERIOD`。

---

## 审查角度交叉矩阵

| 发现 | 正确性 | 鲁棒性 | 安全性 | 性能 | 架构 | 测试 | 文档 |
|------|--------|--------|--------|------|------|------|------|
| H1 vy=0 | ✓ | | ✓ | | | ✓ | ✓ |
| H2 负距离 | ✓ | ✓ | ✓ | | | | |
| H3 碰撞过滤 | | ✓ | ✓ | | | | |
| M1 W3不完整 | ✓ | | ✓ | | | | |
| M2 缺零件匹配 | ✓ | | | | | | ✓ |
| M3 drops无过滤 | ✓ | | | | | | |
| M4 y轴缺失 | ✓ | | | | | | |
| M5 dt硬编码 | | ✓ | | | | | |
| M6 mode覆盖 | ✓ | | | | | | |
| M7 _done泄漏 | ✓ | ✓ | | | ✓ | | |
| M8 索引未校验 | | ✓ | ✓ | | | | |
| M9 全局random | | | | | | ✓ | |
| M10 死代码 | | | | | ✓ | | |
| L1 文档过时 | | | | | | | ✓ |
| L2 口径不一致 | | | | | | | ✓ |
| L3 attractor硬编码 | | ✓ | | | | | |
| L4 命名不一致 | | | | | ✓ | | |

---

## 与前次审查的关系

前次审查 (2026-07-01, 26 issues) + 修复 (2026-07-10, 11 issues) 已闭合所有 CRITICAL。本轮 **H1 (vy=0)** 是新发现的最重要问题——它解释了 10k 步测试中 G1 从未进入 MODERATE zone (min distance=0.861m) 的现象。如果 vy 恢复随机采样，G1 将实际覆盖容器 A/B 区域，安全门触发次数会显著增加——这正是测试框架的目标。

H2 (负距离) 和 M1 (W3不完整) 是安全问题。H3 (碰撞过滤静默失败) 是鲁棒性问题，可能在 Isaac Lab 版本升级时触发。

其余 14 个 MEDIUM/LOW 问题是代码质量改进，不必立即修复但应在 Phase 5 前处理。
