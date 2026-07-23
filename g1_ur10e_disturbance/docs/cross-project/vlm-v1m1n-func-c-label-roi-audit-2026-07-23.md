# V1-M1N Func-C 离线人工标注与 ROI 身份审计（2026-07-23）

## 范围与约束
- 目标：对已完成的 `V1-M1M Func-C` 采集结果执行离线身份/ROI 审计，禁止 Docker/Isaac/网络/VLM/SAM2/POST。
- 输入结果目录：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723`
- 历史原始证据保持不变：未改写 `scene/*.png` 与 `safety_logs/**/*.csv`。
- 基线提交：`82d09c0`。

## 审计发现（根因）
- 旧 `target_roi` 为 `[266,203,364,232]`，与右上目标容器几乎不重叠。
- 根因：`v1e01_func_c_capture.py` 复用了 `v1d1b_capture.py` 的经验线性投影 `project_world_to_uv`，该模型忽略 `z` 且针对 D1B 红色代理点拟合，不适用于当前满箱容器语义 ROI。
- 修复：切换为基于 `scene_camera` 固定内参 (`f=18.0`, `h_aperture=20.955`, `640x480`) 与下视相机约定的确定性针孔投影。

## 对象身份映射（A/B/填充内容）
- 场景几何（`gmrobot_env_cfg.py`）：
  - `box_A` 世界位姿中心：`(0.75,-0.25,0.0)`（左侧）
  - `box_B` 世界位姿中心：`(0.75,0.25,0.0)`（右侧）
- Func-C 资产映射（`target_full_override` + `gmrobot_env_cfg`）：
  - 源容器 A：`container_fixed.usd`（空箱语义来源 `container.usd`）
  - 目标容器 B：`container_full_visual.usd`（语义来源 `container_full.usd`，含 Part_* 填充几何）
- 像素证据（frame 100/200）：
  - `source_box_a_roi`（左侧）绿色占比显著高（~0.487）。
  - `target_box_b_roi`（右侧）绿色占比显著低（~0.008~0.012），暗色填充占比高（~0.609~0.617）。
  - `target_identity_evidence.ok=true`（两帧均成立）。

## ROI 更正
- 旧 ROI（manifest）：`[266,203,364,232]`
- 新 ROI（重算，step=100/200 一致）：`[341,80,415,211]`
- 旧/新 IoU（离线核算）：约 `0.017`（几乎不重叠）。
- 填充内容 ROI（新）：`[350,97,407,192]`，且 `filled_inside_target=true`。

## 标签 gate 判定（保守）
- `reviewer_approved=false`（保持关闭，fail-closed）。
- 阻塞项（精确）：
  - 目前仅可离线证明“目标 B 身份 + 填充几何/像素证据 + ROI 对齐正确”；
  - 但“full/unavailable for continued placement”的任务语义仍为 `provisional`，缺少独立人工语义裁决记录，故不提升为 `reviewer_approved=true`。
- 保持：
  - `label_status=provisional`
  - `not_vlm_positive=true`
  - `ready_for_vlm_screen=false`

## 回归防回退
- 新增 `target_identity_evidence` 到每帧记录，并纳入 `visual_gate_ok`。
- 新增离线单测：若 archived M1M 帧存在，则断言目标 ROI 在颜色统计上与 source ROI 可区分（source 更绿、target 更暗、target 在 source 右侧），可拦截 ROI 偏到错误对象的回归。

## 本次改动文件
- `g1_ur10e_disturbance/docker/context/GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py`
- `g1_ur10e_disturbance/docker/context/GMRobot/scripts/test_e01_func_c_capture_unit.py`
- `g1_ur10e_disturbance/docs/cross-project/vlm-v1m1n-func-c-label-roi-audit-2026-07-23.md`
- `g1_ur10e_disturbance/docs/cross-project/vlm-v1m1n-func-c-label-roi-audit-2026-07-23.json`

## 离线测试
- `python g1_ur10e_disturbance/docker/context/GMRobot/scripts/test_e01_func_c_capture_unit.py` → PASS
