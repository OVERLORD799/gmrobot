# V1-E2F Dyn-C Motion Preflight (2026-07-23)

- status: `motion_preflight_fail`
- gate decision: `STOP_NO_FORMAL_CAPTURE`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2f_dyn_c_motion_preflight_20260723`

## Build/Run Contract
- build: 1/1, copy-only, no retry
- image tag: `gmdisturb:e01-dyn-c-motion-preflight-m1e2f-20260723`
- run: 1/1, no retry, seed=44, scenario=`mirrored_outer_lateral_patrol`, `--freeze-ur10e`, max_steps=260

## Runtime Outcome
- process exit: `0`
- runtime error: `KeyError: 'joint_pos'` in `run_phase3.py` freeze path
- traceback appears in stdout, therefore `POST0/no errors` gate fails

## Gate Summary
- `exit0`: pass
- `UR10 effective action/joint delta/hash stable`: **not evaluable** (no telemetry data rows)
- `G1 actual root/link displacement direction consistent`: **not evaluable** (run aborted before step data)
- `projection>=40px` / `ROI>=1.2%` / `no fall`: **not evaluable**
- `telemetry <-> frame/step sync`: fail (no step/frame rows and no diagnostic frames)

## Command vs Actual (Required STOP)
- command: scripted mirrored G1 patrol should cross at least two waypoint segments
- actual: no measurable motion evidence generated in this run (steps/body/events empty; scene PNG count=0)
- action: STOP and do not proceed to formal capture

## Artifacts
- telemetry csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2f_dyn_c_motion_preflight_20260723/safety_logs/phase3_runtime_telemetry.csv` (rows=0)
- steps csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2f_dyn_c_motion_preflight_20260723/safety_logs/phase3_steps.csv`
- body poses: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2f_dyn_c_motion_preflight_20260723/meta/body_poses.jsonl`
- events csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2f_dyn_c_motion_preflight_20260723/safety_logs/phase3_events.csv`
- diagnostic frames saved: `0`
