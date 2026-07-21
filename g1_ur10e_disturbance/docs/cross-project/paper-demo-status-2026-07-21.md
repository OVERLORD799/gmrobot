# 论文演示项目状态（2026-07-21）

> 本文件取代 `paper-demo-status-2026-07-20.md` 作为当前状态索引。  
> 物理基准正式验收见：`paper-demo-physical-baseline-acceptance-2026-07-21.md`。

## 1. 一句话结论

**物理安全基准 B0/B1/B2/B4 已完成并冻结于 `defe95e…`；VLM/Grounding DINO/SAM2 五阶段尚未进入论文验证，不能宣称已完成。**

## 2. 冻结身份

- 最终镜像 tag：`gmdisturb:b4-p010-20260721`
- image ID：`sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- 规则：不再修改或重跑冻结基准（代码、阈值、轨迹、YAML、结果、镜像）

### 机器汇总

- B0/B1：`results/paper_demo/b0_b1_final_summary_p010.json`
- B2/B4：`results/paper_demo/b2_b4_final_summary_p010.json`

### 文档

- 验收：`docs/cross-project/paper-demo-physical-baseline-acceptance-2026-07-21.md`
- B0/B1：`docs/cross-project/b0-b1-final-regression-p010-2026-07-21.md`
- B2/B4：`docs/cross-project/b2-b4-final-validation-p010-2026-07-21.md`

历史 0320 证据保留于 `results_paper_final_0320/final_six_ordered/`（不覆盖）。

## 3. 里程碑状态

| 里程碑 | 状态 | 说明 |
|---|---|---|
| M0 可信测试基础 | 完成 | 保持回归测试全绿 |
| B0/B1/B2/B4 物理安全基准 | **完成并冻结** | 统一镜像 `defe95e…` |
| M2 G1 静止真实手臂 | 未纳入本冻结 | 与物理代理基准分开 |
| M3 五阶段视觉闭环 | **未进入论文验证** | 不得宣称完成 |
| M4 论文结果全量冻结 | 部分 | 物理层已冻；视觉层未开始 |

## 4. 下一步（仅当继续五阶段目标时）

1. **只读可行性审计**：VLM 服务/端点、相机输入、GDINO/SAM2 接线、结构化输出是否真实可运行。
2. 再设计**独立 shadow 实验**，避免影响实时安全层与已冻结论文数字。
3. 在审计与实验设计通过前，不改 B0–B4 冻结资产。
