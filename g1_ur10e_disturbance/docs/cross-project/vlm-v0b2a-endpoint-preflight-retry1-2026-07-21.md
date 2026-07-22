# V0-B2A endpoint 预检（retry1，2026-07-21）

## 判定：**CONTRACT_MISMATCH**

`endpoint_contract_ready=false`  
`ready_for_v0b2b_single_frame=false`

首次 UNAVAILABLE 产物保留于  
`results/paper_demo/v0b2a_endpoint_preflight_20260721/`（未覆盖）。

---

## 可达性（本轮）

| alias | safe authority | GET /health | GET /openapi.json |
|---|---|---|---|
| `vlm_endpoint` | `http://127.0.0.1:18080` | HTTP 200 | HTTP 200 |
| `perception_endpoint` | `http://127.0.0.1:18082` | HTTP 200 | HTTP 200 |

未 POST；未读凭据；未由 agent 创建 tunnel；未跑 Isaac。

---

## VLM：FAIL（`VLM_CONTRACT_MISMATCH`）

### Health（脱敏）

```json
{
  "status": "ok",
  "model_id": "Qwen/Qwen2.5-VL-7B-Instruct",
  "gpu": "NVIDIA L40S"
}
```

| 检查 | 结果 |
|---|---|
| HTTP 200 | PASS |
| `ok=true` | 仅有遗留 `status=ok`（无 `ok` 字段） |
| `stub=false` | **FAIL**（字段缺失） |
| `schema_version=five_stage_vlm_v1` | **FAIL**（缺失） |
| `prompt_version=five_stage_safety_v1` | **FAIL**（缺失） |
| `model_id` 非空 | PASS |
| `gpu` | PASS（设备名 `NVIDIA L40S`） |
| `loaded` | 缺失（记为未验证；不得声称模型已验证） |

### OpenAPI `/analyze`

| 检查 | 结果 |
|---|---|
| 路径存在 | PASS |
| 请求含 `request_id`,`frame_id`,`prompt_version`,`schema_version` | **FAIL**（仅有 `image_b64`,`image_path`,`meta`,`prompt`） |
| 响应为 V0-A 结构化成功/显式失败 | **FAIL**（为遗留 `vlm_*` / `text` / `detail` 字段，无 V0-A `ok`/`error_code`/`schema_version` 等） |

结论：远端为**旧 VLM 服务**，不是 V0-A `five_stage_vlm_v1` 合约。

---

## Perception：FAIL

标签：`REAL_PERCEPTION_BACKEND_NOT_READY` + `PERCEPTION_TRACK_API_MISMATCH` + `PERCEPTION_SCHEMA_MISMATCH`

### Health（脱敏）

```json
{
  "status": "warming",
  "gdino_model_id": "IDEA-Research/grounding-dino-base",
  "sam2_checkpoint": "sam2.1_hiera_small.pt",
  "gpu": "NVIDIA L40S",
  "models_loaded": false
}
```

| 检查 | 结果 |
|---|---|
| HTTP 200 | PASS |
| `ok=true` | **FAIL**（`status=warming`） |
| `backend_available=true` | **FAIL**（字段缺失；`models_loaded=false`） |
| `schema_version=five_stage_perception_v1` | **FAIL**（缺失） |
| GDINO/SAM2 标识 | 遗留扁平字段存在（非 fake/test/mock） |
| 真实 backend 就绪 | **否**（仍 warming / 未加载） |

### OpenAPI

| 路径 | 结果 |
|---|---|
| `/ground` | 存在 |
| `/track/init`,`/track/step`,`/track/reset` | **缺失**（仅有合并 `/track`） |
| `/ground` 含 `request_id`,`frame_id`,`keywords`,`text_prompt`,`run_sam2` | **部分失败**（有 `text_prompt`,`run_sam2`；缺 `request_id`,`frame_id`,`keywords`） |
| track 含 `track_session_id`,`track_id`,`track_state` | **FAIL**（openapi 见 `session_id`/`action`/`init`，无 `track_session_id`/`track_state`） |

不得用 FakePerceptionBackend 替代。本轮也**未**声称真实推理可用。

---

## 最小方案（仅建议；agent 不部署、不 POST）

### 方案 1 — Compatibility gateway（本地适配）

在客户端与 tunnel 之间加薄网关：

- 映射 health：补齐/翻译 `ok`、`stub`、`schema_version`、`prompt_version`、`backend_available`、`model_versions`
- `/analyze`：注入 `request_id`/`frame_id`/versions；把遗留 `vlm_*` 响应规范化为 V0-A schema（含显式失败）
- perception：把 V0-A `/track/init|step|reset` 适配到远端单一 `/track`；`/ground` 补 `keywords`→`text_prompt`
- **仍须**远端 models 实际 loaded 后才能做 B2B；网关不能把 `warming` 伪造成 ready

### 方案 2 — 远端升级到 V0-A（运维侧）

部署/替换为仓库内：

- `GMRobot/deploy/ai_server/vlm_service.py` + `vlm/schema.py` + `vlm/service_handlers.py`
- `GMRobot/deploy/ai_server/perception_service.py` + **真实** GDINO/SAM2 `PerceptionBackend`（非 Fake / 非默认 Unavailable）

升级后 health 必须出现 `five_stage_vlm_v1` / `five_stage_safety_v1` / `five_stage_perception_v1`，以及分离 track 路由。

---

## 操作声明

- 未读 `.github_token`；未输出密码/token
- 未创建新 tunnel；未部署远端
- 仅 GET `/health` + `/openapi.json`；timeout ≤ 5s；每 URL 最多一次重试（本轮均一次成功）
- 未进入 V0-B2B；未跑模型推理 POST

---

## 产物

```text
docs/cross-project/vlm-v0b2a-endpoint-preflight-retry1-2026-07-21.md
results/paper_demo/v0b2a_endpoint_preflight_retry1_20260721/
  vlm_health_redacted.json
  perception_health_redacted.json
  contract_summary.json
  openapi_summary.json
  *_raw.body / *_raw.meta   # 本地原始响应（gitignore）
```

**停止。等待合约对齐或批准 gateway 方案后再议 V0-B2B。**
