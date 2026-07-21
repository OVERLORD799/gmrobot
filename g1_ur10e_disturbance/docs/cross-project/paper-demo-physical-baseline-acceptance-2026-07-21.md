# 物理安全基准验收冻结（2026-07-21）

## 正式结论

- **物理安全基准 B0/B1/B2/B4：完成并冻结**
- **最终镜像：`sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`**（tag：`gmdisturb:b4-p010-20260721`）
- **VLM / Grounding DINO / SAM2 五阶段：尚未进入论文验证，不能宣称已完成**

后续**不再修改或重跑**已冻结物理基准（代码阈值、轨迹、冻结 YAML、结果目录、镜像）。历史证据与非官方残留目录一律保留、不覆盖。

## 冻结范围

| 模块 | 状态 | 证据 |
|---|---|---|
| B0 安全基线 | 三 seed PASS，冻结 | `b0-b1-final-regression-p010-2026-07-21.md` |
| B1 静态占位恢复 | 三 seed PASS，冻结 | 同上；机制见下 |
| B2 动态 TTC 主动干预 | 三 seed PASS，冻结 | `b2-b4-final-validation-p010-2026-07-21.md` |
| B4 active/shadow 对照 | 三 seed PASS，冻结 | 同上 |
| 同一最终镜像统一回归 | 完成 | `b0_b1_final_summary_p010.json` / `b2_b4_final_summary_p010.json` |

## 机制标签（勿混写）

- **B1**：`B1 static occupancy → replan recovery`（held-critical dominant；seed44 mixed held-critical/static）。seed44 的 `static×3` **不是** B2 式 proactive TTC。
- **B2**：*TTC-triggered pre-collision intervention before the geometric hard-stop boundary.*

## 明确未宣称完成

- GMRobot 五阶段视觉闭环（VLM / Grounding DINO / SAM2）
- 工具/PPE、功能性误抓等视觉相关论文实验
- 任何将五阶段表述为“已验收 / 已冻结”的说法

## 若继续五阶段目标

下一步必须先做**只读可行性审计**（不改实时安全层、不动冻结基准数字），确认：

1. 现有 VLM 服务与模型端点是否可达；
2. 相机输入路径是否真实可取流；
3. Grounding DINO / SAM2 接线是否可运行；
4. 结构化输出 schema 是否稳定可解析。

审计通过后再设计**独立 shadow 实验**，与 B0–B4 物理安全层及既有论文数字隔离。
