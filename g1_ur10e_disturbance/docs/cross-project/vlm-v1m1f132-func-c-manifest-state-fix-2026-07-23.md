# V1-M1F13.2 Func-C Manifest State Fix (Offline)

- Date: `2026-07-23`
- Base HEAD: `cbeb4c46481bf2cc848ad8d2f0a152330bd046a1`
- Scope: minimal consistency repair for V1-E0.2 dataset candidate manifest + validator

## Changes
- Added explicit allowed candidate status: `reference_visual_pass_pending_user_confirmation`.
- Enforced strict flag contract when status is `reference_visual_pass_pending_user_confirmation`:
  - `artifact_removal_technical_pass=true`
  - `reference_bin_visual_contract_pass=true`
  - `reviewer_approved=false`
  - `formal_recapture_allowed=false`
- Tightened `semantic_clarity` semantics:
  - if present, value must be exactly `user_confirmation_required`
  - arbitrary values are rejected
- Repaired current manifest Func-C entry to satisfy the contract:
  - `semantic_clarity: user_confirmation_required`

## Unit Coverage Added
- Positive case:
  - accepts `reference_visual_pass_pending_user_confirmation` with all required flags.
- Negative case:
  - rejects illegal reviewer/formal/technical flag combinations for the same status.

## Offline Verification Commands
- validator:
  - `python g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py --manifest g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json --repo-root /home/czz/GMrobot`
- unit:
  - `python g1_ur10e_disturbance/scripts/test_v1e02_dataset_candidate_manifest_unit.py`
- pycompile:
  - `python -m py_compile g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py g1_ur10e_disturbance/scripts/test_v1e02_dataset_candidate_manifest_unit.py`
- sensitive:
  - `rg -n "AKIA|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|password\\s*=|SECRET|TOKEN" g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py g1_ur10e_disturbance/scripts/test_v1e02_dataset_candidate_manifest_unit.py g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json`
- diffcheck:
  - `git diff --check`

## Constraints Observed
- No Docker / Isaac / network operations
- No image edits
- No status semantic broadening
