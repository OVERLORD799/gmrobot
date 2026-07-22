# V1-B Deterministic Semantic Safety Supervisor（离线实现，2026-07-21）

## 结论

| 项 | 值 |
|---|---|
| semantic_supervisor_implemented | **true** |
| enforcement_mode | **shadow**（默认 enabled=false） |
| offline_tested | **true**（29/29 unit scripts） |
| negative_replay_pass | **true**（V0-C3 accepted=0） |
| synthetic_positive_pass | **true**（dynamic 两连 → accepted） |
| monotonic_fusion_pass | **true** |
| live_control_connected | **false** |
| real_post_count | **0** |
| isaac_run | **false** |
| docker_build | **false** |
| human_tool_ppe_validated | **false** |
| paper_five_stage_complete | **false** |

本轮只实现建议与确定性裁决；**不**写入 action/gate/clock/replan。

---

## 模块

- `GMRobot/source/GMRobot/GMRobot/safety/semantic_supervisor.py`
- `GMRobot/source/GMRobot/GMRobot/safety/semantic_supervisor_logger.py`
- `GMRobot/configs/semantic_safety_supervisor.yaml`
- `GMRobot/scripts/replay_semantic_supervisor_v1b.py`

### 规则顺序（拒绝必有稳定 reason）

enabled → mode → schema → error → stale → age → ids → duplicate → action → risk_type → confidence → horizon → consequence → entities → consistency → cooldown → monotonic fusion

### 单调融合

`ALLOW < SLOW_DOWN < STOP`；未知 gate 失败；VLM 不可放宽几何结果。  
`effective_gate_shadow` 仅日志，V1-B 不应用。

### 一致性

`semantic_key = risk_type|action|entities|consequence_class|spatial_hint`  
同 key 累加；换 key / 超 window 重置；同 request_id 不重复计数；cooldown 内不重复发 accepted advisory。

### V1-B 硬约束

- 仅 `slow_down` → `requested_gate=SLOW_DOWN`
- `would_stop=false` / `would_replan=false` / `intentional_control_effect=false`
- static 默认拒绝（`risk_type_not_allowed`）

---

## V0-C3 负样本回放

源（只读）：`results/paper_demo/v0c3_isaac_shadow_20260721/five_stage_shadow_requests.jsonl`

| 帧 | VLM | 拒绝原因 |
|---|---|---|
| 0 | static / slow_down / conf=0.3 | `risk_type_not_allowed` |
| 1 | dynamic / slow_down / conf=0.7 | `low_confidence` |

输出：`results/paper_demo/v1b_semantic_supervisor_replay_20260721/`  
`accepted_count=0`，`intentional_control_effect=0`。

---

## 合成正例

两次 `dynamic@0.92` 同 key → 第 1 次 `consistency_pending`，第 2 次 `accepted`；`synthetic=true`，不进论文结果。

---

## 旧 live replan

`vlm_stage5_replan` 仍存在于 `gm_state_machine_agent.py`，**本轮未删除**。  
新 supervisor **不调用**它；默认 `allow_replan=false`；后续 active 阶段必须与旧 live replan **互斥**。  
旧路径 **不属于** 论文 V1 控制方案。

---

## 冻结边界

未修改/重跑：B0–B4、`gmdisturb:b4-p010-20260721`、V0-C1/C2 FAIL、V0-C3 PASS 原始结果。  
无 POST / endpoint / Isaac / Docker / 凭据读取。
