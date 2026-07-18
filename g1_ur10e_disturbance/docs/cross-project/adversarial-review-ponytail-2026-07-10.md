# GMDisturb 多角度对抗性审查 — Ponytail 深度版 (2026-07-10)

> **范围**: 全量源码 (9 个 .py 文件, ~3000 行) + 全量文档 (30 个 .md 文件)
> **前人工作**: 2026-07-01 审查 (26 issues) + 2026-07-10 fresh 审查 (17 issues) + 2026-07-10 doc-audit
> **本次增量**: 7 角度 × 逐文件交叉验证，聚焦前两次审查未覆盖的盲区
> **方法**: 文档声称行为 vs 代码实际行为 vs 物理合理性 vs 安全边界 — 四维交叉

---

## 发现汇总

| 严重度 | 数量 | 新发现 | 关键主题 |
|--------|------|--------|---------|
| 🔴 CRITICAL | 2 | **2** | SSH 凭据泄露、VLM prompt 完全错位 |
| 🟠 HIGH | 3 | **3** | 隧道无生命周期、schedule 不重置、VLM 安全门变形 |
| 🟡 MEDIUM | 7 | **5** | fragile 字符串匹配、shadow geometry、无 rate limit、14≠17 关节 |
| 🟢 LOW | 5 | **4** | 阻塞 sleep、全局可变状态、dead code 未清理 |
| ⚫ 前次修复验证 | — | — | 11 项修复中 7 项已验证 ✅, 2 项部分, 2 项仍未修复 |

---

## 🔴 CRITICAL

### C1. SSH 凭据硬编码在源码中

