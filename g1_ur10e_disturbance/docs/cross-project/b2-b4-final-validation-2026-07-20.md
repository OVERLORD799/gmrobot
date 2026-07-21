# B2 / B4-Dynamic 最终多 seed 验证（2026-07-20）

## 结论（历史状态 — 已被 P0-10 降级）

本文件保留 d6cb… 批次的完整统计，**不得删除或覆盖**。

**状态标注：** `functional/statistical PASS; raw redeploy logging duplicated (15 raw, 8 canonical)`

- 镜像：`gmdisturb:b4-iso-20260720`
- image ID：`sha256:d6cb7cc09d66a19012c6e934b67f015121e4b0cc395e03602b1c9e01e4b5adbf`
- 功能门禁（8/8、pre-hard-stop replan、recovery metrics 去重后 8）通过
- **原始 events CSV 不宜冻结为论文证据**：每 attempt 1–7 有 2 条 redeploy（RETREATING→IDLE + PLACE→RESET latch 重断言），合计 15 条 raw / 8 canonical
- machine summary：`results/paper_demo/b2_b4_final_summary.json`
- 批次根目录：`results/paper_demo/b2_b4_final_20260720/`
- P0-10 修复后的最终候选见后续新镜像汇总（本文件角色降为历史候选）

## 镜像角色区分（保留历史，不覆盖）

| 镜像前缀 | image ID | 角色 |
|---|---|---|
| d6cb… | `sha256:d6cb7cc09d66a19012c6e934b67f015121e4b0cc395e03602b1c9e01e4b5adbf` | **历史候选**：functional PASS；raw redeploy 15≠8 canonical |
| f126… | `sha256:f1267b1c39f8944b9885e2dab788642f9ce5817c2ab9e7e8d5ea6012edfe246f` | 历史 control-isolation FAIL（shadow clock leakage） |
| 20da… | `sha256:20da7e8d0a450902dadfd3de061751116f060b617c626edb539d131bb87960a0` | 8-part 开发 PASS（非最终统一统计） |

## 碰撞分布备注（不阻塞安全门禁）

三 seed 真实碰撞计数差异大（112 / 101 / 20）。论文统计应报告分布，不应只报均值。

## Active / Shadow 配对（seeds 42–44）

| seed | pair | traj match | prefix mismatch | active 1/1 | shadow 1/1 | would-trigger | leakage clock/action/replan/retreat |
|---:|---|---|---:|---|---|---:|---|
| 42 | PASS | yes | 0 | 1/1 / B2=PASS | 1/1 / B4=PASS | 1 | 0/0/0/0 |
| 43 | PASS | yes | 0 | 1/1 / B2=PASS | 1/1 / B4=PASS | 1 | 0/0/0/0 |
| 44 | PASS | yes | 0 | 1/1 / B2=PASS | 1/1 / B4=PASS | 1 | 0/0/0/0 |

### 配对明细

#### seed 42
- note: isolation_revalidation_not_rerun_in_multiseed_batch
- active: `results/paper_demo/b4_iso_active_20260720/dynamic_lateral_sweep_proxy_1part_s42_111423`
- shadow: `results/paper_demo/b4_iso_shadow_20260720/dynamic_lateral_sweep_proxy_shadow_mini_s42_111746`
- trajectory_id: `37b55da03802e6c35f92c453c5059daba5ae6f400981b67491d0612bcae80d89`
- active intervention: pre_hard_stop_replan=1, d_stop/slow/replan=1/0/1
- shadow would-trigger=1; nonallow_evaluated_steps=99

#### seed 43
- active: `results/paper_demo/b2_b4_final_20260720/pair_s43/active/dynamic_lateral_sweep_proxy_1part_s43_s43_112546`
- shadow: `results/paper_demo/b2_b4_final_20260720/pair_s43/shadow/dynamic_lateral_sweep_proxy_shadow_mini_s43_s43_112736`
- trajectory_id: `4fa45001a9d44f1ca225fa991db771384e4b4927d11d75a4a7e8fe3d1d0b562f`
- active intervention: pre_hard_stop_replan=1, d_stop/slow/replan=1/0/1
- shadow would-trigger=1; nonallow_evaluated_steps=99

