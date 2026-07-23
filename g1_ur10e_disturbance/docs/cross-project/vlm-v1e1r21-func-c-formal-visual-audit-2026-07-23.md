# V1-E1R2.1 Func-C 正式视觉审计与冻结（离线）

- 日期：`2026-07-23`
- preflight：`HEAD=f035cfa`（完整 `f035cfa346bc1a7a2a86345e92e9380c8c04aec1`）、`worktree clean=true`
- 约束：不运行 Docker / Isaac / network / model（纯离线证据更正）

## 固定事实
- `frame_000100_env0.png` 存在，SHA256=`97c1998fa08e6ead3ade1ed7bd49d3fe4640f724bb5f557ca7e7a808b3e8b934`
- `frame_000200_env0.png` 存在，SHA256=`626e8c6be85324b64b7756cda58d52d5933df2c6b6d682fa14a7da7a4e480417`
- `raw_exit_code=0`
- `elapsed_seconds=46`
- 人工视觉复核（主 agent）：双绿箱/白格、A 空、B 20 格内、无白托架阶梯扇形，均 PASS

## Composite Assertion Evidence（非本 run 原生）
- E1R2 本目录 `runtime_scene_assertions.json` 缺失，不能伪称本 run runtime assertion。
- 引用 M1F13 `runtime_scene_assertions.json`（`ok=true`，20 B slots / A empty）。
- 组合前提：同 image SHA 系列、同 `GMDISTURB_V1E01_FUNC_C_VISUAL=1`、同 camera pose、同 scene 初始化路径。
- E1R2 stdout 含 `part_1..part_20` 与 `slot_A/slot_B` 观测项，作为观测结构一致性证据。

## 物理/控制限制（保留原错误）
- 保留 E1R2 stderr 中 RigidBody 层级错误与 CCD 错误。
- `geometry_evidence=false`
- `control_evidence=false`
- `physics_clean=false`
- 结论：视觉 artifact 有效，不等价于几何/控制/物理 clean 证据。

## 双结论并存（不得覆盖 raw）
- `raw_automation_verdict=FAIL_FINAL`（保留）
- `audited_visual_dataset_verdict=FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE`（新增）

## 冻结与后续门禁
- Func-C 候选状态更新：`func_c_formal_visual_capture_pass`
- `reviewer_approved=true`
- `formal_recapture_allowed=false`
- `consumed=true`
- `group_count=1`，frames 不可拆组
- 全局约束：`human_hand/glove/PPE/VLM_output=false`
- dataset sufficiency：至少 functional 正式视觉组 1、dynamic 技术候选组 1；整体仍 `DATASET_INSUFFICIENT`，不可进入 live/active。
