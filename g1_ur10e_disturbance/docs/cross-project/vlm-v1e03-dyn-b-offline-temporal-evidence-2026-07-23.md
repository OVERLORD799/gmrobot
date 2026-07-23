# V1-E0.3 Dyn-B Offline Temporal Evidence

- run_id: `v1e03_dyn_b_offline_temporal_evidence_20260723`
- motion_attribution: `SCRIPTED_G1_MOTION_SUPPORTED`
- technical_review_status: `technical_temporal_pass_pending_user`
- semantic_identity: `scripted_g1_locomotion`
- human_motion/human_hand/PPE: `false/false/false`
- ur10e_region_change_ratio: `not_available` (可靠分割不可保证)

## 固定门禁阈值
- links>=`4`; ROI>=`0.01`; clipping<=`0.5`; centroid>=`20.0`
- local ROI change(220->330)>=`0.02`; ROI内外对照>=`1.2`

## 关键结论
- A组(219/220/221)稳定性通过: `True`
- B组(329/330/331)稳定性通过: `True`
- 220->330 centroid displacement(px): `24.297366596071075`
- 220->330 ROI inner/outer/full change: `0.317816091954023` / `0.06957083250546393` / `0.0737890625`

## 数据充分性复评（按 scene_group，不拆相邻帧）
- functional_positive_groups: `2`（D1B 历史组 + M1M 组）
- dynamic_positive_groups: `1`
- dataset_status: `DATASET_INSUFFICIENT`
- gap: `dynamic` 仍只有单组，缺少跨组动态正样本与独立 holdout 组，不能支撑稳健泛化评估。
