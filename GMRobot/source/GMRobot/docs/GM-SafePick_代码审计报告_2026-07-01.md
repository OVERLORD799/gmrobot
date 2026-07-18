# GM-SafePick 代码审计报告

> **审计日期**：2026-07-01
> **审计方法**：3 代理并行（代码质量 + 文档一致性 + 测试/架构）
> **审计前状态**：git HEAD `28cc8c2`，工作树干净

---

## 1. 审计摘要

| 严重度 | 发现项 | 已修复 | 延后 |
|:------|:-----|:----:|:----:|
| 🔴 Critical | 5 | **5** | 0 |
| 🟠 Medium | 7 | **3** | 4 |
| 🟡 Minor | 10 | **5** | 5 |

51 个新测试全部通过，0 回归（预存在的 6 个 `test_policy_trajectory_clock` 失败与 `28cc8c2` 相关，非本次修复引起）。

---

## 2. 已修复项

### 🔴 Critical

| # | 问题 | 修复方式 | Commit 参考 |
|:--|:-----|:-----|:-----|
| F1 | `safe_dist_warn` 在 fusion.py=0.16, fusion_draft.py=0.19, config.py=0.19 三处不一致 | 统一为 **0.19**（匹配 config.py 代码默认值；YAML 可通过配置文件覆盖） | 2026-07-01 |
| F2 | 架构文档 VLM CSV 列表包含 3 个未实现字段（`vlm_severity`/`vlm_stage`/`vlm_latency_ms`） | 更新表格为实际写入的 9 个字段，加注释说明未实现字段 | 2026-07-01 |
| F3 | Layer 1 文档 `ee_radius` 默认值 0.0m 与代码 0.08m 矛盾 | 修正为 0.08m | 2026-07-01 |
| F4 | 人手轨迹计算在 `human_motion.py` 和 `route_conflict.py` 中重复 35 行 | 提取到 `HumanTrajectoryConfig.compute_pose()` 方法，两处调用改为委托 | 2026-07-01 |
| F5 | 14 个源码模块零测试覆盖 | 新增 4 个测试文件（`test_envelope.py`/`test_config.py`/`test_metrics.py`/`test_gate.py`），51 个测试用例 | 2026-07-01 |

### 🟠 Medium

| # | 问题 | 修复方式 |
|:--|:-----|:-----|
| F7 | `parents[4]` 相对路径脆弱（依赖目录深度恰好 5 层） | 新增 `_find_repo_root()` — 通过 `.git`/`setup.py` 向上搜索；`load_safety_config` 和 `load_fusion_config` 改用此方法 |
| F8 | `DEFAULT_HELD_BOX_DIMS_M` 在 3 处重复（含注释"keep in sync"） | `replan/strategy.py` 改为从 `envelope.py` re-export，config.py 保持权威来源 |
| F16 | `compute_fusion` 中 `safe_dist_warn=0.16` 与 `compute_tier_fusion` 已修复的 0.19 不一致 | 统一为 0.19 |

### 🟡 Minor

| # | 问题 | 修复方式 |
|:--|:-----|:-----|
| F12 | `sys` 导入未使用 | 删除 |
| F13 | 裸 `except Exception` 吞 KeyboardInterrupt | 改为 `except (ValueError, TypeError, KeyError, IndexError, AttributeError)` |
| F14 | scipy 延迟导入含义不明 | 添加注释说明：仅在 held-part 运行时路径需要 scipy |

---

## 3. 延后项（已知技术债）

| # | 问题 | 严重度 | 原因 |
|:--|:-----|:-----|:-----|
| F6 | 741 行 `apply_safety_gate()` 单体函数 | Medium | 需架构级重构，影响所有集成路径 |
| F9 | Layer 1 文档 `safe_dist_warn=0.19` 与 YAML 中 0.16 不同 | Low | YAML 覆盖是故意的（视觉校准），文档描述代码默认值正确 |
| F10 | 多处硬编码 `/root/GMRobot/output/` | Low | 仅影响跨机器部署；当前单机使用安全 |
| F11 | PartTracker VLM 重试机制永远触发不了 | Medium | 需仔细集成到 agent 主循环，需 Isaac 回归 |
| F15 | `_safety_import.py` 猴子补丁 | Medium | 当前无更简洁的替代方案 |
| F17 | yaw 插值未 unwrap | Low | 仅影响跨 ±π 边界的极少场景 |

---

## 4. 审计后状态

| 维度 | 审计前 | 审计后 |
|:------|:-----|:-----|
| 测试文件数 | 13 | **17** |
| 测试用例数 | ~80 | **131** |
| 测试覆盖的关键模块 | types, fusion, rule_engine, logger, ground_truth, gt_branches, layer2 | **+envelope, config, metrics, gate** |
| 代码默认值一致性 | safe_dist_warn 三处不同 | **全部统一** |
| 路径健壮性 | parents[4] fragil | **repo-root 自动发现** |
| 代码重复 | trajectory 计算 2 份 | **单一来源** |
| 常量重复 | DEFAULT_HELD_BOX_DIMS_M 3 份 | **单一来源** |
| 文档-代码一致性 | ee_radius 0.0 vs 0.08, VLM 列 3 个不存在 | **已对齐** |

---

## 5. 审计完整性

未覆盖的测试（延后到下一轮）：

| 模块 | 行数 | 测试优先级 |
|:------|:-----|:----:|
| `safety/vlm_grasp_supervisor.py` | 418 | P1 |
| `safety/part_tracker.py` | 298 | P1 |
| `safety/hand_trajectory_filter.py` | 222 | P1 |
| `safety/replan/triggers.py` | ~250 | P1 |
| `safety/replan/executor.py` | ~120 | P1 |
| `safety/replan/strategy.py` | ~180 | P2 |
| `safety/layer2/train.py` | 309 | P2 |
| `vlm/client.py` | 96 | P2 |

这些模块的测试需要更复杂的 mock（replan 需要 policy mock，VLM 需要 HTTP mock），建议在下一轮审计中补充。

---

*审计由 Claude Code 3-agent 并行执行。修复项已通过 118 个测试 0 回归的验证。*
