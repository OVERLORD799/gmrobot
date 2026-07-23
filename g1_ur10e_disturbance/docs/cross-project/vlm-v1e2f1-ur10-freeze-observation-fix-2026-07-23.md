# V1-E2F.1 UR10 Freeze Observation Schema Fix (2026-07-23)

- status: `offline_fix_complete`
- scope: `run_phase3 --freeze-ur10e` initialization + freeze metrics observation path
- prior raw failure retained: `V1-E2F` (`KeyError: 'joint_pos'`) is preserved as historical evidence

## Root Cause
- `run_phase3.py` freeze path read `obs["ur10e_policy"]["joint_pos"]`.
- Real observation-manager schema exposes:
  - `ur10e_policy`: `ee_pos` + object/slot transforms (no `joint_pos`)
  - `safety`: `joint_pos`, `joint_vel` (6-DoF arm terms, separate group)
- Result: `KeyError: 'joint_pos'` before any preflight telemetry rows.

## Fix
- Added fail-closed helper in `motion_isolation.py`:
  - `resolve_ur10_freeze_action_seed(...)`
  - `extract_ur10_pose7_from_policy_obs(...)`
- Source priority for freeze hold seed:
  1. `UR10eController.get_action(..., advance=False)` runtime 8D action (`pose7 + gripper`)
  2. explicit `ur10e_policy.ee_pos` indices for pose extraction (no key guessing)
- Gripper seed is required from runtime action state and is never synthesized from zeros.
- `run_phase3.py` now:
  - initializes hold action from runtime state interface
  - computes per-step freeze delta using explicit `ur10e_policy.ee_pos` extraction
  - logs provenance string for auditability

## Added Offline Evidence
- fixture: `scripts/fixtures/ur10_observation_manager_snapshot.json`
  - captures real manager shape split (`ur10e_policy.ee_pos` vs `safety.joint_pos`)
- tests:
  - `test_motion_isolation_unit.py`
    - extracts 7D pose from real obs fixture (tensor-like input)
    - missing schema fails closed
    - runtime-state priority + stable hold hash
  - `test_v1e2e_fake_controller_pipeline_unit.py`
    - freeze hold seeded from runtime action (7 pose + gripper)
    - hash stability and freeze override semantics

## Validation (Offline)
- `python -m py_compile` on changed modules/tests: pass
- `test_motion_isolation_unit.py`: pass
- `test_v1e2e_fake_controller_pipeline_unit.py`: pass
- `test_v1e2b1_dyn_c_import_closure_unit.py`: pass
- `test_v1e2e_dyn_c_motion_preflight_config_unit.py`: pass
- `test_v1e02_dataset_candidate_manifest_unit.py`: pass
- `test_held_critical_wiring_unit.py`: pass
- `test_v1e2e_dyn_c_motion_preflight_unit.py`: pass
- `git diff --check`: pass

## Next Step Budget (unchanged)
- one source-only rebuild
- one replacement motion preflight
- formal capture remains blocked until replacement preflight passes
