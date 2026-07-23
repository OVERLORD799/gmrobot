# V1-M1F6 Func-C 左箱遮挡根因修复（2026-07-23）

## 前置核验
- HEAD: `24b807f`（匹配要求）
- worktree: `clean`（开始时无未提交修改）

## 根因判定（已证实，不是猜测）
- `GMRobot/.../gmrobot_env_cfg.py` 中 `PART_LOCATIONS` 默认是 `A@1..A@20`，`build_part_assets()` 会生成 `Part_1..Part_20` 并挂到 `{ENV_REGEX_NS}/Part_*`。
- 同文件 `build_container_grid_assets()` 同时生成左箱 `ContainerA` 与 `GridA`，因此默认场景里左箱与 20 个任务件共存。
- 历史运行 `.../v1e01_func_c_reference_bin_smoke_m1f5_20260723/meta/smoke_stdout.txt` 的 Observation 列表明确包含 `part_1_pos..part_20_pos`，证明 M1F5 渲染路径确实加载了 20 个任务件。
- 新增离线投影审计 `audit_source_bin_task_part_occlusion()`：将 20 个 `A@slot` 世界坐标投影到相机平面后，`20/20` 落在 `source_roi_aabb=[224,80,298,211]` 内，`occlusion_possible=true`。
- 结论：白色矩形/顶部重复件由任务件（`Part_*` / `part_fixed`）覆盖左侧 `ContainerA/GridA` 视觉导致；`verdict != OCCLUSION_ROOT_CAUSE_BLOCKED`。

## 参考 Dyn-B 对照（含/不含任务件）
- `g1_ur10e_disturbance/dual_env_cfg.py` 同样定义 `PART_LOCATIONS=A@1..A@20` 与 `build_part_assets()`，默认 Dyn-B 也包含这 20 个任务件。
- Dyn-B 参考帧 `frame_000330_env0` 属于该配置族，未发现“禁用任务件”的专门分支。

## 实施改动（仅显式 opt-in）
- 新增显式模式：`GMROBOT_V1E01_VISUAL_ONLY=1`（默认关闭）。
- 新增门禁：visual-only 必须同时满足 `GMROBOT_V1E01_TARGET_FULL=1` 且 `GMROBOT_V1D1B_FUNCTIONAL_BLOCK!=1`；否则启动即 fail-fast。
- visual-only 模式下：
  - `task_execution=false`
  - `visual_dataset_only=true`
  - `spawn_task_parts=false`（禁止生成/显示/碰撞 20 个任务件）
- 左侧保持 canonical `container.usd + GridA`；右侧保持 `container_full_visual.usd`；未采用相机裁剪/箱体隐藏/材质覆盖。
- 默认 GMRobot 任务路径与 B0-B4 行为不变。

## 静态测试与门禁
- `GMRobot/scripts/test_e01_func_c_capture_unit.py`：
  - 默认仍 20 parts；
  - `target_full` 且非 visual-only 仍原行为；
  - visual-only 时 `spawn_task_parts=false`，并校验 `task_execution=false/visual_dataset_only=true`；
  - 新增 `audit_source_bin_task_part_occlusion()` 投影/AABB 审计（20/20 命中 source ROI）。
- `g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py` 与对应单测：
  - 新增合法状态 `visual_rework_parts_occlusion_fix_pending`；
  - 保持 `formal_recapture_allowed=false`、`reviewer_approved=false` 约束。

## Manifest 记录更新
- `vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json`：
  - Func-C `technical_review_status=visual_rework_parts_occlusion_fix_pending`
  - `formal_recapture_allowed=false`
  - 记录 `m1f5_user_rejected=true`

## 本次离线验证
- `python3 GMRobot/scripts/test_e01_func_c_capture_unit.py` PASS
- `python3 g1_ur10e_disturbance/scripts/test_v1e02_dataset_candidate_manifest_unit.py` PASS
- `python3 -m py_compile ...` PASS
- `python3 g1_ur10e_disturbance/scripts/validate_v1e02_dataset_candidate_manifest.py --manifest ...` PASS
- `git diff --check` PASS
- 敏感信息扫描（改动文件）无命中

## 下一步约束
- 仅允许 `source-only build + 1 次 visual smoke`，`formal_recapture=false`。
