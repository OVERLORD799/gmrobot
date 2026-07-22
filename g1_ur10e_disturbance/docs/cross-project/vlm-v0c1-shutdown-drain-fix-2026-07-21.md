# V0-C1.1 Shutdown drain 修复（2026-07-21）

## 结论

| 项 | 值 |
|---|---|
| v0c1_failure_preserved | **true**（`results/paper_demo/v0c1_isaac_shadow_20260721/` 未覆盖） |
| root_cause | **shutdown_drain_insufficient** |
| shutdown_drain_fixed | **true** |
| offline_tested | **94 OK**（含 10 项 drain） |
| new_image | `gmdisturb:five-stage-shadow-v0c2-20260721` |
| new_image_id | `sha256:882da3eef062fe11e7c6a7f2b4dab736c2f235d516910f169a920145f85fb140` |
| real_post_count | **0** |
| v0c2_shadow_not_run | **true** |
| paper_five_stage_complete | **false** |

本轮**未**重跑 V0-C1，**未**真实 POST，**未**靠增加 `max_steps` 掩盖问题。

---

## 根因（V0-C1 FAIL）

- `submitted=2`，`logged=1`
- 第一帧 pipeline **PASS**（~4.8s）
- 第二帧已 submit，但 episode 结束时 `shutdown(stop_timeout_s=2)` < pipeline 耗时
- logger 在第二帧完成前关闭 → 第二帧未落盘
- **不是**模型失败

---

## Drain 实现

`FiveStageShadowScheduler.shutdown()`（仅在 sim loop 结束后）：

1. 禁止新 submit（`_accepting_submissions=False`）
2. 记录 submitted / processed / logged
3. 若未齐：drain，每 50ms 非阻塞 poll，去重写 logger；直到齐或 `shutdown_drain_timeout_s`
4. 再 `worker.stop()`
5. 最后 `logger.close()`

配置：`shutdown_drain_timeout_s: 15.0`（与 `max_submissions: 2`、`stop_submissions_on_pipeline_error: true` 一并写入 v0c yaml）。  
未改 `inference_hz` / `queue_size` / `max_steps` / 模型 timeout。

---

## Worker.stop 语义

返回：`stopped_cleanly` / `thread_alive` / `processed_frames` / `queue_depth`。  
join 超时后若线程仍存活：**不**把 `_thread` 置 `None`；drain 超时不得伪装成功。

---

## 无 POST smoke

- config resolve + fake drain：`V0C2_CONFIG_RESOLVE_OK` / `V0C2_DRAIN_FAKE_OK`（2/2）
- 1-step Isaac（shadow 关）：exit 0，`scene_rgb` ready，无 Traceback，无 endpoint

---

## 先验镜像未覆盖

| tag | id |
|---|---|
| `b4-p010-20260721` | `defe95e7…` |
| `five-stage-shadow-v0c-20260721` | `b28c65a6…` |
| `five-stage-shadow-v0c1-20260721` | `b32fbd1a…` |