#### seed 44
- active: `results/paper_demo/b2_b4_final_20260720/pair_s44/active/dynamic_lateral_sweep_proxy_1part_s44_s44_112915`
- shadow: `results/paper_demo/b2_b4_final_20260720/pair_s44/shadow/dynamic_lateral_sweep_proxy_shadow_mini_s44_s44_113111`
- trajectory_id: `ea29dc0b4a315d1a546d968e15e3b62c8e280d86a7c0583fda90a4985d4adcec`
- active intervention: pre_hard_stop_replan=1, d_stop/slow/replan=1/0/1
- shadow would-trigger=1; nonallow_evaluated_steps=99

## B2 8-part（最终候选镜像）

| seed | verdict | parts | pre-HS replan | held_critical | trig/app/ret/redeploy | recovered | unpaired | max lat | min margin | progress | STOP/SLOW/replan | knock/G1 | steps(pol) | elapsed_s |
|---:|---|---|---:|---:|---|---:|---|---:|---:|---|---|---|---|---:|
| 42 | PASS | 8/8 | 8 | 0 | 8/8/8/15 | 8 | 0 | 0 | 0.0727 | True | 7/64/8 | 0/False | 5259(4948) | 670.9 |
| 43 | PASS | 8/8 | 8 | 0 | 8/8/8/15 | 8 | 0 | 0 | 0.0728 | True | 7/64/8 | 0/False | 5259(4948) | 1035.8 |
| 44 | PASS | 8/8 | 8 | 0 | 8/8/8/15 | 8 | 0 | 0 | 0.0727 | True | 7/64/8 | 0/False | 5259(4948) | 637.7 |

### 8-part seed 42
- run: `results/paper_demo/b2_b4_final_20260720/b2_8part_s42/dynamic_lateral_sweep_proxy_8part_s42_s42_113245`
- trajectory_id: `37b55da03802e6c35f92c453c5059daba5ae6f400981b67491d0612bcae80d89`
- collisions: count=112, episodes=112, raw_frames=4379, robot_object=73, proxy_contact=0
- attributed STOP/SLOW/replan: 7/1/8
- hard_stop_at_trigger=0.25; trigger dist_min_for_gating=[0.3227, 0.3481, 0.3779, 0.4116, 0.4262, 0.449, 0.476, 0.5066]
- unpaired event_ids: ∅

### 8-part seed 43
- run: `results/paper_demo/b2_b4_final_20260720/b2_8part_s43/dynamic_lateral_sweep_proxy_8part_s43_s43_114415`
- trajectory_id: `4fa45001a9d44f1ca225fa991db771384e4b4927d11d75a4a7e8fe3d1d0b562f`
- collisions: count=101, episodes=101, raw_frames=3507, robot_object=66, proxy_contact=0
- attributed STOP/SLOW/replan: 7/1/8
- hard_stop_at_trigger=0.25; trigger dist_min_for_gating=[0.3228, 0.348, 0.3778, 0.4112, 0.4263, 0.449, 0.4761, 0.5066]
- unpaired event_ids: ∅

### 8-part seed 44
- run: `results/paper_demo/b2_b4_final_20260720/b2_8part_s44/dynamic_lateral_sweep_proxy_8part_s44_s44_120201`
- trajectory_id: `ea29dc0b4a315d1a546d968e15e3b62c8e280d86a7c0583fda90a4985d4adcec`
- collisions: count=20, episodes=20, raw_frames=820, robot_object=12, proxy_contact=0
- attributed STOP/SLOW/replan: 7/1/8
- hard_stop_at_trigger=0.25; trigger dist_min_for_gating=[0.3227, 0.3482, 0.3774, 0.4117, 0.4263, 0.449, 0.4756, 0.5068]
- unpaired event_ids: ∅

## 门禁总表

- all_pairs_pass: `True`
- all_8part_pass: `True`
- **freeze_ready: `True`**

## 下一步建议

- ~~冻结 d6cb… 为论文证据~~ → **否**：raw redeploy 重复（P0-10）。
- 在 P0-10 新最终候选镜像上重验配对 + 8-part 三 seed，再考虑 B0/B1 回归。
- 碰撞计数请按 seed 报告分布（112/101/20），勿只报均值。
