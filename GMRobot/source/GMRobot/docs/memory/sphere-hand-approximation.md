---
name: sphere-hand-approximation
description: Design rationale for using a single sphere as human hand proxy in safety gating
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

项目使用单个球体（r=0.05m）近似人手，这是主动设计决策（架构总览 §8 决策#4），不是简化遗漏。

**合理之处：**
- 安全性保守：球体完全包络真实手部几何，不会偏激进
- 与 GT v1.2 距离法天然对齐，无需 mesh-mesh 碰撞检测
- 算力 O(1)，50Hz 下 <1ms，与全包络原语统一在同一距离计算框架
- Layer 3 VLM+GDINO+SAM2 弥补球体的语义盲区（手指/手掌/手套/工具）
- 论文平台要求只要求"场景库覆盖时机/距离/速度/轨迹"，未要求骨骼建模

**局限性（已知且已缓解）：**
- 手指尖细几何被 5cm 球过度膨胀 → 用 warn 带而非直接 STOP 缓解
- 无法区分正面/背面 → 论文 Stage 4 VLM 职责
- kinematic 手不产生 PhysX contact → 审计分支 A 已记录为 `unknown`

**对导师陈述**：球体近似是"保守安全裕度 + 分层分工"的工程决策，不是能力缺失。Layer 1 管实时空间冲突（球体胜任），Layer 3 管语义理解（VLM 胜任）。

**Why:** 这是导师最可能质疑的设计点之一，需要准备好论证。

**How to apply:** 在答辩/汇报中主动解释这个决策，而非被动等待提问。引用架构总览 §8 决策#4 和三层能力边界表。
