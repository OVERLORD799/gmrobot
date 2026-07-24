# V1-D3A Dyn-C Fixed-Frame Replay Result (2026-07-24)

## Verdicts

- **Phase 1（native discipline）：`D3A_NATIVE_DISCIPLINE_PASS`**
- **Phase 2（真实 SAM2 时序融合）：`D3A_TEMPORAL_DYNAMIC_FAIL`**
- run_count=1 / retry=0 / POST=5（P1 analyze×2 + track×2 + P2 analyze×1）+ health GET×2
- 结果目录：`results/paper_demo/v1d3a_dyn_c_fixed_frame_replay_20260724/`
- 输入：E2K 已批准帧 170/249（sha256 与 manifest 预检一致后才 POST）

## Phase 1 — 模型守规（PASS）

无时序证据时两帧均未猜 dynamic（prompt v2 规则遵从）：

| 帧 | risk_type | conf | action |
| --- | --- | --- | --- |
| 170 | static | 0.8 | alert |
| 249 | static | 0.7 | slow_down |

意义：模型在无证据时不过度声称 dynamic——与 D2B 的"不虚报 functional"一致，边界纪律成立。

## Phase 2 — 失败根因：GDINO 目标选择错误（非 VLM 语义失败）

失败链（全程如实记录）：

1. GDINO ground `"white humanoid robot"` → box `[333,108,414,239]`（**画面上半部 = UR10e 臂/容器区域**；G1 实际在底部 v≈380–460），score 0.99——**ground 到了错误的机器人**；
2. SAM2 跟踪该静止目标：帧 249 box 完全不变（mask_area 10654→10556），session 连续性 OK；
3. 运动学补全 speed=0 px/s → `validate_temporal_evidence` 按设计拒绝（`rejection_reason=speed_below_threshold`，门槛 10 px/s）；
4. VLM 收到 invalid evidence → 正确输出 static@0.7，未虚报 dynamic。

**正面发现**：证据链端到端 fail-closed 行为正确——错误的感知目标未能污染语义判断，这正是五阶段设计要验证的失效安全性。

**真正的缺口**：GDINO 的开放词汇 grounding 在本场景无法把 "humanoid robot" 与机械臂区分开（目标选择层失败）。0.85 门槛、prompt、证据校验器均无需也不得调整。

## 附带观察

- 远端响应回报 `prompt_version=five_stage_safety_v1`（legacy 服务端本地版本回显），本地发送的 prompt v2 sha256 已入档；gateway parse OK。
- 感知服务懒加载确认：首个 track 请求触发 GDINO+SAM2 加载（首请求 7.9 s，次请求 43 ms）。

## Next gate（不重跑本轮）

`GROUNDING_TARGET_SELECTION_EVAL`：离线设计 grounding 目标选择改进评估——候选方向：(a) 更判别性的 text prompt（含空间/外形描述），(b) GT bbox 种子 track-init 的**诊断性**对照组（明确标注 target selection 来自 GT、运动测量仍来自 SAM2，不计入端到端声称），(c) 四象限探针集（v1e04）作为 grounding 评估的标注真值。执行前需用户批准 POST 预算。

## 边界重申

- body-pose 真值未用作运动证据（evidence_source 全程 `sam2_track`）；
- shadow-only，无控制作用；0.85 与证据门槛未动；
- Dyn-C E2K 样本的数据集资格不受本评估影响。
