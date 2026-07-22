# V1-D2A 任务上下文 + 前一帧 tracking 时序融合（离线实现，2026-07-22）

## 结论

| 项 | 值 |
|---|---|
| POST / 网络 / Isaac / Docker | **0** |
| 远端改动 | **无** |
| active / B0–B4 / 历史 D1A·D1B 改写 | **无** |
| `min_risk_confidence` | **仍为 0.85**（未降低） |
| 默认行为 | **v1 不变**；v2 仅显式启用 |
| 新增单测 | **35** |
| 全量离线 `test_*unit.py` | **140 OK** |

边界重申：时序融合可把 **VLM 高置信实体风险** 与 **SAM2 真实运动证据** 组合；**禁止**用 tracker 替 VLM 补造高置信度。

---

## 1. 改动文件

### 新增

| 路径 | 作用 |
|---|---|
| `vlm/versions.py` | v1/v2/fusion 版本常量 |
| `vlm/task_context.py` | `TaskSemanticContext` 严格枚举 schema |
| `vlm/temporal_evidence.py` | `TemporalTrackEvidence` + 独立运动阈值校验 |
| `vlm/prompt_v2.py` | 确定性 `five_stage_safety_v2_temporal` + prompt hash |
| `safety/semantic_temporal_fusion.py` | 纯函数融合 + provenance |
| `safety/semantic_key_v2.py` | 规范字段 JSON→SHA-256 key |
| `configs/five_stage_shadow_temporal_v2.yaml` | 显式 v2 shadow（`enabled=false`） |
| `configs/semantic_safety_supervisor_temporal_v2.yaml` | 显式 v2 supervisor（`enabled=false`） |
| `configs/vlm_client_legacy_gateway_temporal_v2.yaml` | 显式 v2 prompt/schema 客户端 |
| `scripts/fixtures/v1d2a/*.json` | 脱敏历史负样本 + synthetic 正/反例 |
| `scripts/test_v1d2a_temporal_fusion_unit.py` | 35 项离线门禁测试 |

### 扩展（本地）

| 路径 | 作用 |
|---|---|
| `shadow/five_stage_worker.py` | 显式 `temporal_fusion_enabled`；N 存证→N+1 入 prompt；同帧不回灌 |
| `shadow/logger.py` | 融合/时序/task/key 审计字段 |
| `safety/semantic_supervisor.py` | 可选 `semantic_key_version=v2` + override；默认 v1 |
| `vlm/__init__.py` | 导出版本常量 |

未改：远端 VLM/perception 服务、geometry gate、action/clock/protocol/replan、B0–B4。

---

## 2. v1 兼容性

- 默认 `temporal_fusion_enabled=false` → 不构造 v2 prompt、不存/用 track 证据、不跑 fusion。
- 默认 `semantic_key_version=v1` → 原 `build_semantic_key`。
- **禁止**根据 health/响应静默切换 v1/v2。
- v2 失败 **不** fallback 到 legacy `vlm_*` 补造字段。

---

## 3. v2 prompt / schema / fusion 版本

| 项 | 值 |
|---|---|
| prompt_version | `five_stage_safety_v2_temporal` |
| schema_version | `five_stage_vlm_v2` |
| fusion_version | `five_stage_temporal_fusion_v1` |
| semantic_key_version | `semantic_key_v2` |
| 远端 HTTP 契约 | 仍 `legacy_v2` `/analyze`（仅本地 prompt 文本变化） |

---

## 4. TaskSemanticContext

枚举字段：`task_name`, `task_phase`, `task_goal_type`, `source_container`, `target_container`, `held_object_class`, `transport_active`, `placement_target_occupied`, `context_source`, `context_sim_step`。

- 未知 → `unknown`/`none`
- **禁止**携带 `risk_type` / `recommended_action` / confidence（构造时抛错）
- 记录 `context_source` provenance

---

## 5. TemporalTrackEvidence

字段含：source request/frame、track_id（允许 `"0"`）、canonical_entity、label、state、continuity、score、speed、direction、motion_bucket、re_detected、age、`evidence_source=sam2_track`、valid。

独立阈值（不复用 0.85）：

