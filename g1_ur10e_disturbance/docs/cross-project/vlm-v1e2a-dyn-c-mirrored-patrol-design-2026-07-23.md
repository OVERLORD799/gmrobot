# V1-E2A Dyn-C Mirrored Outer Patrol Offline Design

- verdict: `PREBUILD_READY`
- scene/scenario: `E01-Dyn-C` / `mirrored_outer_lateral_patrol`
- motion_source: `scripted_g1_mirrored_outer_lateral_patrol`
- seed: `44`
- scene_group: `e01_dyn_c_formal_m1e2a_20260723`
- camera pose: `[0.45, 0.0, 2.7]` / `[0.7071, 0.0, 0.7071, 0.0]`
- capture steps: `[240, 310]`
- adjacent triplets: `A=[239, 240, 241]`, `B=[309, 310, 311]`
- geometry window: `[220, 330]`

## Offline Projection Gates
- visible links per frame >= `4`
- ROI area fraction per frame >= `0.01`
- clipping ratio per frame <= `0.5`
- centroid displacement at capture frames >= `30.0` px
- predicted centroid displacement: `66.94691421141476` px
- workcell/double bins visible: `True`

## Trajectory Identity
- dyn_c trajectory_id: `7beb111400ccc2f8cd5d9ed1ab19192705714ff3d6cbc7dc3ccb16154c74683c`
- dyn_b trajectory_id: `759e778529465b118250e90b84d9cfafade6dca9c7011603794f05724d9d164e`
- distinct from Dyn-B: `True`

## Label Boundary
- dynamic / provisional / reviewer_approved=false / synthetic=false
- scripted_locomotion=true / human_motion=false / human_hand=false / glove=false / PPE=false
- VLM_output=false / geometry_evidence=false / control_evidence=false

## Next Step Budget
- only allow 1 build + 1 visual capture
