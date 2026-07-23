# V1-E2D.1 Dyn-C 纯离线运动归因审计与修复设计

- verdict: `REDESIGN_READY`
- user_rejected: `true`
- reviewer_approved: `false`
- Dyn-C group status: `user_rejected_no_visible_g1_motion`（不计 dynamic positive）

## 关键事实
- raw centroid(240->310): `27.905`（保留但不单独作为运动证据）
- g1_root_xy_delta_m(240->310): `0.144798`
- ur10e_ee_delta_xyz_m(240->310): `[0.007500112056732178, 0.12246793322265148, -0.26888781785964966]`

## 离线像素归因（ROI对照）
- global_shift(dx,dy): `[0, 0]`
- G1 ROI change fraction: `0.448848`
- UR10 equal-area ROI change fraction: `0.355541`
- control equal-area ROI change fraction: `0.000000`
- visible_g1_local_motion: `False`

## 结论与改造方向
- `task_execution=false` 不等于 UR10 冻结；下一场必须 `freeze_ur10e=true` 并加 action/hash/joint-delta=0 运行时门禁。
- Dyn positive 必须同时满足：G1 实际 root/link 位移 + G1-local pixel 位移（建议 center 40-60px、ROI>=1.2%、相邻稳定、主帧明显变化）。
- 唯一下一步 prebuild：`V1-E2E-prebuild-freeze-ur10e-and-instance-mask-contract`

## UNKNOWN / 证据不足
- phase3_steps.csv does not log exact capture steps (240/310); UR10 stage/action at capture is UNKNOWN.
