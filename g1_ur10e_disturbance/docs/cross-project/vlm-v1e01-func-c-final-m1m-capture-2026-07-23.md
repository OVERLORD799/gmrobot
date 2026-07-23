# V1-E01 Func-C Final M1M Capture - 2026-07-23

## 结论
- Verdict: `CAPTURE_PASS_PROVISIONAL_FUNCTIONAL_FINAL`
- 本次严格执行单次正式捕获：通过 `GMRobot/scripts/capture_one_shot_runner.py` 执行 **1 条** Docker/Isaac 命令，无重跑。
- 显式保留历史失败：`5fdc79a` 仍为失败记录，未覆盖未改写。

## 固定镜像与基线
- 镜像：`gmdisturb:e01-func-c-m1j-20260723`
- 镜像 ID：`sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`（与要求 `sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248` 一致）
- 运行器基线：`1078cdf`（hardened runner）
- 固定资产基线：`cff7bbe`

## 预检与配置快照
- 结果目录（新建）：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723/`
- runtime safety YAML：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723/meta/runtime_safety_config.yaml`
- 配置 diff：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723/meta/runtime_safety_config.diff`
- 结论：仅 `log_dir` 改为新结果目录，其他字段保持 canonical 不变。
- 预检元数据：image/git/seed/GPU/Xid 均已保存于 `meta/`。

## 单次运行证明（Runner 状态）
- `phase=finished`
- `exit_code=0`
- `elapsed_monotonic_sec=51.960305059`
- `start_time_utc=2026-07-23T04:15:25.557+00:00`
- `end_time_utc=2026-07-23T04:16:17.517+00:00`
- 证明链文件：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723/meta/run_status.json`

## 帧与哈希（Scene RGB）
- step 0: `dc3a5449ce7b65a56e615f20ef54f4717400dd8fae4779ff16bcd37e02e07d41`
- step 100: `8da7319646faf76734624fd8b2453e3b0a0eea13b903ff5eeaf26d3531e96d80`
- step 200: `37baa81ff93ece84dd2a7cc13a11b65837e56876bd7eff83101a1cff84698051`
- PNG 形状审计：`480x640x3`, `uint8`（见 `meta/post_audit_summary.json`）

## 安全与日志门禁
- POST 期望值：`0`；实测：`0`
- geometry window `100..200`：`rows=101`, `ALLOW=101`, `STOP=0`, `SLOW=0`, `replan=0`
- 满足要求：窗口内恰好 101 行，且 `ALLOW=101`、`STOP/SLOW/replan=0/0/0`
- 异常扫描：Traceback/FileNotFound/DEVICE_LOST/nestedRB 均未命中。

## 修复后满箱视觉伪影检查
- 白扇形伪影：未见（自动检查通过）
- `containerB` 满箱内容在目标 ROI 内：step100/200 均为 true
- `filled_content_rgb_evidence.ok`：step100/200 均为 true
- 结论：repaired full bin visual artifact checks 通过（见 `manifest/capture_manifest.json`）

## 离线分析器
- 命令：`python3 GMRobot/scripts/analyze_e01_func_c_capture.py --results-dir g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723 --assets-dir GMRobot/source/GMRobot/GMRobot/assets`
- exit code：`0`
- 输出：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723/meta/analyzer_stdout.txt`

## 标签约束
- 保持 `functional/provisional/reviewer_approved=false`
- 未宣称 VLM 成功；未运行 VLM/SAM2/Dyn-B。
