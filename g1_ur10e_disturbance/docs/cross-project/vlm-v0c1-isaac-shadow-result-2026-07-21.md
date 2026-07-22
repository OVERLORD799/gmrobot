# V0-C1 Isaac five-stage short shadow 结果（2026-07-21）

## 最终分类：**FAIL**

按门禁停止；**不调参、不重跑**；产物已保留。

| 保留证据 | 值 |
|---|---|
| submitted | **2** |
| logged | **1** |
| 第一帧 | **PASS** |
| 第二帧 | 未完成 / 未落盘 |
| root_cause | **shutdown_drain_insufficient** |
| no_rerun | **true** |

（生命周期修复见 `vlm-v0c1-shutdown-drain-fix-2026-07-21.md`；本目录结果不被覆盖。）

### 明确非声称 / 运行上下文

- **负样本** scene RGB（非人体 / 工具 / PPE 语义验证）
- **safety disabled**；shadow **独立于** safety
- local gateway IDs；inferred track state
- **非**论文最终五阶段完成
- 未启用 `--enable_vlm` / `--enable_perception` / `--enable_replan`

---

## V0-C0.1 修复（本轮先做）

1. **配置路径**：`resolve_shadow_client_configs` — `GMROBOT_ROOT` → shadow 目录 → cwd；启动前明确失败。
2. **熔断**：`pipeline_ok` / `pipeline_error_stage` / `pipeline_error` + `stop_submissions_on_pipeline_error`。
3. 离线测试 **84 OK**（含 resolve + halt）。
4. 新镜像 `gmdisturb:five-stage-shadow-v0c1-20260721`
   `sha256:b32fbd1acb0d57fd79fcf6df4e3654784bb732eb14fc20e0e7b79b90dfe1af46`  
   （未覆盖 `defe95e7…` / `b28c65a6…`）

---

## 正式短 Shadow 执行摘要

| 项 | 值 |
|---|---|
| Isaac exit | **0** |
| steps | 120（PROGRESS 见到 120） |
| cameras | `scene_rgb` ready |
| submitted_count | **2** |
| logged_result_count | **1**（要求 2 → FAIL） |
| processed（首条 metrics） | **1** |
| dropped_frames | 0 |
| stale_result_count | 0 |
| halt_submissions | false |
| leakage 五项 | **全 0** |
| Traceback | 无 |
| 冻结镜像 | 未变 |
| 远端修改 | 无 |
| 重试 | 0 |

### 已确认完成的 POST（≥3）

唯一完整落地帧（sim_step=0）：

1. VLM analyze ≈ 3979 ms — schema OK；keywords=`robotic arm, enclosure, pins, white object`
2. ground ≈ 524 ms — 10 detections
3. track init ≈ 264 ms — `track_state=initialized`，`track_id=0`，`id_source=local_gateway`

第二帧：scheduler 已 submit（`submitted_count=2`），但 **shutdown 前未写入 logger**（疑似仍在飞或 `stop()` 后未再 poll）。上界估计 POST≤6；**不能证明**完整 6 次顺序。

### 未满足的 PASS 项

- logged unique results ≠ 2
- 未能证明第二帧 VLM/ground/track_step 全完成
- 无法验证 init→tracking 跨帧 `session_match` / track_id 连续

---

## 产物路径

`g1_ur10e_disturbance/results/paper_demo/v0c1_isaac_shadow_20260721/`

- `five_stage_shadow_requests.jsonl`
- `five_stage_shadow_steps.csv`
- `five_stage_shadow_summary.json`
- `run_manifest.json`
- `stdout.txt` / `stderr.txt`
- 会话子目录 `five_stage_shadow_20260721_114857/`（原始）

状态 JSON：`docs/cross-project/vlm-v0c1-isaac-shadow-status-2026-07-21.json`
