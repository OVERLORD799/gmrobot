# V1-D3A Dyn-C Fixed-Frame Replay Preregistration (2026-07-24)

- status: **PREREGISTERED_BLOCKED_ON_TUNNEL**（设计+脚本就绪，执行等待 AI 服务器隧道）
- 输入样本：`E02-DYN-C-E2K-STEP170-249`（manifest v3.3.0，reviewer_approved=true）
- 脚本：`GMRobot/scripts/run_v1d3a_dyn_c_fixed_frame_replay.py`
- 单元测试：`GMRobot/scripts/test_v1d3a_gate_eval_unit.py`（门禁判定逻辑离线验证）

## 目的

回应 D2B 结论（"下一步应为专门的 prompt/model 评估，而非放宽门禁"）：用**已批准的动态正样本**探测 VLM 对底层控制反馈的两条边界。

## Phase 1 — native discipline（无时序证据）

- POST 帧 170、249 各一次（prompt v2，temporal evidence=none，诚实 TaskSemanticContext：idle/none/false/unknown）。
- prompt v2 规则明文要求"无有效运动证据不得猜 dynamic"。
- **预注册判定**：
  - 两帧 `risk_type != dynamic` 且 parse OK → `D3A_NATIVE_DISCIPLINE_PASS`（模型守规）；
  - 任一帧无证据猜 dynamic → `D3A_NATIVE_DISCIPLINE_FAIL`（过度声称，控制级不可用证据）。

## Phase 2 — 真实 SAM2 时序融合（`--with-sam2`，需 18082）

- GDINO ground（帧 170）→ SAM2 track init → track 帧 249 → 由**真实 track 结果**构造 `TemporalTrackEvidence`（合同强制 `evidence_source=sam2_track`；**body-pose 真值永不冒充运动证据**，遵守 D2B §13 边界）。
- 证据经 `validate_temporal_evidence` 校验后，POST 帧 249（prompt v2 + evidence）。
- **预注册判定**：`risk_type=dynamic` 且 `conf >= 0.85` 且 evidence valid → `D3A_TEMPORAL_DYNAMIC_PASS`；否则 `D3A_TEMPORAL_DYNAMIC_FAIL`（如实记录，不调 prompt、不降门槛、不重试）。
- 这是 D2B 留空的 "static→dynamic temporal fusion 真实验证" 的首次执行。

## 执行约束

- 单次执行、retry=0、POST 计数如实记录（Phase1=2；Phase2 另计 ground/init/track/analyze）；
- shadow-only：无 Isaac、无控制作用、不启用 active semantic control；
- 帧 SHA256 与 manifest 预检一致才允许 POST（fail-closed）；
- 0.85 置信门槛不变。

## 阻塞项

- `127.0.0.1:18080`（VLM）与 `127.0.0.1:18082`（感知）均未响应；SSH 隧道需密码凭证（`ssh -f -N -L 18080:127.0.0.1:8080 -L 18082:127.0.0.1:8082 -p 30481 root@120.209.70.195`），需用户建立隧道后执行：

```bash
python3 GMRobot/scripts/run_v1d3a_dyn_c_fixed_frame_replay.py \
  --result-dir g1_ur10e_disturbance/results/paper_demo/v1d3a_dyn_c_fixed_frame_replay_20260724 \
  --with-sam2
```
