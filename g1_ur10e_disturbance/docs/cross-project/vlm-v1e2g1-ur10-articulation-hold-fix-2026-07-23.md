# V1-E2G.1 UR10 Articulation Hold Fix (Offline)

- status: `offline_fix_implemented_pending_single_rebuild_and_final_preflight`
- policy: 仅离线修复，不重写 E2G raw fail 结论
- baseline contract: `HEAD=101f915`、clean worktree

## 修复点
- UR10 hold 基线改为 `env.unwrapped.scene['robot_ur10e'].data.joint_pos` 实测状态。
- 按 `ARM_JOINT_NAMES(6) + gripper actual(1)` 构造 7 维 `hold_target7`，并记录 `joint_name/joint_id/value` provenance。
- 明确禁止 hold 基线来源为 controller proposed action 或 zero vector。
- hold 采样时机固定为 `env.reset` 完成后、首个 `env.step` 前。
- `joint_delta` 全程相对同一实测基线计算；允许 `settling_window=5 steps`，正式门禁在 settling 后执行 near-zero。

## Analyzer 补充
- 新增 `scripts/v1e2g1_postrun_analyzer.py`，从同步 `body_poses + camera` 离线计算每个 preflight frame：
  - visible links
  - ROI 与 clipping
  - projected actual displacement（像素）与 actual link displacement（米）
- 不依赖 runtime CSV 预先存在 projected/ROI 字段。

## 测试覆盖
- `scripts/test_motion_isolation_unit.py` 新增 fake articulation/real observation fixtures：
  - joint order mapping
  - missing joint fail-closed
  - gripper mapping
  - controller action 不同仍采用 actual articulation
- 新增 `scripts/test_v1e2g1_postrun_analyzer_unit.py`。

## 证据保留
- 保留 E2G raw fail：`docs/cross-project/vlm-v1e2g-dyn-c-motion-preflight-2026-07-23.md`
- 保留并加强 G1 actual movement evidence：通过 body poses 与 postrun projected/actual displacement 联合审计。

## 下一步预算（唯一）
- `1x rebuild` + `1x final motion preflight`
- `0x formal capture`
