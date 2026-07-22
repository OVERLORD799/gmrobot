# GMRobot 五阶段 V0-A 实现报告（2026-07-21）

## 结论

**V0-A 离线 shadow 基础设施已实现（P0-1…P0-6）。未进行真实模型推理、网络连接、Isaac、Docker 或凭据读取。五阶段闭环仍未完成，不得宣称 LIVE-VALIDATED。**

物理基准仍冻结于 `defe95e…`，本轮未改动。

## P0-1 … P0-6 对照

| ID | 状态 | 说明 |
|---|---|---|
| P0-1 | **完成** | 删除 `static/medium/slow_down` 硬编码；严格 schema；stub → `ok=false` + `stub_mode` |
| P0-2 | **完成** | `perception_service.py` contract + `FakePerceptionBackend` / `UnavailableBackend`；无权重 |
| P0-3 | **完成** | keywords 规范化 → ground payload；空 keywords → `skipped_no_keywords` |
| P0-4 | **完成** | `FiveStageShadowWorker` 有界队列 + latest-frame-wins；submit 不做 HTTP |
| P0-5 | **完成** | `enforcement_mode=shadow`；`shadow_control_decision` 零泄漏；默认 disabled |
| P0-6 | **完成** | request_id/frame_id/parent_request_id/track_* 贯通 + schema/prompt/model 版本字段 |
| P0-7 | **未解决** | 无真实 RGB artifact |
| P0-8 | **未解决** | 无真实 endpoint 可达性验证 |

## 改动文件清单

新增：

- `GMRobot/source/GMRobot/GMRobot/vlm/schema.py`
- `GMRobot/source/GMRobot/GMRobot/vlm/service_handlers.py`
- `GMRobot/source/GMRobot/GMRobot/perception/schema.py`
- `GMRobot/source/GMRobot/GMRobot/perception/backends.py`
- `GMRobot/source/GMRobot/GMRobot/shadow/`（worker / logger / isolation）
- `GMRobot/deploy/ai_server/perception_service.py`
- `GMRobot/configs/five_stage_shadow.yaml`
- 6 个新离线单测脚本

修改：

- `GMRobot/deploy/ai_server/vlm_service.py`
- `GMRobot/source/GMRobot/GMRobot/vlm/client.py`（默认 localhost；结构化 analyze）
- `GMRobot/configs/vlm_client.yaml`
- `GMRobot/source/GMRobot/GMRobot/perception/client.py`（keywords API）
- `GMRobot/scripts/gm_state_machine_agent.py`（`--enable_five_stage_shadow`）

未修改：`g1_vlm_client.py`、B0/B1/B2/B4 YAML/结果/冻结文档。

## 数据流（V0-A）

```text
camera RGB
  → FiveStageShadowWorker.submit()   # 控制线程，无 HTTP
  → bounded queue (latest-frame-wins)
  → worker: VLMClient.analyze / schema
  → keywords
  → PerceptionClient.ground(keywords=…)
  → optional track
  → FiveStageShadowLogger (独立 JSONL/CSV)
  → would_stop / would_replan 仅审计
```

Shadow **不**写入 gate / action / policy clock / replan。

## Shadow 隔离证明

- `shadow_control_decision(..., enforcement_mode="shadow")` 原样返回控制字段。
- `FiveStageShadowWorker.leakage` 五计数器恒为 0；`assert_no_control_side_effects()`。
- 当 five-stage shadow 启用时，旧 live `run_vlm_inference` → `vlm_stage5_replan` 路径被绕开。

## 测试

新增测试函数：**25**（6 个文件）。旧 logger 单测继续通过。

| 命令 | 退出码 |
|---|---:|
| `python scripts/test_vlm_schema_unit.py` | 0 |
| `python scripts/test_vlm_service_contract_unit.py` | 0 |
| `python scripts/test_perception_service_contract_unit.py` | 0 |
| `python scripts/test_five_stage_shadow_worker_unit.py` | 0 |
| `python scripts/test_five_stage_shadow_logging_unit.py` | 0 |
| `python scripts/test_five_stage_shadow_isolation_unit.py` | 0 |
| `python scripts/test_safety_logger_vlm_unit.py` | 0 |
| `python scripts/test_safety_logger_perception_unit.py` | 0 |

`submit()` 最大测得耗时约 **0.017 ms**（慢 HTTP 在 worker 线程）。

## 明确声明

- **没有**真实模型推理。
- Fake backend 仅用于 contract 测试，**不得**写入论文结果。
- 五阶段仍 **未** LIVE-VALIDATED。

## 下一阶段 V0-B 所需资源

1. 少量真实 RGB 帧（或短采集许可）
2. 可达 VLM / perception endpoint（审批后）
3. 凭据（`.github_token` 末行声明；V0-A 未读取）
4. 远端模型权重确认

完成后停止；不自动进入 V0-B。
