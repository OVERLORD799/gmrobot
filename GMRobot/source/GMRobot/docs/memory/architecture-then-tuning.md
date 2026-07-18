---
name: architecture-then-tuning
description: "Why the project's approach of completing architecture before parameter tuning is correct engineering"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

项目的调参顺序——先完成架构（Phase 1–4）再系统化调参——完全符合工程常识。

**四层原因：**
1. 架构决定参数空间上界：Phase 2.5 全包络门控引入后，`dist_min` 替代 `dist_ee`，之前基于 EE 点距标定的参数全部作废。架构未稳定时调参是浪费
2. 场景库覆盖决定调参是否有意义：从 Phase 1 的 3 场景扩展到现在的 9 preset，场景不够时调参必然过拟合
3. 离线重放依赖 CSV 格式稳定：日志列名在 Phase 1→2.5 期间经历了双写、GT 口径切换，格式稳定后重放才有意义
4. 指标定义先于参数优化：在 `false_stop_rate`/`miss_rate`/`safety_recall` 的口径确定之前，无法定义"好参数"

**具体案例**：`safe_dist_warn` 从 0.19→0.16 的调整不是因为"之前调错了"，而是全包络门控改变了触发语义。baseline tier0 锁死（task_ts≈286）→ tier0_allow 修复后（≈1777），这是架构问题而非参数问题。

**当前状态**：架构已稳定，自动调参需求已定义（[GM-SafePick_自动调参需求规格.md](source/GMRobot/GMRobot/docs/GM-SafePick_自动调参需求规格.md)），离线重放脚本 `replay_params_on_csv.py` 待实现。

**Why:** 导师可能问"为什么参数像手动凑的"，需要系统性解释。

**How to apply:** 在汇报中用 baseline task_ts 286→1777→2015 的演进作为"架构改进 > 参数微调"的例证。
