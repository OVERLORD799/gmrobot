# V1-C1.1 只读 GPU/Isaac 故障审计（2026-07-22）

## 结论

| 项 | 值 |
|---|---|
| 分类 | **NVIDIA_XID_CONFIRMED** |
| 置信度 | **high** |
| Xid | **109**（`CTX SWITCH TIMEOUT`） |
| 应用症状 | `VkResult: ERROR_DEVICE_LOST` → GPU crash |
| exit 137 含义 | `docker stop` 强制 SIGKILL（挂起约 15 min 后），**非** OOM killer |
| 是否覆盖 V1-C1 FAIL / NOT_RUN | **否** |
| 本轮是否重跑 / 启动 Isaac / POST | **否** |
| 具备申请 V1-C1R 的条件 | **是**（分类已锁定；宿主机当前 GPU/RAM 空闲；证据已固化） |
| 进入 V1-D | **否** |

---

## 1. 失败产物与时间线

**正式失败目录（只读）：**  
`g1_ur10e_disturbance/results/paper_demo/v1c1_isaac_semantic_shadow_20260722/`

| 文件 | 行数 / 值 |
|---|---|
| `stdout.txt` | 152 |
| `stderr.txt` | 12 |
| `exit_code.txt` | **137** |
| `run_manifest.json` | `verdict=FAIL`, `vk_result=ERROR_DEVICE_LOST` |

容器 ID（journal）：`62160c9838a2b6d5ac2e4b06f437319c23969d512514bdb16e582284c0b78209`（`--rm`，事后 inspect **unavailable**）。

### 时间线（UTC / 本地 +08）

| 时刻 (UTC) | 本地 +08 | 事件 |
|---|---|---|
| 04:51:43 | 12:51:43 | 容器启动（systemd `docker-62160c…scope`；Isaac Kit 开始写 `kit_20260722_045143.log`） |
| 04:51:43–44 | 12:51:43–44 | Vulkan/CUDA 设备探测：RTX 5090 Laptop、Driver 580.159.03；`AppLauncher` → `cuda:0`；加载 `isaaclab.python.headless.rendering.kit` |
| 04:51:45–55 | 12:51:45–55 | Kit/PhysX/Replicator 插件装载；GLFW/display 警告（headless 预期） |
| 04:52:01 | 12:52:01 | IsaacLab env 创建开始（PhysX step 0.005 / render 0.02） |
| 04:52:06–08 | 12:52:06–08 | 场景 prim 质量属性警告；**PhysX** RigidBody/CCD 错误写入 stderr（非 fatal） |
| 04:52:08 | 12:52:08 | PhysX joint / fabric 警告 |
| 04:52:11 | 12:52:11 | **renderer**：`rtx.postprocessing` DLSS 分辨率警告（camera/render 路径已进入） |
| **04:52:15** | **12:52:15** | **首次硬错误**：kernel `NVRM: Xid 109 … CTX SWITCH TIMEOUT`（pid=50754, `python3`）与应用 `ERROR_DEVICE_LOST` / `GPU crash` / GPU pagefault **同一秒** |
| 04:52:15 | 12:52:15 | 写出 `.nvdbg` / `.nv-gpudmp`（容器内路径；宿主 cache 未找到同名文件） |
| 04:52:15–13:07:15 | — | 进程挂起；无 PROGRESS / 无 five-stage / 无 semantic 日志 |
| 13:07:15 | 13:07:15 | dockerd：`Container failed to exit within 10s of signal 15 - using the force` |
| 13:07:15–16 | 13:07:15–16 | 容器停止；systemd 记录 **5.2G memory peak**；宿主收到 exit **137** |

### ERROR_DEVICE_LOST 前后摘录（stderr 全文 12 行；stdout 邻近）

```text
# stderr @ 04:52:08 — PhysX（先于 device lost）
[Error][omni.physicsschema] Rigid Body ... missing xformstack reset ...
[Error][omni.physx] kinematic bodies with CCD enabled are not supported! ...

# stderr @ 04:52:15 — 首次 DEVICE_LOST
[Error][carb.graphics-vulkan] VkResult: ERROR_DEVICE_LOST
[Error][carb.graphics-vulkan] submitToQueueCommon failed.
[Error][gpu.foundation] A GPU crash occurred. Exiting the application...
Reasons for the failure: a device lost, out of memory, or an unexpected bug.
... shader debug / crash dump written ...

# stdout @ 04:52:11–15 — renderer 后紧接 crash
[Warning][rtx.postprocessing] DLSS increasing input dimensions ...
[Warning][gpu.foundation] polling aftermath dump status ...
[Warning][carb.graphics-vulkan] GPU pagefault occured on virtual address(...)
```

