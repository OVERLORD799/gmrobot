# V1-M1Q E01-Dyn-B Runtime Preflight (2026-07-23)

## 结论
- Verdict: **DYN_B_PREFLIGHT_CAPTURE_FAIL**
- Formal run count: **1**（严格单次，无重跑）
- 核心失败原因：运行时 Isaac/NumPy 二进制不兼容，导致无有效采集产物（缺失 step 220/330 帧与 safety CSV）。

## 运行身份与约束
- Base commit（要求）: `679d1bc`
- Run HEAD: `679d1bc`
- Image: `gmdisturb:e01-func-c-m1j-20260723`
- Image ID: `sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`
- New image built: `false`
- Smoke count: `0`（M1P 未强制）
- POST target: `0`（未启用 VLM/perception/five-stage/SAM2/red-ball/proxy）

## 预检与单测
- 已通过：
  - `python3 g1_ur10e_disturbance/scripts/test_e01_dyn_b_offline_readiness_unit.py`
  - `python3 g1_ur10e_disturbance/scripts/test_e01_dyn_a_capture_unit.py`
  - `python3 GMRobot/scripts/test_capture_one_shot_runner_unit.py`
- 运行前已核验结果目录初始不存在。
- 运行时配置包含 `motion_source: scripted_g1_outer_lateral_patrol`。
- 运行前修复：`run_phase3.py` 的 `--scenario` choices 加入 `outer_lateral_patrol`。

## 单次正式运行
- Runner: `GMRobot/scripts/capture_one_shot_runner.py`
- Runner exit: `0`
- Runner elapsed: `16.225717977` s
- 原子状态文件：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/run_status.json`
- 正式命令：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/formal_command.txt`

## 审计结果
- Required frames: `scene/frame_000220_env0.png`, `scene/frame_000330_env0.png` -> **missing/missing**
- Safety CSV: `safety_logs/phase3.csv` -> **missing**
- G1 ROI 可见性：**N/A（帧缺失）**
- 220/330 质心位移：**N/A（帧缺失）**
- Geometry window `190..340` 全 ALLOW 且 0 STOP/SLOW/replan：**N/A（CSV 缺失）**
- 错误扫描：Traceback=`true`，DEVICE_LOST=`false`，POST 关键词=`false`，NumPy ABI 异常=`true`

## GPU/Xid
- Pre: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/gpu_xid_pre.txt`
- Post: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/gpu_xid_post.txt`
- Diff: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/gpu_xid_pre_post.diff`

## 标签声明
- `dynamic=true`
- `provisional=true`
- `reviewer_approved=false`
- `scripted provenance=true`
- `vlm claim=false`

## 下一里程碑建议
- **V1-M1R**：修复 Isaac 容器内 NumPy/扩展 ABI 冲突（确保 `run_phase3` 可生成帧与 safety CSV），随后按同一协议重新申请单次 preflight。
