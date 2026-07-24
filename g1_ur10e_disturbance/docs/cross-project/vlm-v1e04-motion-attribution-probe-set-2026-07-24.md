# V1-E04 Motion Attribution Probe Set (2026-07-24)

- 用途：**G1 vs UR10e 运动归因**的四象限真值探针集——评估/few-shot/SAM2 tracker 校验专用；
- **不是**训练语料（单相机、单场景、纯合成、样本量小），**不构成** dynamic positive 声称；
- 真值来源：`body_poses.jsonl` 世界位姿 → 相机投影（G1 质心 px）+ UR10e EE 欧氏位移（m）；
- 机器可读清单：`vlm-v1e04-motion-attribution-probe-set-2026-07-24.json`（含全部帧 sha256）。

## 四象限

| 象限 | 帧对 | G1 质心位移 | G1 像素可辨 | UR10e EE 位移 | 标签 |
| --- | --- | --- | --- | --- | --- |
| 仅 G1 | E2K 170→249 | 47.6 px | 是 | 0.000 m | `g1_moving_ur10e_frozen` |
| 仅 UR10e（视觉） | E2D 240→310 | 27.9 px（投影动、像素静） | 否 | 0.296 m | `ur10e_moving_g1_pixel_static` |
| 两者都动 | Dyn-B 220→330 | 23.3 px | 是 | 0.458 m | `g1_slight_motion_with_ur10e_distractor` |
| 都不动 | 3 组稳定对 | <5 px / sha 一致 | 否 | ≈0 | `static_stability_pairs` |

## 重分类记录（用户批准 2026-07-24）

- **E02-DYN-B-M1Z9**：pending_user 审查以重分类方式解决——归入 `slight_motion + motion_attribution`（both_moving 象限），**不计入**干净 dynamic positive；历史 verdict `DYN_B_FORMAL_M1Z9_FAIL_FINAL` 不改写。
- **E02-DYN-C-E2A（E2D 帧对）**：复用为 `ur10e_only_visible` 归因样本；`user_rejected` verdict 不改写。
- **E02-DYN-C-E2K**：登记 `g1_only` 象限（正样本资格不变）。

## 边界

- "仅 UR10e" 象限记录了关键现象：G1 世界坐标在动但渲染像素静止——归因判定必须基于像素可辨运动 + 逐 agent 真值，投影质心单独不构成运动证据（E2D 教训）。
- manifest 同步升级 **v3.4.0**（dynamic 候选清零、新增辅助类别计数）。
