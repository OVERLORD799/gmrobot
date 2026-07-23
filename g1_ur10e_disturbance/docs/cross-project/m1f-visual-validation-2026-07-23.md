# M1F 一次性视觉验证（2026-07-23）

## Verdict

**M1F_VISUAL_GATE_FAIL**

仍不是正式 Func-C 正样本；**未运行**正式 Func-C capture。禁止重跑（本轮已用尽唯一一次 Docker 运行）。

---

## 运行元数据

| 项 | 值 |
|---|---|
| HEAD | `2741c7af63c106f99dd228cd6dbcad03edb967d2` |
| image tag | `gmdisturb:e01-func-c-m1e-20260723` |
| image SHA | `sha256:3364f5165f35136ccbd93d3a7b46ca67f5e106b862c852f7167322572850feee` |
| image created | `2026-07-23T03:56:55.537309693+08:00` |
| Entrypoint | `["/opt/projects/g1_ur10e_disturbance/docker/entrypoint.sh"]` |
| exit | **1** |
| elapsed_seconds | **0** |
| Docker runs | **1**（失败不重跑） |
| results | `g1_ur10e_disturbance/results/paper_demo/m1f_visual_validation_20260723/`（不提交） |

---

## 失败根因（运行时，非视觉）

按授权命令直接传入：

`/isaac-sim/python.sh /opt/projects/GMRobot/scripts/gm_state_machine_agent.py ...`

该镜像 ENTRYPOINT 为 `entrypoint.sh`。一次运行立即失败：

- stdout: `There was an error running python`
- stderr: `File "/isaac-sim/python.sh", line 21` → `SyntaxError`（shell 脚本被当作 Python 源解析）

**未启动** Isaac / `gm_state_machine_agent` 仿真循环；**无** `scene/frame_000000_env0.png`。

未 bind-mount 宿主机 USD；未改代码/镜像/阈值；未调用 VLM/perception。

---

## Xid / 警告 / Traceback

| 项 | before | after |
|---|---|---|
| `NVRM: Xid` count (dmesg) | 0 | 0 |
| 新 Xid | 无 | 无 |
| Traceback（agent 日志） | 0 | （进程未进入 agent） |
| DEVICE_LOST | 0 | 0 |
| nested RigidBodyAPI warning | 0 | 0（未进仿真） |

---

## 门禁逐项

| 门禁 | 结果 |
|---|---|
| exit=0 | **FAIL**（1） |
| PNG 存在、非空、480×640×3 | **FAIL**（无文件） |
| 无 Traceback / DEVICE_LOST / 新 Xid | PASS（无新 Xid；无 DEVICE_LOST；无 agent Traceback） |
| nested RigidBodyAPI warning=0 | N/A→记为未观察（仿真未起） |
| 白色扇形完全消失 | **未验证**（无 PNG） |
| 两只箱体尺寸正常 | **未验证** |
| ContainerA + 20 source parts 正常 | **未验证** |
| ContainerB 完整 + filled contents 清晰 | **未验证** |
| 实际读取 PNG 视觉判断 | **不可能** |

不得仅凭 hash/结构数据判视觉 PASS → 本轮亦未做该捷径。

---

## frame SHA256

无帧。`frame_sha256`: `null`

---

## 是否允许进入 Func-C 正式单次重采集

**否。** M1F 视觉门禁未过；需在**另行授权**下修正 Docker 调用方式（例如经 `bash -lc` 绕过 entrypoint 误解析）后再做视觉验证，本轮不得重跑。

---

## 停止边界

- 不重跑 Docker
- 不修改代码 / USD / YAML / 镜像
- 不跑正式 Func-C capture
- 不调用 VLM/perception
- 仅提交本 md/json
