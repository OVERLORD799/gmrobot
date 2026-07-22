# V0-C3 Isaac five-stage short shadow 结果（2026-07-21）

## 最终分类：**PASS**

一次正式短 shadow（最多 6 POST）通过全部门禁，含 **session continuity**（脱敏前比较 + 本地 alias）。  
**未重跑**。V0-C1 / V0-C2 FAIL 目录未覆盖。

### 明确非声称

- 负样本 scene；safety disabled；shadow 独立于 safety
- 真实 Isaac camera；真实远端 VLM / GDINO / SAM2
- local gateway IDs / session alias；inferred track state
- **无**人体 / 工具 / PPE 语义验证
- **非**论文五阶段最终完成

---

## 运行身份

| 项 | 值 |
|---|---|
| 镜像 | `gmdisturb:five-stage-shadow-v0c3-20260721` |
| image SHA | `sha256:cab6bf5cf637a1f16bd1ac4b14cd6611bb85c7c75ec71cacfddffc963b6ed452` |
| runtime config | bind-mount `five_stage_shadow_legacy_gateway_v0c3.yaml` |
| config SHA-256 | `0bbc300cc127ce61fc795fa9d07410b0c2a3b8e68d630ffd35f1cf4924e9da7b` |
| log_dir | `results/paper_demo/v0c3_isaac_shadow_20260721`（不含 v0c1/v0c2） |

---

## 门禁摘要

| 项 | 值 |
|---|---|
| exit | **0** |
| PROGRESS | **120** |
| scene RGB | ready |
| submitted / processed / logged | **2 / 2 / 2** |
| POST | **6**：VLM→ground→init，VLM→ground→step |
| 重试 / 第三帧 | 0 / 无 |
| pipeline_ok | true, true |
| VLM schema | 两帧 `gateway_parse_ok=true` |
| ground detections | 非空（10 / 2） |
| track | `initialized→tracking`；track_id **0→0** |
| id_source | local_gateway |
| track_state_native / source | false / legacy_gateway_inferred |
| dropped / stale | 0 / 0 |
| drain | complete=true；elapsed≈0.35s；pending_end=0；thread stopped |
| leakage | 五项 0 |
| raw session 泄漏 | **0**（仅 `<redacted>` + `session_1`） |
| Traceback | 无 |
| safety / live VLM / replan | 均未启用 |
| 远端修改 / 凭据读取 | 无 |

### Session continuity

| 帧 | state | present | match | applicable | verified | generation | ref |
|---|---|---|---|---|---|---|---|
| 0 | initialized | true | null | false | false | 1 | session_1 |
| 1 | tracking | true | **true** | **true** | **true** | 1 | session_1 |

匹配依据为 gateway 内存比较，**非** `<redacted>==<redacted>`，**非**仅 track_id。

---

## 两帧延迟（ms）

| 帧 | VLM | ground | track | e2e |
|---|---|---|---|---|
| 0 (init) | 3631 | 493 | 252 | 4375 |
| 1 (step) | 3448 | 454 | 281 | 5132（queue_wait≈950） |

---

## 产物

`g1_ur10e_disturbance/results/paper_demo/v0c3_isaac_shadow_20260721/`

含 stdout/stderr/exit_code、shadow jsonl/csv/summary、runtime_config_snapshot、run_manifest。
