# V0-C2 Isaac five-stage short shadow 结果（2026-07-21）

## 最终分类：**FAIL**

严格门禁 `session_match=true` 未满足（字段为 **absent/None**）。  
**不调参、不延长 step、不重跑**；全部原始产物已保留。  
V0-C1 FAIL 目录未覆盖。

**正式原因码：`session_continuity_not_recorded`**

审计说明（不可改判 PASS）：

- 实际 pipeline **2/2**；track **0→0**；`initialized→tracking`
- `session_present=true`，但脱敏前未记录 `session_match`
- **不是**远端已证实 session mismatch
- 连续性审计修复见 `vlm-v0c2-session-continuity-fix-2026-07-21.md`（V0-C2.1）

### 明确非声称

- 负样本 scene；safety disabled；shadow 独立于 safety
- local gateway IDs；inferred track state
- 非人体/工具/PPE 验证；非论文最终五阶段完成

---

## 运行身份

| 项 | 值 |
|---|---|
| 镜像 | `gmdisturb:five-stage-shadow-v0c2-20260721` |
| image SHA | `sha256:882da3eef062fe11e7c6a7f2b4dab736c2f235d516910f169a920145f85fb140` |
| runtime config | bind-mount `five_stage_shadow_legacy_gateway_v0c2.yaml` |
| config SHA-256 | `9bc51da8238e8f5686efe3f6c1cc8a056a73442f032033280f5e14c06d7b1856` |
| log_dir | `results/paper_demo/v0c2_isaac_shadow_20260721`（不含 v0c1） |

---

## 已满足项（摘要）

| 项 | 值 |
|---|---|
| exit | **0** |
| PROGRESS | **120** |
| scene RGB | ready |
| submitted / processed / logged | **2 / 2 / 2** |
| POST 估计 | **6**（VLM→ground→init，VLM→ground→step） |
| 重试 | 0 |
| pipeline_ok | true, true |
| VLM schema | 两帧字段齐全 |
| ground | 非空（10 / 2 dets） |
| track | init → tracking；track_id **0→0** |
| id_source | local_gateway |
| track_state_native | false |
| dropped / stale | 0 / 0 |
| drain | complete=true；elapsed≈1.06s；pending_end=0；thread_alive=false |
| leakage | 五项 0 |
| Traceback | 无 |
| safety/live VLM/replan | 均未启用 |

### 未满足

- **session_match=true**：两帧均为 `null`（gateway 仅写 `session_present=true`，未写 `session_match`）

---

## 两帧延迟（ms）

| 帧 | VLM | ground | track |
|---|---|---|---|
| 0 (init) | 4317 | 515 | 253 |
| 1 (step) | 3430 | 512 | 285 |

---

## 产物

`g1_ur10e_disturbance/results/paper_demo/v0c2_isaac_shadow_20260721/`

含 stdout/stderr/exit_code、shadow jsonl/csv/summary、runtime_config_snapshot、run_manifest。
