# V0-B2B track-step 单请求续跑（2026-07-21）

## 最终分类：**LEGACY_GATEWAY_FEASIBLE_COMPOSITE**

含义（必须同时成立）：

- VLM / ground / track init 证据来自 `v0b2b_legacy_probe_20260721`
- track step 证据来自本续跑目录
- **同一**远端 session（报告仅写 `session_match=true`，不回显 UUID）
- 原 probe 的 `TRACK_INIT_FAIL` **保留**为历史本地审计 bug（`bool(track_id=0)`）
- **不是**五阶段论文验证完成
- 仅证明 **legacy gateway 技术可行**
- 输入为**无人体风险负样本** scene RGB

---

## 本轮操作

| 项 | 值 |
|---|---|
| 新增 POST | **1**（`/track` action=step） |
| HTTP | 200 |
| 耗时 | **0.213 s** |
| 重试 | 0 |
| 重跑 VLM/ground/init | **否** |
| 新建 session | **否** |
| 凭据 / tunnel / 远端修改 | **否** |

---

## 门禁结果

| 检查 | 结果 |
|---|---|
| `session_match` | **true** |
| `track_id=0` 关联 | **true** |
| `frame_index` | 10 |
| `box_xyxy` | `[217, 74, 423, 364]` |
| `mask_area` | 56243 (>0) |
| `sam2_score` | ≈0.919（有限） |
| `velocity_xy_px_s` | `[0, 0]` |
| `speed_px_s` | 0.0 |
| `direction_deg` | 0.0 |
| `re_detected` | false |
| `track_state_native` | **false**（未伪造 lost/reacquired） |

---

## 证据路径

| 角色 | 路径 |
|---|---|
| 原始 probe（未覆盖） | `results/paper_demo/v0b2b_legacy_probe_20260721/` |
| 原始文档（未覆盖） | `docs/cross-project/vlm-v0b2b-legacy-capability-probe-2026-07-21.md` |
| 续跑结果 | `results/paper_demo/v0b2b_track_step_continuation_20260721/` |
| 续跑文档 | 本文件 |

脚本 / 测试：

- `GMRobot/scripts/probe_v0b2b_track_step_continuation.py`
- `GMRobot/scripts/test_v0b2b_track_step_continuation_unit.py`（10 passed）

---

## 说明

stdout 仅输出 `continuation_verdict=… session_match=…`，不含 session UUID。  
ledger / summary 不含 `session_id` 与 `image_b64`。

**已停止。**
