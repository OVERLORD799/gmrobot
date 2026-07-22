# V0-B3 Legacy Compatibility Gateway 实现（2026-07-21）

## 状态

| 字段 | 值 |
|---|---|
| gateway_implemented | **true** |
| offline_tested | **true** |
| live_probe_evidence | **COMPOSITE**（V0-B2B probe + track-step continuation） |
| formal_gateway_live_replay | **true**（V0-B4；审计 PASS，见 B4.1） |
| negative_scene_only | **true** |
| stale_metric_bug_fixed | **true**（V0-B4.1） |
| replay_validator_bug_fixed | **true**（V0-B4.1） |
| human_tool_ppe_validated | **false** |
| isaac_shadow_validated | **false** |
| paper_five_stage_complete | **false** |

V0-B3 本轮曾：**仅实现 + 离线测试**。V0-B4 已做正式 6×POST；V0-B4.1 为离线指标/校验修复（无重跑）。无改远端/tunnel/凭据、无改 B0–B4 冻结镜像。

---

## V0-B3.1 live wiring correction（2026-07-21）

**问题**：正式路径若 track callback 只收到 `detections`、不收 VLM `keywords`，
`select_detection_for_track` 会退化为“最高分标签”，违背“关键词匹配优先”。

**修复**（`shadow/five_stage_worker.py`）：

1. VLM `keywords` 经 `perception.schema.normalize_keywords` 规范化；
2. 同一列表同时传给 ground 与 track：`keywords=keywords`；
3. 空 keywords → `skipped_no_keywords`，**不**调用 ground/track。

**证明测试**：

- 高分非匹配 detection 不得压过低分关键词匹配目标；
- worker 实际把规范化 keywords 传给 track callback；
- 空 keywords 行为明确；
- canonical_v0a 默认不受影响；
- leakage 五项为 0。

本项为 **live wiring correction**；仍未批准真实 gateway 6×POST 回放。

---

## 实现摘要

### 模块

| 文件 | 作用 |
|---|---|
| `vlm/legacy_gateway.py` | 旧 `/analyze` → canonical `five_stage_vlm_v1`（仅解析 `text`） |
| `perception/legacy_gateway.py` | 旧 `/ground`+`/track` → canonical + **有状态** session lifecycle |
| `vlm/client.py` | `contract_mode`: `canonical_v0a`（默认）/ `legacy_v2` |
| `perception/client.py` | 同上；`legacy_track_callback` 托管 session |
| `shadow/five_stage_worker.py` | 接收有状态 track；输出 gateway 元数据；`track_id=0` 安全 |
| `gm_state_machine_agent.py` | legacy 模式下注入 `perception_track`（状态不在 agent 散落） |

### 配置（显式，不静默切换）

- `configs/five_stage_shadow.yaml` → `contract_mode: canonical_v0a`（保持）
- `configs/five_stage_shadow_legacy_gateway.yaml` → `legacy_v2`，`enabled: false`，仅 localhost
- `configs/vlm_client_legacy_gateway.yaml` / `perception_client_legacy_gateway.yaml`

禁止根据 health 自动切换协议。

### 关键行为

- VLM：严格五阶段 prompt；ID 仅放 `meta`；不用 `vlm_*` 补造 consequence/horizon/entities/spatial_hint
- Ground：keywords → `text_prompt`；本地 `detection_id` / `keyword_detection_map`；空 label 不计 match
- Track：init/step/reset；推断 `track_state` 且 `track_state_native=false`；同帧失败不重试；`track_id=0` 合法
- Worker：submit 非阻塞；leakage 五计数保持 0；shadow 不进 live replan

---

## 测试

新增 **23** 个用例：

- `test_vlm_legacy_gateway_unit.py`（8）
- `test_perception_legacy_gateway_unit.py`（11）
- `test_five_stage_legacy_gateway_pipeline_unit.py`（4）

脱敏 fixture：`scripts/fixtures/v0b3_legacy/`（无真实 session UUID / b64 / host / 凭据）

**回归全绿**：原 V0-A schema/service/worker/isolation/logging/logger + 上述 23。

---

## 尚未验证（明确边界）

- 人体 / 工具 / PPE 语义
- Isaac 内 shadow 实跑
- 论文五阶段 LIVE 统计
- 真实 gateway 对 tunnel 的在线调用（本轮禁止）

证据基线未覆盖：`v0b2b_legacy_probe_20260721` / `v0b2b_track_step_continuation_20260721`。

---

## 状态 JSON

见 `vlm-v0b3-legacy-gateway-status-2026-07-21.json`。

**已停止。未运行真实 gateway / Isaac shadow。**
