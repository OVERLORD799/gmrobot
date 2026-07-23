# V1-M1U2.3 Dyn-B NumPy De-dup Final Recovery（2026-07-23）

## Scope and Policy

- Final authorized recovery only, base commit: `672097c`.
- No formal capture, no network models, no POST path enablement, no safety/USD/B0-B4 changes.
- Hard budget enforced:
  - Docker build: `1/1` (used)
  - Canonical AppLauncher smoke: `1/1` (used)
  - No retry, sequential only.

## Code and Test Changes

- Added `g1_ur10e_disturbance/scripts/assert_numpy_dedup_report.py`
  - No version hard-code.
  - Requires exactly one `numpy-*.dist-info`.
  - Requires `numpy` and `numpy.libs`.
  - Rejects zero/multiple dist-info targets.
  - Asserts no `remaining_importable_numpy_prebundle`.
  - Asserts Kit NumPy origins under Kit site-packages root.
- Added `g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u23`
  - Tag: `gmdisturb:e01-dyn-b-m1u23-20260723`.
  - Runs dedup + dynamic assertion.
  - Copies quarantine report into image:
    - `/opt/projects/g1_ur10e_disturbance/numpy_prebundle_quarantine_report.json`
- Updated:
  - `g1_ur10e_disturbance/e01_dyn_b_runtime_guard.py`
  - `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`
  - `g1_ur10e_disturbance/scripts/test_pip_prebundle_numpy_dedup_unit.py`

## Offline and Static Validation (Pre-build)

- PASS `g1_ur10e_disturbance/scripts/test_pip_prebundle_numpy_dedup_unit.py`
  - includes `1.26.0` and synthetic `9.9.9` variants
  - includes static parse of Dockerfile RUN command and execution of assertion logic against temp fixture
- PASS `g1_ur10e_disturbance/scripts/test_numpy_abi_guard_unit.py`
- PASS `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`
- PASS `GMRobot/scripts/test_capture_one_shot_runner_unit.py`

## Single Build Result

- Build command:
  - `docker build -f g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u23 -t gmdisturb:e01-dyn-b-m1u23-20260723 g1_ur10e_disturbance`
- Result: **SUCCESS**
- Image SHA:
  - `sha256:8b70b0b16f973c0a3297c960d12492300af6b3f9f90fe709cfc14687f11c1c84`
- Exit/elapsed:
  - exit code `0`
  - elapsed `4s`
- Build logs:
  - `g1_ur10e_disturbance/results/paper_demo/v1m1u23_dyn_b_numpy_dedup_smoke_20260723/meta/docker_build_stdout.log`
  - `g1_ur10e_disturbance/results/paper_demo/v1m1u23_dyn_b_numpy_dedup_smoke_20260723/meta/docker_build_stderr.log`

## Quarantine Report (Export + Static Retrieval)

- Exported in image and retrieved by static inspection:
  - image path: `/opt/projects/g1_ur10e_disturbance/numpy_prebundle_quarantine_report.json`
  - host copy: `g1_ur10e_disturbance/results/paper_demo/v1m1u23_dyn_b_numpy_dedup_smoke_20260723/meta/numpy_prebundle_quarantine_report.from_image.json`
- Dynamic dist-info target:
  - `numpy-1.26.0.dist-info`
  - evidence: `g1_ur10e_disturbance/results/paper_demo/v1m1u23_dyn_b_numpy_dedup_smoke_20260723/meta/numpy_dist_info_target.from_image.txt`
- Exact quarantined paths/digests:
  - `.../pip_prebundle/numpy` -> `f4e470860b22a5a45fcfcf922f5c2adeb04321b17dd4da244ec001fb261ed543`
  - `.../pip_prebundle/numpy-1.26.0.dist-info` -> `4dcfbe476e7bffb59837b1700126b90eedf94718fea07c9542ab06eff27b8a45`
  - `.../pip_prebundle/numpy.libs` -> `720dcf1b94745d0647880c3d063e750244987f59a5bc6a03ec66e105214d240c`
- Non-NumPy sentinel in image:
  - `.../pip_prebundle/typing_extensions/__init__.py` present (static check: `SENTINEL_PRESENT`)

## Canonical AppLauncher One-step Smoke

- Runner: `GMRobot/scripts/capture_one_shot_runner.py`
- Invocation path: `g1_ur10e_disturbance/docker/run.sh`
- Constraints: no host source mount, `seed 43`, `outer_lateral_patrol`, `max_steps 1`, require CSV + pre/post origin JSON, forbid target error tokens.
- Result: **FAILED**
  - runner exit code: `86` (postcheck failed)
  - elapsed: `16.101766124s`
  - forbid hit: `Traceback` (stderr)
  - required CSV missing: `.../safety_logs/phase3.csv`
  - pre/post origin JSON generated:
    - `.../meta/numpy_origin_pre.json`
    - `.../meta/numpy_origin_post.json`
  - no `Xid` observed
  - `POST0` token not observed
  - error includes extension startup failure chain (`typing_extensions ParamSpec import`)

## NumPy Origin Status

- Post normalized roots:
  - exactly `/isaac-sim/kit/python/lib/python3.11/site-packages`
- Loaded prebundle NumPy modules:
  - none
- Evidence:
  - `g1_ur10e_disturbance/results/paper_demo/v1m1u23_dyn_b_numpy_dedup_smoke_20260723/meta/static_inspection.json`

## Verdict

- `NUMPY_DEDUP_FAIL_FINAL_STOP`
- next gate: `STOP_NO_CAPTURE`
- Formal capture executed: `NO`