完整 stdout 仅 152 行（不足 ±100 行窗口时等价于全文）；关键路径见上表。

---

## 2. 候选根因对照

| 候选 | 判定 | 证据 |
|---|---|---|
| NVIDIA Xid / driver reset | **确认** | `journalctl -k`：`Xid (PCI:0000:02:00): 109 … CTX SWITCH TIMEOUT`，与 DEVICE_LOST 同秒 |
| GPU 显存耗尽 | **不支持** | 崩溃瞬间无 `nvidia-smi` 快照；事后 Used=82 MiB；无 FB OOM 日志；应用文案含 “or OOM” 但无独立显存耗尽证据 |
| 宿主机 RAM OOM / OOM killer | **否定** | 同期 kernel **无** `Out of memory` / `Killed process` / `oom-kill`；启动时 Free Memory ~113 GB；容器 peak **5.2G** |
| Docker shared memory 不足 | **证据不足** | `run.sh` **未**设 `--shm-size`；容器已 `--rm`，`HostConfig.ShmSize` **unavailable**；宿主 `/dev/shm` 62G 空闲；**同一 run.sh** 下 V0-C3 曾成功 |
| 多 Isaac/GPU 进程竞争 | **不支持（当时）** | Xid 仅点名 `python3` pid=50754；审计时 `nvidia-smi` compute apps 为空；无并存 Isaac 证据 |
| renderer/camera 初始化失败 | **症状层确认** | DLSS 警告后立刻 DEVICE_LOST；未到 `scene_rgb` ready / PROGRESS |
| 容器 runtime/device 映射问题 | **不支持** | 启动时 GPU 枚举成功（UUID 与 Xid PCI 一致）；`--gpus all`；非映射缺失表现 |
| 未知瞬时 device lost | **被 Xid 取代** | 已有明确 Xid 109 |

---

## 3. 只读采集摘要

### 命令与退出码

| 命令 | EXIT | 要点 |
|---|---|---|
| `nvidia-smi` | 0 | 5090 Laptop；82 MiB used；无 compute app |
| `nvidia-smi -q`（筛选） | 0 | Driver 580.159.03；CUDA 13.0；ECC N/A；Temp ~39–40°C；Power ~15 W；P8 |
| `nvidia-smi --query-gpu=...` | 0 | 同上 |
| `nvidia-smi --query-compute-apps=...` | 0 | 空（无进程） |
| `free -h` | 0 | 122 Gi total；~110 Gi available；swap 0 used |
| `df -h /` | 0 | 641G，30% used |
| `df -h /dev/shm` | 0 | 62G，1% used |
| `docker inspect 62160c…` | 非 0（对象不存在） | State.ExitCode / OOMKilled / ShmSize / device requests → **unavailable**（`--rm`） |
| `journalctl --since 12:50 --until 13:10` | 0 | Xid 109；docker start/stop；**无** OOM |
| `journalctl -k` + OOM 过滤 | rg EXIT 1 | 无匹配 |
| `dmesg -T` + NVRM/OOM | 视权限/缓冲 | 本轮未依赖；journal -k 已覆盖 Xid |
| `curl -m 5 http://127.0.0.1:18082/health`（**仅一次 GET**） | 0 / HTTP 200 | 见 §5 |
| 提权 / 改驱动 / 杀进程 / 清 cache | **未执行** | — |

原始命令摘录：`/tmp/v1c11_audit_cmds_final.txt`、`/tmp/v1c11_xid_kernel.txt`。

### journal 关键行

```text
2026-07-22T12:51:43+08:00 ... Started docker-62160c9838a2...scope
2026-07-22T12:52:15+08:00 ... NVRM: Xid (PCI:0000:02:00): 109, pid=50754, name=python3, ... CTX SWITCH TIMEOUT, Info 0x3c009
2026-07-22T13:07:15+08:00 ... Container failed to exit within 10s of signal 15 - using the force
2026-07-22T13:07:15+08:00 ... Consumed ... 5.2G memory peak ...
```

---

