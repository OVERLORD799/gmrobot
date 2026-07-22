# V1-C1R-P1 Isaac semantic shadow replacement validation（2026-07-22）

## 最终判定：**PASS**

| 项 | 值 |
|---|---|
| reason | 正式门禁全部满足；负样本 `accepted=0`（`risk_type_not_allowed`×2）合法 |
| Isaac exit | **0** |
| PROGRESS | **120** |
| POST | **6**（顺序正确；无重试；无第三帧） |
| 重跑 / 调参 / 改代码语义 / 重建镜像 | **否** |
| V1-D | **未进入** |
| 正式配额 | **已消耗**（仅一次） |

---

## 1. 镜像 / runtime config SHA

| 项 | 值 |
|---|---|
| image | `gmdisturb:semantic-shadow-v1c0p1-20260722` |
| image_id | `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c` |
| five-stage cfg | `GMRobot/configs/five_stage_shadow_legacy_gateway_v1c1r_p1.yaml` |
| five-stage SHA | `33e7a4d9bf45131f38742acc2f9f6df2c8e939a86d94af1098d278c3353d5e9a` |
| semantic cfg | `GMRobot/configs/semantic_safety_supervisor_shadow_v1c1r_p1.yaml` |
| semantic SHA | `9915617928d7743e4b4b719e2d33fedde32caac9a2dd0447790df228fae95de5` |
| vs v1c1r | **仅** `log_dir` → 独立 P1 目录；`shutdown_drain_timeout_s=60`、`max_submissions=2`、阈值未改 |

---

## 2. 运行前门禁

| 检查 | 结果 |
|---|---|
| 完整 image SHA | 匹配 `f81e59ce…` |
| canonical module 路径 | `/opt/projects/GMRobot/source/GMRobot/GMRobot/`（`shadow/`、`safety/`、`perception/`、`vlm/` 存在） |
| tunnel socket | `/tmp/gmrobot-v0b2-tunnel.sock` |
| 18080 / 18082 | 监听正常 |
| VLM GET health | HTTP 200，`status=ok` |
| perception GET health | HTTP 200，`warming` / `models_loaded=false`（lazy-load 初态允许） |
| boot `NVRM: Xid` | **0** |
| 残留 Isaac/Kit compute | **无** |
| 结果目录未预存在 | `v1c1r_p1_…` 新建 |

---

## 3. exit / steps / camera / Xid

| 项 | 结果 |
|---|---|
| exit | **0** |
| PROGRESS | **step_counter=120** |
| scene_rgb | ready：`(480, 640, 3)` |
| ModuleNotFoundError / Traceback | **无** |
| DEVICE_LOST / pagefault | **无** |
| Xid 前→后 | **0 → 0** |

---

## 4. canonical import 路径

镜像内验证通过：

- `/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/semantic_bridge.py`
- `/opt/projects/GMRobot/source/GMRobot/GMRobot/safety/semantic_supervisor.py`
- `/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/five_stage_worker.py`

运行日志：`semantic supervisor shadow enabled` + `five-stage shadow enabled`（无 import 失败）。

---

## 5. POST 数 / 顺序 / 重试

| 项 | 结果 |
|---|---|
| POST 总数 | **6** |
| 重试 | **0** |
| 第三帧 | **无** |
| 额外 warm-up POST | **无** |

| 帧 | sim_step | 顺序 |
|---|---|---|
| frame0 | 0 | VLM → ground（cold）→ track_init |
| frame1 | 50 | VLM → ground（warm）→ track_step |

`submitted=processed=logged=2`（`halt_reason=shutdown`）。

---

## 6. 两帧 pipeline

| 帧 | pipeline_ok | ground detections | track_state | track_id |
|---|---|---|---|---|
| 0 | **true** | 10（非空） | `initialized` | **0**（合法） |
| 1 | **true** | 2（非空） | `tracking` | **0**（连续） |

---

## 7. cold / warm latency（分帧，不合并平均）

### Health

| 时刻 | status | models_loaded |
|---|---|---|
| before（运行前 GET） | `warming` | **false** |
| after（结束后 **仅 1×** GET） | `ok` | **true** |

### Frame0（cold）

| 阶段 | latency_ms |
|---|---|
| VLM | 6195.98 |
| ground（cold / lazy-load） | **13118.06**（remote ground `12882.6`） |
| track | 246.68 |
| e2e | 19560.83 |

### Frame1（warm）

| 阶段 | latency_ms |
|---|---|
| VLM | 4799.50 |
| ground（warm） | **472.69**（remote ground `236.1`） |
| track | 230.17 |
| e2e | 21453.66 |

---

## 8. session / track continuity

| 项 | 结果 |
|---|---|
| initialized → tracking | **是** |
| track_id 连续 | **0 → 0** |
| frame1 `session_match` | **true** |
| frame1 `session_continuity_verified` | **true** |
| session_ref / generation | `session_1` / `1` |
| 落盘 session | `<redacted>` |

---

## 9. semantic accepted / rejection

