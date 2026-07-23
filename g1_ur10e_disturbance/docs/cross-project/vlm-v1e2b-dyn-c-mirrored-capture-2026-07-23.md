# V1-E2B Dyn-C mirrored capture (2026-07-23)

- verdict: `FAIL_FINAL`
- next_gate: `STOP_NO_RETRY`
- reviewer_approved: `false`
- requested_initial_verdict: `REVIEW_REQUIRED`
- image: `gmdisturb:e01-dyn-c-mirrored-m1e2b-20260723`
- image_sha: `sha256:bf17f8437d5987f95fc25aabb9136257695a5e6429e004e3df3c3913d81318dd`
- elapsed_seconds: `0.506`
- run_exit_code: `1`
- inference POST count: `0`
- failure_reason: `ModuleNotFoundError: dyn_b_per_step_audit_writer`

## Constraints + Observations
- build1/run1 executed; no retry performed.
- camera requested and fixed reference pose env was forwarded.
- run terminated before frame export; 6 target frames missing.
- geometry/control gates are explicitly disabled (`false`) for visual-only policy bookkeeping.

## Artifact Paths
- report json: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e2b-dyn-c-mirrored-capture-2026-07-23.json`
- artifact manifest: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e2b-dyn-c-mirrored-capture-2026-07-23.artifact-manifest.jsonl`
- artifact summary: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e2b-dyn-c-mirrored-capture-2026-07-23.artifact-summary.json`
- result dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2b_dyn_c_mirrored_capture_20260723`
