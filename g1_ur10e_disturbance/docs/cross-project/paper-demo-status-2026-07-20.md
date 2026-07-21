# 论文演示项目状态与证据索引（2026-07-20）

> **已归档。** 当前状态与正式验收请见：  
> - `paper-demo-status-2026-07-21.md`  
> - `paper-demo-physical-baseline-acceptance-2026-07-21.md`  
> 结论摘要：物理安全基准 B0/B1/B2/B4 已完成并冻结于 `defe95e…`；五阶段 VLM/GDINO/SAM2 **尚未**进入论文验证。

## 1. 一句话结论

项目尚未完成。可信测试基础已经完成，B0/B1 最小纵向切片已经通过；B2–B4、G1 真实手臂、五阶段视觉闭环和论文最终实验矩阵仍待实现。

## 2. 当前可复现基线

- Docker 镜像：`sha256:0320fd6e9d7c061c48fdb51bf44a738bbee5e6bd469f8e5f2e52c05963ae0ca6`
- 最终结果根目录：`results_paper_final_0320/final_six_ordered/`
- 联合汇总：`results_paper_final_0320/final_six_ordered/batch_summary_combined.json`
- B0 配置：`paper_scenarios_b0b1/baseline_safe.yaml`
- B1 配置：`paper_scenarios_b0b1/static_occupancy_proxy.yaml`
- 可信 seeds：42、43、44

所有最终 episode 均保存配置快照、CLI、seed、stdout/stderr、step CSV、事件 CSV 和 episode 结果。旧调参目录是回归材料，不得混入论文最终数字。

## 3. 六组最终结果

| 场景 | seed | task | 归因 STOP | 归因 SLOW | 归因 replan | knock-off | G1 fell | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| B0 | 42 | 20/20 | 0 | 0 | 0 | 0 | false | PASS |
| B0 | 43 | 20/20 | 0 | 0 | 0 | 0 | false | PASS |
| B0 | 44 | 20/20 | 0 | 0 | 0 | 0 | false | PASS |
| B1 | 42 | 20/20 | 4 | 4 | 4 | 0 | false | PASS |
| B1 | 43 | 20/20 | 4 | 3 | 4 | 0 | false | PASS |
| B1 | 44 | 20/20 | 5 | 12 | 7 | 0 | false | PASS |

B1 合计：

- `trigger/applied/retreat/redeploy = 15/15/15/15`；
- 未配对 attempt：0；
- trigger→apply 延迟：全部 0 step；
- `proxy_physical_contact_count=0`；
- 12 次 `held_critical` replan，3 次 SLOW replan；
- 三个 episode 均在 replan/retreat 后继续取得进度并完成任务。

## 4. 已证明与未证明

### 4.1 已证明

- B0 在三 seed 下没有 G1 归因误报，UR10e 完成任务。
- 明确标注的脚本化占位代理能够触发静态风险门控、replan、撤离和恢复。
- attempt、触发源、事件边沿和恢复进度可由原始记录复核。
- 种子已闭环到 Python、NumPy、Torch/CUDA、Isaac 环境、G1 控制器和虚拟手。
- 代理手的运动学可达半径与占位包络半径已经拆分。

### 4.2 未证明

- B1 主要是 `held_critical STOP → replan`，不能代替稳定的接触前动态预测证据。
- B1-s44 的 3 次 SLOW replan 是有价值的补充样本，但不是独立、受控、可重复的 B2 场景。
- 没有 G1 真实手 body 触发安全门的已验收证据。
- 没有恢复 G1↔UR10e 默认 PhysX 碰撞响应，也没有真机验证。
- 没有完成工具/PPE、功能性误抓或五阶段视觉链的端到端验收。
- 当前只有 3 seeds，不是最终论文要求的至少 5 seeds 和消融矩阵。

## 5. 已知运行问题

连续在同一长生命周期容器内重新启动 Isaac 时，B1-s43 曾在相机 observation 初始化阶段发生一次 CUDA illegal memory access。该运行没有进入仿真，未纳入统计。随后使用“每个 episode 一个新容器”完成剩余五组。

后续长批次规则：

1. 每个 episode 使用新容器；
2. 环境启动失败不得重标为场景 FAIL；
3. 失败 episode 仍保留 manifest/stdout/stderr；
4. 不得因启动失败继续消耗完整 episode timeout；
5. 环境失败与算法/场景失败分别统计。

## 6. 里程碑状态

| 里程碑 | 状态 | 下一完成门 |
|---|---|---|
| M0 可信测试基础 | 完成 | 保持回归测试全绿 |
| M1 可重复代理手基准 | 部分完成 | B2 seed42 1-part / pairing / 8-part 已绿；待多 seed 与 B3/B4 全量 |
| **B2 1-part pilot** | **PASS**（seed42） | 证据见 `docs/cross-project/b2-1part-evidence-2026-07-20.md` |
| B2/B4 pairing（seed42） | trajectory PASS / **control-isolation FAIL**（f126…） | 历史失败证据保留；见 b2-1part-evidence |
| B2 8-part（seed42） | PASS（开发功能，20da…） | 非最终统一镜像统计 |
| B4 无控制副作用基线 | **PASS**（d6cb… / `b4-iso-20260720`） | shadow 1/1；leakage 计数全 0 |
| **B2/B4 三 seed（d6cb…）** | 历史 functional PASS | raw redeploy 15≠8；见 `b2-b4-final-validation-2026-07-20.md` |
| **B2/B4 三 seed（P0-10 / defe…）** | **PASS / freeze_ready** | `gmdisturb:b4-p010-20260721`；8/8/8/8/8；见 `b2-b4-final-validation-p010-2026-07-21.md` |
| B0/B1 回归（同新镜像） | 暂缓 | 待 P0-10 冻结确认后再跑 |
| M2 G1 静止真实手臂 | 未完成 | 真实左右手 body 至少一次触发门禁且 G1 稳定 |
| M3 五阶段视觉闭环 | 未完成验收 | Stage 1–5 端到端证据及工具/PPE 对照 |
| M4 论文结果冻结 | 未开始 | 消融、统计、视频和最终环境快照 |

## 7. 下一步

下一切片限定为 B2 动态横扫和与其轨迹匹配的 B4-Dynamic shadow/no-enforcement 对照。它不包含 B1/B3 的 B4 配对，因此不会单独完成整个 B4。执行合同见：

`docs/cross-project/code-agent-b2-b4-instructions-2026-07-20.md`
