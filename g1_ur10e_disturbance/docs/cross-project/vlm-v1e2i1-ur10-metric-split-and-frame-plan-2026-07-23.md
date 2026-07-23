# V1-E2I.1 UR10 Metric Split And Next Frame Plan (Offline)

- mode: `offline_only` (no Docker / no Isaac / no network run)
- based on: existing `V1-E2I` telemetry + mirrored trajectory evidence only
- policy: keep historical FAIL evidence immutable; only add retrospective interpretation

## 1) UR10 Freeze Metric Split (Implemented)

- runtime telemetry now splits UR10 freeze metrics into:
  - `ur10_arm_joint_delta_norm`
  - `ur10_arm_joint_delta_max_abs`
  - `ur10_gripper_joint_delta`
  - `ur10_arm_joint_delta_max_abs_settled`
  - `ur10_gripper_joint_delta_settled`
  - `ur10_gripper_selected_state`
- legacy aggregate fields are retained without semantic change:
  - `ur10_joint_delta_norm`
  - `ur10_joint_delta_max_abs`
  - `ur10_joint_delta_max_abs_settled`
- legacy semantics are explicitly labeled via:
  - `ur10_joint_delta_semantics=legacy_aggregate_arm6_plus_gripper1`

## 2) E2I Retrospective Attribution (No Rewrite)

- observed legacy aggregate settled delta: `0.314159`
- attribution: `finger_joint` converged from init `0.0` to `GRIPPER_OPEN=0.314159`
- UR10 EE settled displacement: `3.129243850708008e-07 m` (near numerical noise)
- retrospective interpretation:
  - arm freeze is **qualified** under arm-only + EE displacement criteria
  - this does **not** change historical E2I verdict record
  - visual-margin gate remains FAIL (`max projected displacement=36.888px < 40px`)

## 3) Analyzer/Preflight Decision Policy (Updated)

- arm freeze decision must use only:
  - `ur10_arm_joint_delta_max_abs_settled_max <= 1e-6`
  - `ur10_ee_displacement_settled_max_m <= 1e-6`
- gripper is report-only:
  - `selected open/close`
  - `settled delta`
  - never counted as arm motion by itself

## 4) Next Single Precheck Collection Plan (Do Not Run)

- unchanged:
  - camera pose
  - mirrored trajectory / command profile
  - speed profile
  - thresholds (including `>=40px` gate)
- current frame timing evidence:
  - existing frames: `149,150,219,220`
  - peak projected displacement occurs at interval `150->219` (`36.888px`)
  - immediate next interval `219->220` drops to `0.4358px` (post-peak)
- phase-based rationale:
  - `149/150` are in `settle_heading_mirror`
  - `219/220` are in `lateral_negative_sweep_mirror`
  - `phase3_steps` trend indicates lateral motion continues after `220` toward `250`
- proposed next precheck frames:
  - `149,150,239,250`
  - goal: delay postrun tail frames deeper into `lateral_negative_sweep_mirror` to increase parallax
- preregistered gate (unchanged):
  - projected centroid displacement `>=40px`
  - at least `2` frame-pairs must satisfy the gate

## 5) Scope Guardrail

- if a next-precheck frame override is introduced, it must be scenario-scoped to `mirrored_outer_lateral_patrol` preflight only
- default behavior for all other scenarios must remain unchanged
