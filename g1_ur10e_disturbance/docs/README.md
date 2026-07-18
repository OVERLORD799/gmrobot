# GMDisturb 项目文档总索引

GMDisturb 是一个**双机器人联合仿真框架**，用于测试 GMRobot 安全层的边界和弱点。
G1 人形机器人作为扰动源在 UR10e 机械臂旁行走/伸手，触发安全门（STOP/SLOW_DOWN），
验证 GMRobot 的 RuleEngine + SafetyGate 在真实物理交互下的行为。

## 涉及项目

| 项目 | 路径 | 角色 |
|------|------|------|
| **GMDisturb** | `/root/g1_ur10e_disturbance` | 测试框架（G1 + UR10e 联合仿真） |
| **GMRobot** | `/root/GMRobot` | 被测系统（UR10e 安全推理） |
| **Pressure Mat** | `/root/pressure_mat_repro` | 触觉传感器（已吸收到 GMDisturb） |
| **AI / AMO** | 已评估，不采用 | [AMO_ANALYSIS.md](ai/AMO_ANALYSIS.md) — 遥操作框架，不适于脚本化测试 |

## 文档导航

### GMDisturb 框架（[]()）

| 文件 | 内容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构：场景布局、观测/动作空间、实施阶段 |
| [DATA_FLOW.md](DATA_FLOW.md) | 数据流：G1 行走管线、安全适配器、扰动控制器 |
| [INTERFACES.md](INTERFACES.md) | 接口定义：G1EnvelopeAdapter、G1DisturbanceController、UR10eController |
| [SCENARIOS.md](SCENARIOS.md) | 测试场景定义：8 个预定义场景 + YAML schema + 批量测试 |
| [VARIABLES.md](VARIABLES.md) | 变量参考：场景参数、传感器参数、机器人配置 |
| [ROBOT_SELECTION.md](ROBOT_SELECTION.md) | 机器人选型分析：G1 vs H1 详细技术对比及最终裁决 |

### GMRobot 被测系统（[gmrobot/](gmrobot/)）

| 文件 | 内容 |
|------|------|
| [架构总览.md](gmrobot/架构总览.md) | GMRobot 3 层安全架构（L1 规则 → L2 ML → L3 VLM） |
| [Layer1_规则安全层.md](gmrobot/Layer1_规则安全层.md) | Layer 1 详细规格：距离阈值、TTC 计算、门控决策 |
| [Phase2.5_EnvelopeDecisions.md](gmrobot/Phase2.5_EnvelopeDecisions.md) | 包络门控：全几何胶囊体 + 决策逻辑 |
| [Phase3.5_MotionReplan契约.md](gmrobot/Phase3.5_MotionReplan契约.md) | 运动重规划接口：触发条件、绕行策略、恢复机制 |
| [variable_reference.md](gmrobot/variable_reference.md) | GMRobot 变量参考 |
| [代码审计报告_2026-07-01.md](gmrobot/代码审计报告_2026-07-01.md) | 代码审计报告：26 个问题按严重度分级 |
| [项目进展与遗留问题.md](gmrobot/项目进展与遗留问题.md) | 进度跟踪 + 待办清单 + 已知限制 |

### 压力垫子系统（[pressure-mat/](pressure-mat/)）

| 文件 | 内容 |
|------|------|
| [MANIFEST.md](pressure-mat/MANIFEST.md) | 压力垫清单：文件结构、依赖关系 |
| [README.md](pressure-mat/README.md) | 压力垫项目说明（英文） |
| [README_CN.md](pressure-mat/README_CN.md) | 压力垫项目说明（中文） |

### AI / 灵巧手（[ai/](ai/)）

| 文件 | 内容 |
|------|------|
| [AMO_ANALYSIS.md](ai/AMO_ANALYSIS.md) | AMO 算法调研：架构、能力、GMDisturb 适用性评估 |

### 跨项目分析（[cross-project/](cross-project/)）

| 文件 | 内容 |
|------|------|
| [iteration-plan.md](cross-project/iteration-plan.md) | 迭代计划：4 轮测试 → AGGRESSIVE→MODERATE→CAUTIOUS 循环 |
| [gmrobot-weaknesses.md](cross-project/gmrobot-weaknesses.md) | GMRobot 弱点报告：W1-W5 分析 + 验证场景 |
| [adversarial-review.md](cross-project/adversarial-review.md) | 对抗性审查 #1 (2026-07-01)：26 个问题 |
| [adversarial-review-2026-07-10-fresh.md](cross-project/adversarial-review-2026-07-10-fresh.md) | 对抗性审查 #2 (2026-07-10)：17 个问题 |
| [adversarial-review-ponytail-2026-07-10.md](cross-project/adversarial-review-ponytail-2026-07-10.md) | 对抗性审查 #3 (2026-07-10 ponytail)：17 个问题 (2 CRITICAL 全新) |
| [adversarial-review-ponytail-2026-07-11.md](cross-project/adversarial-review-ponytail-2026-07-11.md) | 对抗性审查 #4 (2026-07-11 ponytail)：12 个问题 (1 CRITICAL 回归 + 2 HIGH 全新) |
| [doc-audit-2026-07-10.md](cross-project/doc-audit-2026-07-10.md) | 文档可靠性审计：doc vs code 差异 |

### 修复清单（[fixes/](fixes/)）

