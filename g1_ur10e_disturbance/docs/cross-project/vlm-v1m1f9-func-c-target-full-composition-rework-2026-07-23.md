# V1-M1F9 Func-C TARGET_FULL 视觉组合重构（2026-07-23）

## 前置与范围
- 仓库前置：`HEAD=c1bdc60cac0a0417c1436adbfd8fcd558d4d37a3`，`git status --porcelain` 为空（clean）。
- 执行约束：纯离线；未执行 Docker/Isaac/build/capture/network/POST。
- 作用域：仅 `GMROBOT_V1E01_TARGET_FULL=1` + `GMROBOT_V1E01_VISUAL_ONLY=1` 组合模式；默认任务与 B0-B4 不变。

## 左右映射与错误结论撤回（源码证据）
- 相机位姿固定：`pos=(0.35,0.0,2.5)`，`rot=(0.7071,0.0,0.7071,0.0)`。
- world-to-image 映射修正：`u` 轴与 `-world_y` 同向（此前“+world_y”注释与推断错误，已撤回）。
- `ContainerA(0.75,-0.25,0)` 投影 `u≈374.97`，`ContainerB(0.75,0.25,0)` 投影 `u≈265.03`，因此屏幕左侧对应 `ContainerB`。
- ROI 几何映射：`source_box_a_roi.centroid_uv=[378.0,145.5]`，`target_box_b_roi.centroid_uv=[261.0,145.5]`，满足 `B 在 A 左侧`。

## M1F8 左白物归因交叉验证
- 代码归因链：在 `TARGET_FULL=1`（且非 visual-only）时，`box_B -> container_full_visual.usd`；异常白物只可能来自 `ContainerB` 路径。
- M1D 证据交叉：`hide ContainerB` 后白扇/白块异常消失（`m1d-asset-isolation-2026-07-23.md` 既有结论）。
- 结论：撤回“左侧是 source A”的旧结论；M1F8 左侧白异常归因于 `ContainerB/container_full_visual.usd`。

## M1F9 实施：visual-only 组合重构
- `box_A` 与 `box_B` 在 `TARGET_FULL+VISUAL_ONLY` 下均使用 canonical `container.usd`（同材质/scale/orientation）。
- `GridA` 与 `GridB` 均保留，同一 divider，不再跳过 `grid_B`。
- 新增独立 content-only payload：`container_full_content_visual.usd`，以 `filled_content_B` 挂载到 B。
- `container_full_visual.usd` 不再作为 `box_B` 壳体（仅保留历史/兼容语义路径用途）。

## content-only 资产门禁（离线）
- 生成方式：确定性生成器 `GMRobot/scripts/generate_container_full_content_visual_usd.py`，冻结源 `part_5000.usd` SHA=`71fd48...91aa6`。
- 输出资产：`GMRobot/source/GMRobot/GMRobot/assets/container_full_content_visual.usd`。
- 输出 SHA：`5ca656f996c783c0ab9717cae265c8461054d98bd487b08d9b5770f3bb36f935`。
- 结构约束满足：仅 `FilledContent_00..19`（20 个），无 `Part_*`，无容器壳 prim，无 physics/collision/rigid body/mass，slot 坐标与 5x4/20 槽严格匹配。

## Runtime Assertions 与断言缺失根因
- 断言预期已更新为：
  - `box_A_usd` 末尾 `container.usd`
  - `box_B_usd` 末尾 `container.usd`
  - `grid_A/grid_B/filled_content_B` 全存在
  - `filled_content_stage == 20`
  - `part_count_cfg == 0` 且 `part_count_stage == 0`
- M1F8 断言缺失根因（源码可确认，未运行）：
  - `gm_state_machine_agent.py` 仅在 `GMROBOT_RUNTIME_SCENE_ASSERTIONS_PATH` 存在且 `TARGET_FULL=1`、`VISUAL_ONLY=1` 同时满足时才落盘；
  - 缺任一条件即不会产生 `runtime_scene_assertions.json`。

## 记录字段（按要求）
- `user_rejected_visual=true`（M1F8 人工结论保留，即使自动门禁失败）。
- `manifest_status=target_full_composition_rework_pending`。
- `formal_recapture_required=false`（本次仅代码与离线门禁重构，不触发正式重采集）。

## 离线检查结果
- `python3 -m py_compile ...`：PASS
- `python3 GMRobot/scripts/test_generate_container_full_content_visual_usd_unit.py`：PASS
- `python3 GMRobot/scripts/test_runtime_scene_assertions_unit.py`：PASS
- `python3 GMRobot/scripts/test_e01_func_c_capture_unit.py`：PASS
