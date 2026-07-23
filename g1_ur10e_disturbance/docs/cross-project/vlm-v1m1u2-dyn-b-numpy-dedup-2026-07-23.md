# V1-M1U2 Dyn-B NumPy 定向去重（2026-07-23）

## Verdict

**NUMPY_DEDUP_FAIL_STOP**

- 构建次数：`1/1`（已用尽）
- full AppLauncher one-step smoke：`0/1`（未执行）
- 原因：唯一一次 build 在 Dockerfile `RUN` 阶段失败（`/bin/sh` 不支持 `set -o pipefail`），新镜像未生成，无法在“不重试 build”的约束下继续 AppLauncher smoke。

## 本次实现（代码层）

- 新增镜像定义：`g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u2`
  - 保留 `pip_prebundle`，仅定向隔离 `numpy`、`numpy.libs`、`numpy-*.dist-info`
  - 设计为构建期落盘：
    - inventory
    - hashes
    - quarantine report
  - 并断言：
    - Kit NumPy 与 `numpy.random` 编译模块存在且来自 Kit site-packages
    - pip_prebundle 下不再存在可导入 NumPy 变体
- 新增脚本：`g1_ur10e_disturbance/scripts/pip_prebundle_numpy_dedup.py`
  - 先盘点再隔离，支持 symlink 记录与哈希
  - 仅匹配 NumPy 目标，不触碰其他 prebundle 包
- 更新 guard：`g1_ur10e_disturbance/scripts/numpy_abi_guard.py`
  - 不再全局移除 `pip_prebundle` 路径
  - 改为仅上报冲突路径并做来源一致性校验
- 更新运行态标识：`g1_ur10e_disturbance/e01_dyn_b_runtime_guard.py`
  - 切换到 `M1U2` tag / Dockerfile / bake 文件列表

## 离线测试

- `scripts/test_numpy_abi_guard_unit.py`：PASS
- `scripts/test_e01_dyn_b_runtime_guard_unit.py`：PASS
- `scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`：PASS（覆盖 M1U2 常量）
- `scripts/test_pip_prebundle_numpy_dedup_unit.py`：PASS（验证仅影响 NumPy 族）
- `GMRobot/scripts/test_capture_one_shot_runner_unit.py`：PASS

## 运行证据目录

`g1_ur10e_disturbance/results/paper_demo/v1m1u2_dyn_b_numpy_dedup_smoke_20260723/meta/`

- `build_attempt_command.txt`
- `smoke_planned_command.txt`
- `static_inspection.txt`
- `execution_report.json`

## 关键事实

- image tag：`gmdisturb:e01-dyn-b-m1u2-20260723`
- image SHA：未生成（构建失败）
- 实际隔离路径：未生成（构建未完成，quarantine 报告未落盘）
- NumPy origin pre/post：未生成（未执行 AppLauncher smoke）
- GPU：`NVIDIA GeForce RTX 5090 Laptop GPU`，driver `580.159.03`
- Xid：`dmesg` 读取受限，无法在当前权限下确认

## Next Gate

`BUILD_AND_APP_LAUNCHER_SMOKE_REQUIRED`
