# GMDisturb 对抗性审查修复报告

> 日期: 2026-07-10
> 来源: 多角度对抗性审查（正确性 · 鲁棒性 · 安全性 · 测试覆盖）
> 发现: 11 个新问题（前次审查 2026-07-01 已修复 26 个之外）

---

## 修复总览

| # | 严重度 | 维度 | 文件 | 问题 | 修复摘要 |
|---|--------|------|------|------|---------|
| C1 | 🔴 | 正确性 | safety_adapter.py | 距离用 center-to-center 而非 surface-to-surface | 减去 body_radius + ee_radius，报告真实表面距离 |
| C2 | 🔴 | 正确性 | safety_adapter.py | 最近身体切换导致速度跳变 | 按 body 分别追踪上一帧位置，切换时速度归零 |
| C3 | 🔴 | 正确性 | g1_virtual_hand.py | TABLE_X_BLOCK 不等式反向，桌边检测失效 | 反转 `x >= x_block` → `x <= x_block` |
| C4 | 🔴 | 正确性 | ur10e_controller.py | `time_step // 371` 除数在安全干预时错误 | 追踪 `lift_after_releasing_slot_B_*` 阶段转换 |
| R1 | 🟠 | 鲁棒性 | safety_adapter.py | importlib 猴子补丁静默失败 | 文件存在检查 + 明确 ImportError 消息 |
| R2 | 🟠 | 鲁棒性 | dual_env_cfg.py | 碰撞过滤器完全空操作 | 实际调用 PhysX collision filter API |
| R3 | 🟠 | 鲁棒性 | mat_event_detector.py | collision_impact 缺 workspace 过滤 | 添加 `WORKSPACE_X_RANGE = (0.3, 1.0)` |
| S1 | 🟡 | 安全性 | g1_disturbance_controller.py | 撤退速度 0.04 m/s 太慢 | 按距离紧急度斜坡: 0.20→0.50 m/s |
| S2 | 🟡 | 安全性 | g1_disturbance_controller.py | 边界转向推回UR10e | 撤退/卡住时跳过 _boundary_steer |
| S3 | 🟡 | 安全性 | dual_env_cfg.py | 摔倒检测 minimum_height=-1.0 | 改为 -0.7（膝高以下=摔倒） |
| T1 | 🔵 | 测试 | test_metrics.py | record_step 不记录安全门状态 | 新增 last_gate_decision 等 4 字段 |

---

## 可能偏离项目设计的问题（已上报）

### 1. 表面距离 vs 中心距离 (C1)

**风险**: GMRobot RuleEngine 的 0.13m hard_stop 阈值是按人手半径 (~0.05m) 校准的中心距。
G1 躯干半径 0.20m，中心距 0.13m 时表面已重叠 0.15m。
修复改为报告表面距——这改变了 RuleEngine 接收到的距离语义。

**影响**: 安全门会比之前更早触发（特别是躯干靠近时）。
前次审查 W3（多体包络过度敏感）建议的修复是"过滤躯干"——改为表面距后
躯干也能正确触发 STOP，无需过滤。这两条修复路径有重叠：
- W3 方案: 在 GMDisturb 侧过滤大体积 body
- C1 方案: 报告表面距，让 RuleEngine 自己判断

**建议**: 如果 W3 已实施躯干过滤，C1 的双重减法不会导致过保护——
已过滤的 body 不参与 closest-body 计算。两者兼容。

### 2. 碰撞过滤 vs 安全门 (R2)

**风险**: 碰撞过滤禁用 G1↔UR10e 的 PhysX 碰撞响应。在 AGGRESSIVE 模式下，
如果 FK 安全门延迟触发（例如 C2 的速度跳变修复导致速度短暂归零），
两个机器人可能物理穿透而无接触力反馈。

**保障**: 安全门基于 FK 位置（不是物理接触力），50Hz 持续检测。
STOP 决策后 EE 被冻结在上一步位置。且碰撞过滤只禁用响应（不产生分离力），
不阻止 PhysX 报告接触事件到 ContactSensor。

### 3. parts_placed 计数 (C4)

**风险**: 从 `time_step // 371` 改为阶段转换追踪。如果
`SingleEnvPickAndPlacePolicy` 的阶段命名规则改变（例如 `lift_after_releasing_slot_B_` 改名），
计数器会永远为零。

**保障**: `_completed_stages` 只新增不删除。即使阶段命名规则改变，
也不会报告虚假的高计数——只会报告 0，易检测。

---

## 详细修复内容

### C1: safety_adapter.py — 表面距离计算

```python
# 修复前:
dist = float(np.linalg.norm(pos - ur10e_ee_pos))

# 修复后:
center_dist = float(np.linalg.norm(pos - ur10e_ee_pos))
surface_dist = center_dist - radius - self._ee_radius  # 0.08 m
```