## 4. 与成功运行的参数对比（仅事实差异）

| 参数 | V0-C3 PASS | V1-C0 1-step smoke PASS | V1-C1 FAIL |
|---|---|---|---|
| image | `cab6bf5c…`（v0c3） | `e516c78e…`（v1c0） | **同 V1-C0** `e516c78e…` |
| `max_steps` | 120 | **1** | 120 |
| `--enable_cameras` | yes | yes | yes |
| `--enable_five_stage_shadow` | yes | **no** | yes |
| `--enable_safety` | **no**（`safety_disabled=true`） | **no** | **yes** |
| `--enable_semantic_supervisor_shadow` | no | no | **yes** |
| `--network=host` + runtime bind-mount | yes（five-stage cfg） | 无（无 shadow cfg） | yes（five-stage + semantic cfg） |
| Docker 入口 | 同一 `run.sh`：`--gpus all --rm`，**无**显式 `--shm-size` / memory limit | 同左 | 同左 |
| POST | 6（预期） | 0 | **0**（未到控制环） |

**不得凭猜测归因：** Xid/DEVICE_LOST 发生在 env bring-up / renderer 阶段，**早于** PROGRESS 与任何 five-stage/semantic 提交；CLI 上多出的 `--enable_safety` / semantic **没有时间线证据**证明是 Xid 触发器。镜像与 V1-C0 成功 smoke 相同，差异主要是 **步数与开关栈**（120 + safety + dual shadow vs 1 + 全关）。

---

## 5. 感知 health（前置条件，非本次根因）

单次 GET `http://127.0.0.1:18082/health`：

```json
{"status":"warming","models_loaded":false,"backend_available":（字段未返回；HTTP 200）,"gpu":"NVIDIA L40S", ...}
```

记录：`status=warming`，`models_loaded=false`，HTTP 200。  
**禁止**将此解释为 DEVICE_LOST / Xid 根因；仅作后续 V1-C1R 前置观测。

---

## 6. 分类

**NVIDIA_XID_CONFIRMED**（置信度 high）

并列症状标签（非主分类）：Isaac Vulkan `ERROR_DEVICE_LOST` + GPU pagefault；exit 137 = 强制停容器。

排除：`HOST_OOM_CONFIRMED`、`CONTAINER_OOM_CONFIRMED`（无 OOM 证据；peak 5.2G）。

---

## 7. 最小恢复建议（本轮不执行）

1. **只读保留**：V1-C1 FAIL 目录与 NOT_RUN 文档继续冻结。
2. **非破坏性**：确认无残留 Isaac/python GPU 进程后再申请 V1-C1R（当前 audit 时已无 compute app）。
3. **需用户审批的破坏性/状态变更操作**（本轮未做）：
   - 重启 NVIDIA 驱动 / `nvidia-smi -r` / 卸载重载 `nvidia` 模块
   - 重启宿主机
   - 清理 Docker/GPU cache、杀进程、重建镜像、修改驱动或 Docker runtime
4. **V1-C1R 申请条件（已具备，待用户批准）**：根因已分类；宿主 GPU/RAM 当前健康；正式 FAIL 证据完整；不覆盖旧产物；仍禁止擅自重跑。

---

## 8. 关键路径

| 类型 | 路径 |
|---|---|
| FAIL 产物 | `results/paper_demo/v1c1_isaac_semantic_shadow_20260722/` |
| FAIL 文档（勿覆盖） | `docs/cross-project/vlm-v1c1-isaac-semantic-shadow-run-2026-07-22.md` |
| NOT_RUN 文档（勿覆盖） | `docs/cross-project/vlm-v1c1-isaac-semantic-shadow-result-2026-07-22.md` |
| 本审计 | `docs/cross-project/vlm-v1c1-gpu-failure-audit-2026-07-22.md` |
| 本审计 JSON | `docs/cross-project/vlm-v1c1-gpu-failure-audit-2026-07-22.json` |
| 运行终端捕获 | `~/.cursor/projects/home-czz-GMrobot/terminals/220933.txt` |
| 命令摘录 | `/tmp/v1c11_audit_cmds_final.txt` |

---

## 明确非声称

- 未重跑 V1-C1；未进入 V1-D；未执行 V1-C1R。
- 未证明 `--enable_safety` / semantic 为 Xid 原因。
- 感知 `warming` 不是本次 GPU 丢失根因。
