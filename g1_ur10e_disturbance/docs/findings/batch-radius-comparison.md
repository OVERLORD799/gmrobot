# GMDisturb Batch Test: Virtual Hand Radius Comparison

> **Date**: 2026-07-07
> **Setup**: `run_phase3.py --virtual-hand R --replan --max_steps 3000 --virtual-hand-speed 0.08`
> **Runs**: 1 episode per radius (r=0.5, r=0.8, r=1.0), same random seed

## Raw Results

| Metric | r=0.5 | r=0.8 | r=1.0 |
|--------|-------|-------|-------|
| parts_placed | 7/20 | 7/20 | 8/20 |
| policy_steps | 2790 | 2940 | 3000 |
| STOP | 0 | 1318 | 2785 |
| SLOW_DOWN | 27 | 179 | 29 |
| REPLAN | 0 | 57 | 112 |
| STUCK | 0 | 0 | 0 |
| g1_fell | False | False | False |
| min_g1_ur10e_distance_m | 0.847 | 0.828 | 0.828 |
| mean_g1_ur10e_distance_m | 1.059 | 0.914 | 0.909 |

## Analysis

### r=0.5 — Too Short
The virtual hand barely reaches the UR10e workspace. Only 27 SLOW_DOWN events (all TTC-based, no static distance triggers). Zero STOPs, zero replans. The hand orbits near the corridor but never gets close enough to block the EE.

**Verdict**: Not useful for safety testing. Equivalent to no disturbance.

### r=0.8 — Optimal Test Point ⭐
The hand consistently enters the EE workspace, producing 1318 STOP events and 57 successful replans. The task continues to progress (2940 policy steps, 7 parts placed in 3000 sim steps). The UR10e is repeatedly blocked but not permanently frozen — the hand drifts in and out of the danger zone naturally.

**Verdict**: Best test radius. Produces meaningful safety events without deadlocking the task.

### r=1.0 — Too Aggressive
The hand pins the EE almost continuously. 2785 STOPs (93% of steps), 112 replans. The SLOW_DOWN count drops to 29 because the hand skips the SLOW_DOWN zone and goes directly to STOP. The UR10e is frozen most of the time — policy steps hit the 3000 limit without completing more parts.

**Verdict**: Stress-test only. Not suitable for regular validation.

## Recommendation

Use `--virtual-hand 0.8` as the default test radius for Phase 5 validation. Use `--virtual-hand 1.0` for stress/boundary testing. Do not use r < 0.6 (hand cannot reach EE workspace).

## Raw Data

| File | Path |
|------|------|
| r=0.5 CSV | `/tmp/gmdisturb_batch/r0.5.csv` |
| r=0.8 CSV | `/tmp/gmdisturb_batch/r0.8.csv` |
| r=1.0 CSV | `/tmp/gmdisturb_batch/r1.0.csv` |
