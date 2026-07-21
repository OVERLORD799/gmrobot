# B0/B1 最终回归 — P0-10（2026-07-21）

## 结论

**六组（B0/B1 × seed 42/43/44）在 `defe95e…` 最终候选镜像上全部通过门禁；可与 B2/B4-Dynamic 统一冻结。无需再跑物理基准。**

- 冻结镜像：`gmdisturb:b4-p010-20260721`
- image ID：`sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- 结果根目录：`results/paper_demo/b0_b1_final_p010_20260721/`
- machine summary：`results/paper_demo/b0_b1_final_summary_p010.json`

### 冻结 YAML（未修改）

- `baseline_safe.yaml` sha256=`ca0f641bcca6c0130dd0081f0744a033147652b73ad1bb096aa598d07bab88df`
- `static_occupancy_proxy.yaml` sha256=`f11c1aeec65e61152bac302e7562dfd5ce2137feb3b8054034f96685c1bc63ff`

### B1 机制标注（勿与 B2 混写）

总表标签：

> **B1 static occupancy → replan recovery**  
> (held-critical dominant; seed44 mixed held-critical/static)

准确表述：

> B1 static-occupancy recovery benchmark，主要通过 held-critical STOP 触发恢复；seed44 另出现 3 次 static-triggered replan。

逐 seed `trigger_rules`：

| seed | trigger_rules |
|---:|---|
| 42 | `held_critical ×4` |
| 43 | `held_critical ×4` |
| 44 | `held_critical ×4 + static ×3` |

- seed44 的 `static` **不是** B2 式 proactive TTC。
- B2 仍单独表述为：*TTC-triggered pre-collision intervention before the geometric hard-stop boundary.*

## 六组结果

| 场景 | seed | run_id | parts | attr STOP/SLOW/replan | held_crit | trigger_rules | trig/app/ret/redeploy/rec | unpaired | progress | collide | knock/G1 | subprocess/scenario | vs 0320 | gate |
|---|---:|---|---|---|---:|---|---|---|---|---:|---|---|---|---|
| baseline_safe | 42 | `baseline_safe_s42_s42_052251` | 20/20 | 0/0/0 | 0 | — | 0/0/0/0/0 | 0 | False | 1 | 0/False | True/True | 回归一致 | PASS |
| static_occupancy_proxy | 42 | `static_occupancy_proxy_s42_s42_055446` | 20/20 | 4/4/4 | 4 | held_critical×4 | 4/4/4/4/4 | 0 | True | 204 | 0/False | True/True | 回归一致 | PASS |
| baseline_safe | 43 | `baseline_safe_s43_s43_061517` | 20/20 | 0/0/0 | 0 | — | 0/0/0/0/0 | 0 | False | 3 | 0/False | True/True | 回归一致 | PASS |
| static_occupancy_proxy | 43 | `static_occupancy_proxy_s43_s43_064650` | 20/20 | 4/3/4 | 4 | held_critical×4 | 4/4/4/4/4 | 0 | True | 192 | 0/False | True/True | 回归一致 | PASS |
| baseline_safe | 44 | `baseline_safe_s44_s44_063107` | 20/20 | 0/0/0 | 0 | — | 0/0/0/0/0 | 0 | False | 0 | 0/False | True/True | 回归一致 | PASS |
| static_occupancy_proxy | 44 | `static_occupancy_proxy_s44_s44_070557` | 20/20 | 5/12/7 | 4 | held_critical×4 + static×3 | 7/7/7/7/7 | 0 | True | 0 | 0/False | True/True | 回归一致 | PASS |

## 与历史 0320 对比

- 历史根目录：`results_paper_final_0320/final_six_ordered/`（**不覆盖**）
- 历史镜像：`sha256:0320fd6e9d7c061c48fdb51bf44a738bbee5e6bd469f8e5f2e52c05963ae0ca6`

### baseline_safe seed42

- 标注：**回归一致**
- hist run：`baseline_safe_s42_051225`
- new run：`baseline_safe_s42_s42_052251`
- 关键可比指标与 0320 完全一致（回归一致）。

### static_occupancy_proxy seed42

- 标注：**回归一致**
- hist run：`static_occupancy_proxy_s42_012630`
- new run：`static_occupancy_proxy_s42_s42_055446`
- 关键可比指标与 0320 完全一致（回归一致）。
- trigger_rules：`held_critical=4`

### baseline_safe seed43

- 标注：**回归一致**
- hist run：`baseline_safe_r1_s43_054917`
- new run：`baseline_safe_s43_s43_061517`
- 关键可比指标与 0320 完全一致（回归一致）。

### static_occupancy_proxy seed43

- 标注：**回归一致**
- hist run：`static_occupancy_proxy_r1_s43_034046`
- new run：`static_occupancy_proxy_s43_s43_064650`
- 关键可比指标与 0320 完全一致（回归一致）。
- trigger_rules：`held_critical=4`

### baseline_safe seed44

- 标注：**回归一致**
- hist run：`baseline_safe_r2_s44_062605`
- new run：`baseline_safe_s44_s44_063107`
- 关键可比指标与 0320 完全一致（回归一致）。

### static_occupancy_proxy seed44

- 标注：**回归一致**
- hist run：`static_occupancy_proxy_r2_s44_042409`
- new run：`static_occupancy_proxy_s44_s44_070557`
- 关键可比指标与 0320 完全一致（回归一致）。
- trigger_rules：`held_critical=4, static=3`（static ≠ B2 TTC）

## 门禁

- `all_six_pass`: `True`
- `freeze_b0_b1_b2_b4_on_defe95e`: `True`

历史 0320 证据保留于 `results_paper_final_0320/final_six_ordered/`。

## 备注

- B0 seed42 在分阶段门禁中完成 episode；主机侧 batch wrapper 提前停止，无 `batch_summary.json`；subprocess/scenario 由完整产物离线推断（与 0320 关键指标一致）。
- `b0_s42/` 下早期 `repeat:3` 产生的 `r1_s43`（完整）/`r2_s44`（中断）目录保留为非官方产物，**不覆盖、不作为正式证据**；正式 seed43/44 使用单次 seed override 目录。
- B1 事件类型为 `trigger`（非 B2 的 `proactive_trigger`）；配对按 `trigger/applied/retreat/redeploy` + `attempts.recovered` 审计。
- 本文件仅为机制标签的元数据修正：不改代码、镜像、YAML 或结果文件。
