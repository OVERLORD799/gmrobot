# V1-E2D final Dyn-C mirrored capture (2026-07-23)

- verdict: `user_rejected_no_visible_g1_motion`
- next_gate: `REDESIGN_REQUIRED`
- reviewer_approved: `false`
- user_rejected: `true`
- requested_initial_verdict: `REVIEW_REQUIRED`
- image: `gmdisturb:e01-dyn-c-mirrored-m1e2d-20260723`
- image_sha: `sha256:2bde63f2c5450e43828e0e8965ade03f798dcab83a06793d96b7760a69243af5`
- elapsed_seconds: `64.419441`
- run_exit_code: `0`
- inference POST count: `0`
- models/inference refs in logs: `0`
- failure_reason: `n/a`

## Constraint Execution
- full config load/schema/import closure/prebuild/unit gates passed before build.
- strict single `1 rebuild + 1 run`, no retry.
- frame evidence uses post-exit `find/sha256` only.
- task_execution=false and visual-only command contract retained.

## Required Frame Paths
- frame240: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2d_dyn_c_mirrored_capture_20260723/scene/frame_000240_env0.png`
- frame310: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2d_dyn_c_mirrored_capture_20260723/scene/frame_000310_env0.png`

## Saved Evidence
- body poses: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2d_dyn_c_mirrored_capture_20260723/meta/body_poses.jsonl`
- trajectory signature: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2d_dyn_c_mirrored_capture_20260723/meta/trajectory_signature.json`
- camera pose: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2d_dyn_c_mirrored_capture_20260723/meta/camera_pose.json`

## Artifact Paths
- report json: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e2d-dyn-c-mirrored-capture-2026-07-23.json`
- artifact manifest: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e2d-dyn-c-mirrored-capture-2026-07-23.artifact-manifest.jsonl`
- artifact summary: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e2d-dyn-c-mirrored-capture-2026-07-23.artifact-summary.json`
- result dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2d_dyn_c_mirrored_capture_20260723`

## Metrics
- links(min visible): `8`
- ROI(area fraction avg): `0.009191`
- clipping(max ratio): `0.0`
- centroid(240->310, px): `27.905`
- local motion px: `239_240=1.467`, `240_241=1.543`, `309_310=0.628`, `310_311=0.757`
