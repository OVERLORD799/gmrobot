# V1-M1V Dyn-B 干净物理基准重建（2026-07-23）

## Verdict

**CLEAN_BASE_APP_LAUNCHER_FAIL**

`next_gate=STOP_NO_CAPTURE`

- build 次数：**1**（成功）
- smoke 次数：**1**（失败，**不重试**）
- package mutation：**无**（无 pip/conda/apt；无 NumPy quarantine）
- 正式 Dyn-B capture：**未执行**
- 历史 M1Q–M1U2.3 FAIL 目录：**未覆盖**

---

## 基线

| 项 | 值 |
|---|---|
| HEAD（启动） | `510761fd221d037b191c4bedf4736108e805e39d` |
| origin/main | 同步 |
| M1U2.3 | `NUMPY_DEDUP_FAIL_FINAL_STOP`（不继承其依赖改动） |

---

## A. 基础镜像审计（只读）

| 项 | `gmdisturb:b4-p010-20260721` |
|---|---|
| image SHA | `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68` |
| numpy | `…/pip_prebundle/numpy` **1.26.0** |
| numpy.random | 同根 `pip_prebundle` |
| typing_extensions | kit `typing_extensions.py`；**ParamSpec=true** |
| torch / gymnasium / isaaclab | 均存在 |

对比 broken M1U2.3（`sha256:8b70b0b1…`）：曾 quarantine prebundle NumPy，改用 kit NumPy；smoke 再卡在 ParamSpec 扩展加载链。M1V **不继承**该依赖层，仅从 B4 复制 Dyn-B 源码。

---

## B–D. Dockerfile / 测试 / Build

| 项 | 值 |
|---|---|
| Dockerfile | `docker/Dockerfile.e01-dyn-b-clean-m1v` |
| FROM | `gmdisturb:b4-p010-20260721` |
| mutation | 无 pip/conda/apt；无 site-packages COPY；无 quarantine |
| tag | `gmdisturb:e01-dyn-b-clean-m1v-20260723` |
| new image SHA | `sha256:1c75ea8a6e247bb49f75e65c701c545a38e9e1530bea955801d5b3a4532127d9` |
| Created | `2026-07-23T14:10:14.557281565+08:00` |
| build exit / elapsed | **0** / **2** s |
| 未覆盖历史镜像 | `defe95e7` / `f81e59ce` / `c3fd8087` / `19196c23` / `8b70b0b1` 等 |

离线测试（build 前）：`test_e01_dyn_b_m1v_clean_runtime_unit` / runtime_guard / offline_readiness / m1u0 bake / numpy_abi_guard / capture_one_shot_runner — **全部 PASS**。

### 复制源码 SHA（镜像内一致）

| 文件 | SHA256 |
|---|---|
| `scripts/run_phase3.py` | `1c35245ef87a7055fec4276932219973d07be6cdd3b79b9205558208988cadb2` |
| `g1_disturbance_controller.py` | `4415fa7f5938c7f9c35db8cef61e7d87f3926efa0521847d20401b9023a19695` |
| `scripts/numpy_abi_guard.py` | `6eabd4e8ab846ee1bd853f0a69bcf9742b06c2b964685fb510b6d83e225d7806` |
| `e01_dyn_b_runtime_guard.py` | `a15495df4770f8f46577f2ad0ab20b526bdb1087f38b2b686a4656858c2011a6` |
| `configs/e01_dyn_b_capture.yaml` | `3bc416dfd795e8f80dc27755620587248307d7ecff3bddd98d791dcdd9aaf729` |

---

## E. 静态核验

- `outer_lateral_patrol` 已 bake；config 含 `scripted_g1_outer_lateral_patrol`
- NumPy/typing_extensions 指纹与基础镜像一致（未被新层修改）
- ParamSpec 可用
- 无 dedup/quarantine 脚本；无 token
- 无宿主机源码挂载策略（canonical `run.sh` 仅 results/cache）

---

## F–G. Smoke（唯一一次）

| 项 | 值 |
|---|---|
| runner exit | **86**（postcheck） |
| returncode_raw | 0 |
| elapsed | **31.399** s |
| AppLauncher | **已创建**（`Using device: cuda:0`） |
| NumPy pre/post | **ok=true**；单根 `pip_prebundle` 1.26.0 |
| typing_extensions pre/post | **ParamSpec_available=true** |
| `outer_lateral_patrol` | 已被接受（进入 env 构建） |
| simulation step | **未完成** |
| CSV | **缺失**（仅有 `phase3_seeds.json`） |
| POST | **0** |
| 新 Xid | **无** |
| 残留 container | **无** |

### 失败根因（非依赖修补类）

```
ModuleNotFoundError: No module named 'scene_camera_override'
```

`run_phase3.py` 在 env 构建阶段 import `scene_camera_override`，但 M1V Dockerfile **未 COPY** 该模块。NumPy / ParamSpec 门禁已通过；失败发生在其后。按硬预算 **不重跑、不二次 build**。

forbid 命中：`Traceback`；缺失：`phase3.csv`。

---

## 是否允许申请下一次正式 Dyn-B preflight

**否**（`STOP_NO_CAPTURE`）。若另行授权新里程碑，应在 clean-base Dockerfile 中补齐 `scene_camera_override.py`（及同类缺失本地模块）后重建，**仍禁止**继续改 NumPy/typing_extensions/pip_prebundle。

即使未来 PASS，也不得自行启动正式 Dyn-B capture。

---

## 结果路径

`g1_ur10e_disturbance/results/paper_demo/v1m1v_dyn_b_clean_runtime_20260723/`（不提交）