| 文件 | 内容 |
|------|------|
| [gmdisturb-self-fixes.md](fixes/gmdisturb-self-fixes.md) | GMDisturb 自修：13 项已完成 |
| [coordination-items.md](fixes/coordination-items.md) | 跨项目协调：9 项待定接口对齐 |
| [gmrobot-fix-proposals.md](fixes/gmrobot-fix-proposals.md) | GMRobot 修复提案 |
| [adversarial-review-fixes-2026-07-10.md](fixes/adversarial-review-fixes-2026-07-10.md) | 对抗性审查 #2 修复记录 (11 项) |

## 快速导航

### 按角色

- **新开发者** → [ARCHITECTURE.md](ARCHITECTURE.md) + [DATA_FLOW.md](DATA_FLOW.md)
- **测试工程师** → [SCENARIOS.md](SCENARIOS.md) + [cross-project/gmrobot-weaknesses.md](cross-project/gmrobot-weaknesses.md)
- **GMRobot 开发者** → [gmrobot/架构总览.md](gmrobot/架构总览.md) + [fixes/coordination-items.md](fixes/coordination-items.md)
- **架构决策** → [ROBOT_SELECTION.md](ROBOT_SELECTION.md) + [cross-project/iteration-plan.md](cross-project/iteration-plan.md)

### 按阶段

| 阶段 | 关键文档 |
|------|---------|
| Phase 1-2（已完成） | [fixes/gmdisturb-self-fixes.md](fixes/gmdisturb-self-fixes.md) |
| Phase 3（已完成） | [DATA_FLOW.md](DATA_FLOW.md) + [INTERFACES.md](INTERFACES.md) |
| Phase 4（已完成） | [ROBOT_SELECTION.md](ROBOT_SELECTION.md)。手臂控制 (`g1_arm_controller.py`) 已实现但因行走策略限制不启用；虚拟手 (`g1_virtual_hand.py`) 作为替代方案 |
| Phase 5+（未完成） | [cross-project/gmrobot-weaknesses.md](cross-project/gmrobot-weaknesses.md) + [fixes/coordination-items.md](fixes/coordination-items.md) + **[ARCHITECTURE.md §未完工清单](ARCHITECTURE.md#未完工清单2026-07-11审计)** |

---

## 项目状态（2026-07-11 最终）

| Phase | 状态 |
|-------|------|
| 1-4, 6-7 | ✅ 全部完成 |
| 5 | ✅ 完成 — [4 场景对比 + F1-F4 发现](findings/phase5-batch-results.md) |
| 代码 gap | ✅ 13/13 清零 |
| 已知限制 | G1 物理手臂不启用；vy=0 限制覆盖（见 F1）；VLM 服务器临时 |

**全部 7 个 Phase 完工。**

---

## 项目发展历史

| 日期 | 事件 | 文档 |
|------|------|------|
| 2026-06 | Phase 1-2: 场景组装 + G1/UR10e 联合仿真 | [ARCHITECTURE.md](ARCHITECTURE.md) (设计稿) |
| 2026-07-01 | Phase 3: 扰动注入 + 安全层集成。v1 概率状态机设计 | [fixes/gmdisturb-self-fixes.md](fixes/gmdisturb-self-fixes.md) |
| 2026-07-01 | 对抗性审查 #1: 26 issues (3 CRITICAL) | [cross-project/adversarial-review.md](cross-project/adversarial-review.md) |
| 2026-07-05 | Phase 3.1-3.2: 卡住检测 + 脚本化场景。v2 距离门控调速 (替换 v1 概率状态机) | [DATA_FLOW.md](DATA_FLOW.md) Phase B |
| 2026-07-05 | UR10e 布局修复 (z=0.762→0, xy 偏移→0) | [adversarial-review.md §补充](cross-project/adversarial-review.md) |
| 2026-07-08 | 配置外部化: `config/default.yaml` + `config_loader.py` | [config/default.yaml](../config/default.yaml) |
| 2026-07-10 | 对抗性审查 #2: 17 issues。11 项修复 (41% 通过率) | [cross-project/adversarial-review-2026-07-10-fresh.md](cross-project/adversarial-review-2026-07-10-fresh.md) |
| 2026-07-10 | 文档可靠性审计: v1/v2 架构矛盾 | [cross-project/doc-audit-2026-07-10.md](cross-project/doc-audit-2026-07-10.md) |
| 2026-07-10 | 对抗性审查 #3 (ponytail): 17 issues (2 CRITICAL 全新)。SSH 凭据泄露修复，VLM prompt 纠正，5 文件 9 改动 | [cross-project/adversarial-review-ponytail-2026-07-10.md](cross-project/adversarial-review-ponytail-2026-07-10.md) |
| 2026-07-11 | 文档全面同步: ARCHITECTURE/DATA_FLOW/INTERFACES/VARIABLES/SCENARIOS/README 全部与代码对齐 | 本文件 |
| **2026-07-11** | **对抗性审查 #4 (ponytail): 12 issues (1 CRITICAL 回归 + 2 HIGH 全新)** — C1 密码仍在 git 追踪的 YAML 中；H1 配置管线断开；H2 argparse 幽灵选项 | [cross-project/adversarial-review-ponytail-2026-07-11.md](cross-project/adversarial-review-ponytail-2026-07-11.md) |
