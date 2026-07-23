# V1-M1U2.2 Dyn-B NumPy De-dup Recovery（2026-07-23）

## Scope and Authorization

- Narrow recovery only: fix `pip_prebundle` NumPy de-dup directory hashing failure.
- No formal capture; no VLM/perception/SAM2/POST; no safety/USD/B0-B4 changes.
- Build/smoke budget respected: one build attempt only, no retry, no concurrency.

## Code/Test Changes

- Updated `g1_ur10e_disturbance/scripts/pip_prebundle_numpy_dedup.py`
  - Fixed root cause: directory hashing now uses deterministic tree digest instead of `open()` on directory.
  - Added deterministic support for regular files, directories, symlinks:
    - records kind (`regular_file`/`directory`/`symlink`)
    - records `size_bytes`, `file_count`, `digest`, `symlink_target`
    - directory digest includes sorted relative paths, file types, file content hashes and symlink targets.
- Replaced `g1_ur10e_disturbance/scripts/test_pip_prebundle_numpy_dedup_unit.py`
  - realistic temp fixture with `numpy/`, `numpy.libs/`, `numpy-*.dist-info/`, regular files and symlinks
  - asserts quarantine only moves NumPy targets and keeps non-NumPy sentinels intact
  - runs de-dup script end-to-end against fixture via subprocess (not helper-only mocks)
- Added `g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u22`
  - new tag line for `gmdisturb:e01-dyn-b-m1u22-20260723`
  - build-time de-dup run + report checks for exact NumPy target names, Kit NumPy origin, non-NumPy sentinel intact.
- Updated runtime/tag pointers:
  - `g1_ur10e_disturbance/e01_dyn_b_runtime_guard.py`
  - `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`

## Offline Validation (pre-build)

- PASS `g1_ur10e_disturbance/scripts/test_pip_prebundle_numpy_dedup_unit.py`
- PASS `g1_ur10e_disturbance/scripts/test_numpy_abi_guard_unit.py`
- PASS `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`
- PASS `GMRobot/scripts/test_capture_one_shot_runner_unit.py`

## Static Inspection

- `outer_lateral_patrol` core bake targets all true:
  - `scripts/run_phase3.py`
  - `g1_disturbance_controller.py`
  - `configs/e01_dyn_b_capture.yaml`
  - `e01_dyn_b_runtime_guard.py`
  - `e01_dyn_b_offline_readiness.py`
- ABI guard checks present:
  - `verify_numpy_single_root`
  - `conflicting_sys_path`
  - `NUMPY_ABI_GUARD_FAIL`
- Evidence:
  - `g1_ur10e_disturbance/results/paper_demo/v1m1u22_dyn_b_numpy_dedup_smoke_20260723/meta/static_inspection.json`

## Budgeted Execution

- Docker build count: `1/1` (used)
- AppLauncher one-step smoke count: `0/1` (blocked because build failed; no retry allowed)
- Build tag (distinct, no overwrite): `gmdisturb:e01-dyn-b-m1u22-20260723`
- Build command record:
  - `g1_ur10e_disturbance/results/paper_demo/v1m1u22_dyn_b_numpy_dedup_smoke_20260723/meta/build_attempt_command.txt`

## Build Result and Failure Fact

- Build result: **FAILED**
  - exit code: `1`
  - elapsed: `1s`
  - image SHA: not generated
  - stderr: `g1_ur10e_disturbance/results/paper_demo/v1m1u22_dyn_b_numpy_dedup_smoke_20260723/meta/docker_build_stderr.log`
- De-dup hashing bug itself is fixed (no `IsADirectoryError`).
- New failure is a strict version pin in Dockerfile assertion:
  - expected `numpy-1.26.4.dist-info`
  - actual `numpy-1.26.0.dist-info`
  - assertion payload in build log: `['numpy', 'numpy-1.26.0.dist-info', 'numpy.libs']`

## NumPy De-dup Evidence Status

- Build-time report indicates exact quarantined names during failed assertion gate:
  - `numpy`
  - `numpy.libs`
  - `numpy-1.26.0.dist-info`
- Quarantined full paths/digests in host evidence: unavailable (image layer failed before host export).
- Kit NumPy intact assertion: configured and executed before failure gate; final success not reached due version mismatch assert.
- Non-NumPy sentinel intact assertion: configured in Dockerfile gate.
- NumPy origin pre/post JSON: unavailable (smoke not run).

## Smoke Policy Status

- Required smoke command path prepared:
  - `g1_ur10e_disturbance/docker/run.sh`
  - hardened runner: `GMRobot/scripts/capture_one_shot_runner.py`
- Not executed because one allowed build failed and retries are forbidden.

## Verdict and Gate

- Verdict: `NUMPY_DEDUP_FAIL_STOP`
- next_gate: `STOP_NO_CAPTURE`
- Formal capture executed: `NO`
