---
name: advisor-submission-checklist
description: Checklist for preparing the project for advisor submission with priorities
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

上交给导师前的检查清单，按优先级排列。

> 用户是本科生。本科阶段的评判重点与研究生不同：导师更关注**对系统的理解程度、工程实现能力、文档清晰度**，而非研究的创新性。GM-SafePick 作为本科项目，完成度（三层安全系统+仿真+ML+VLM集成）已经远超一般水平。

**P0 — 必须修复：**
1. 代码与文档一致性：验证文档中所有文件路径仍然存在，CLI 参数仍生效
2. 单元测试全部通过：`pytest tests/ -v`（13 个测试文件）
3. 至少一个可复现端到端演示：优先离线 `report_safety_metrics.py`（无需 GPU），其次 Isaac 3000 步短跑
4. 已知限制明确标注：`is_success()` 轨迹代理而非物理完成、活锁历史、PhysX contact=unknown、仅仿真

**P1 — 强烈建议：**
5. README 增加三层安全架构概述（当前 README 只覆盖基础拾放）
6. 准备"项目指标一页纸"：recall=1.0、false_stop=0%、成功率下降=0%、task_ts 286→2015
7. 检查无敏感信息泄露（密码、token、IP）在代码/提交历史中
8. Git 提交信息清晰有意义

**P2 — 加分项：**
9. 引用已有架构解耦分析文档证明系统可复用
10. 引用自动调参路线图展示工程完整性
11. 论文对齐差距表（G1-G6 已完成，G7 待硬件）
12. 录制带安全门控的仿真演示视频/GIF

**Why:** 导师在 30 秒内形成印象——README 是第一眼，指标表是核心论据，已知限制体现学术诚实。

**How to apply:** 提交前按此清单逐项检查，P0 必须全通过。
