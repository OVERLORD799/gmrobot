# V1-M1P E01-Dyn-B 离线就绪（2026-07-23）

## 结论

- Verdict: **GO_PRECHECK_ONLY**
- 适用范围：仅针对 **单次 0-POST preflight capture** 的离线放行，不执行采集。
- 本里程碑保持默认关闭：未运行 Docker/Isaac/network/VLM/SAM2/POST。

## 设计边界与来源标注

- 场景：`E01-Dyn-B`
- 脚本：`outer_lateral_patrol`（显式、确定性）
- 种子：`43`
- 运动来源标签：`scripted_g1_outer_lateral_patrol`
- 证据性质：`synthetic_scripted_motion_evidence`
- 明确排除：非 human-hand/PPE、非 VLM 输出、无 red-ball proxy

## 采帧选择（仅设计，不执行）

- 预选采帧步：`220` 与 `330`
- 相位：`lateral_positive_sweep` 与 `lateral_negative_sweep`
- 两步均在移动相位内（非 stand）
- 预测质心位移：`51.29 px`（门限 `>=20 px`）

## 几何/就绪预检（保守 fail-closed）

- 预检窗口：`190..340`
- UR10e 保守包络模型：
  - center `(0.75, 0.0)`
  - UR10e 半径 `0.55 m`
  - G1 体包络半径 `0.35 m`
  - 轨迹不确定性 `0.10 m`
- 窗内最小分离裕量：`0.2767 m`
- 预检要求最小裕量：`0.10 m`
- 判定：通过（若窗口与安全包络发生可疑相交或相位不明确，则直接 NO_GO）

## 相机可见性假设

- Pose（仅 override 开启时生效）：`pos=(0.2,0.0,3.2)`，`rot=(0.7071,0,0.7071,0)`
- 默认行为不变：override 默认关闭
- 预选两步的可见性假设检查通过（G1 保持可观察）

## 单次 0-POST preflight 提议（不执行）

- 建议命令（精确）：
  - `GMDISTURB_SCENE_CAMERA_OVERRIDE=1 GMDISTURB_SCENE_CAMERA_POS=0.2,0.0,3.2 GMDISTURB_SCENE_CAMERA_ROT=0.7071,0.0,0.7071,0.0 /isaac-sim/python.sh scripts/run_phase3.py --headless --seed 43 --scenario outer_lateral_patrol --max_steps 420 --progress_interval 1 --motion_source_label scripted_g1_outer_lateral_patrol --save_camera --camera_output_dir results/paper_demo/v1e01_dyn_b_preflight_20260723/scene --camera_save_steps 220,330 --camera_pose_json results/paper_demo/v1e01_dyn_b_preflight_20260723/meta/camera_pose.json --body_pose_jsonl results/paper_demo/v1e01_dyn_b_preflight_20260723/meta/body_poses.jsonl --output_csv results/paper_demo/v1e01_dyn_b_preflight_20260723/safety_logs/phase3.csv`
- 结果目录策略：
  - `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_20260723/`
- 图像策略：
  - 只取 `scene/frame_000220_env0.png` 和 `scene/frame_000330_env0.png`
  - 必须满足：两步 ALLOW、窗口无 STOP/SLOW/replan、位移达标、证据链无 red proxy

## 默认关闭与冻结约束核对

- `enable_capture=false` 且 `execute_capture=false`（guard 通过）
- 未修改安全阈值
- 未改动 B0-B4 配置/资产/结果
- 未改动历史采集结果
- 未改变 canonical benchmark 行为

## 本里程碑离线测试

- `python3 g1_ur10e_disturbance/scripts/test_e01_dyn_b_offline_readiness_unit.py` 通过
- `python3 g1_ur10e_disturbance/scripts/test_e01_dyn_a_capture_unit.py` 通过

