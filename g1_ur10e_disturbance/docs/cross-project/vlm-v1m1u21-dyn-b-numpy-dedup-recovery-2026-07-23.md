# V1-M1U2.1 Dyn-B NumPy De-dup Recovery（2026-07-23）

## Scope and Authorization

- Narrow recovery only: fix Dockerfile shell execution issue from M1U2.
- No formal capture; no VLM/perception/SAM2/POST; no safety/USD/B0-B4 changes.
- Preserve NumPy-only `pip_prebundle` quarantine design.

## Code/Test Changes

- Added `g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u21`
  - Uses explicit bash exec-form RUN:
    - `RUN ["/bin/bash","-lc","set -euo pipefail; ..."]`
  - Keeps quarantine targets unchanged: `numpy`, `numpy.libs`, `numpy-*.dist-info`
- Updated runtime guard tag/dockerfile to M1U2.1:
  - `g1_ur10e_disturbance/e01_dyn_b_runtime_guard.py`
    - `M1U2_IMAGE_TAG=gmdisturb:e01-dyn-b-m1u21-20260723`
    - `M1U2_DOCKERFILE=docker/Dockerfile.e01-dyn-b-m1u21`
- Updated offline bake test path expectations to M1U2.1 result root:
  - `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`
- Corrected historical M1U2 failed-run next gate:
  - `vlm-v1m1u2-dyn-b-numpy-dedup-2026-07-23.md/.json`
  - `BUILD_AND_APP_LAUNCHER_SMOKE_REQUIRED`

## Offline Validation (pre-build)

- PASS `g1_ur10e_disturbance/scripts/test_pip_prebundle_numpy_dedup_unit.py`
- PASS `g1_ur10e_disturbance/scripts/test_numpy_abi_guard_unit.py`
- PASS `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`
- PASS `GMRobot/scripts/test_capture_one_shot_runner_unit.py`

## Static Inspection

- `outer_lateral_patrol` targeted bake sources: all true.
- ABI guard checks present:
  - `verify_numpy_single_root`
  - `conflicting_sys_path` reporting
  - `NUMPY_ABI_GUARD_FAIL` fail token
- Evidence:
  - `g1_ur10e_disturbance/results/paper_demo/v1m1u21_dyn_b_numpy_dedup_smoke_20260723/meta/static_inspection.json`

## Budgeted Execution

- Docker build count: `1/1` (used)
- AppLauncher one-step smoke count: `0/1` (not eligible after build failure)
- Build tag (distinct, no overwrite): `gmdisturb:e01-dyn-b-m1u21-20260723`
- Build command record:
  - `.../meta/build_attempt_command.txt`
- Build result:
  - exit code: `1`
  - elapsed: `1s`
  - image SHA: not generated
  - stderr: `.../meta/docker_build_stderr.log`

## Build Failure Fact

- Dockerfile shell issue is resolved (`/bin/bash -lc` path is active).
- Single allowed build failed later in dedup script hashing stage:
  - `IsADirectoryError` on prebundle `numpy` directory hashing.
- Because no retry is allowed, smoke was not executed.

## NumPy De-dup Evidence Status

- Quarantined prebundle NumPy package paths: unavailable (build failed before report output was persisted to host evidence tree).
- Quarantined `numpy.libs` paths: unavailable (same reason).
- Quarantined `numpy-*.dist-info` paths: unavailable (same reason).
- Proof non-NumPy prebundle untouched:
  - covered by offline unit test `test_pip_prebundle_numpy_dedup_unit.py` (PASS).
- NumPy origin JSON pre/post: unavailable (smoke not run).

## Smoke Policy Assertions (configured, not executed)

- Via `docker/run.sh` + hardened runner `GMRobot/scripts/capture_one_shot_runner.py`
- Intended scenario: `--seed 43 --scenario outer_lateral_patrol --max_steps 1`
- Required artifacts and forbids were prepared, including:
  - non-empty CSV and pre/post NumPy origin JSON
  - forbid `Traceback`, `NUMPY_ABI_GUARD_FAIL`, `dtype size changed`,
    `broadcast_to`, extension startup failure, `DEVICE_LOST`

## Verdict and Gate

- Verdict: `NUMPY_DEDUP_FAIL_STOP`
- next_gate: `STOP_NO_CAPTURE`
- Formal capture executed: `NO`
