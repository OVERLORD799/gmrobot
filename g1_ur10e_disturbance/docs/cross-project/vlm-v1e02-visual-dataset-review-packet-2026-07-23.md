# V1-E0.2 Func-C + Dyn-B Visual Dataset Review Packet (Offline)

- preflight HEAD: `5e52299` (full SHA matched in run metadata)
- reviewer_approved: `false` (fixed)
- technical_review_status: `pending_user_review`
- candidate manifest: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json`
- manifest index: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-manifest-index-2026-07-23.json`

## Objective Technical Review
- Func-C step100/200: target and contents clear; no USD garble.
- Dyn-B M1Z9 step220/330: G1 visible with white-background low contrast.
- Dyn-B dynamic claim requires temporal pair / tracking evidence; single frame not sufficient.
- M1Z9 geometry_isolated=false with historical `FAIL_NONALLOW_GEOMETRY`; cannot be promoted to live-control positive.

## Compliance Notes
- Offline-only workflow; no Docker/Isaac/build/capture/network/POST/VLM/perception/SAM2/GDINO/credentials.
- Original PNG files are not modified or overwritten.
- Stability-adjacent frames (219/221/329/331) are evidence-only.
