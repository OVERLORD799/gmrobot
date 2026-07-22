# V0-B4 正式 Legacy Gateway 两帧真实回放（2026-07-21）

## 最终分类：**FORMAL_GATEWAY_REPLAY_PASS**（审计）

| 层 | 值 | 文件 |
|---|---|---|
| 原始退出 | `GROUND_FAIL` | `five_stage_shadow_summary.json`、`replay_summary.json`（保留） |
| 确定性审计 | `FORMAL_GATEWAY_REPLAY_PASS` | **`audited_summary.json`**（新增，不覆盖 raw） |

PASS 基于原始响应的确定性审计修正：**没有重跑 POST**。  
Future runner 已修：`stale_result_count` 唯一计数；step 不再要求 keyword 重匹配。

### 明确非声称

- **负样本** scene RGB replay
- **非**人体 / 工具 / PPE 语义验证
- **非** Isaac shadow
- **非**论文五阶段最终完成
- `track_state` 为 **legacy gateway 推导**（`track_state_native=false`）
- 新 ID 为 **local_gateway** 维护
- 真实模型与延迟仅证明**工程可行性**，不可当语义准确率

---

## V0-B4.1 指标/校验修复（离线，无 POST）

1. **stale_result_count**：按 `(request_id, frame_id, completed_at_s)` 唯一计数；轮询记入 `stale_poll_count`。原始 raw=48 → 语义期望 **1**。
2. **replay validator**：keyword match **仅 init**；step 验 session/track_id/box/mask/score/tracking|lost。
3. raw 文件不可变；审计写入 `audited_summary.json`。

---

## POST 预算

| 顺序 | alias | 结果 |
|---|---|---|
| 1 | vlm_analyze（frame0） | completed |
| 2 | ground（frame0） | completed |
| 3 | track_init | completed |
| 4 | vlm_analyze（frame1） | completed |
| 5 | ground（frame1） | completed |
| 6 | track_step | completed |

**实际 POST = 6**；重试 = 0；凭据/tunnel/远端修改 = 无。

---

## 两帧结果

### Frame 0（`frame_000000`）

| 项 | 值 |
|---|---|
| VLM | schema PASS；keywords=`robotic arm, electronic device, human safety` |
| ground | 7 detections；真实 GDINO/SAM2 |
| track | **initialized**；`track_id=0` |
| VLM/ground/track latency_ms | ~3861 / ~484 / ~225 |
| e2e_ms | ~4571 |
| submit_ms | ~0.016 |

### Frame 1（`frame_000010`）

| 项 | 值 |
|---|---|
| VLM | schema PASS；keywords=`robotic arm, container, small objects` |
| ground | 2 detections |
| track | **tracking**；`track_id=0`（与帧0关联） |
| VLM/ground/track latency_ms | ~3617 / ~512 / ~232 |
| e2e_ms | ~4361 |
| submit_ms | ~0.018 |

Session：gateway 输出 `session_present` / redacted id；`id_source=local_gateway`。

---

## 隔离

| 项 | 值 |
|---|---|
| dropped_frames | **0** |
| leakage 五项 | **全 0** |
| retries | **0** |
| stale_result_count | 48（wait 轮询 `latest_result` 在 `max_result_age_s` 后重复计入；**非**队列丢帧） |

使用组件：`VLMClient legacy_v2`、`PerceptionClient legacy_v2`、`Legacy*Gateway`、`FiveStageShadowWorker`、`FiveStageShadowLogger`、V0-B3.1 keyword→track 接线。

---

## 产物

```text
g1_ur10e_disturbance/results/paper_demo/v0b4_legacy_gateway_replay_20260721/
  request_ledger.jsonl
  input_manifest.json
  frame_000000_result.json
  frame_000010_result.json
  five_stage_shadow_*.jsonl/csv/json
  replay_summary.json
  post_run_audit.json
  stdout.txt / stderr.txt

GMRobot/scripts/run_v0b4_legacy_gateway_replay.py
docs/cross-project/vlm-v0b4-legacy-gateway-replay-2026-07-21.md
```

**已停止。未进入 Isaac shadow。**
