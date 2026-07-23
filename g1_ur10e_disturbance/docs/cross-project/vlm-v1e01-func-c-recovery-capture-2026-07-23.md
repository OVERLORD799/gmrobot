# VLM V1E01 Func-C Recovery Capture — 2026-07-23

## 结论
- **Verdict:** `CAPTURE_FAIL`
- 原因：本次仅执行了**一次**正式 `docker run`，仿真产出/帧/geometry 达标，但未能按要求持久化“真实 docker exit/elapsed”（初始包装脚本环境变量未导出；按规则禁止重跑）。
- 是否可进入人工标签审批：**否**（需先补齐一次性运行证据链规范项）。

## 固定身份与基线
- image: `gmdisturb:e01-func-c-m1j-20260723`
- image id(SHA): `sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`
- expected SHA: `sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`
- Created: `2026-07-23T11:58:01.198543397+08:00`
- git HEAD: `7764e300170e2ba898c3aa6e2b7fadaa71c88ead`
- results root: `g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723`（全新目录，未覆盖历史）

## 预检与运行时 safety 快照
- tracked safety config SHA256: `b30f728b32deb528621ef6e552f2306133eba123f946681b0d1aca5a8731fee8`
- USD SHA256:
  - `container.usd`: `ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9`
  - `container_full.usd`: `ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0`
  - `container_full_visual.usd`: `f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e`
- generator 脚本 SHA256: `63226bb47b544e33f2bc5396c200513de0a3ef5df674b6e8cd0ed2bfffaa8fa0`
- runtime safety 快照：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723/meta/runtime_safety_config.yaml`
- diff：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723/meta/runtime_safety_config.diff`（仅 `log_dir` 指向新目录；阈值/trajectory/e01 字段保持不变）
- seed record：`seed=51` 为场景标签；CLI 无 `--seed`，不宣称完整 RNG 闭环。

## 单次运行证明
- command：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723/meta/command.txt`
- stdout/stderr：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723/meta/capture_stdout_stderr.txt`（直接重定向，无 tee/pipe）
- `--entrypoint /isaac-sim/python.sh` 正确；命令参数不重复 `python.sh`。
- mount 仅 results/runtime YAML/cache；未绑定宿主 USD/代码。
- 仅执行一次：是。
- 规范缺口：`docker_exit_code_real_captured=false`，`elapsed_real_captured=false`（禁止重跑）。

## 运行后审计
- 帧完整性（PNG/uint8/480x640x3）：
  - frame 0 SHA256: `76c164f86f325e8c894a273ed354bf80db347a6563276dbb1b863beaa16c023d`
  - frame 100 SHA256: `de9249150255bc43013a7d062cae6b4150dc13ef4b45392bbae3afbab25fc048`
  - frame 200 SHA256: `903e6f4e1874bd0b66ae33457bd67e9625b2985130dee94a4956ce2902ad79e0`
- 视觉检查（读取 100/200）：
  - 白扇形：0（通过）
  - A 箱 + 20 source parts：规整（通过）
  - B 箱尺度/完整性：正常（通过）
  - filled contents：清晰（100/200 均通过）
- safety logs 来自新目录：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723/safety_logs/20260723_040407/episode_0000.csv`
- geometry (step 100..200)：`101/101 ALLOW`，STOP/SLOW/replan = `0/0/0`
- 窗口外事件（单独报告）：`g_rule` 计数 `{'0': 173, '2': 24, '1': 2}`
- 异常扫描：无 Traceback/FileNotFound/DEVICE_LOST/nestedRB；POST=0。
- Xid：`dmesg` 无权限读取；保留 pre/post `nvidia-smi` 快照，未观测到明确 Xid 文本。

## 离线 analyzer
- 命令：`python3 GMRobot/scripts/analyze_e01_func_c_capture.py --results-dir g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723 --assets-dir GMRobot/source/GMRobot/GMRobot/assets`
- exit code: `0`
- 输出：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723/meta/analyzer_stdout.txt`

## 标签约束
- `functional/provisional/reviewer_approved=false` 保持。
- 未宣称 VLM 识别成功。
