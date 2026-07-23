# V1-M1F13.1 Func-C Reference Visual Review（2026-07-23）

结论：**REFERENCE_VISUAL_PASS_PENDING_USER_CONFIRMATION**

## 固定比对帧
- reference（Dyn-B / frame330）：
  `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png`
- reference SHA256：
  `6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- M1F13（Func-C / frame0）：
  `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f13_20260723/scene/frame_000000_env0.png`
- M1F13 SHA256：
  `f8046771b1f23f892ae4c46a9b7fc1a102310283f7bebfc80859342a022a9ae6`

## 主agent人工并排视觉验收
- 左箱：绿色壳体 + 白色 `5x4` 栅格，尺度/朝向与 reference 一致。
- 左箱：无白托架/白阶梯/扇形异常/关键遮挡。
- 右箱：同源绿色壳体，`20` 个内容件全部在格内。
- 机器人姿态/地面构图差异来自 `step0` vs `step330`，不作为箱体合同失败。

## 状态更新
- `artifact_removal_technical_pass=true`
- `reference_bin_visual_contract_pass=true`
- `technical_review_status=reference_visual_pass_pending_user_confirmation`
- `reviewer_approved=false`（保持）
- `formal_recapture_allowed=false`（保持，直到用户确认）

## 执行约束
- 仅文档与 candidate manifest 更新。
- 不运行代码/仿真/网络。
- 不修改源码/图像/历史 verdict。