| 参数 | 默认 |
|---|---|
| `max_evidence_age_s` | 2.0 |
| `min_track_score` | 0.5 |
| `min_speed_px_s` | 10.0 |

仅 **frame N 已完成** 的 track 可进入 **frame N+1** VLM；lost/reset/re_detected/过期/session·entity mismatch → `valid=false`。

---

## 6. Fusion truth table（摘要）

| 条件 | 结果 |
|---|---|
| action≠slow_down | reject |
| native conf &lt; 0.85（即使高速 track） | reject（**tracker 不得补置信**） |
| native `functional` + target/phase 匹配 | accept；`task_context_fusion` |
| native `functional` + target mismatch | reject |
| native `dynamic` + conf≥0.85 | accept；`vlm_native` |
| native static + 有效 track + entity 匹配 + conf≥0.85 | accept dynamic；`temporal_fusion`；conf=`min(vlm,track_score)` |
| static 单独 / slow_down 单独 / task 单独 / 静止 track | reject |
| fused conf 抬高 VLM conf | **禁止** |

---

## 7. semantic_key 格式

规范 payload（排序 JSON）→ SHA-256：

`fused_risk_type | recommended_action | canonical_entity | target_container | task_phase | motion_bucket`

- explanation / spatial_hint **不入 key**
- request_id **不入 key**；同 request 不双计 consistency

---

## 8. 测试数

| 套件 | 数量 | 结果 |
|---|---|---|
| `test_v1d2a_temporal_fusion_unit.py` | **35** | OK |
| 全部 `scripts/test_*unit.py` | **140** | OK |

---

## 9. 历史负样本回归

| 样本 | accepted |
|---|---|
| V0-C3 两帧 | **0** |
| V1-C1R-P1 两帧 | **0**（`risk_type_not_allowed`） |
| D1B-S static 0.3/0.7（即使给高速 track） | **fusion 拒绝 + supervisor accepted=0** |

---

## 10. 合成正/反例

均标注 `synthetic=true`，**仅单测**，不得计入论文 live：

- 正：高置信 static + 有效手部运动 → temporal dynamic；functional + 匹配 task
- 反：低 conf+高速；高 conf+静止；entity mismatch

---

## 11. Leakage / control hash

- Semantic leakage 五项、five-stage leakage 五项：测试断言全 0
- control hash：同快照相等；`intentional_control_effect=false`

---

## 12. POST / 网络 / Isaac / Docker

**全部为 0。**

---

## 13. 尚未验证（留给 D2B/C）

- 真实远端对 v2 prompt 的分类质量
- 真实 Isaac live-loop `accepted≥1` + geometry ALLOW
- agent 侧 `task_context_provider` 与协议 phase 的在线接线（本轮仅 worker 钩子）
- D1B 几何时序修复（历史 verdict 未改写）

---

## 14. D2B 所需最多 POST 与精确输入

| 项 | 值 |
|---|---|
| 最多 VLM POST | **4**（建议 2 帧 × 至多 2 种显式 prompt 对照；禁止刷阈值） |
| perception POST | **0**（优先用历史 jsonl track 离线注入；或本轮只测 VLM+fusion） |
| Isaac | **否** |
| 精确 RGB | `…/v1d1b_functional_blockage_capture_20260722/scene/frame_000100_env0.png` SHA `3fdafcbb…` |
| | `…/frame_000200_env0.png` SHA `40d0966a…` |
| 配置 | 显式挂载 `*_temporal_v2.yaml`；confidence **仍 0.85** |

若 D2B 仍无高置信正例 → 结论应为 **当前模型/prompt 不适合控制反馈**，而不是继续放宽门禁。

---

## 15. git diff --stat

已跟踪文件快照（含既有未提交工作树）：

```
 10 files changed, 628 insertions(+), 80 deletions(-)
```

本轮主要交付为 **untracked 新模块/配置/fixtures/测试**（`shadow/`、`safety/semantic_*.py`、`vlm/{prompt_v2,task_context,temporal_evidence,versions}.py`、`configs/*temporal_v2.yaml`、`scripts/test_v1d2a_*`、`fixtures/v1d2a/`）。

---

## 停止

**不进入 D2B。**