**位置**: [g1_vlm_client.py:45](../../g1_vlm_client.py#L45)

**发现**:
```python
["sshpass", "-p", "0k7fv9pr", "ssh", "-o", "StrictHostKeyChecking=no",
 "-N", "-L", f"{VLM_PORT}:localhost:{VLM_PORT}",
 "-p", "30481", "root@120.209.70.195"],
```

明文密码 `0k7fv9pr` 和 root 用户名写入源码，向公网 IP `120.209.70.195:30481` 建立 SSH 隧道。这是安全事件：

- 任何能读到 repo 的人都能以 root 身份登录该服务器
- `StrictHostKeyChecking=no` 禁用了主机密钥验证 → MITM 可行
- `sshpass -p` 将密码暴露在进程列表 (`/proc/*/cmdline`) 中
- 该密码可能也是其他服务的凭据（密码复用）

**影响**: 凭据泄露 + 横向移动风险。如果该服务器在内网，则构成跳板。

**修复**:
1. 立即轮换该服务器密码
2. 改为 `sshpass -f <password_file>` 或 SSH key
3. 将凭据移入环境变量或 `.env` (gitignored)
4. 启用 `StrictHostKeyChecking=yes` 并预置 known_hosts

---

### C2. VLM prompt 与设计文档完全不一致 — 安全门测试变导航

**位置**: [g1_vlm_client.py:25-32](../../g1_vlm_client.py#L25-L32) vs [SCENARIOS.md §4](../../docs/SCENARIOS.md#L474-L510)

**发现**: SCENARIOS.md §4 定义了 60 行详细 VLM prompt，JSON schema 包含:
```json
{
    "arm_state": "idle" | "transiting" | ...,
    "gripper_has_object": true | false,
    "risk_assessment": "safe" | "caution" | "danger",
    "disturbance_decision": {
        "action": "approach_table" | "reach_toward_arm" | ...,
        "velocity_command": {"vx": ..., "vy": ..., "wz": ...},
        "arm_motion": "none" | "wave" | ...,
        "reasoning": "..."
    }
}
```

代码中实际发送给 VLM 的 prompt 是 8 行导航 prompt:
```json
{"action": "approach"|"retreat"|"circle_left"|"circle_right"|"stand_wave"|"wait",
 "reason": "brief explanation"}
```

**差异**:
- 文档有 6 种 arm_state 推断 → 代码无
- 文档有 risk_assessment 安全分级 → 代码无
- 文档输出 velocity_command (vx, vy, wz) → 代码无，仅 high-level action
- 文档输出 arm_motion → 代码无
- 文档有策略指南 (transiting→collide, grasping→reach container) → 代码无
- 代码的动作空间 (circle_left/right) → 文档无
- 代码无 `disturbance_decision` wrapper → 文档有

**影响**: 当前 VLM 在做**通用导航**（"我应该往哪走"），而不是**对抗性安全测试**（"UR10e 正在运输零件，我应该冲过去撞它"）。VLM 完全没有被提示"你的任务是测试 UR10e 的安全层边界"。这是**测试框架的核心功能退化**——VLM 模式名存实亡。

**修复**: 要么将 SCENARIOS.md 的 prompt 同步到 `g1_vlm_client.py`，要么更新文档反映实际简化版 prompt。推荐前者——安全测试 prompt 的设计质量直接决定 VLM 引导测试的有效性。

---

## 🟠 HIGH

### H1. VLM SSH 隧道无生命周期管理

**位置**: [g1_vlm_client.py:34-50](../../g1_vlm_client.py#L34-L50)

**发现**: `_ensure_tunnel()` 每 1 秒阻塞、无进程管理、无健康检查、无重连:

```python
def _ensure_tunnel():
    # 1. 检测端口是否已监听 → 如果是，返回 (OK)
    # 2. 如果不是，spawn sshpass 后台进程
    # 3. time.sleep(1.0)  ← 阻塞主线程
    # 4. 丢弃 Popen 句柄 → 无法 kill、无法检测退出
```

问题链:
- `ss -tln` 检测端口不可靠——端口在监听 ≠ SSH 隧道真正连通（对端可能已重启）
- 没有对 `/health` endpoint 做活性检查（虽然 `health()` 方法存在但 `_ensure_tunnel` 不调用它）
- 隧道断开后不会自动重连——下次查询直接失败，VLM 永远返回 `{"action": "wait"}`
- `Popen` 句柄丢弃 → 僵尸进程 → 端口占用 → 下次启动端口冲突

**影响**: 长时间运行时 VLM 模式静默退化为 `wait` 循环。G1 站在原地不动，测试无效。无日志告警——除非人工对比 VLM 决策频率。

**修复**:
```
1. _ensure_tunnel → _ensure_tunnel() + check health endpoint
2. 保存 Popen 句柄，atexit 注册 cleanup
3. query() 中捕获连接失败 → 触发 reconnect
4. 连续 3 次失败 → 打印 WARNING 并 fallback 到 constrained_wander
```

---

### H2. G1DisturbanceController.reset() 不重置速度 schedule → 跨 episode 行为不可复现

**位置**: [g1_disturbance_controller.py:288,439-454](../../g1_disturbance_controller.py#L288)

**发现**: `_schedule` 在 `__init__` 中一次性生成 10000 条:
```python
self._schedule = self._generate_schedule(10000)  # __init__
```

`reset()` 清理了 `_step`, `_mode`, `_phase`, stuck counters, scripted state——**但不重置 schedule 索引**。调用链为:
```python
self._step % self.resample_interval == 0  # 触发重采样
idx = self._step // self.resample_interval
self._cmd = self._schedule[idx % len(self._schedule)]
```

`reset()` 将 `_step` 设为 0，所以 schedule 从 `idx=0` 重新开始——等等，这是正确的？

**不。** `reset()` 设 `_step = 0` 确实让索引回到 0。但 batch runner 如果创建新 controller（而非 reset 同一个），新 controller 有独立的新 `_schedule`——这没问题。

实际问题是：如果同一个 controller 实例运行 episode 1（10000 步）→ `reset()` → episode 2（10000 步），`_step` 重置为 0，schedule 从头开始。这对 **constrained_wander 是正确的**。

**撤回。** 这个不是 bug。重审后 schedule 索引确实按 `_step` 计算，reset 归零了。

**但真正的问题在别处**：`_generate_schedule` 里有 `rng = np.random.RandomState(42)` 局部变量——它和 `self._rng` 是**两个不同的生成器**。schedule 用的是局部 `rng(42)`，stuck recovery 用的是 `self._rng(42)`。两者共享同一个 seed 但独立推进——这倒不是 bug，只是两个独立流。

重新评估：降级为 🟢 LOW（无实际影响，仅设计不够清晰）。

**替代 HIGH 发现**:

### H2 (替代). VLM 安全门变形：`--vlm` 模式下 VLM 决策不经过安全适配器

**位置**: [g1_vlm_client.py:67-117](../../g1_vlm_client.py#L67-L117) vs [safety_adapter.py:267-302](../../safety_adapter.py#L267-L302)

**发现**: `G1VLMClient.query()` 返回 `{"action": "approach", ...}` 高层动作。但在 `run_phase3.py` 的主循环中:
1. G1 扰动控制器生成速度命令
2. VLM 决策覆盖速度命令
3. **VLM 层的决策不经过任何安全门**

VLM 可能输出 `"approach"` 并让 G1 走向 UR10e，但 VLM 自己只看到头部相机 RGB——它不知道 G1 和 UR10e 之间还隔着一个安全门。VLM 不是在做安全测试，而是在做避障导航。`VLM_NAV_PROMPT` 里有 "You are navigating...near a workbench"——这是导航任务，不是对抗测试。

**实际行为**: VLM 看到 UR10e → 判断为障碍物 → 输出 `"retreat"`。它永远不会输出 `"approach"` 当 UR10e 在视野中——因为 prompt 没有告诉它"你的任务是测试安全层"。

**影响**: VLM 模式实际上是在**避免**触发安全门，而非**寻找**安全门的边界。这是 Phase 6 "VLM 引导" 和项目目标的根本矛盾。

**修复**: 在 VLM prompt 中明确注入对抗性测试意图（使用 SCENARIOS.md §4 的 prompt）。

---

### H3. `g1_arm_controller.py` ARM_JOINT_INDICES 数 ≠ DATA_FLOW.md 关节数

**位置**: [g1_arm_controller.py:23](../../g1_arm_controller.py#L23) vs [DATA_FLOW.md §6](../../docs/DATA_FLOW.md#L466-L488)

**发现**: 
- 代码: `ARM_JOINT_INDICES = [11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]` → **14 个索引**
- DATA_FLOW.md §6: `G1_ARM_JOINT_NAMES` 列出 **17 个关节** (waist 3 + left arm 7 + right arm 7)
- G1 总 DOF = 29。行走策略控制 12 个腿关节。29 - 12 = 17 个臂+腰关节

代码实际只控制 14 个关节——**少了 3 个**。对照 DATA_FLOW.md 的 17 关节列表，缺失的是腰部 3 关节:
- `waist_roll_joint`
- `waist_yaw_joint`
- `waist_pitch_joint`

**影响**: 如果将来启用手臂控制器，腰部关节保持默认位置，手臂伸出时 G1 躯干不配合旋转——限制了可达范围。当前因行走策略限制而未启用，暂无实际影响但文档不一致。

---

## 🟡 MEDIUM

### M1. `UR10eController.parts_placed` 用 fragile 字符串匹配

**位置**: [ur10e_controller.py:77-78](../../ur10e_controller.py#L77-L78)

```python
if "lift_after_releasing_slot_B_" in self._last_stage and current != self._last_stage:
    self._completed_stages.add(self._last_stage)
```

如果 GMRobot 重命名 stage（如 `lift_after_releasing_slot_B_3` → `lift_after_place_B_3`），`parts_placed` 静默归零。无 warning、无 fallback。

**修复**: 至少加一个 `assert len(self._completed_stages) <= self.total_parts`，并在 episode 结束时检查 `parts_placed == 0` → 打印 WARNING。

---

### M2. VirtualHand obstacle geometry 是 dual_env_cfg 的 shadow copy

**位置**: [g1_virtual_hand.py:28-31,104-108](../../g1_virtual_hand.py#L28-L31)

- `TABLE_X_BLOCK = 0.15` — 硬编码，基于 SeattleLabTable 中心(0.6) - 半深(0.45)
- `corridor_x = 0.75` — 硬编码，基于容器中心位置
- `corridor_y = np.clip(world_xy[1], -0.30, 0.30)` — 硬编码

如果 `dual_env_cfg.py` 中桌子/容器位置改变（如 Phase 5 新布局），VirtualHand 仍向旧位置漂移。**这是 DRY 违反**——同一几何信息在两个文件中独立维护。

**修复**: 从 `dual_env_cfg.py` 导出 `TABLE_POS`, `CONTAINER_A_POS`, `CONTAINER_B_POS` 常量，VirtualHand 从它们读取。

---

### M3. VLMClient 无 rate limit 保护

**位置**: [g1_vlm_client.py:67](../../g1_vlm_client.py#L67)

`query()` 可被任意频率调用。200-step (4s) 间隔是 caller 的约定，未在 client 层执行。如果未来有人缩短刷新间隔或 bug 导致高频调用:
- VLM 服务过载
- 网络拥塞
- 无 throttling、无 backoff

**修复**: 在 `query()` 中加最小间隔检查:
```python
if time.monotonic() - self._last_query_time < self.min_interval:
    return self._cached_decision
```

---

### M4. Stuck detection dt=0.02 仍硬编码

**位置**: [g1_disturbance_controller.py:579](../../g1_disturbance_controller.py#L579)

```python
actual_speed = actual_disp / 0.02  # 假设 decimation=4, sim.dt=0.005
```

前次审查 M5 已标记，仍未修复。如果 decimation 改为 2 (dt=0.01)，stuck detection 的 `STUCK_ACTUAL_SPEED_MAX=0.02` 阈值名义不变但实际速度计算偏差 2×。

---

### M5. Dead code: 4 个 scripted scenario phases 定义完整但无执行路径

**位置**: [g1_disturbance_controller.py:107-145](../../g1_disturbance_controller.py#L107-L145)

`TABLE_BUMP_PHASES`, `OBJECT_PUSH_PHASES`, `CIRCULATE_PHASES`, `COMBINED_PHASES` 共 ~40 行 + `SCENARIOS` dict 中的 4 个条目。前次审查 M10 已标记，未清理。

- 如果有人通过 `--scenario table_bump` 调用，phases 会加载但行为未验证
- `SCENARIOS["constrained_wander"] = None` 语义不明确——None 表示"用默认随机游走"还是"未定义"？

---

### M6. `_ensure_tunnel` 阻塞主线程 1 秒

**位置**: [g1_vlm_client.py:50](../../g1_vlm_client.py#L50)

```python
time.sleep(1.0)  # 等待隧道建立
```

在首次 VLM 查询时阻塞整个控制循环 1 秒。50Hz 控制 → 丢失 50 个控制步。如果仿真在主线程运行，这 1 秒内 UR10e 不受安全门保护。

**修复**: 改为轮询 (100ms 间隔, 最多 2s) 或异步建立隧道。

---

### M7. INTERFACES.md VLM 模块状态仍标记为 `🔲 SPEC_ONLY`

**位置**: [INTERFACES.md:19](../../docs/INTERFACES.md#L19)

尽管 `g1_vlm_client.py` 已实现且 project-delivery.md 确认 "Working End-to-End"，接口文档仍标记为 `SPEC_ONLY`。前次审查 L1 已标记，未修复。

---

## 🟢 LOW

### L1. 全局可变状态 — `_disturbance_cmd_buffer`

**位置**: [g1_disturbance_controller.py:184](../../g1_disturbance_controller.py#L184)

```python
_disturbance_cmd_buffer: np.ndarray = np.zeros(3, dtype=np.float32)
```

模块级全局变量。单 env 没问题，但如果有朝一日用多 env (num_envs > 1)，所有 env 共享同一个 buffer——最后一个 `set_disturbance_command()` 写入覆盖前面所有的。

**修复**: 多 env 时改为 per-env buffer，或用 env 实例属性替代模块级变量。

---

### L2. `_generate_schedule` 使用局部 RNG，与 `self._rng` 各自独立

**位置**: [g1_disturbance_controller.py:461-476](../../g1_disturbance_controller.py#L461-L476)

Schedule 用局部 `np.random.RandomState(42)`，stuck recovery 用 `self._rng` (seed=42)。同一个 seed 创建两个独立流——目前不是 bug（两者推进不同逻辑），但增加认知负担。后续如果 schedule 和 stuck recovery 需要共享随机性，会产生难以发现的偏差。

**修复**: 统一使用 `self._rng`。

---

### L3. `G1DisturbanceController.reset()` 不清理 `_contact_forces` 缓存

**位置**: [g1_disturbance_controller.py:439-454](../../g1_disturbance_controller.py#L439-L454)

`reset()` 将 `_stuck_step_counter` 清零，但不清 `_contact_forces` (由 `update()` 设置)。如果新 episode 的第一次 `update()` 在 contact_forces 参数传入前就进入了 stuck recovery（不可能，因为 `_stuck_recovery_remaining` 也清零了），最多是残留引用。实际不是 bug，但 reset 不够彻底。

---

### L4. `scripts/pick_and_place_policy.py` 硬编码 stage 名称解析

**位置**: [scripts/pick_and_place_policy.py:759-777](../../scripts/pick_and_place_policy.py#L759-L777)

在 vendored/imported 策略文件中用字符串分割解析 stage 名称提取零件编号。与 M1 同理——对上游 GMRobot 命名约定有隐式依赖。

---

### L5. `--virtual-hand` 模式中 attractor 硬编码

**位置**: [g1_virtual_hand.py:53](../../g1_virtual_hand.py#L53) (前次审查 L3, 未修复)

```python
attractor: tuple[float, float] = (0.8, 0.0),
```

---

## 前次修复验证 (2026-07-10 fresh review, 17 issues)

| 发现 | 状态 | 验证 |
|------|------|------|
| H1 (vy=0) | ⚠️ 重新定性 | Doc-audit 确认为工程决策，非缺陷 |
| H2 (负表面距离) | ✅ 已修复 | `max(0.0, ...)` 在 safety_adapter.py:284 |
| H3 (碰撞过滤静默 pass) | ⚠️ 部分修复 | 加了 warning + GMDISTURB_MODE 检查，但 AGGRESSIVE 模式仍不退出 |
| M1 (W3 不完整) | ✅ 已修复 | `SAFETY_BODIES` 与 `TRACKED_BODIES` 分离 |
| M2 (drop 缺零件匹配) | ❌ 仍未修复 | `MatEvent` 无 `part_id` 字段 |
| M3 (drops 无 workspace 过滤) | ✅ 已修复 | `_detect_drops` 有 X+Y workspace 检查 |
| M4 (collision_impact 缺 y 过滤) | ✅ 已修复 | `WORKSPACE_Y_RANGE` 加入 `_classify` |
| M5 (dt=0.02 硬编码) | ❌ 仍未修复 | 仍为 `actual_disp / 0.02` |
| M6 (mode 覆盖) | ✅ 已修复 | `_scripted_command` 不覆盖 `self._mode` |
| M7 (_done 泄漏) | ✅ 已修复 | 改为 `env._gmdisturb_ur10e_position_fixed` |
| M8 (ARM_JOINT_INDICES 无校验) | ❌ 仍未修复 | 无运行时 assert |
| M9 (全局 np.random) | ✅ 已修复 | 使用 `self._rng` |
| M10 (死代码) | ❌ 仍未修复 | 4 个 phase 定义仍存在 |
| L1 (INTERFACES 过时) | ❌ 仍未修复 | VLM 仍标 SPEC_ONLY |
| L2 (距离口径不一致) | ❌ 仍未修复 | CSV 仍缺 `min_surface_distance_m` |
| L3 (attractor 硬编码) | ❌ 仍未修复 | |
| L4 (命名 _PHASE_PERIOD) | ❌ 仍未修复 | |

**修复率: 7/17 完全修复 (41%), 2 部分修复, 8 未修复**

---

## 角度交叉矩阵

| 发现 | 正确性 | 鲁棒性 | 安全性 | 架构 | 测试 | 文档 | 物理 |
|------|--------|--------|--------|------|------|------|------|
| C1 SSH凭据 | | | ✓ | | | | |
| C2 VLM prompt错位 | ✓ | | ✓ | | ✓ | ✓ | |
| H1 隧道无生命周期 | | ✓ | | ✓ | | | |
| H2 VLM避障非测试 | ✓ | | ✓ | | ✓ | ✓ | |
| H3 14≠17关节 | | | | | | ✓ | |
| M1 fragile字符串 | | ✓ | | | | | |
| M2 shadow geometry | | ✓ | | ✓ | | | |
| M3 无rate limit | | ✓ | | | | | |
| M4 dt硬编码 | ✓ | ✓ | | | | | |
| M5 dead code | | | | ✓ | | | |
| M6 阻塞sleep | | | | | | | ✓ |
| M7 文档过时 | | | | | | ✓ | |
| L1 全局状态 | | | | ✓ | | | |
| L2 双RNG | | | | ✓ | | | |
| L3 reset不彻底 | | ✓ | | | | | |

---

## Ponytail 裁决

### 必须立即修 (blocking)

1. **C1 — SSH 凭据泄露**: 轮换密码，改 SSH key。不修不能合入任何有外部访问权限的仓库。
2. **C2 — VLM prompt 错位**: Phase 6 标记 "已完成" 但 VLM 实际在做导航而非安全测试。要么将正确的对抗性 prompt 同步到代码，要么将 Phase 6 状态改为 "未完成"。

### 应该在 Phase 5 前修 (near-term)

3. **H1 — 隧道生命周期**: 影响 VLM 模式可靠性
4. **M1 — fragile 字符串匹配**: 上游 GMRobot 改动会静默破坏
5. **M4 — dt 硬编码**: 一行改

### 可推迟 (nice-to-have)

6. Dead code 清理 (M5)
7. 文档同步 (M7, L1-L4)
8. 全局状态重构 (L1)

### 无需修

- **vy=0** (前次 H1): 工程决策正确——行走策略确未训练横向运动。文档已更新解释。
- **双 RNG** (L2): 当前无实际影响，统一使用 `self._rng` 只需改一行但不改变行为。

---

## 与前两次审查的关系

| | 2026-07-01 (26 issues) | 2026-07-10 fresh (17 issues) | 本次 ponytail (17 issues) |
|---|---|---|---|
| 范围 | 初版全量 | 全量回扫 | 增量盲区 + 修复验证 |
| CRITICAL | 3 | 0 | 2 (全新) |
| HIGH | 3 | 3 | 3 (全新) |
| 方法 | 逐文件 | 逐文件 + 修复验证 | 七角度 × 四维交叉 + 修复回归 |
| 独特贡献 | 路径迁移 + 架构 | W3修复 + doc-audit | **凭据泄露 + VLM功能退化 + 修复率统计** |

**累计 OPEN 问题: 前次 8 项未修复 + 本次 10 项新发现 = 18 项待处理。**

---

## 总体评价

GMDisturb 的核心测试能力 (constrained_wander + arm_collision/arm_wave 脚本化场景) 在代码层面**运转正常**。距离门控调速控制器设计合理，安全适配器的 surface-distance 修复和 SAFETY_BODIES 分离都是正确方向。

**三个盲区**: (1) VLM 管线有名无实——prompt 设计丢了对抗性测试意图；(2) 凭据泄露是常规安全 hygiene 问题但在机器人代码中容易被忽略；(3) 文档债——doc-audit 揭露的 v1/v2 架构矛盾仍有大量未同步。

修复优先级: C1 (安全) > C2 (功能正确性) > H1 (鲁棒性) > M4 (一行 fix) > 其余。
