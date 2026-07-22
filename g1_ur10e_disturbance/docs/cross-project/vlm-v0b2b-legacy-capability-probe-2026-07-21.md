# V0-B2B 旧远端服务受限能力探测（2026-07-21）

## 最终分类：**TRACK_INIT_FAIL**

`five_stage_paper_validated=false`  
`LEGACY_GATEWAY_FEASIBLE` **未达成**（track step 未执行）

> 负样本 scene RGB（工业场景），**不含**人手 / PPE / 工具语义验证。

---

## 执行约束遵守情况

| 项 | 结果 |
|---|---|
| 实际 POST 总数 | **3**（≤4） |
| 重试 | **0** |
| 读取凭据 / `.github_token` | **否** |
| 修改 tunnel / 远端 | **否** |
| Isaac / Docker / B0–B4 | **否** |
| FakePerceptionBackend | **否** |
| 用 legacy `vlm_*` 补造 schema | **否**（已忽略） |

脚本：`GMRobot/scripts/probe_v0b2b_legacy_endpoint.py`  
离线 limiter 测试：12 passed。

---

## 每步 POST

| # | alias | 时间 (UTC) | HTTP | 耗时 | 结果 |
|---|---|---|---|---|---|
| 1 | `vlm_analyze` `/analyze` | planned 09:34:10 → done 09:34:14 | 200 | **4.45 s** | schema 门禁 **PASS** |
| 2 | `ground` `/ground` | planned 09:34:14 → done 09:34:22 | 200 | **7.49 s** | 真实 detections **PASS** |
| 3 | `track_init` `/track` init | planned/done 09:34:22 | 200 | **0.23 s** | 远端成功；**本地门禁误判 FAIL** |
| 4 | `track_step` | — | — | — | **未执行** |

### 事后审计（无额外 POST）

远端 init 响应含：

- `session_id=6b39b416-…`
- `tracks[0].track_id=0`（整数零）
- 合法 `box_xyxy` / `mask_area=57955` / `sam2_score≈0.966`

探针使用 `bool(track_id)`，将 `0` 当成缺失 → 记录 `TRACK_INIT_FAIL` 并停止。  
**按批准：不重跑、不做第 4 次 POST。**  
脚本已事后修正为 `track_id is not None`（允许 0），但**未再次执行**。

因此：**不能**改判为 `LEGACY_GATEWAY_FEASIBLE`；track 时序能力本轮**未证明**。

---

## VLM

- **model_id**：`Qwen2.5-VL-7B-Instruct-4bit-nf4`（响应体）
- 从 `text` 提取完整目标 JSON：**是**
- 全部必需字段 + 枚举 / confidence / keywords / consequence / horizon：**PASS**
- keywords：`["robotic arm", "electronic device", "human safety"]`
- legacy `vlm_*` 字段存在但**未用于**补造

## Ground

- **gdino_model_id**：`IDEA-Research/grounding-dino-base`
- **sam2_checkpoint**：`sam2.1_hiera_small.pt`
- detections：7（非空）
- keywords→detection：成立（如 `electronic device` score≈0.49；`robotic arm` score≈0.41）
- 选择：keyword 匹配后最高分 → `electronic device` + SAM2 mask

## Track

- init：**远端 HTTP 200 成功**；本轮因本地门禁未进入 step
- `track_state_native`：远端 schema 无该字段（legacy）
- session/track ID 关联：仅本地 ledger；**不**把远端未回显 local UUID 当成 ID 贯通成功

---

## ID 关联（本地）

| 角色 | ID |
|---|---|
| VLM `local_request_id` | `08f0adfe-3d96-4daf-bb92-0a0a8221c630` |
| frame_id（frame0） | `1503005b-57ad-40b2-b10b-8b97b0385fb8` |
| ground `local_request_id` | `5d867cb0-d0c9-4a47-942c-9d42f72b06af` |
| track_init `local_request_id` | `5c74ba28-328e-4ed8-af8b-38189eb89013` |
| remote `session_id` | `6b39b416-f32a-4151-b529-3cccc7e16149` |
| remote `track_id` | `0` |

---

## Gateway 是否值得实现？

**有条件值得**（基于本轮证据，非 FEASIBLE 终局）：

- VLM：旧 `/analyze` 的 `text` 已能产出完整五阶段 JSON
- Ground：真实 GDINO/SAM2，keywords→`text_prompt`→detections 成立
- Track init：远端看起来可用（含 `track_id=0`）
- 缺口：本轮未验证 step；无 native `track_state`；health/openapi 仍非 V0-A

完整声明 `LEGACY_GATEWAY_FEASIBLE` 需要**另一次批准**的受限 probe（修复门禁后跑完 init+step，仍 ≤4 POST，新空目录）。

---

## 产物

```text
GMRobot/scripts/probe_v0b2b_legacy_endpoint.py
GMRobot/scripts/test_v0b2b_probe_limiter_unit.py
g1_ur10e_disturbance/docs/cross-project/vlm-v0b2b-legacy-capability-probe-2026-07-21.md
g1_ur10e_disturbance/results/paper_demo/v0b2b_legacy_probe_20260721/
  request_ledger.jsonl
  input_manifest.json
  vlm_*.json ground_*.json track_*.json
  probe_summary.json
  post_run_audit.json
  stdout.txt stderr.txt
```

**已停止。未再次运行探测脚本。**
