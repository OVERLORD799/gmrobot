# V1-M1X Dyn-B telemetry + ROI audit (2026-07-23)

- mode: **offline-only audit + implementation**
- base commit: `8d88cd5`
- docker/isaac/network/VLM/perception/SAM2/POST/image-rebuild: **not executed**

## Why the 341-step run only had 3 rows in window 190..340

- `phase3.csv` is an **episode summary** file and writes exactly one final row.
- `phase3_steps.csv` is **progress-interval sampling**, not full per-step logging.
- In `M1W1`, `progress_interval=50`, and step rows are written only under `step % progress_interval == 0`.
- Therefore in window `190..340`, only steps `200/250/300` appear (3 rows), while simulation still ran `341` steps.
- `policy_steps=335` is UR10e policy clock advancement under gate logic; it is not equal to simulation loop length.

## What was implemented (default-off, explicit path only)

- Added `--dyn-b-per-step-audit-csv` to `run_phase3.py` (default empty/off).
- When explicitly set, writes **exactly one row per simulation step** with per-row flush.
- Added dedicated schema for geometry proof and independent completeness audit:
  - `sim_step`, `policy_step`, `phase`
  - `gate_evaluated`, `gate_effective`, `trigger_rule`
  - `stop_flag`, `slow_flag`, `replan_flag`
  - `dist_min_g1_body_m`, `margin_to_gate_m`
  - `g1_fell_flag`, `g1_root_x/y/z`, `g1_tilt_rad`
  - `motion_source_label`, `camera_capture_marker`, `body_pose_marker`

## Fail-closed analyzer + offline tests

- Added analyzer: `g1_ur10e_disturbance/scripts/dyn_b_per_step_audit_analyzer.py`
- Enforces fail-closed for window `190..340`:
  - every integer step appears exactly once (no gaps, no duplicates)
  - all `gate_effective == ALLOW`
  - `stop_flag == slow_flag == replan_flag == 0`
  - `margin_to_gate_m >= 0.10`
  - `phase(220)=lateral_positive_sweep`, `phase(330)=lateral_negative_sweep`
- Added tests: `g1_ur10e_disturbance/scripts/test_dyn_b_per_step_audit_analyzer_unit.py`
  - pass fixture
  - missing rows
  - duplicate rows
  - historical sparse 3-row shape
  - non-ALLOW
  - low margin
  - wrong phase

## M1W1 ROI provenance audit (body_poses + camera projection)

- ROI provenance source is projected G1 body links from `body_poses.jsonl` with camera from `camera_pose.json`.
- Step `220`:
  - projected links: `8`
  - in-frame links: `0`
  - clipped links: `8`
  - ROI area: `129.1743 px^2` (`0.042%` of frame)
- Step `330`:
  - projected links: `8`
  - in-frame links: `1` (`left_wrist_pitch_link`)
  - clipped links: `7`
  - ROI area: `1161.7446 px^2` (`0.378%` of frame)
- Displacement attribution:
  - G1 ROI centroid shift `220->330`: `20.6549 px`
  - G1 root projected shift: `23.7669 px`
  - UR10e EE projected shift: `81.2903 px`
  - Conclusion: `20.65 px` metric is a **G1 ROI centroid movement metric**, not UR10e/image-difference metric.

## ROI adequacy verdict

- verdict: **INADEQUATE_FOR_HUMAN_DYNAMIC_LABEL_REVIEW**
- reason: key-step visual support is heavily clipped (220: 0/8 links in-frame, 330: 1/8 in-frame), so human dynamic label confidence is insufficient.
- stricter future visual gate (proposal only, no camera/trajectory change in this milestone):
  - key steps each require in-frame projected links `>= 4`
  - key steps each require ROI fraction `>= 1%`
  - key steps each require clipped-link fraction `<= 50%`

## Future command builder update

- Updated future preflight command builder (`build_m1v1_dyn_b_preflight_inner_command`) to include explicit:
  - `--dyn-b-per-step-audit-csv .../safety_logs/phase3_dyn_b_per_step_audit.csv`
- command was **not executed** in this milestone.

## Preservation and scope controls

- Preserved all historical raw files and historical verdicts.
- No fabricated historical rows.
- No M1W1 promotion.
- No thresholds/USD/B0-B4 changes.
