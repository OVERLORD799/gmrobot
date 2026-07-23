# V1-M1Z Dyn-B reviewable preflight (2026-07-23)

- verdict: **DYN_B_REVIEWABLE_PREFLIGHT_FAIL_FINAL**
- next_gate: `STOP_NO_RETRY`
- anchor_commit: `2f3df8d`
- build_count/run_count: `1/0`
- image: `gmdisturb:e01-dyn-b-clean-m1z-20260723` (sha unavailable due to build failure)
- camera target pos/rot: `[0.45, 0.0, 2.7]` / `[0.7071, 0.0, 0.7071, 0.0]`
- offline tests: `7/7` passed (command/runtime guard/camera framing/per-step analyzer/source-closure/docker-copy-policy/run.sh env forwarding)
- build failure signature: `FileNotFoundError: /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w1_20260723/meta/body_poses.jsonl`
- policy applied: build failure stops; no retry; no preflight run; no second capture
