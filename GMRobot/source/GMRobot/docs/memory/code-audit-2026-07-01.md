---
name: code-audit-2026-07-01
description: "Results of the 2026-07-01 comprehensive code audit — 8 fixes applied, 51 new tests"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

2026-07-01 代码审计结果摘要：

**3 代理并行审计**：代码质量 + 文档一致性 + 测试/架构。

**已修复（8 项）**：
- F1: safe_dist_warn 默认值在 fusion.py/fusion_draft.py/config.py 三处统一为 0.19
- F2: 架构文档 VLM CSV 列表更新，移除 3 个未实现字段
- F3: Layer 1 文档 ee_radius 从 0.0 修正为 0.08
- F4: 人手轨迹计算提取到 HumanTrajectoryConfig.compute_pose()
- F5: 新增 test_envelope/config/metrics/gate.py 共 51 用例
- F7: parents[4] 改为 _find_repo_root()
- F8: DEFAULT_HELD_BOX_DIMS_M 单一来源（replan import 自 envelope）
- F12–F14, F16: 未使用 import 删除、裸 except 收窄、scipy 注释、fusion 函数默认值统一

**延后（6 项技术债）**：F6 单体函数、F9 文档微小不一致、F10 硬编码路径、F11 PartTracker 死代码、F15 import 猴子补丁、F17 yaw unwrap。

**测试状态**：131 用例，118 通过（6 个预存在失败与 28cc8c2 相关）。

**How to apply:** 讨论代码变更时优先参考此报告，F6/F11/F15 可在后续开发中逐步解决。
