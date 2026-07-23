# V1-E2G Dyn-C Replacement Motion Preflight (2026-07-23)

- status: `motion_preflight_fail`
- gate decision: `STOP_NO_FORMAL_CAPTURE`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2g_dyn_c_motion_preflight_20260723`

## Build/Run Contract
- build: 1/1, copy-only, no retry
- image tag: `gmdisturb:e01-dyn-c-motion-preflight-m1e2g-20260723`
- run: 1/1, no retry, seed=44, scenario=`mirrored_outer_lateral_patrol`, `--freeze-ur10e`, max_steps=260

## Preflight Checks
- HEAD=`da24a10`, origin一致, worktree clean
- E2F1 tests/config: pass
- import preflight:
  - host python: fail (`ModuleNotFoundError: gymnasium`) 
  - container (`/isaac-sim/python.sh`): pass

## Runtime Outcome
- process exit: `0`
- no runtime traceback/KeyError/Xid/residual found
- no model POST evidence (`POST`/`/analyze`/`/ground`/`enable_vlm`/`enable_perception`: all zero)

## Telemetry Gate Summary
- `exit0`: pass
- `UR10 action/joint delta/hash`: **fail** (`hold_hash`稳定，但 `joint_delta_max_abs=0.278264`，不满足 near-zero)
- `G1 commanded vs actual root/link displacement`: pass
  - commanded XY=(1.1164, -0.2928)m
  - actual XY=(1.059859, -0.287552)m
  - direction dot=1.2674 (>0)
- `projected>=40px`: **fail**（字段未导出）
- `ROI>=1.2%`: **fail**（字段未导出）
- `no fall`: pass (`phase3.csv.g1_fell=False`)
- `frame sync`: pass（runtime frame/body pose/scene PNG 对齐）

## Command vs Actual (Required STOP)
- command: 固定 seed44/scenario/camera/`--freeze-ur10e` 的 mirrored patrol 预期可复现
- actual: G1 方向一致，但 UR10 冻结偏差超阈，且缺少 projected/ROI/fall telemetry 字段，门禁不满足
- action: STOP，禁止 formal capture

## Artifacts
- telemetry csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2g_dyn_c_motion_preflight_20260723/safety_logs/phase3_runtime_telemetry.csv` (rows=264, sha256=`2e7a8572c93013baa84efc58223918b41e7a39fe6347b188e25b7b07dba91f58`)
- steps csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2g_dyn_c_motion_preflight_20260723/safety_logs/phase3_steps.csv` (rows=6)
- body poses: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2g_dyn_c_motion_preflight_20260723/meta/body_poses.jsonl` (rows=4)
- events csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2g_dyn_c_motion_preflight_20260723/safety_logs/phase3_events.csv` (rows=0)
- diagnostic frames saved: `4`
