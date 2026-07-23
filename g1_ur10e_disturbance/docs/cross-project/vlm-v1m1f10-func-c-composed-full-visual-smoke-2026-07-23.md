# V1-M1F10 Func-C composed-full visual smoke（2026-07-23）

- image/tag: `gmdisturb:e01-func-c-composed-full-m1f10-20260723`
- frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_composed_full_smoke_m1f10_20260723/scene/frame_000000_env0.png`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_composed_full_smoke_m1f10_20260723`
- visual_verdict: `REVIEW_REQUIRED`
- overall_status: `STOP_NO_RETRY`

## 执行约束与预算
- build: `1/1`（无重试）
- smoke: `1/1`（无重试）
- env: `TARGET_FULL=1` + `VISUAL_ONLY=1`，并设置 `GMROBOT_RUNTIME_SCENE_ASSERTIONS_PATH=.../meta/runtime_scene_assertions.json`
- Dockerfile: `GMRobot/docker/Dockerfile.e01-func-c-composed-full-m1f10`（COPY-only，无 pip 依赖改动）

## 自动门禁
- gates: `{"exit0": true, "PNG": true, "doubleROI": true, "content": true, "assertions": false, "POST0": false, "no_errors": false, "residual": true, "no_traceback": true, "no_device_lost": true, "no_new_xid": true}`
- runtime assertions present/passed: `False` / `False`
- runtime required checks: `{'Part_count0': False, 'ContainerA_B+GridA_B': False, 'boxA_B_container.usd': False, 'FilledContent_stage_count20': False, 'content_asset_identity': False}`
- smoke exit: `0`

## 人工视觉对比（reference frame_000330）
- reference frame330: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png`
- reference sha256: `6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- current frame sha256: `a04ffc7709c2b35c573986a07b440f6f7aecb89e549a398d480d7d9bafef53a5`
- 结论：`REVIEW_REQUIRED`（继续保持人工并排检查，不自动判视觉 PASS）
- 要求校核项：两侧绿色边框+白格、左侧B允许格内20件、禁止白托架/阶梯/扇形

## 资产/相机/GPU/Xid审计
- container.usd sha256: `ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9`
- container_full_content_visual.usd sha256: `5ca656f996c783c0ab9717cae265c8461054d98bd487b08d9b5770f3bb36f935`
- camera: `pos=(0.35,0.0,2.5)` `rot=(0.7071,0.0,0.7071,0.0)`
- GPU: `| 0   | NVIDIA GeForce RTX 5090 Laptop.. | Yes: 0 |     | 24463   MB | 10de      | 0          |`
- Xid new: `False`

## STOP_NO_RETRY
- `runtime_scene_assertions.json` 未生成且 stderr 存在 `[Error]`，按规则失败即停、无重试。

## M1F10 人工结论（后置）
- decision: `rejected_manual`
- status: `ABANDONED_WASTEFUL_LOOP`
- reason: `frame场景结构缺失/仅1绿框+5散件，非reference；stderr存在nested RigidBody/CCD errors。`
- route: `停止旧路线（container_full/content overlay），转向DualEnvCfg同源reference scene重构（M1F11）。`
