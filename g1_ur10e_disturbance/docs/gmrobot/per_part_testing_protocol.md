# 逐零件测试协议 — 设计规格

## 目标

将 GMDisturb 从"G1 随机靠近 UR10e，统计 STOP 总数"升级为**每个零件每个阶段的定量避障测试**：
夹取阶段测 STOP 响应 → 运输阶段测 replan 绕行 → 放置阶段测 STOP 响应 → 手撤回 → 下一零件。

## 零件信息可获取性

- `SingleEnvPickAndPlacePolicy.user_commands` — 每个零件的 `part_id`、`source_slot`（容器 A 槽位）、`target_slot`（容器 B 槽位）
- `UR10eController.stage_name` — 当前阶段名：`"descend_to_slot_A_3"`、`"grasp_slot_A_3"`、`"move_above_box_with_slot_B_3"` 等
- 槽位坐标固定：容器 A (0.75, -0.25)、容器 B (0.75, 0.25)，槽间距约 0.04m

## 阶段协议

```
零件 k 的一个测试周期：
┌──────────┬──────────┬──────────┬──────────┐
│  Pick    │  Transit │  Place   │  Reset   │
│  手追随EE │  手挡路径 │  手追随EE │  手撤回   │
│  STOP测试 │  REPLAN  │  STOP测试 │  UR10e   │
│          │  测试     │          │  自由完成 │
└──────────┴──────────┴──────────┴──────────┘
     ↑           ↑          ↑          ↑
  descend    lift→     move_above  open_gripper
  →grasp     transit   →open      →下一个零件
```

阶段切换触发：从 `stage_name` 前缀检测。

## 核心问题与解决方案

### 问题一：策略时钟脱耦导致 STOP 死锁

**现象**：
```
STOP 时 time_step 照走 → 策略以为到了下一阶段 → 手位跟随新阶段移动
→ 但 EE 物理位置没动 → 手挡错了地方 → 安全门继续 STOP → 循环
```

**根因**：`ur10e.get_action(advance=True)` 一次调用既拿动作又推进时钟，发生在安全门评估之前。

**解法**：
```python
proposed = ur10e.get_action(obs, advance=False)  # 只拿动作，不推进
if gate != STOP:
    ur10e.advance()  # 只有非 STOP 才推进时钟
```

这样 `time_step` 和 EE 物理位置永远同步。

### 问题二：时钟暂停引入的新风险

1. `advance=False` 幂等性：反复调用返回同一个 waypoint 位姿。需确认 `SingleEnvPickAndPlacePolicy` 内部无累积状态损坏。
2. SLOW_DOWN 振荡收敛：EE 缓慢逼近手球 → 距离 < 0.13m → STOP → EE 冻 → G1 离开 → 距离 > 0.16m → SLOW_DOWN → 循环。集中在同一个 waypoint 上比之前更剧烈。
3. 超长 STOP 观测退化：几百步 STOP 中 UR10e 观测不变、IK 重复、仿真做无用功。
4. Replan 插入点不一致：`at_step` 是 frozen 的 `time_step`，`ee_pos` 是物理位置。绕行路径从物理位置出发恰好正确——但如果 STOP 发生在 transit 初期（刚离开 A），绕行可能绕回 A。

### 问题三：SLOW_DOWN "穿透"手球

EE 进入手球包络 → SLOW_DOWN 减速但不停止 → EE 缓慢穿过手球 → ALLOW 恢复全速。整个过程 EE 没有绕行——遮挡测试无效。
根因：SLOW_DOWN 的 alpha 机制允许 EE 在不触发 STOP 的距离下滑过去。

### 问题四：零件掉落时手位不追踪掉落物

`object_drop` 发生后零件从 z=0 掉到 z=-1.05，但手继续追 EE。无法模拟人或障碍物持续阻挡掉落物区域的场景。

### 问题五：阶段边界一步切换

`lift_slot_A_5` → `move_above_slot_A_6` 之间只有一步。手从"追随"切换到"阻挡"必须在一步内完成，否则在两种模式间闪烁。

### 问题六：手撤回后 G1 身体仍可能触发安全门

手撤了但 G1 身体还在旁边 → head/torso 包络半径大 → 安全门继续 STOP。手撤回无效。

### 问题七：G1 不受时钟暂停影响

G1 是纯前馈推理（588D → 12D），跟安全门 STOP 无关。UR10e 被冻时 G1 继续走——可能导致 G1 越走越近。

## 解决方案汇总

| 问题 | 解法 |
|------|------|
| STOP 死锁（时钟脱耦） | `advance=False` + 只在 ALLOW 时推进 |
| SLOW_DOWN 振荡 | 连续 SLOW_DOWN > N 步 → 强制手撤退，不等 STOP |
| 超长 STOP 观测退化 | 每阶段超时上限（如 transit ≤ 300 步），超时强制撤手进 Reset |
| SLOW_DOWN 穿透 | 检测手-EE 距离 < 0.10m 且门=SLOW_DOWN → 触发警告日志 |
| 阶段边界一步切换 | 预计算下一阶段的手位，在阶段切换前 5 步预加载 |
| 手撤回后 G1 仍触发 | 撤回时把 `adapter.human_hand_pos` 设为远离 EE 的位置（如 (0, 0, 2)） |
| G1 不受 STOP 影响 | 停 UR10e 时钟 ≠ 停 G1，无额外处理——G1 自由走是正确行为 |

## 实现清单

| 组件 | 位置 | 改动 |
|------|------|------|
| 时钟推进分离 | `ur10e_controller.py` | 把 `advance()` 从 `get_action` 里拆出来，暴露独立接口 |
| 安全门后推进 | `run_phase3.py` 主循环 | 只在 `gate != STOP` 时调 `ur10e.advance()` |
| 阶段检测 | 新建 `per_part_state.py` | 从 `stage_name` 前缀解析阶段类型 + 零件编号 |
| 槽位→坐标映射 | 同上 | 从容器基准坐标 + 槽间距推算每个槽位的世界坐标 |
| 运输路径遮挡点 | 同上 | A 槽位 → B 槽位线性插值，中点 + 侧向偏移 0.1m |
| 阶段超时 + 撤手 | 同上 | 每阶段计数器，超时 → 手位强制撤到安全距离 |
| 死锁检测 | 同上 | 连续 STOP > 50 + EE 位置方差 < 阈值 → 判定死锁 |
| 死锁挣脱 | 同上 | L1: 手位抖动 → L2: 手位排斥 → L3: G1 撤退 (逐级升级) |
| 迟滞区 | 同上 | 撤回后手位 > 0.30m + 稳定 30 步 → 才允许再次接近 |
