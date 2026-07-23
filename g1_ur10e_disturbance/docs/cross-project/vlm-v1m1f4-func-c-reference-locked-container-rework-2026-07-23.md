# V1-M1F4 Func-C 左侧箱体参考锁定返工（2026-07-23）

结论：`Func-C source container visual identity` 已收敛到 Dyn-B `frame_000330_env0` 左侧绿色空箱同一 canonical 资产身份；未引入近似重建、白色托架、隐藏/裁剪/贴图假象。

## 参考锁定
- 参考图：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png`
- 参考 SHA256：`6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- 不合格图：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_visual_smoke_m1f3r_20260723/scene/frame_000000_env0.png`
- 不合格 SHA256：`a5155db466dcca5c9cff64a1828843b325ba1b89766c5f2f36450bd716fcb5c5`

## Dyn-B 左箱资产身份合同（唯一标准）
- USD 资产：`/home/czz/GMrobot/GMRobot/source/GMRobot/GMRobot/assets/container.usd`
- SHA256：`ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9`
- defaultPrim：`/Root`
- prim contract：`{ENV_REGEX_NS}/ContainerA`
- material path：`/Root/Container/Ref/Looks/DefaultMaterial`
- scale：`(0.01, 0.01, 0.01)`
- orientation（spawn quat wxyz）：`(0.5, 0.5, 0.5, 0.5)`
- spawn config 来源：`g1_ur10e_disturbance/dual_env_cfg.py` 与 `GMRobot/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py`

## 最小修复
- `GMRobot/source/GMRobot/GMRobot/shadow/target_full_override.py`
  - Func-C 开启时 `box_A` 从 `container_fixed.usd` 改为 `container.usd`。
  - 新增 `source_visual_contract()`，固化 source visual 的 `asset path/SHA/material/defaultPrim/prim/scale/orientation`。
- `GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py`
  - 新增断言：Func-C 模式下 `box_A` 必须解析到 `container.usd`。
  - 输出 `source_container_visual_contract` 到 manifest；若哈希不匹配，直接 `REFERENCE_IDENTITY_BLOCKED`。
- `GMRobot/scripts/test_e01_func_c_capture_unit.py`
  - 更新 Func-C 期望：`box_A=container.usd`。
  - 新增 reference-locked 单测，禁止回退到 `container_fixed` 或 `container_full_visual` 作为 source container。
- `g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py`
  - 新增状态 `visual_rework_in_progress_reference_locked` 静态校验。
  - 要求 `reviewer_approved=false`、`formal_recapture_allowed=false`、并必须记录 `reference_frame_sha256/rejected_frame_sha256`。

## 文档与清单同步
- `M1F3.1` 增补 `user_rejected=true`（不覆盖历史结论）：
  - `g1_ur10e_disturbance/docs/cross-project/vlm-v1m1f31-func-c-human-visual-review-2026-07-23.json`
  - `g1_ur10e_disturbance/docs/cross-project/vlm-v1m1f31-func-c-human-visual-review-2026-07-23.md`
- candidate manifest 中 Func-C 更新为：
  - `technical_review_status=visual_rework_in_progress_reference_locked`
  - `reviewer_approved=false`
  - `formal_recapture_allowed=false`
  - 写入 reference/rejected frame SHA
  - 文件：`g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json`

## 离线门禁与下一步
- 离线门禁覆盖：`source_visual_asset_path/SHA/material/scale/orientation/prim contract` 与 Dyn-B 参考一致。
- 禁止 fallback 到旧 source 形态（`container_fixed`/白色 holder）。
- 下一步仅允许：**source-only build + 一次 visual smoke**。
