# V1-M1Z6 Dyn-B M1Z5 root-cause audit and recapture plan (2026-07-23)

- verdict: **BLOCKED**
- root_cause_confidence: `low_to_medium` (0.45)
- fixed_result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z5_20260723`
- expected image: `gmdisturb:e01-dyn-b-clean-m1z4-20260723` / `sha256:962de1e3f5e9c761d5106c660af7e7dfdbc79319194839a284a06e64dfb45e83`

## 212 / 228 审计结论
- step `212`: gate `SLOW_DOWN/SLOW_DOWN`, trigger `ttc`, dist_min `1.118868` m, margin `1.018868` m, phase `lateral_positive_sweep`, source `scripted_g1_outer_lateral_patrol`, slow/stop/replan `1/0/0`
- step `212` TTC/velocity: unavailable (`phase3_events.csv is empty; per-step audit retains trigger_rule only`; `velocity fields are not persisted in phase3_dyn_b_per_step_audit.csv`)
- step `228`: gate `SLOW_DOWN/SLOW_DOWN`, trigger `ttc`, dist_min `1.083372` m, margin `0.983372` m, phase `lateral_positive_sweep`, source `scripted_g1_outer_lateral_patrol`, slow/stop/replan `1/0/0`
- step `228` TTC/velocity: unavailable (`phase3_events.csv is empty; per-step audit retains trigger_rule only`; `velocity fields are not persisted in phase3_dyn_b_per_step_audit.csv`)

## 0..340 非 ALLOW 区间
- ranges: [75,75] len=1, [98,98] len=1, [103,103] len=1, [167,167] len=1, [212,212] len=1, [228,228] len=1

## 新固定窗口与关键帧
- review window: `159..338` (连续固定，覆盖正/负横移)
- keyframe group A: `[219, 220, 221]`
- keyframe group B: `[329, 330, 331]`
- centroid displacement px(220->330): `24.297366596071075` (gate >=20)

## 执行约束与一次性预算
- build/run budget: `{'build_runs_allowed': 0, 'capture_runs_allowed': 1}`
- forbidden items: no Docker/Isaac/build/network execution in this milestone; no POST, VLM, GDINO, SAM2; no credentials read; no change to B0-B4 frozen configs/results; no safety threshold or gate/replan/control semantic changes; no deletion or rewrite of M1Z5 FAIL evidence
- stop conditions: HEAD mismatch or dirty worktree at execution time; result directory already exists; events telemetry still missing exact TTC/velocity for non-ALLOW steps; any non-ALLOW appears inside declared review window 159..338; centroid displacement < 20px or any keyframe ROI/link/clipping gate fails; missing per-step evidence for declared keyframes or window
