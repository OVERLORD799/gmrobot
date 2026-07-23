# V1-M1R Dyn-B Isaac ABI Repair (2026-07-23)

## 结论
- Verdict: `GO_PRECHECK_ONLY`
- Root cause 已可证明：`M1Q` 命令在挂载宿主缓存后触发 Isaac 扩展的 NumPy 路径混装，`numpy 2.4.6`（`/isaac-sim/kit/python/lib/.../site-packages`）与 `omni.kit.pip_archive` 预打包 `numpy 1.26.0` 发生 ABI/符号冲突，出现 `broadcast_to` 导入异常与 `numpy.dtype size changed`。
- 修复策略采用**调用/环境纠偏**（不改镜像内包版本）：在运行前显式注入 `omni.usd.libs` 与 `omni.kit.pip_archive` 到 `PYTHONPATH/LD_LIBRARY_PATH`，并新增 fail-fast 导入预检。

## M1M vs M1Q 关键差异与证据
- M1M 成功命令：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723/meta/command.txt`
- M1Q 失败命令：`g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/formal_command.txt`
- M1Q 失败日志：`g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1q_20260723/meta/capture_stderr.txt`
  - 命中：`cannot import name 'broadcast_to' from 'numpy.lib.stride_tricks'`
  - 命中：`ValueError: numpy.dtype size changed, may indicate binary incompatibility`
- M1M 不触发 Dyn-B 的 `run_phase3` 导入链；M1Q 直接走 `run_phase3`，触发了 Isaac 扩展与 NumPy 混装路径问题。

## 代码修复
- 新增导入预检：`g1_ur10e_disturbance/scripts/isaac_abi_import_preflight.py`
  - 打印并落盘模块版本/来源：`numpy`、`numpy.random`、`gymnasium`、`torch`、`isaaclab.app`、`AppLauncher`
  - 任一导入失败立即非零退出。
- 新增环境守卫构造：`g1_ur10e_disturbance/e01_dyn_b_runtime_guard.py`
  - 统一生成 `PYTHONPATH/LD_LIBRARY_PATH` 防护前缀（`omni.usd.libs` + `omni.kit.pip_archive`）。
- 新增一键预检 runner：`g1_ur10e_disturbance/scripts/run_e01_dyn_b_abi_preflight.sh`
  - 通过 `capture_one_shot_runner.py` 执行容器预检，禁止 `Traceback`/ABI 关键词，并强制产出报告文件。
- 强化 runner 非零门禁：`GMRobot/scripts/capture_one_shot_runner.py`
  - 新增 `--forbid-pattern`、`--require-path`；
  - 即使子命令 `exit=0`，若命中禁用模式或缺失必需产物，runner 强制 `exit=86`。

## 离线回归测试
- `python3 GMRobot/scripts/test_capture_one_shot_runner_unit.py` ✅
- `python3 g1_ur10e_disturbance/scripts/test_e01_dyn_b_offline_readiness_unit.py` ✅
- `python3 g1_ur10e_disturbance/scripts/test_e01_dyn_b_runtime_guard_unit.py` ✅

## 最小 smoke（POST=0，无正式采集）
- Smoke count: **1**（M1R 最终验收计数）
- 命令：`bash g1_ur10e_disturbance/scripts/run_e01_dyn_b_abi_preflight.sh`
- 结果：
  - `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1r_20260723/meta/run_status.json` -> `exit_code=0`
  - `.../meta/import_preflight_report.json` 存在且全部模块 `status=ok`
  - `forbid_pattern_hits=[]`，`missing_required_paths=[]`

## 镜像身份
- 使用镜像：`gmdisturb:e01-func-c-m1j-20260723`
- Image ID：`sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`
- 新镜像构建：`false`（无需构建 `gmdisturb:e01-dyn-b-m1r-20260723`）

## 新编号 one-shot preflight 建议
- Next milestone: `V1-M1S`
- GO/NO_GO: **GO**
- 约束：仅允许 one-shot 预检；若出现 `Traceback`/ABI 异常或必需产物缺失，按 runner 门禁直接判失败，不得以 `exit=0` 通过。
