# V1-E0 控制级 VLM 语义评估集与 prompt/model 实验协议设计（2026-07-22）

## 本轮边界

- **0 POST**；不跑 Isaac/Docker；不改远端/模型/权重/**0.85 阈值**
- 不实现 active；不改写 V1-D 历史 FAIL；不把 **0.8** 当作通过
- 不创建“为了通过”的新场景；不重编码原图

---

## 1. 冻结结论（不得改写）

| 项 | 冻结值 |
|---|---|
| D1A | 视觉语义低 + geometry 非全程 ALLOW → **FAIL** |
| D1B | 功能阻塞视觉成立；**GEOMETRY_OVERLAP** |
| D1B-S v1 | `static@0.3/0.7`；`SEMANTIC_SCREEN_FAIL` |
| D2B v2 | `static@0.8/0.8`；`D2B_TASK_CONTEXT_FAIL` |
| `slow_down` 单独 | **不构成正例** |
| semantic_key | 历史仍不一致 |
| confidence 门禁 | **保持 0.85**（禁止降到 0.8） |
| 监督器拒绝 0.8/static | **正面安全结果** |
| V1-D active | **暂停** |

### 项目能力边界（当前）

| 能力 | 状态 |
|---|---|
| 五阶段真实 shadow | **PASS** |
| 语义监督器控制隔离 | **PASS** |
| 低置信/类型错误的安全拒绝 | **PASS** |
| 真实 VLM 主动控制反馈 | **尚不具备** |

---

## 2. Artifact 盘点

只读搜索 `results/paper_demo`（及 B0–B4 结果树）。**唯一真实 Isaac scene RGB：14 张**（按 SHA；不计入 screen 目录对同源图的 symlink）。

| 来源 | 帧数 | 有 RGB？ | 备注 |
|---|---|---|---|
| V0-B1 `v0b1_rgb_capture_20260721` | 8 | 是 | 名义 pick/place；无 VLM |
| V1-D1A far corridor | 3 | 是 | 红球；geometry FAIL；`visual_semantic_risk=low` |
| V1-D1B functional blockage | 3 | 是 | B 箱零件占用；100/200 曾 VLM |
| V0-C3 / V1-C1R-P1 shadow | 0 | **否** | 有 VLM+SAM2 日志，**无落盘 RGB** |
| B0/B1/B2/B4 结果树 | 0 | **否** | 无 PNG |

未复制/重编码原图。

---

## 3–5. 类别候选 / provisional 标签 / 分组

Manifest：`results/paper_demo/v1e0_semantic_dataset_manifest_20260722.jsonl`（14 行）。

| 类别 | 候选数 | 说明 |
|---|---|---|
| SAFE_NEGATIVE | 8 | 全部 V0-B1 |
| STATIC_GEOMETRY | 3 | 全部 D1A（应交 Layer-1，勿作 VLM 控制正例） |
| FUNCTIONAL_POSITIVE | 2 | D1B step100/200（provisional） |
| DYNAMIC_POSITIVE | **0** | 无「真实 RGB + SAM2」样本 |
| AMBIGUOUS_EXCLUDED | 1+meta | D1B step0；外加无 RGB 的 C3/P1/B0–B4 说明项 |

### 可用 positive

| 类型 | 数量 | 场景组 |
|---|---|---|
| functional（provisional） | 2 | **仅** `scene_d1b_20260722` |
| dynamic（可靠） | **0** | — |

**数据集状态：`DATASET_INSUFFICIENT`**

原因：仅 1 个 functional 场景组；无带 RGB 的 dynamic 正例；V0-C3/P1 有 track 无图。  
→ **不批准 V1-E1 live prompt 评估**；不得用 ambiguous 填数；不得围绕 D1B 两图刷 prompt。

所有标签：`label_status=provisional`，`reviewer_approved=false`。

### 泄漏控制分组（按 `scene_group`）

| split | 样本 |
|---|---|
| prompt_development | V0-B1 step 0/10/20 |
| held_out_evaluation | V0-B1 30/40 + **D1B 0/100/200（同组不可拆）** |
| negative_regression | V0-B1 50/60/70 + 全部 D1A |

禁止：held-out 图进 few-shot；文件名/历史答案注入；无记录次数地改 prompt 刷过。

---

## 6–7. P0–P3 设计（只设计，不调用）

完整正文：`results/paper_demo/v1e0_prompt_candidates_20260722.json`

| ID | version | SHA-256（摘要） | 要点 |
|---|---|---|---|
| **P0** | `five_stage_safety_v2_temporal` | preamble `698a8697…`；空 ctx 实例 `40c9d7e9…` | 冻结基线（现网 D2A/D2B） |
| **P1** | `five_stage_safety_v2_ontology_p1` | `dbf33bc056adfd62…` | 互斥定义强化；functional=任务不可执行；无 D1B 答案 |
| **P2** | `five_stage_safety_v2_evidence_p2` | `46ae06ca33c9bcd6…` | 先 evidence 字段再分类；无 motion/target 证据禁高置信 dynamic/functional |
| **P3** | `five_stage_safety_v2_temporal_p3` | `a8fd56a92fa42fb4…` | 仅真实上一帧 SAM2；区分 image vs tracker |

共同：独立 version；确定性文本；无自由 fallback；**不降低 0.85**；不含控制阈值答案。

### 指标与控制级门禁（设计）

指标：risk_type accuracy、accept P/R、false accept、SAFE_NEGATIVE FA、STATIC 误提升、置信校准、同场景 key 一致、parse rate、latency、幻觉证据数。

最低门禁建议：SAFE_NEGATIVE FA=0；STATIC 误提升=0；同场景 key 一致；parse=100%；accept 可追溯；**禁止降阈值改善结果**。  
样本过少必须标 **pilot**，不报泛化。

### 后续最小 POST 矩阵（**不执行**）

若数据集充足：2 neg + 2 evidenced pos × {P0,P1,P2} ≤ **12 POST**；每格 1 次；seed=`20260722`；无 retry。

**当前批准：`NOT_APPROVED_DATASET_INSUFFICIENT`。**

---

## 8–10. 远端边界 / E1 资格

| 问题 | 答案 |
|---|---|
| P1/P2/P3 可否本地 gateway 构造？ | **可以** |
| 需要远端多图？ | **否（默认）** |
| 需要远端新 schema 字段？ | **否（P2 可先本地解析扩展；远端仍收 text JSON）** |
| 现在换模型？ | **否**；阶段1 固定 Qwen 只比 prompt；全失败再比模型 |
| 具备进入 V1-E1？ | **否**（`DATASET_INSUFFICIENT`） |

论文可表述口径：系统已完成真实五阶段 shadow 与安全拒绝验证；**主动语义控制仍为后续工作**，需先扩充有证据的评估集。

---

## 11. git diff --stat（快照）

```
 10 files changed, 628 insertions(+), 80 deletions(-)
```

（工作树另有既有 untracked；本轮新增 E0 文档/manifest/prompt 候选 JSON。）

---

## 交付路径

- `docs/cross-project/vlm-v1e0-semantic-evaluation-design-2026-07-22.md`
- `docs/cross-project/vlm-v1e0-semantic-evaluation-design-2026-07-22.json`
- `results/paper_demo/v1e0_semantic_dataset_manifest_20260722.jsonl`
- `results/paper_demo/v1e0_prompt_candidates_20260722.json`

**已停止。**
