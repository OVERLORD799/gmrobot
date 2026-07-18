---
name: novel-contributions
description: Novel contributions of GM-SafePick relative to the original paper
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

GM-SafePick 是原论文 *Proactive Physical Safety Reasoning for Robot Manipulation*（Interim Report，他人撰写）的系统实现。用户在忠实实现原论文三层安全框架的基础上，做了以下工程增量贡献：

## 1. Tier 融合策略（原论文未定义具体融合方案）
原论文仅给出 $g_t = g_{rule} \lor g_{ml}$ 的示意公式。本项目实现了三级 Tier 融合：
- Tier0：硬碰撞区不可覆盖（`dist < hard_stop` → STOP）
- Tier1：规则误停区 ML 降级（`g_rule=STOP` static 但 `g_ml=ALLOW` → ALLOW）
- Tier2：减速区保持
- 效果：shoulder_pass 上 false_stop 从 L1 的 38.8% → 融合后 0%

## 2. Motion Replan 执行器（原论文 Stage 5 仅设计）
原论文将 `replan` 列为 Stage 5 的设计输出。本项目实现了完整的执行器：
- 三种 held-aware 绕行策略（raise_then_lateral / lateral_first / retreat_then_arc）
- 阶段感知参数（transit 可大步幅，place 仅微调）
- 放置区约束（clamp 在目标 0.15m 半径内）
- 预测式触发（TTC forecast + route_conflict 前向扫描）
- 效果：block_place 活锁消解（task_ts 286→2015）

## 3. 全包络门控（原论文用 EE 点距）
- 扩展到臂段（6 link × 3 插值球体 = 15 额外原语）
- 指尖包络（left/right_outer_finger）
- 夹持物包络（3 球体沿零件 local Z 轴）
- 审计显示：block_place 上臂段与 EE GT 45.5% 行不一致 → 门控切换后消除盲区

## 4. 工程贡献
- VLM Grasp Supervisor（连续 3 帧丢失检测 + 自动重抓）
- Scene Inventory（全场景零件盘点）
- 3+1 层 knock-off 防御（碰撞冷却 + 物理检测 + VLM 视觉 + 姿态稳定）
- PPO 训练适配（FlatObsWrapper 解决 Dict→Box 翻译）
- 自动调参框架设计（离线 CSV 重放 + 评分函数 + 搜索空间）

## 5. 对抗式代码审计
25 项发现（21 代码修复 + 3 架构延后已落地），证明系统经过了严格的质保流程。

**Why:** 论文需要清晰的 contribution list 来区别于原论文。本科生完成这些"超出复现"的工作，审稿人会更认可。

**How to apply:** 在论文 introduction 和 contributions 章节中逐条列出。每个贡献点都需有对应的实验数据支撑。
