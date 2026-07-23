# V1-M1F12 Func-C Dual-reference visual smoke（2026-07-23）

- image/tag: `gmdisturb:e01-func-c-dual-reference-m1f12-20260723`
- frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f12_20260723/scene/frame_000000_env0.png`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f12_20260723`
- visual_verdict: `REVIEW_REQUIRED`
- overall_status: `STOP_NO_RETRY`

## 预算与约束
- build: `1/1`；smoke: `1/1`；retry: `0`
- 仅使用 `GMDISTURB_V1E01_FUNC_C_VISUAL=1`（seed=51）
- DualEnvCfg 启动，要求 `task_execution=false`（本次因相机启用参数错误提前失败）
- 相机目标锁定：`pos=[0.45,0,2.7]` `rot=[0.7071,0,0.7071,0]`

## 失败原因（无重试）
- `A camera was spawned without the --enable_cameras flag`
- 未生成 `frame_000000_env0.png`
- 未生成 `runtime_scene_assertions.json`

## 自动门禁
- gates: `{'exit0': True, 'png': False, 'double_green_box_roi': False, 'grid': False, 'content': False, 'assertions': False, 'POST0': True, 'noTraceback': False, 'device': True, 'xid': True, 'residual': True}`

## 人工复核（必须）
- 结论固定：`REVIEW_REQUIRED`（禁止自动视觉 PASS）
- 本次因帧缺失，无法进行场景布局与双绿壳/白格对照

## 审计元数据
- HEAD: `d2b5d09f500a5bf3d7e029133bf7dc9a4432a883`
- image_id: `sha256:6fbba6b81106f5193d4ae03f446deafeae17e7bb324c33d1401d96baa250711e`
- reference(frame330) sha256: `6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- GPU: `Thu Jul 23 18:39:13 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.159.03             Driver Version: 580.159.03     CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
`
- Xid new: `False`