| 项 | 结果 |
|---|---|
| accepted | **0**（负样本合法） |
| rejection_reason | **`risk_type_not_allowed` × 2**（稳定；未调阈值） |
| intentional_control_effect_count | **0** |
| would_stop / would_replan / would_slow | 全 **false** |
| request_id 消费 | 各 **1** 次（`c77479c0…`、`adc69ec4…`） |

---

## 10. capture / decision / age / geometry gate

| request | source_capture_sim_step | decision_sim_step | result_age | geometry_gate | geometry_gate_reason |
|---|---|---|---|---|---|
| c77479c0… | **0** | **120** | **0.00790** | `SLOW_DOWN` | `shutdown_drain` |
| adc69ec4… | **50** | **120** | **0.00341** | `SLOW_DOWN` | `shutdown_drain` |

---

## 11. evaluated / effective gate

| request | evaluated_semantic_gate | effective_control_gate |
|---|---|---|
| c77479c0… | `""`（未接受 → 无 semantic 请求门） | `SLOW_DOWN`（= geometry） |
| adc69ec4… | `""` | `SLOW_DOWN`（= geometry） |

字段分离记录完整；effective 始终跟随 decision-time geometry，未被 semantic 覆盖。

---

## 12. control hash mismatch

`control_hash_mismatch_count = **0**`  
两帧 advisory 的 `control_decision_hash` 相同：`eea9f3ee92df99a9cd579145364390627fd5eba8fdcbd608a4969b7dc11de082`。

---

## 13. 两组 leakage

### Semantic（五项）

运行中 `SemanticLeakageCounters.assert_all_zero()` 每次 flush 通过；`intentional_control_effect_count=0`：

| 计数器 | 值 |
|---|---|
| semantic_gate_apply_count | **0** |
| semantic_action_apply_count | **0** |
| semantic_clock_block_count | **0** |
| semantic_replan_apply_count | **0** |
| semantic_protocol_mutation_count | **0** |

### Five-stage（五项）

| 计数器 | 值 |
|---|---|
| shadow_gate_override_count | **0** |
| shadow_action_override_count | **0** |
| shadow_clock_blocked_steps | **0** |
| shadow_replan_applied_count | **0** |
| shadow_protocol_override_count | **0** |

---

## 14. drain / queue / stale

| 项 | 结果 |
|---|---|
| shutdown_drain_timeout_s | **60.0** |
| drain_elapsed_s | **16.47** |
| drain_complete | **true** |
| pending_at_shutdown_end | **0** |
| worker_thread_alive_after_stop | **false**（`stopped_cleanly=true`） |
| dropped | **0** |
| stale_result_count / stale 唯一 | **0 / 0** |
| queue_depth end | **0** |

---

## 15. 脱敏扫描

对结果树 json/jsonl/csv/txt 扫描：

- raw `track_session_id`（非 `<redacted>`）：**0**
- api_key / Bearer / `sk-` 凭据模式：**0**

---

## 16. 结果路径

`g1_ur10e_disturbance/results/paper_demo/v1c1r_p1_isaac_semantic_shadow_20260722/`

含：`stdout.txt`、`stderr.txt`、`exit_code.txt`、health before/after、xid before/after、runtime config 副本、`five_stage_shadow_20260722_075037/`、`semantic_supervisor_20260722_075037/`、`historical_evidence_sha256.txt`。

---

## 17. 历史证据未覆盖证明

独立新目录；未复用/覆盖：

- V1-C1 NOT_RUN / FAIL：`results/.../v1c1_isaac_semantic_shadow_20260722/`（newest_mtime **早于** P1）
- V1-C1R import FAIL：`results/.../v1c1r_isaac_semantic_shadow_20260722/`（newest_mtime **早于** P1）
- GPU preflight / perception warming / canonical import 审计文档与结果

快照：`results/.../v1c1r_p1_.../historical_evidence_sha256.txt`。

---

## 18. git diff --stat（tracked）

```
 GMRobot/configs/perception_client.yaml             |   1 +
 GMRobot/configs/vlm_client.yaml                    |   3 +
 GMRobot/deploy/ai_server/vlm_service.py            | 119 +++++-----
 GMRobot/scripts/gm_state_machine_agent.py          | 249 +++++++++++++++++++++
 GMRobot/source/GMRobot/GMRobot/__init__.py         |  14 +-
 .../source/GMRobot/GMRobot/perception/__init__.py  |  20 +-
 .../source/GMRobot/GMRobot/perception/client.py    | 101 ++++++++-
 GMRobot/source/GMRobot/GMRobot/vlm/__init__.py     |  35 ++-
 GMRobot/source/GMRobot/GMRobot/vlm/client.py       | 149 ++++++++++--
 9 files changed, 611 insertions(+), 80 deletions(-)
```

本轮正式运行仅新增 bind-mount 配置（`*_v1c1r_p1.yaml`）与本结果/文档；**未**修改代码语义、阈值、prompt、模型或远端服务；**未**重建镜像。

---

## 19. 后续

**停止。不进入 V1-D。**
