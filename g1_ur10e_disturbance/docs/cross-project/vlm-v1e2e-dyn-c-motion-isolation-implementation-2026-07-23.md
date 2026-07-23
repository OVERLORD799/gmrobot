# V1-E2E Dyn-C Motion Isolation Implementation

- status: `IMPLEMENTATION_READY`
- verdict policy: offline implementation only, no Isaac displacement claim
- freeze switch: `--freeze-ur10e` wired (default off)
- mirrored locomotion wiring: `True`

## Root-Cause Audit
- task_execution=false vs UR10 freeze: `task_execution=false disables task reward/completion contract but does not freeze UR10 policy stepping`
- UR10 freeze path: effective action overridden to hold action before env write
- UR10 telemetry: initial_joint_pose + hold_hash + per-step action_norm/joint_delta

## Motion Preflight Contract
- seed/camera fixed: `44` / `{'pos': [0.45, 0.0, 2.7], 'rot': [0.7071, 0.0, 0.7071, 0.0]}`
- gate: projected displacement >= `40.0` px
- gate: ROI area >= `1.20%`
- gate: UR10 action_norm <= `1e-06`
- gate: UR10 joint_delta_max_abs <= `1e-06`
- gate: no fall + command/actual direction consistent

## Next Step Budget
- only 1 source-only build + 1 short motion preflight (not formal capture)
