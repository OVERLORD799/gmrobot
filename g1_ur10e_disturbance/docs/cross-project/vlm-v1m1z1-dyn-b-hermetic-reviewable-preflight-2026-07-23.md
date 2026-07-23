# V1-M1Z1 Dyn-B hermetic reviewable preflight (2026-07-23)

- based_on_commit: `979482c451b6dda7f7777042f7b6b7217027f6e0`
- policy: Docker build must be hermetic and source/fixture-only; no dependency on `results/paper_demo` or archived runtime artifacts.
- build_count/run_count: `1/0` (hard budget respected; no retry)
- requested_image_tag: `gmdisturb:e01-dyn-b-clean-m1z1-20260723`
- build_result: `FAIL` at Docker RUN static grep guard (`scripted_g1_outer_lateral_patrol` literal mismatch)
- capture_result: `NOT_ATTEMPTED` (blocked by failed build/static image check precondition)
- host offline tests: `PASS` (`test_e01_dyn_b_m1v1_source_closure_unit`, `test_e01_dyn_b_m1v1_docker_copy_coverage_unit`, `test_e01_dyn_b_m1y_camera_framing_unit`, `test_e01_dyn_b_m1z_build_hermetic_policy_unit`, `test_e01_dyn_b_m1w1_command_construction_unit`, `test_e01_dyn_b_m1z_image_policy_unit`, `test_e01_dyn_b_runtime_guard_unit`)
- image/frame hashes: unavailable (`image not produced`, `no frames captured`)
- telemetry/visual metrics: unavailable (`no canonical run executed`)
- verdict: **DYN_B_REVIEWABLE_PREFLIGHT_FAIL_FINAL**
- next_gate: `STOP_NO_RETRY`
