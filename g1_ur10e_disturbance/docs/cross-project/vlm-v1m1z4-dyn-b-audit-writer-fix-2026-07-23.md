# V1-M1Z4 Dyn-B Audit Writer Fix (2026-07-23)

## Scope
- Narrow repair only: proven `NameError: name 'csv' is not defined` at `scripts/run_phase3.py` Dyn-B per-step writer initialization path.
- No Dyn-B formal capture.
- No VLM/perception/SAM2/POST changes.
- No safety/trajectory/camera/USD/B0-B4 behavior changes.

## Code/Test/Docker Changes
- `scripts/run_phase3.py`
  - Added missing standard-library import path coverage via dedicated writer support integration.
  - Replaced inline Dyn-B per-step writer setup with a single support helper call.
- `scripts/dyn_b_per_step_audit_writer.py` (new)
  - Centralized per-step CSV schema and `init -> header -> flush` writer initialization.
  - Imports audited for required stdlib/global names (`csv`, `os`, `typing.IO`).
- `scripts/test_dyn_b_per_step_audit_writer_unit.py` (new)
  - Offline focused test that executes actual writer init/header/one-row/flush/close path.
  - Asserts exact schema and one data row output.
- `docker/Dockerfile.e01-dyn-b-clean-m1z4` (new)
  - Pure `FROM/WORKDIR/COPY/LABEL`; no package mutation; no test or runtime gating in Dockerfile.

## Host-side Validation
- `python -m py_compile`:
  - `scripts/run_phase3.py`
  - `scripts/dyn_b_per_step_audit_writer.py`
  - `scripts/test_dyn_b_per_step_audit_writer_unit.py`
- Relevant host test set:
  - `test_e01_dyn_b_m1z_image_policy_unit.py`
  - `test_e01_dyn_b_m1y_camera_framing_unit.py`
  - `test_e01_dyn_b_m1z2_dockerfile_policy_unit.py`
  - `test_e01_dyn_b_m1z_build_hermetic_policy_unit.py`
  - `test_dyn_b_per_step_audit_writer_unit.py`
- Result: all PASS.

## Build/Smoke (strict count)
- Docker build count: **1**
  - Image: `gmdisturb:e01-dyn-b-clean-m1z4-20260723`
  - Image SHA: `sha256:962de1e3f5e9c761d5106c660af7e7dfdbc79319194839a284a06e64dfb45e83`
- Canonical AppLauncher smoke count (`max_steps=1`): **1**
  - Enabled `--dyn-b-per-step-audit-csv`
  - No camera capture flag used
  - Exit code: `0`
  - Elapsed: `30.97s`

## Evidence Paths
- Evidence root:
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/`
- Normal smoke CSV:
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/safety_logs/phase3.csv`
- Dyn-B per-step CSV:
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/safety_logs/phase3_dyn_b_per_step_audit.csv`
- NumPy/typing origin JSON:
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/meta/numpy_origin_pre.json`
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/meta/numpy_origin_post.json`
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/meta/typing_extensions_pre.json`
  - `results/paper_demo/v1m1z4_dyn_b_audit_writer_smoke_20260723/meta/typing_extensions_post.json`

## Per-step CSV Schema + One-row Check
- Expected header present:
  - `sim_step,policy_step,phase,gate_evaluated,gate_effective,trigger_rule,stop_flag,slow_flag,replan_flag,dist_min_g1_body_m,margin_to_gate_m,g1_fell_flag,g1_root_x,g1_root_y,g1_root_z,g1_tilt_rad,motion_source_label,camera_capture_marker,body_pose_marker`
- Data row count: **exactly 1**
- Observed single row:
  - `sim_step=0`, `policy_step=1`, `gate_effective=ALLOW`, `camera_capture_marker=0`, `body_pose_marker=0`

## Guardrail Outcome
- No `Traceback`.
- No `NameError`.
- No missing module errors.
- No ABI/ParamSpec/extension/device fatal errors observed in this one-step smoke run.
- No camera capture run performed.

## Verdict
`DYN_B_AUDIT_WRITER_SMOKE_PASS`

Next state:
`ONE_REVIEWABLE_DYN_B_PREFLIGHT_MAY_BE_REQUESTED`
