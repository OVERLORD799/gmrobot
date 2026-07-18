---
name: paper-submission-readiness
description: Paper submission readiness assessment and key claims verification for GM-SafePick
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

用户是本科生，项目目标为**发表论文**。论文对齐 *Proactive Physical Safety Reasoning for Robot Manipulation* 的三层安全框架，并扩展了 Motion Replan 模块。

## 论文级检查清单

### P0 — 可复现性（审稿人第一关）
1. ✅ 单元测试全部通过（13 个测试文件）
2. ⏳ 一键复现脚本：需确保 `run_safety_regression.sh` 可在干净环境运行
3. ⏳ 关键 run_id 的 CSV 日志是否可访问（用于复现指标表）
4. 🔶 VLM/感知依赖 gm-ai-server——需提供部署文档或离线模式 fallback
5. ⏳ 参数搜索的离线重放脚本（`replay_params_on_csv.py`）待实现

### P1 — 论文贡献叙事
1. **相对于原论文的增量贡献**：
   - L1+L2 Tier 融合（原论文仅有门控框架，未给出具体融合策略）
   - Motion Replan 模块（原论文 Stage 5 仅描述为设计输出，本项目实现了执行器）
   - 全包络门控（原论文用 EE 点距，本项目扩展到臂段+指尖+夹持物）
   - PPO 训练适配（FlatObsWrapper 解决 Dict→Box 翻译问题）
   - 对抗式代码审查（25 项发现 25 项修复，展示系统成熟度）

2. **实验叙事需要支撑的数据**：
   - 已具备：安全召回率 1.000、false_stop 0%（Tier 融合后）、成功率下降 0%
   - 已具备：block_place 活锁消解（task_ts 286→2015）
   - 缺少：PPO vs 脚本策略的对比数据（`eval_ppo_vs_scripted.py` 已就位，待跑）
   - 缺少：20-parts 全场景集成测试（R3 ⏳）
   - 缺少：全功能集成测试（R1 ⏳）

3. **消融实验（审稿人最关心）**：
   - L1-only vs L1+L2：已有 A/B 数据（shoulder/fast_sweep/intrusion）
   - with/without Motion Replan：已有（286 vs 2015）
   - with/without VLM：当前仅能证明 VLM 不降级，需论证增量价值
   - 全包络 vs EE-only：审计分支数据可支撑

### P2 — 论文写作
- README 需要从"拾放演示"升级为"安全推理系统"的论文级概述
- 论文差距 G1-G6 已全部完成，可声称完整实现论文框架
- 真人部署（G7）作为 limitations 章节内容
- 功能风险（G5）的 ivj_functional_misgrasp preset 可作为扩展场景

## 关键指标表（可直接入论文）

| 指标 | 数值 | 场景 |
|:------|:-----|:-----|
| Safety Recall | **1.000** | intrusion_positive (GT STOP=3239, miss=0) |
| False Stop Rate | **0.0%** | shoulder_pass (Tier fusion, L1 alone=38.8%) |
| Success Rate Drop | **0%** | far_observer A/B |
| Replan Task Recovery | **286→2015** | block_place (L1-only baseline→replan) |
| Control Frequency | **50 Hz** | All scenarios (vs paper 20 Hz) |
| VLM Reliability | **500/500 non-empty** | Full VLM CSV fields |
| Perception Latency | **~130ms** | GDINO+SAM2 @10Hz |

**Why:** 论文发表需要清晰的贡献叙事、可复现的实验、消融对比。本科生的身份反而可以成为加分项——"本科生独立完成了该系统"。

**How to apply:** 每项 P0/P1 检查项在投稿前必须闭环。实验结果表需从 Isaac 日志中提取并制成论文格式的表格。
