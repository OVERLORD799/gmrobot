# V1-M1U1 Dyn-B NumPy ABI remediation（2026-07-23）

## Verdict

**ABI_REMEDIATION_FAIL_STOP**

- build 次数：**1/1**
- full AppLauncher smoke 次数：**1/1**（失败，不重试）
- 正式 Dyn-B capture：**未执行（且不授权）**
- next_gate：**NO_CAPTURE_AUTHORIZATION**

## 根因证据（静态 + 运行）

- `run_phase3` 在 AppLauncher 创建前，`numpy` 与 `numpy.random` 均来自 kit site-packages，且为单根。
- AppLauncher 初始化后，`numpy` 仍指向 kit，但 `sys.modules` 中出现大量 `numpy.*` 子模块来自 `omni.kit.pip_archive/.../pip_prebundle`，形成混合命名空间。
- 新增不变量在 `after_app_launcher` 阶段 fail-fast（非零退出），阻断进入后续 Dyn-B 捕获流程。

## 本次修复（已入镜像）

- 新增 `scripts/numpy_abi_guard.py`：
  - 清理 `sys.path` 中 `pip_prebundle`/`omni.kit.pip_archive` 路径；
  - AppLauncher 前 eager import `numpy.random`、`numpy.lib.recfunctions`、`numpy.ma`、`numpy.testing`；
  - 记录并校验 `numpy`/`numpy.random` 文件与规范化根路径；
  - AppLauncher 后再次校验所有已加载 `numpy.*` 模块必须同根，否则立即失败。
- `scripts/run_phase3.py` 接入双阶段 guard：
  - `--numpy-origin-pre-json`
  - `--numpy-origin-post-json`
- `e01_dyn_b_runtime_guard.py` 更新到 M1U1 镜像与 canonical smoke 命令构造。

## 镜像与静态核验

- image tag：`gmdisturb:e01-dyn-b-m1u1-20260723`
- image SHA：`sha256:195b141daa0ba6935f8409da3f46781925b98eeca4a4ac2993ea4de474e700c9`
- Dockerfile：`g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u1`
- 静态核验文件：`results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/image_bake_static_check.txt`
  - 含 `outer_lateral_patrol`
  - 含 `verify_numpy_single_root` 与 `--numpy-origin-pre-json/--numpy-origin-post-json`

## 唯一一次 canonical full AppLauncher smoke

- runner：`GMRobot/scripts/capture_one_shot_runner.py`
- 入口：`g1_ur10e_disturbance/docker/run.sh`
- seed/scenario：`--seed 43 --scenario outer_lateral_patrol`
- 精确内层命令见：`results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/smoke_inner_command.sh.txt`
- 退出：
  - runner exit: `86`
  - elapsed: `18.095590358s`
  - forbid 命中：`Traceback (most recent call last):`
  - 必需产物缺失：`safety_logs/phase3.csv`（未产生）

## NumPy origins（前/后）

- pre: `results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/numpy_origin_pre.json`
  - `numpy_file`: `/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/__init__.py`
  - `numpy_random_file`: `/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/random/__init__.py`
  - `normalized_roots`: 单根（kit）
- post: `results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/numpy_origin_post.json`
  - `normalized_roots`: 双根（kit + `.../pip_prebundle`）
  - 触发 `NUMPY_ABI_GUARD_FAIL`

## GPU / Xid（前后）

- pre: `results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/gpu_pre.txt`
- post: `results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/gpu_post.txt`
- Xid 日志：
  - pre: `results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/xid_pre.txt`（空）
  - post: `results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/meta/xid_post.txt`（空）
  - 结论：本次未观察到新增 Xid / DEVICE_LOST

## 离线测试

- `g1_ur10e_disturbance/scripts/test_numpy_abi_guard_unit.py`：PASS
- `g1_ur10e_disturbance/scripts/test_e01_dyn_b_runtime_guard_unit.py`：PASS
- `g1_ur10e_disturbance/scripts/test_e01_dyn_b_m1u0_image_bake_unit.py`：PASS
- `GMRobot/scripts/test_capture_one_shot_runner_unit.py`：PASS

## 结果目录

`g1_ur10e_disturbance/results/paper_demo/v1m1u1_dyn_b_abi_smoke_20260723/`
