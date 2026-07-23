# V1-M1V1 Dyn-B clean-base source-closure recovery (2026-07-23)

## Verdict

**CLEAN_BASE_SOURCE_CLOSURE_PASS**

`next_gate=ONE_DYN_B_PREFLIGHT_MAY_BE_REQUESTED`

- build count: **1** (success)
- smoke count: **1** (success, no retry)
- formal Dyn-B capture: **not run** (forbidden in this milestone)
- package mutation: **none** (no pip/conda/apt/quarantine/PYTHONPATH injection)

## Clean base evidence

- base image: `gmdisturb:b4-p010-20260721`
- base image SHA: `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- build image tag: `gmdisturb:e01-dyn-b-clean-m1v1-20260723`
- build image SHA: `sha256:19112b9c1e8f63c04e8ef777840da823f0323b55f950f432f27ea8ba9d4cf14f`
- Dockerfile: `docker/Dockerfile.e01-dyn-b-clean-m1v1`
- Docker build elapsed: **1s**

## Source closure and bake coverage

- host-side static closure for `scripts/run_phase3.py`: **31 members**
- unresolved local modules: **0**
- `scene_camera_override.py`: **included in closure**
- image static check: **31/31 closure files located in baked path**
- missing closure members in image: **0**

Closure members:

`config_loader.py`, `dual_env_cfg.py`, `dynamic_audit_csv.py`, `dynamic_sweep_proxy.py`, `event_csv.py`, `g1_arm_controller.py`, `g1_disturbance_controller.py`, `g1_virtual_hand.py`, `g1_vlm_client.py`, `g1_walk_controller.py`, `mat_event_detector.py`, `mdp/__init__.py`, `mdp/gm_safety_obs.py`, `mdp/tactile_obs.py`, `mdp/terminations.py`, `mdp/walk_action.py`, `paths.py`, `per_part_state.py`, `protocol_vhand.py`, `safety_adapter.py`, `scenarios.py`, `scene_camera_override.py`, `scripts/numpy_abi_guard.py`, `scripts/pick_and_place_policy.py`, `scripts/run_phase3.py`, `seed_utils.py`, `spawn_utils.py`, `test_metrics.py`, `ur10e_controller.py`, `vendored/robot_cfg.py`, `vendored/ur10e_cfg.py`

## Smoke (single canonical one-step)

- runner: `docker/run.sh` + hardened `GMRobot/scripts/capture_one_shot_runner.py`
- scenario: `outer_lateral_patrol`
- seed: `43`
- max_steps: `1`
- elapsed: **30.880s**
- exit: **0**
- CSV: `results/paper_demo/v1m1v1_dyn_b_clean_runtime_20260723/safety_logs/phase3.csv` (**non-empty, 2 rows**)
- NumPy pre/post: **ok=true**, same single root
- typing_extensions pre/post: **ParamSpec_available=true**
- forbidden pattern hits: **0**
- POST count in stdout/stderr: **0**
- Xid count in stdout/stderr: **0**
- leftover containers from this image: **none**

NumPy root:

`/isaac-sim/extscache/omni.kit.pip_archive-0.0.0+69cbf6ad.lx64.cp311/pip_prebundle`

typing_extensions origin:

`/isaac-sim/kit/python/lib/python3.11/site-packages/typing_extensions.py`

## Evidence directory

`g1_ur10e_disturbance/results/paper_demo/v1m1v1_dyn_b_clean_runtime_20260723/`

## Policy confirmation

- no VLM/perception/SAM2/POST changes
- no safety/USD/B0-B4 changes
- no NumPy/typing_extensions package-layer changes
- no formal capture executed