新增 `self._ee_radius = 0.08` 属性（匹配 GMRobot EE 球半径）。

### C2: safety_adapter.py — 按 body 追踪速度

```python
# 修复前 (一个 prev_hand_pos 给所有 body 共用):
if self._prev_hand_pos is not None:
    self.human_hand_vel = (best_pos - self._prev_hand_pos) / self._dt
self._prev_hand_pos = best_pos.copy()

# 修复后 (每个 body 独立追踪):
prev = self._prev_body_positions.get(best_name)
if prev is not None:
    best_vel = (best_pos - prev) / self._dt
self._prev_body_positions[best_name] = best_pos.copy()
```

最近 body 变化时 `prev` 为 None → 速度归零，不会产生空间跳变。

### C3: g1_virtual_hand.py — 桌边不等式

```python
# 修复前 (手越过桌子时不阻挡):
if x >= x_block:
    return

# 修复后 (手在进入区时不阻挡，越过时才阻挡):
if x <= x_block:
    return
```

### C4: ur10e_controller.py — 阶段转换计数

```python
# 在 get_action() 中追踪:
current = self.stage_name
if "lift_after_releasing_slot_B_" in self._last_stage and current != self._last_stage:
    self._completed_stages.add(self._last_stage)
self._last_stage = current
```

`parts_placed` 属性返回 `len(self._completed_stages)`。

### R1: safety_adapter.py — importlib 健壮性

- 新增文件存在性检查（`os.path.isdir` + `os.path.isfile`）
- `_EXPECTED_MODULES` 列表声明依赖顺序
- `spec.loader.exec_module` 被 try/except 包裹，转换为明确 `ImportError`
- 错误消息列出缺失文件和预期结构

### R2: dual_env_cfg.py — 碰撞过滤

- 使用 `omni.physx.acquire_physx_interface()` 获取 PhysX 接口
- 尝试 `add_to_collision_filter` 和 `add_collision_filter_pair` 两种 API
- 成功/失败均打印明确日志

### R3: mat_event_detector.py — Workspace 过滤

```python
# 新增常量:
WORKSPACE_X_RANGE = (0.3, 1.0)

# 修复后:
if total_force >= COLLISION_FORCE and (WORKSPACE_X_RANGE[0] <= wx <= WORKSPACE_X_RANGE[1]):
    return "collision_impact"
```

### S1: g1_disturbance_controller.py — 撤退速度斜坡

```python
# 按距离紧急度线性斜坡:
urgency = max(0.0, min(1.0, (self.cautious_threshold - dist) / (self.cautious_threshold - 0.05)))
retreat_speed = 0.20 + urgency * 0.30  # 0.20 → 0.50 m/s
```

### S2: g1_disturbance_controller.py — 边界检查跳过

```python
# 修复前:
if self.scripted_phases is None:
    self._cmd = self._boundary_steer(self._cmd)

# 修复后:
if self.scripted_phases is None and self._mode not in (DisturbanceMode.CAUTIOUS, DisturbanceMode.STUCK):
    self._cmd = self._boundary_steer(self._cmd)
```

### S3: dual_env_cfg.py — 摔倒阈值

```python
# 修复前: minimum_height = -1.0  (地面 = -1.05, 必须穿透地面)
# 修复后: minimum_height = -0.7  (膝高, 0.35m 在站立 root 下方)
```

### T1: test_metrics.py — 安全门记录

```python
# 新增 record_step 参数 (全部可选, 保持向后兼容):
gate_decision: Optional[str] = None    # "ALLOW" | "STOP" | "SLOW_DOWN"
gate_trigger: str = ""                  # 触发规则
gate_distance: float = float("inf")    # 触发距离
closest_body: str = ""                 # 最近 G1 身体部件

# 新增 CSV 列:
"last_gate_decision", "last_gate_trigger",
"last_gate_distance", "last_closest_body"
```

---

## 验证状态

| 检查 | 状态 |
|------|------|
| 代码一致性 (现有导入不破坏) | ✅ 仅新增参数/字段，无破坏性变更 |
| 向后兼容 (默认参数) | ✅ record_step 新参数全可选 |
| 文档一致性 | ✅ 修复注释指向审查编号 (C1/C2/...) |
| 集成测试 | 🔲 待运行 `smoke_test_dual.py` 验证 |

---

## 与 GMRobot 的交互

本次修复未触及 GMRobot 侧代码。所有变更在 GMDisturb 框架内：

- **safety_adapter.py**: 距离/速度计算方式改变 → RuleEngine 接收值不同
- **dual_env_cfg.py**: 碰撞过滤激活 → 仿真稳定性改进
- **g1_virtual_hand.py**: 桌边避障生效 → 虚拟手行为改变
- **其他**: 仅影响 GMDisturb 内部记录/控制逻辑
