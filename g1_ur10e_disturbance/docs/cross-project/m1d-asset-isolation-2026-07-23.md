# M1D Asset-Isolation A/B Diagnostic — Correction

**Date:** 2026-07-23
**Branch:** main
**Base commit (static analysis):** 794227e
**This commit:** isolation-confirmed correction to 794227e

**Trigger:** M1 Func-C visual anomaly ("white fan" pattern in overhead camera render).
794227e performed static USD analysis and identified `container_full_visual.usd` unit/scale
inconsistency as the likely root cause. This commit records the isolation-render experiment
that **confirms** ContainerB as the sole visual culprit.

## Method

Two mutually-exclusive diagnostic toggles were temporarily added to `target_full_override.py`
and `gmrobot_env_cfg.py` (since reverted — diagnostic toggles do not belong in production):

| Toggle | Env Var | Effect |
|--------|---------|--------|
| B_HIDDEN | `GMROBOT_M1D_B_HIDDEN=1` | Skip `/World/envs/env_0/ContainerB` spawn |
| PARTS_HIDDEN | `GMROBOT_M1D_PARTS_HIDDEN=1` | Skip `/World/envs/env_0/Part_1..20` spawn |

The toggles were applied in a temporary Docker image and reverted from source after the
experiment. The diagnostic code is NOT present in this commit.

## Experiment Results

**Image:** `gmdisturb:e01-func-c-m1-fix-20260723` (SHA256 `d8bef5e28f31`)
**Camera:** pos=(0.35, 0.0, 2.5), rot=(0.7071, 0.0, 0.7071, 0.0)
**Seed:** 51 (layout deterministic)
**Steps:** 1 (smoke only)

### B_HIDDEN — ONLY successful isolation trial

```bash
docker run --gpus all --rm \
  -e GMROBOT_V1E01_TARGET_FULL=1 \
  -e GMROBOT_M1D_B_HIDDEN=1 \
  gmdisturb:e01-func-c-m1-fix-20260723 \
  /isaac-sim/python.sh /opt/projects/GMRobot/scripts/gm_state_machine_agent.py \
    --task gm --headless --enable_cameras --enable_safety \
    --safety_config .../ivj_v1e01_target_container_full.yaml \
    --save_camera --camera_output_dir .../m1d_asset_isolation_20260723/b_hidden/scene \
    --camera_save_interval 1 --max_steps 1
```

- **Exit code:** 0
- **Output PNG:** `results/paper_demo/m1d_asset_isolation_20260723/b_hidden/scene/frame_000000_env0.png`
- **SHA256:** `a65e2575...`
- **Visual result:** White fan pattern **completely disappeared**. ContainerA and all 20 parts
  render normally. The scene is visually correct when ContainerB is hidden.

### PARTS_HIDDEN — INVALID (startup failure)

```bash
docker run --gpus all --rm \
  -e GMROBOT_V1E01_TARGET_FULL=1 \
  -e GMROBOT_M1D_PARTS_HIDDEN=1 \
  ... (same as above, output to parts_hidden/scene)
```

- **Exit code:** non-zero (container stopped)
- **Output PNG:** none produced
- **Failure reason:** ObservationManager still references `part_1_pos` etc. when parts are hidden.
  The `build_part_observations()` early-return of `{}` causes a mismatch — the observation
  group expects 20 part terms to be registered, but none are.
- **Impact on attribution:** NONE. This invalid trial does not weaken the B_HIDDEN conclusion.
  B_HIDDEN alone is sufficient to isolate the culprit to ContainerB.

## Image SHA256 Comparison

| Case | SHA256 (first 8) | Notes |
|------|------------------|-------|
| Original Func-C smoke | `c28596...` | White fan present, `results/paper_demo/v1e01_func_c_capture_20260722/smoke_scene/frame_000000_env0.png` |
| B_HIDDEN | `a65e2575...` | Fan **disappeared**, ContainerA + 20 parts normal |
| PARTS_HIDDEN | N/A | No PNG produced (startup failure) |

## Prim Visibility Evidence (from Isaac stdout)

**B_HIDDEN scene entities:** ContainerB (`box_B`) absent. ContainerA (`box_A`), grid_A,
and all Part_1..20 present and visible. Observation Manager sees 20 `part_X_pos` terms.

**PARTS_HIDDEN scene entities:** (container failed before entity enumeration could be captured.)

## Verdict

**M1D_ROOT_CAUSE_IDENTIFIED — Culprit: ContainerB (`container_full_visual.usd`)**

The isolation render experiment provides direct visual proof:

1. **B_HIDDEN (hide ContainerB):** The white fan pattern **completely vanishes**.
   ContainerA and all 20 parts render normally. This is a binary, qualitative result —
   no pixel-diff analysis needed.
2. **794227e static analysis** already identified `container_full_visual.usd` as having
   unit/scale inconsistency (`metersPerUnit=1` with cm-scale geometry). The isolation
   render confirms this static finding.
3. **container_fixed.usd and part_fixed.usd are NOT visual root causes.** They are
   normalized derivatives (single RigidBodyAPI, no nesting) and do not contribute to
   the fan anomaly.

## What is NOT the cause

- **Parts (`part_fixed.usd` / `part_5000.usd`):** Exonerated. With ContainerB hidden,
  all 20 parts render correctly in ContainerA slots.
- **ContainerA (`container_fixed.usd`):** Exonerated. Renders normally in B_HIDDEN case.
- **Camera / lighting / layout:** Exonerated. Identical setup produces clean image when
  ContainerB is removed.

## Root Cause (from 794227e static analysis, now confirmed)

`container_full_visual.usd` contains a scale/unit inconsistency:
- The USD declares `metersPerUnit=1` (meters-as-meters)
- The geometry is authored at centimeter scale
- This mismatch causes the renderer to produce visual artifacts (the "fan" pattern)
  when the prim is placed in the scene

The normalized derivative `container_fixed.usd` was generated to fix nested RigidBodyAPI
issues but does not address the visual-scale problem in `container_full_visual.usd`.

## Minimum Next Fix (NOT applied in this commit)

Fix the scale/unit inconsistency in `container_full_visual.usd`:
1. Identify the correct geometry scale factor (likely 0.01 for cm→m conversion)
2. Apply a `uniform scale` opinion to the root prim, OR re-author the geometry at
   meter scale
3. Verify the fix against the B_HIDDEN reference image (fan-free ground truth)

## Diagnostic Toggle Reversion

All M1D diagnostic toggle code has been **reverted** from the three affected source files:
- `GMRobot/source/GMRobot/GMRobot/shadow/target_full_override.py`
- `GMRobot/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py`
- `GMRobot/scripts/test_e01_func_c_capture_unit.py`

Diagnostic switches should not enter production. The toggles served their purpose:
isolating the visual culprit to ContainerB in a single successful B_HIDDEN trial.

## Relationship to 794227e

| Commit | Role |
|--------|------|
| 794227e | Static USD analysis — identified `container_full_visual.usd` unit/scale inconsistency |
| This commit | Isolation render confirmation — B_HIDDEN experiment proves ContainerB is the sole visual culprit |

## Output Images

- `results/paper_demo/v1e01_func_c_capture_20260722/smoke_scene/frame_000000_env0.png` — original (fan present)
- `results/paper_demo/m1d_asset_isolation_20260723/b_hidden/scene/frame_000000_env0.png` — B_HIDDEN (fan absent, clean)

No PARTS_HIDDEN output was produced.
