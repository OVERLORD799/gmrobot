# V1-M1F3.2 Func-C Manifest Consistency Fix (Offline)

- Date: `2026-07-23`
- Base HEAD: `f550384f5663956535c4405a531415fcc064a4ca`
- Scope: minimal offline consistency fix for V1-E0.2 manifest validator + unit tests

## Fixes
- Allow explicit status value: `artifact_removed_semantic_clarity_pending_user`.
- Enforce strict status-field combination when above status is used:
  - `reviewer_approved=false`
  - `formal_recapture_allowed=false`
  - `semantic_clarity=user_review_required`
- Reject `semantic_clarity` under other statuses (prevent arbitrary/loose strings).
- Keep old invalid approval combinations failing via regression tests.

## Gymnasium Collection Issue (Host)
- Failing command:
  - `pytest -q g1_ur10e_disturbance/scripts/test_v1e02_dataset_candidate_manifest_unit.py g1_ur10e_disturbance/scripts/test_v1e03_dyn_b_offline_temporal_evidence_unit.py GMRobot/scripts/test_e01_func_c_capture_unit.py`
- Dependency chain:
  - `pytest` collection imports `g1_ur10e_disturbance` package
  - `g1_ur10e_disturbance/__init__.py` imports `gymnasium`
  - host env lacks `gymnasium` -> `ModuleNotFoundError`
- Separation method used: run pure/offline unit entry commands directly (no package-level gym import).

## Offline Verification (Executed)
- `python g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py --manifest g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json --repo-root /home/czz/GMrobot` -> PASS
- `python g1_ur10e_disturbance/scripts/test_v1e02_dataset_candidate_manifest_unit.py` -> PASS
- `python g1_ur10e_disturbance/scripts/test_v1e03_dyn_b_offline_temporal_evidence_unit.py` -> PASS
- `python GMRobot/scripts/test_e01_func_c_capture_unit.py` -> PASS

## Constraints
- No pip install
- No runtime masking change
- No Docker/Isaac/network operations
