# V1-M1Z2 Dyn-B 简化镜像构建（测试移出 Dockerfile）（2026-07-23）

## Verdict

**M1Z2_CLEAN_IMAGE_SMOKE_PASS**

`next_gate=ONE_REVIEWABLE_DYN_B_PREFLIGHT_MAY_BE_REQUESTED`

即使 PASS，**未执行**正式 Dyn-B preflight / capture。

| 项 | 值 |
|---|---|
| Dockerfile | **仅** FROM + WORKDIR + COPY + LABEL（无 RUN / 无测试 / 无依赖修补） |
| prebuild | **PASS**（宿主机） |
| build 次数 | **1** |
| smoke 次数 | **1** |
| package mutation | **无**（本层） |

---

## 基线

| 项 | 值 |
|---|---|
| expected HEAD（启动） | `315c48eec1a7afb424cbf23803651ab86669c5f8` |
| branch | `main` |
| base image | `gmdisturb:b4-p010-20260721` / `sha256:defe95e7…` |

---

## Dockerfile / .dockerignore

- `docker/Dockerfile.e01-dyn-b-clean-m1z2`：copy-only
- `.dockerignore`：排除 `results/`、`docs/cross-project/`、`.git`、`*token*`、`__pycache__`、cache/build/dist 等
- 保留运行与宿主机 fixture：`scripts/run_phase3.py`、`scene_camera_override.py`、controllers、audit、`fixtures/m1y/` 等

---

## 宿主机 prebuild

脚本：`scripts/prebuild_e01_dyn_b_m1z2.sh`

| 检查 | 结果 |
|---|---|
| py_compile | PASS |
| `test_e01_dyn_b_m1v1_source_closure_unit` | PASS |
| `test_e01_dyn_b_m1v1_docker_copy_coverage_unit` | PASS |
| `test_e01_dyn_b_m1y_camera_framing_unit` | PASS |
| `test_dyn_b_per_step_audit_analyzer_unit` | PASS |
| `test_e01_dyn_b_m1w1_command_construction_unit` | PASS |
| `test_run_sh_camera_env_forwarding_unit` | PASS |
| `test_e01_dyn_b_runtime_guard_unit` | PASS |
| `test_e01_dyn_b_m1z2_dockerfile_policy_unit` | PASS |
| import closure unresolved | **0**；含 `scene_camera_override.py` |
| camera fixture `(0.45,0,2.7)` | links≥4/8、clip≤50%、ROI≥1%、disp≥20px、锚点保留 |
| canonical `run.sh --tag/--results bash -lc` | PASS |

`prebuild_summary.json` SHA256：`eebe9158c18fc48edb5a1a2d88d6ca1006e27f937a4704db3bd959828fb49cb3`

---

## Build

| 项 | 值 |
|---|---|
| tag | `gmdisturb:e01-dyn-b-clean-m1z2-20260723` |
| image SHA | `sha256:84b0bdbfb50f3912abd3d55cc2cb9f17a43be82b9bae161df04fab2520777c28` |
| Created | `2026-07-23T15:31:43.133487074+08:00` |
| exit / elapsed | **0** / **1** s |
| 本层 history | LABEL / COPY / WORKDIR only |

说明：完整 `docker history` 仍可见 B4 基座历史 apt/pip 层（物理基准固有）；M1Z2 **未新增** mutation。镜像内 `results/paper_demo` 目录来自基座层，非本轮宿主机 results COPY（已被 dockerignore）。

---

## Smoke

| 项 | 值 |
|---|---|
| exit | **0** |
| elapsed | **30.888** s |
| AppLauncher | 已创建 |
| steps | **1**（CSV `total_steps=1`） |
| CSV | `safety_logs/phase3.csv` 非空（2 行） |
| scenario | `outer_lateral_patrol` |
| NumPy pre/post | ok；单根 `pip_prebundle` **1.26.0** |
| ParamSpec pre/post | **true** |
| POST | **0** |
| 新 Xid | **无** |
| 残留容器 | **无** |
| 宿主机源码挂载 | **无** |

---

## 历史结果

未覆盖 M1Z1 / M1V1 / M1U* / M1W* 等既有 `results/paper_demo` 目录。

---

## 下一步

允许**申请**一次可审查 Dyn-B preflight；本里程碑 **停止**，不自行启动正式 capture。
