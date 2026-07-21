# B2 / B4-Dynamic 最终多 seed 验证 — P0-10（2026-07-21）

## 结论

**三 seed（42/43/44）在 P0-10 最终候选镜像上全部通过；raw redeploy 已与 canonical 一致（8/8/8/8/8）。**

- 冻结镜像：`gmdisturb:b4-p010-20260721`
- image ID：`sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- built_at：`2026-07-21T03:33:44Z`
- P0-10：canonical redeploy = lifecycle `RETREATING→IDLE`；已有 `redeploy_step` 的 attempt 不再写事件
- machine summary：`results/paper_demo/b2_b4_final_summary_p010.json`
- 批次根目录：`results/paper_demo/b2_b4_p010_20260721/`

## 镜像角色

| 前缀 | image ID | 角色 |
|---|---|---|
| **defe…** | `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68` | **最终候选（本文件）** |
| d6cb… | `sha256:d6cb7cc0…` | 历史：functional PASS；raw redeploy 15≠8 |
| f126… | `sha256:f1267b1c…` | 历史 control-isolation FAIL |
| 20da… | `sha256:20da7e8d…` | 8-part 开发 PASS |

## 配对

| seed | pair | mismatch | active | shadow | would | leakage |
|---:|---|---:|---|---|---:|---|
| 42 | PASS | 0 | 1/1 | 1/1 | 1 | 0/0/0/0 |
| 43 | PASS | 0 | 1/1 | 1/1 | 1 | 0/0/0/0 |
| 44 | PASS | 0 | 1/1 | 1/1 | 1 | 0/0/0/0 |

## B2 8-part

| seed | verdict | parts | trig/app/ret/redeploy | recovered | unpaired | lat | margin | STOP/SLOW/replan | collisions | knock/G1 |
|---:|---|---|---|---:|---:|---:|---:|---|---:|---|
| 42 | PASS | 8/8 | 8/8/8/8 | 8 | 0 | 0 | 0.0727 | 7/64/8 | 112 | 0/False |
| 43 | PASS | 8/8 | 8/8/8/8 | 8 | 0 | 0 | 0.0728 | 7/64/8 | 101 | 0/False |
| 44 | PASS | 8/8 | 8/8/8/8 | 8 | 0 | 0 | 0.0727 | 7/64/8 | 20 | 0/False |

### 碰撞分布（勿只报均值）

- seed42/43/44 collision_count = 112 / 101 / 20

## 门禁

- `all_pairs_pass`: `True`
- `all_8part_pass`: `True`
- `canonical_redeploy_all`: `True`
- `freeze_ready`: `True`

旧 d6cb… 汇总仍保留于 `docs/cross-project/b2-b4-final-validation-2026-07-20.md`（标注 raw redeploy duplicated）。
B0/B1 回归已完成：见 `docs/cross-project/b0-b1-final-regression-p010-2026-07-21.md`；B0/B1/B2/B4 统一冻结于 `defe95e…`。
