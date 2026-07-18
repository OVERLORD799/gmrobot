---
name: avoidance-l-shaped-path
description: Why the default robot avoidance uses L-shaped (raise-then-lateral) rather than diagonal paths
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

机械臂避障的默认策略 `raise_then_lateral`（先抬升再横移）刻意使用 L 形路径而非对角直线。

**核心原因（球形障碍物几何特性）**：连接起点和终点的直线段，其到球心的最小距离是点到直线的垂足距离，可能远小于起点或终点距离——对角路径可能在中间穿过更危险的区域。L 形路径保证：先径向远离（纯抬升，距离单调增），再切向绕过（纯横移，距离保持）。

**三种策略的适用条件**（由 `select_detour_strategy()` 评分选出）：
- `raise_then_lateral`（默认）：Z 余量 ≥ 0.08m，transit/carry 阶段
- `lateral_first`：Z 余量 < 0.08m 或 TTC 快扫（避免先抬升把夹持物朝人手方向甩）
- `retreat_then_arc`：夹持物与人手紧邻（`dist_min_held < 0.12m`），先径向后退再弧线绕

**不是 IK 限制**：系统完全能做对角运动（`retreat_then_arc` 的弧线路点就是 XYZ 合成），默认分步是安全几何裕度最大化的设计。

**Why:** 导师可能问"为什么不直接走直线"，需要从几何角度解释 L 形路径的安全性。

**How to apply:** 在汇报中引用球形障碍物的点到直线垂足距离问题，说明这是以安全裕度换路径长度的合理取合。
