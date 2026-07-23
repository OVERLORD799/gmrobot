# V1-M1F8 Func-C empty-source visual smoke（2026-07-23）

- image/tag: `gmdisturb:e01-func-c-empty-source-m1f8-20260723`
- frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f8_20260723/scene/frame_000000_env0.png`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f8_20260723`
- visual_verdict: `VISUAL_REVIEW_REQUIRED`
- overall_status: `STOP_NO_RETRY`

## Preflight
- HEAD required/actual: `655ee79` / `655ee79`（full=`655ee79d04240dc7cd44daacad429ffcb8111ccd`）
- origin/main match: `true`
- worktree clean preflight: `true`
- M1F7.1 offline tests: `PASS`（按前置输入）

## 单次预算执行
- build(1/1): `exit=0`，Dockerfile=`GMRobot/docker/Dockerfile.e01-func-c-empty-source-m1f7`（COPY-only）
- smoke(1/1): `exit=0`，未重试
- env: `TARGET_FULL=1` + `VISUAL_ONLY=1`（同时设置 `GMROBOT_V1E01_TARGET_FULL=1` / `GMROBOT_V1E01_VISUAL_ONLY=1`）

## 产物与门禁
- frame PNG: `present`，sha256=`3696dd2f4d494973ec10b040c3f81f8000c02c227161d18bf87485f7bf1555c7`
- runtime_scene_assertions.json: `missing`（必须 `passed=true`）
- 自动门禁：`{"exit0": true, "png_non_black": true, "doubleROI": true, "rightcontent": true, "assertions": false, "POST0": false, "no_errors": false, "no_residual": true, "no_traceback": true, "no_device_lost": true, "no_new_xid": true}`

## 运行时断言要求（AppLauncher后）
- 必须产出 `runtime_scene_assertions.json` 并 `passed=true`
- 必须满足：`Part_count0`、`ContainerA/GridA/ContainerB` 存在、标志正确、box assets 正确
- 本次结果：`不满足`

## 参考对比（人工）
- 本次 frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f8_20260723/scene/frame_000000_env0.png`
- reference frame330: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png`
- reference sha256: `6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- 结论策略：先标记 `VISUAL_REVIEW_REQUIRED`，主agent人工比对。

## GPU / Xid / 其他审计
- GPU: `GPU 0: NVIDIA GeForce RTX 5090 Laptop GPU (UUID: GPU-6b6f962a-ac86-00b4-e732-e8caafeca73d)`
- dmesg xid lines pre/post: `1` / `1`
- new xid: `false`
- container.usd sha256: `ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9`

## STOP 说明
- 规则为 `失败STOP_NO_RETRY`，本次 `STOP_NO_RETRY`，未执行任何重跑。
