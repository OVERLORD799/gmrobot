# V1-D5A：证据门控动态规则（路径 B：判定权下沉为符号规则）

- 日期：2026-07-24
- 结果目录：`results/paper_demo/v1d5a_rule_offline_eval_20260724/`（不提交）
- POST：0（全部离线复用 D3B/D3C/D4C 真实存档数据），重试：0
- verdict = **D5A_RULE_OFFLINE_EVAL_PASS（5/5）**

## 设计（动机 = F5/F8：提示工程无法让 VLM 成为可靠动态分类器）

新模块 `safety/evidence_gated_rule.py`，版本 `evidence_gated_dynamic_rule_v1`：

- **核心规则一行可审计**：`dynamic_triggered ⇔ validate_temporal_evidence(evidence).valid`。
  全部复杂度（score/speed/age/session/漂移阈值）留在已测试的证据层（含 D4A）。
- **权限合同**：VLM 不能否决触发、不能铸造触发；其输出仅作语义标注附带，
  且只能升级建议动作（stop > slow_down 地板），不能放宽。
- **置信度语义分离**：`gate_confidence` 是 tracker 分数（证据质量量纲），
  明确不是语义置信度，不触碰冻结的 0.85 语义门。
- **fusion v1 未改动**：v1 中"temporal_fusion 升级路径"要求 VLM 原生 conf≥0.85
  且 action=slow_down（"tracker 不得铸造置信度"原则），本规则不修改 v1，
  而是新增显式版本化的并行路径，主张本身不同：检测决策不该依赖语义置信度。

## 离线验证（真实存档回放，零新推理）

| 案例 | 输入 | 触发 | 含义 |
|---|---|---|---|
| C1 | D3C 真实漂移证据 + D4A 标记 + 真实 VLM static@0.7 | 否（`track_drift_suspect`） | 成对栈特异性 |
| C2 | 同一证据、无 D4A（前 D4A 世界） | **是（被演示的继承假阳性）** | 规则质量=证据层质量，**D4A 为部署必要条件** |
| C3 | GT 完美跟踪探针 35.5 px/s + 真实 VLM static@0.7（D4C P3 存档） | **是，action=slow_down** | **VLM 从未产出的动态真阳性，规则直接给出**；探针为 GT 导出，diagnostic_only |
| C4 | D3B 真实稀疏证据（score 0.26） | 否（`score_below_threshold`） | 低质量证据拒绝 |
| C5 | 无证据 + 假设 VLM dynamic@0.99/stop | 否（`no_track_evidence`） | VLM 铸造禁令 |

单测 8/8 新增全过；全量相关回归 63 项通过。

## 架构结论（论文口径）

至此"确定性地板 + 学习增强"结构完成闭环：

- 检测（是否有东西在动）：**符号规则**，可审计、可验证——C3 证明它解决了
  F5/F8 的敏感性缺口；
- 语义（在动什么、后果、动作升级）：**VLM 标注**，不可靠性被权限合同隔离
  ——C5 证明其无法铸造，C1 证明错误证据被 D4A 拦截；
- 未来 VLM 微调（路径 A）只需竞争"天花板"角色，地板永久保留为纵深防御。

## 边界

- C3 探针证据为 GT 导出（diagnostic_only）；C1/C2/C4 证据与全部 VLM 标注
  均为真实存档记录；
- 规则触发的端到端在线验证（真实 SAM2 正确跟踪 → 规则触发）仍受限于
  F1（GDINO 目标选择）与 F3（SAM2 漂移），属数据集/感知层后续工作；
- fusion v1、0.85 语义门、证据阈值、B0–B4 全部未动。
