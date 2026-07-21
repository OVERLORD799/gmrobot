## B2 1-part pilot evidence (seed42) — 2026-07-20

**一句话论文表述：** “TTC-triggered pre-collision intervention before the geometric hard-stop boundary.”

本节证据来自 **B2 active 1-part seed42** 的单次 pilot（不是最终统计结果）。

### Run metadata
- image ID: `sha256:73692cad07a36e51d08cf9ea6488d33afd30a4bf6a9784caaff07f35d7198605`
- run ID: `dynamic_lateral_sweep_proxy_1part_s42_091746`
- 结果目录: `g1_ur10e_disturbance/results/paper_demo/dynamic_lateral_sweep_proxy_1part_s42_091746/`
- seed: `42`
- trajectory_id: `37b55da03802e6c35f92c453c5059daba5ae6f400981b67491d0612bcae80d89`
- active event chain: `trigger → applied → retreat` with `event_id=1`

### 原始 CSV 文件相对路径
- `g1_ur10e_disturbance/results/paper_demo/dynamic_lateral_sweep_proxy_1part_s42_091746/dynamic_lateral_sweep_proxy_1part_s42_091746.csv`

### TTC-triggered intervention timeline (关键步)
1. **step 201: safe start**
   - gate decision: `ALLOW`
   - surface velocity: `0` (first transient-free step)
   - `dist_min_for_gating` (实测): `0.3416` (> hard-stop 0.25)

2. **step 202: TTC STOP pre-collision trigger / applied**
   - gate decision: `STOP`
   - trigger rule: `ttc`
   - `dist_min_for_gating`: `0.3227` vs hard-stop: `0.25`  （仍在几何 hard-stop 外）
   - `ttc`: `0.3506`
   - `approach_rate`: `0.9202`
   - 事件链对应 `event_id=1`

3. **step 203: retreat**
   - retreat event: `event_id=1`

4. **step 566: terminal success**
   - `1/1 task complete` （B2 active 通过）

### 归因 / 碰撞 / G1 / 恢复门禁结果
- 归因（from `batch_summary.json` / episode metrics）:
  - `attributed_STOP=1`, `attributed_REPLAN=1`
  - `d_stop_caused=1`, `d_replan_caused=1`
  - `d_slow_caused=0`
  - `held_critical_replan_count=0`
- 碰撞与最小距离：
  - `collision_count=10`
  - `min_surface_distance_m=0.38688554286956783`
- G1 状态门禁：
  - `g1_fell=false`
- 恢复门禁（与 attempts.csv / events.csv 配对）：
  - `retreat_attempt_count=1`, `recovered_attempt_count=1`
  - `recovery_pairing_ok=true`
  - `events_csv_valid=true`, `max_trigger_apply_latency=0`

### 关键解释（为什么这是主动预测干预）
本次 gate 虽然是 **TTC STOP**，但触发距离仍满足 `dist_min_for_gating=0.3227 > hard_stop=0.25`，因此 intervention 发生在进入几何 hard-stop 之前，属于 **主动预测干预**，而非进入 hard-stop 后的被动制停。

不得写成：“SLOW/warn-stage replan。”  
本次 gate 是 TTC STOP，但触发距离仍在几何 hard-stop 外，因此属于主动预测干预。  
同时注明：这是 **seed42、1-part pilot**，不是最终统计结果。

---

## Addendum — pairing + 8-part (same calendar day)

### Active/shadow pairing image（历史配对 — 控制隔离失败）
- image ID: `sha256:f1267b1c39f8944b9885e2dab788642f9ce5817c2ab9e7e8d5ea6012edfe246f`
- tag: `gmdisturb:b2-20260720`（配对重建）
- active 1-part + shadow mini seed42：**trajectory/counter pairing PASS, control-isolation FAIL due to shadow clock leakage**
  - 同 `trajectory_id=37b55da03802e6c35f92c453c5059daba5ae6f400981b67491d0612bcae80d89`
  - commanded trajectory 前缀一致；shadow actual STOP/SLOW/replan 归因计数为 0，无 applied/retreat 事件
  - **失败证据（保留，不得删除）**：shadow 仍用 evaluated gate 冻结 policy clock  
    （例：`sim_step=2058` 时 `policy_steps≈253`、长时间 `gate=STOP`、终局 `0/1`）
  - 因此 **不能** 作为论文 “无干预对照” 基线

