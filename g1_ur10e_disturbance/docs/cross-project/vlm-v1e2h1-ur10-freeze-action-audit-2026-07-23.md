# VLM V1E2H1 UR10 Freeze Action Audit (2026-07-23)

## Context
- This corrective change is appended after commit `89b3376` without rewriting history.
- `89b3376` correctly audited `ur10e_ee` term contract but did not fix the core freeze-action bug.

## Review Incomplete Findings in 89b3376
- Freeze hold action was still built from articulation joint angles (joint baseline leaked into action payload).
- `ur10e_ee` tracking in runtime loop and body-pose logging was switched from FK `body_link_pos_w + cfg.safety.ee_track.offset` to action-term world pose, exceeding scope and risking safety-geometry regressions.
- Term resolution and audits were executed unconditionally at startup, even when `--freeze-ur10e` was disabled.

## Corrective Implementation
- Freeze-only action path now reads pose from audited `ur10e_ee` term `_compute_frame_pose()` and root transform, then composes raw `pose7=[pos3,quat_wxyz4]` with finite/shape/quaternion-norm fail-closed checks.
- Joint baseline remains independent and is used only for `compute_ur10_freeze_metrics`; it is never used to build the action payload.
- Gripper raw action is derived from articulation `finger_joint` proximity to `GRIPPER_OPEN` / `GRIPPER_CLOSED`, mapped to BinaryJointPositionAction sign (`open=+1.0`, `close=-1.0`) with `ur10e_gripper.action_dim==1` validation.
- Runtime `ur10e_ee` tracking behavior is restored to FK path (`body_link_pos_w + cfg.safety.ee_track.offset`) in loop and camera/body-pose logging.
- Term resolution and freeze hold-action construction now occur only under `--freeze-ur10e`.
- Runtime telemetry provenance fields are split into:
  - `ur10_joint_baseline_provenance_json`
  - `ur10_hold_action_provenance_json`

## Test Coverage Added/Updated
- `joint baseline != hold action`: joint inputs set to obvious `99` still do not affect hold action pose.
- Gripper open/close mapping and invalid `ur10e_gripper.action_dim`.
- Fail-closed coverage for NaN pose and bad quaternion norm.
- Existing fail-closed checks retained for bad IK action dim, bad scale, and relative mode.

## Execution Scope
- No Docker / Isaac simulation run in this corrective pass.
