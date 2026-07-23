# V1-M1U0 Dyn-B 独立镜像 + full AppLauncher smoke（2026-07-23）

## Verdict

**FULL_APP_LAUNCHER_SMOKE_FAIL**

`next_gate=STOP_NO_CAPTURE`

- build 次数：**1**
- smoke 次数：**1**（失败，**不重试**）
- 正式 Dyn-B capture：**未执行**
- M1Q / M1S / M1T 历史 FAIL 结果目录：**未覆盖**

---

## 基线

| 项 | 值 |
|---|---|
| HEAD（启动时） | `fb28e37c98e72a44f607211b1dc8becef7ab4088` |
| origin/main | 同步 |
| M1T | `STOP_DYN_B_RUNTIME_LOOP` |

---

## Build

| 项 | 值 |
|---|---|
| tag | `gmdisturb:e01-dyn-b-m1u0-20260723` |
| image SHA | `sha256:19196c23cbaf754865e77936198e432c69fffad3f783c81e79471d45b9e3a96c` |
| Created | `2026-07-23T13:21:28.738344282+08:00` |
| Dockerfile | `g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-b-m1u0` |
| base（未覆盖） | `gmdisturb:e01-func-c-m1j-20260723` / `sha256:c3fd8087…` |
| build exit / elapsed | **0** / **1** s |
| 未覆盖 | `defe95e7` / `f81e59ce` / `c3fd8087` |

### Build context 关键源码 SHA（bake 后镜像内一致）

| 文件 | SHA256 |
|---|---|
| `scripts/run_phase3.py` | `c1bea236d1f5cdcc100f94452df78ba81e9522ba8eb5235a497635e230f31be9` |
| `g1_disturbance_controller.py` | `4415fa7f5938c7f9c35db8cef61e7d87f3926efa0521847d20401b9023a19695` |
| `e01_dyn_b_runtime_guard.py` | `3947554a996d0273a4f5f73284cd00c84a4ae17d8f3aa3127965ea1ebc113b81` |
| `configs/e01_dyn_b_capture.yaml` | `3bc416dfd795e8f80dc27755620587248307d7ecff3bddd98d791dcdd9aaf729` |

### 静态核验（无 Isaac）

- `run_phase3.py` argparse choices **包含** `outer_lateral_patrol`
- controller / config 含 `outer_lateral_patrol` / `scripted_g1_outer_lateral_patrol`
- guard **无** `pip_prebundle` / `PYTHONPATH` 强制注入
- 结论：非 `IMAGE_CODE_STALE`

---

## Smoke（唯一一次）

路径：`docker/run.sh` + 镜像默认 ENTRYPOINT + baked source（**未** bind-mount 宿主机代码；仅 results/cache）。

Runner：`GMRobot/scripts/capture_one_shot_runner.py`

| 项 | 值 |
|---|---|
| runner exit | **86**（postcheck fail-closed） |
| returncode_raw | 0（容器进程返回码；日志含失败） |
| elapsed_monotonic_sec | **15.954** |
| AppLauncher | 已启动（`Using device: cuda:0`；开始加载 experience） |
| simulation step | **未完成**（gymnasium/numpy ABI 在 import 阶段失败） |
| `outer_lateral_patrol` parser | **已接受**（未再出现 `invalid choice`） |
| smoke CSV | **缺失** |
| POST | **0** |
| 新 Xid | **无**（before/after count=0） |
| 残留 container | **无** |

### NumPy / numpy.random 来源

预检写入 `meta/numpy_origin.json`（phase3 启动前）：

- `numpy_file`: `/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/__init__.py`
- `numpy_random_file`: `/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/random/__init__.py`
- `numpy_version`: `2.4.6`

AppLauncher 扩展加载后实际失败栈显示混装：

- `numpy` 解析自 kit site-packages
- `numpy.random` 落入 `…/omni.kit.pip_archive…/pip_prebundle/numpy/random/…`
- 错误：`numpy.dtype size changed` / `cannot import name 'broadcast_to'`（forbid 命中） / `Failed to startup python extension`

本轮**未**注入 `pip_prebundle` PYTHONPATH；混装来自镜像/Kit 扩展加载路径。

### forbid / require

命中：`Traceback`、`numpy.dtype size changed`、`cannot import name 'broadcast_to'`、`Failed to startup python extension`  
缺失：`safety_logs/phase3.csv`

---

## 测试

| 测试 | 结果 |
|---|---|
| `test_e01_dyn_b_runtime_guard_unit.py` | PASS |
| `test_e01_dyn_b_offline_readiness_unit.py` | PASS |
| `test_e01_dyn_b_m1u0_image_bake_unit.py` | PASS（bake 含 outer_lateral；canonical 无代码 mount；禁 pip_prebundle；无网络模型） |
| `test_capture_one_shot_runner_unit.py` | PASS |

---

## 历史 FAIL 未覆盖

- `results/paper_demo/v1m1t_smoke_20260723/` 保留
- `results/paper_demo/v1m1t_smoke2_20260723/` 保留
- 新结果仅写入：`results/paper_demo/v1m1u0_dyn_b_image_smoke_20260723/`（**不提交**）

---

## 是否允许申请下一次正式 Dyn-B preflight

**否。** `FULL_APP_LAUNCHER_SMOKE_FAIL` → `STOP_NO_CAPTURE`。需另行授权修复镜像内 NumPy/Kit 混装或启动路径后，再开新里程碑。

即使本里程碑已 bake `outer_lateral_patrol`，**不得**自行执行 Dyn-B 正式采集。

---

## 结果路径

`g1_ur10e_disturbance/results/paper_demo/v1m1u0_dyn_b_image_smoke_20260723/`