### 8-part recovery fix + re-gate（开发阶段功能证据）
首次 8-part（配对镜像）任务 8/8 但 `scenario_pass=False`：attempts 1–7 仅有 retreat、缺 redeploy（`RETREATING→IDLE` 边沿漏记）。

修复：`protocol_vhand.dynamic_sweep_redeploy_edge` + `run_phase3` 在 lifecycle 离开 RETREATING 时补记 redeploy。

- **8-part 重跑镜像** ID: `sha256:20da7e8d0a450902dadfd3de061751116f060b617c626edb539d131bb87960a0`
  - `built_at=2026-07-20T10:33:26Z`（仅含 redeploy 记账修复；轨迹/阈值未改）
- run: `results/paper_demo/b2_8part_redeploy_20260720/dynamic_lateral_sweep_proxy_8part_s42_103417/`
- **B2 8-part seed42：scenario PASS**（开发阶段功能链证据；**不是**最终统一镜像统计）
  - 8/8 task complete；`pre_hard_stop_replan_count=8`；`held_critical_replan_count=0`
  - `recovery_pairing_ok=true`；`recovered_attempt_count=8`；`progress_after_retreat=true`
  - `g1_fell=false`；`d_knock_off=0`；`proxy_physical_contact_count=0`
  - events: trigger/applied/retreat 各 8；`subprocess_validated=true`

### 当前准确里程碑（纠正）
- B2 1-part：PASS
- B2 8-part seed42：PASS（开发功能证据）
- B4 trajectory/would-trigger 记录：PASS
- B4 无控制副作用基线：FAIL（shadow clock leakage）→ 待 isolation 修复后重验
- 最终论文统计：尚未冻结

---

## Addendum — B4 control-isolation fix（2026-07-20）

根因：`should_advance` 直接使用 evaluated gate；shadow 虽未改 action，但冻结了 policy clock。

修复：`resolve_effective_gate_name` / `policy_clock_should_advance` —— shadow 下 effective≡ALLOW；新增泄漏计数并纳入 B4 verdict。

### Isolation 重验镜像
- tag: `gmdisturb:b4-iso-20260720`
- image ID: `sha256:d6cb7cc09d66a19012c6e934b67f015121e4b0cc395e03602b1c9e01e4b5adbf`
- `built_at=2026-07-20T11:13:38Z`

### 同镜像配对重跑（seed42）
| 角色 | 结果目录 | 判定 |
|---|---|---|
| active 1-part | `results/paper_demo/b4_iso_active_20260720/dynamic_lateral_sweep_proxy_1part_s42_111423/` | scenario PASS，1/1 |
| shadow mini | `results/paper_demo/b4_iso_shadow_20260720/dynamic_lateral_sweep_proxy_shadow_mini_s42_111746/` | scenario PASS，**1/1** |

Shadow isolation 门禁（本跑）：
- `shadow_clock_blocked_steps=0`
- `shadow_action_modified_steps=0`
- `shadow_replan_applied_count=0`
- `shadow_retreat_count=0`
- `d_stop/d_slow/d_replan=0`
- `shadow_replan_would_count=1`（TTC would-trigger）
- `shadow_nonallow_evaluated_steps=99`（evaluated STOP/SLOW 仍完整记账）
- trajectory 前缀 mismatches=0；同 `trajectory_id`

**B4 无控制副作用基线：PASS（seed42，本镜像）。**  
暂不自动重跑最终 8-part / seeds 43/44。

