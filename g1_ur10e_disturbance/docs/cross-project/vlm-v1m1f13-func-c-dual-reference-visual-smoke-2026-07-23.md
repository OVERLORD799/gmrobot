# V1-M1F13.1 Func-C reference-bin 并排人工视觉验收（2026-07-23）

- review_mode: `manual_side_by_side_visual_only`
- execution_policy: `NO_CODE_NO_SIM_NO_NETWORK`
- preflight: `HEAD=e1f091d66c86ab25910dcdacd8ea6cecea9863e3` 且 `worktree_clean=true`
- reference_locked_frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png`
- reference_locked_frame_sha256: `6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- m1f13_frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f13_20260723/scene/frame_000000_env0.png`
- m1f13_frame_sha256: `f8046771b1f23f892ae4c46a9b7fc1a102310283f7bebfc80859342a022a9ae6`

## 主agent人工并排视觉结论
- 左箱为绿色箱体外壳，顶部白色 `5x4` 栅格，尺度与朝向和 reference 一致。
- 左箱区域未见白托架/白阶梯/扇形异常，也无关键遮挡。
- 右箱与 reference 同源绿色壳体，20 个内容件均位于格内。
- 机器人姿态与地面构图差异来自 `step0` 对比 `step330` 的时序差异，不作为箱体合同失败。

## 状态写回（仅文档与manifest）
- `artifact_removal_technical_pass=true`
- `reference_bin_visual_contract_pass=true`
- `technical_review_status=reference_visual_pass_pending_user_confirmation`
- `reviewer_approved=false`（保持）
- `formal_recapture_allowed=false`（保持，直到用户确认）

## 约束声明
- 禁止修改源码/图像/历史 verdict。
- 本步骤仅记录主agent人工验收与状态更新。
