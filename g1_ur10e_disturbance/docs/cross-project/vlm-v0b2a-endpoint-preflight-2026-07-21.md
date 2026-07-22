# V0-B2A 真实 endpoint 合约与后端能力预检（2026-07-21）

## 判定：**D — UNAVAILABLE**

`endpoint_contract_ready=false`  
`ready_for_v0b2b_single_frame=false`

### 原因

Agent 执行环境中：

| 变量 | 状态 |
|---|---|
| `GMROBOT_VLM_BASE_URL` | **缺失** |
| `GMROBOT_PERCEPTION_BASE_URL` | **缺失** |

按门禁：**环境变量必须存在才允许发 GET**。本轮未对任何 host 发起请求，未创建 tunnel，未读凭据，未 POST，未跑 Isaac。

---

## 期望合约（V0-A 本地源码）

| 端点 | 字段 | 期望值 |
|---|---|---|
| VLM | `schema_version` | `five_stage_vlm_v1` |
| VLM | `prompt_version` | `five_stage_safety_v1` |
| VLM | `ok` / `stub` | `true` / `false` |
| VLM | `model_id` | 非空 |
| VLM | `gpu` | `true`，或文档说明异地推理 |
| VLM | `loaded` | 可为 `false`（仅记“未首次加载”，不得当模型已验证） |
| Perception | `schema_version` | `five_stage_perception_v1` |
| Perception | `ok` / `backend_available` | `true` / `true` |
| Perception | `model_versions` | 明确含 GDINO + SAM2；不得含 fake/test/mock |

OpenAPI 期望：

- VLM：`POST /analyze` 请求含 `request_id`、`frame_id`、`prompt_version`、`schema_version`；响应能表达结构化成功与显式失败（非旧 `static/medium/slow_down` 硬编码）。
- Perception：至少 `/ground`、`/track/init`、`/track/step`、`/track/reset`；`/ground` 含 `request_id`、`frame_id`、`keywords`、`text_prompt`、`run_sam2`；track 含 `track_session_id`、`track_id`、`track_state`。

本地参考实现（**未部署、未修改远端**）：

- `GMRobot/deploy/ai_server/vlm_service.py`
- `GMRobot/deploy/ai_server/perception_service.py`
- `GMRobot/source/GMRobot/GMRobot/vlm/schema.py`
- `GMRobot/source/GMRobot/GMRobot/perception/schema.py` / `backends.py`

默认 perception 后端为 `UnavailableBackend`（`PERCEPTION_BACKEND` 未设或非 `fake`）。**不得**用 Fake 冒充真实 GDINO/SAM2。

---

## 观测结果

| 检查 | 结果 |
|---|---|
| VLM `GET /health` | **未执行**（UNAVAILABLE） |
| VLM `GET /openapi.json` | **未执行** |
| Perception `GET /health` | **未执行**（UNAVAILABLE） |
| Perception `GET /openapi.json` | **未执行** |
| 真实 GDINO/SAM2 backend | **未知 / 未验证** |

脱敏产物中 `redacted_body=null`（无响应体）。

---

## 若后续出现其他判定（参考，本轮未触发）

### B — `VLM_CONTRACT_MISMATCH` 最小部署文件清单（不得由 agent 自行部署）

1. `GMRobot/deploy/ai_server/vlm_service.py`
2. `GMRobot/source/GMRobot/GMRobot/vlm/schema.py`
3. `GMRobot/source/GMRobot/GMRobot/vlm/service_handlers.py`
4. 依赖：FastAPI / uvicorn / 目标 VLM 运行时（由运维侧配置；本预检不下载）

### C — `REAL_PERCEPTION_BACKEND_MISSING` 真实 adapter 接口清单

实现 `PerceptionBackend`（见 `perception/backends.py`）：

- 属性：`available`、`model_versions`（含真实 `gdino_model_id` / `sam2_model_id`，非 fake）
- 方法：`ground`、`track_init`、`track_step`、`track_reset`
- 服务入口：`perception_service.set_backend(...)`；**禁止**默认/生产使用 `FakePerceptionBackend`
- 合约字段：`schema_version=five_stage_perception_v1`；响应含 track 会话与状态字段

### D — 本轮

用户在 **agent 外部**：

1. 建立 SSH tunnel（如需要）；
2. `export GMROBOT_VLM_BASE_URL=...`（仅 scheme://host:port，无 userinfo/query 密钥）；
3. `export GMROBOT_PERCEPTION_BASE_URL=...`；
4. 在同一 shell 中重新批准执行 V0-B2A。

---

## 安全与操作声明

- 未读 `.github_token`；未输出密码/token/key
- 未创建 tunnel；未部署/修改远端服务
- 未 POST；未模型推理；未跑 Isaac；未重建 Docker；未改 B0–B4
- 未把 UNAVAILABLE 记为代码通过
- 未声称五阶段 LIVE 验证完成

---

## 产物

```text
g1_ur10e_disturbance/docs/cross-project/vlm-v0b2a-endpoint-preflight-2026-07-21.md
g1_ur10e_disturbance/results/paper_demo/v0b2a_endpoint_preflight_20260721/
  vlm_health_redacted.json
  perception_health_redacted.json
  contract_summary.json
```

**停止。不进入 V0-B2B 单帧推理。**
