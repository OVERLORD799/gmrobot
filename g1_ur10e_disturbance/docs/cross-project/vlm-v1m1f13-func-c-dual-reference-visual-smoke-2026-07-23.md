# V1-M1F13 Func-C Dual-reference visual smoke（2026-07-23）

- image/tag: `gmdisturb:e01-func-c-dual-reference-m1f13-20260723`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f13_20260723`
- frame: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_dual_reference_smoke_m1f13_20260723/scene/frame_000000_env0.png`
- overall_status: `PASS`
- next_gate: `NONE`

## 预算与约束
- build: `1/1`；smoke: `1/1`；retry: `0`
- copy-only: `true`；dependency change: `false`
- env: `GMDISTURB_V1E01_FUNC_C_VISUAL=1`；seed label=`51`；`task_execution=false`
- canonical command `--enable_cameras` count: `1`（必须恰好 1）

## Kit runtime assertions（必须项）
- Dual identity: `True`
- A/B + GridA/B: `True`
- 20 parts = B slots: `True`
- Aempty: `True`

## 自动门禁
- exit=True, png=True, assertions=True, double boxes=True, grid=True, content=True, POST0=True, no errors=True, xid=True, residual=True

## 人工复核
- verdict: `REVIEW_REQUIRED`
- checks: `REVIEW_REQUIRED` for scene identity / 双绿箱+白网格 / A空箱 / B箱20件

## 结论
- 本次执行策略：`build1/smoke1/no-retry`
- 若判定为新的基础接线缺陷，强制 `next_gate=AUTOMATION_LOOP_STOP_MANUAL_AUDIT`
