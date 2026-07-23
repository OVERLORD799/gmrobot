# V1-E2H Dyn-C Final Motion Preflight (2026-07-23)

- status: `motion_preflight_fail`
- gate decision: `STOP_NO_FORMAL_CAPTURE`
- next: `STOP` (not `ONE_FORMAL_CAPTURE_ALLOWED`)
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2h_dyn_c_motion_preflight_20260723`

## Build/Run Contract
- build: 1/1, copy-only, no retry
- image tag: `gmdisturb:e01-dyn-c-motion-preflight-m1e2h-20260723`
- run: 1/1, no retry, seed=44, scenario=`mirrored_outer_lateral_patrol`, `--freeze-ur10e`, capture steps=`149,150,219,220`, max_steps=260

## Preflight Checks
- HEAD=`7a63f41`, origin一致, worktree clean
- E2G1 tests/import/config: pass

## Runtime Outcome
- process exit: `0`
- runtime traceback/KeyError/Xid/residual: none
- POST/model endpoint evidence: none (`POST`/`/analyze`/`/ground`/`enable_vlm`/`enable_perception` all zero)

## Telemetry Gate Summary
- `UR10 settled joint delta near-zero`: **FAIL**
  - threshold: `ur10_joint_delta_max_abs_settled <= 1e-6`
  - observed: `max=3.231203`
- `UR10 hold provenance is actual articulation`: pass（`ur10_hold_provenance_json`含 `joint_name/joint_id/value`，来自 articulation 实测关节）
- `G1 actual displacement direction consistent`: pass
  - commanded XY displacement (integrated): `(1.116400, -0.292800)m`
  - actual XY displacement: `(1.059805, -0.287814)m`
  - direction dot: `1.2674382412` (>0)
- `projected actual displacement >= 40px`: **FAIL** (`max=36.8884876532px`)
- `ROI area >= 1.2%`: pass (`max=1.9499221084%`)
- `visible links >= 4`: pass (`min=8`)
- `clipping <= 0.5`: pass (`max=0.0`)
- `no fall`: pass (`phase3.csv.g1_fell=False`)
- `frame sync`: pass（capture frame=4, scene PNG=4, body pose rows=4）
- `POST0/no errors`: pass

## Command vs Actual (Required STOP)
- command: 固定 seed/scenario/camera/freeze/preflight steps，验证隔离条件后再决定是否允许正式采集
- actual: UR10 settled joint delta 严重超阈，且 projected displacement 未达 40px；关键门禁未同时满足
- action: `STOP`，formal capture 不允许

## Artifacts
- telemetry csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2h_dyn_c_motion_preflight_20260723/safety_logs/phase3_runtime_telemetry.csv` (rows=264, sha256=`72dad7cbea9b0485b95b7f75cfd9d2236af76e15bbc7a601cbf66d8a674eb83f`)
- steps csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2h_dyn_c_motion_preflight_20260723/safety_logs/phase3_steps.csv` (rows=6)
- body poses: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2h_dyn_c_motion_preflight_20260723/meta/body_poses.jsonl` (rows=4)
- frame inventory: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2h_dyn_c_motion_preflight_20260723/meta/frame_inventory.json`
- postrun analyzer: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2h_dyn_c_motion_preflight_20260723/meta/v1e2g1_postrun_analyzer.json`
