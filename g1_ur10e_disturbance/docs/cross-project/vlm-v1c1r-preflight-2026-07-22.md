# V1-C1R-P 前置验证（2026-07-22）

## 最终判定：**REMOTE_PERCEPTION_NOT_READY**

| 项 | 结果 |
|---|---|
| 120-step GPU 稳定性预检 | **PASS** |
| 当前 boot 新增 NVIDIA Xid | **无**（运行前后均为 0） |
| VLM ready | **是**（HTTP 200, `status=ok`） |
| perception ready | **否**（10 min 仍 `warming` / `models_loaded=false`） |
| tunnel | **正常** |
| POST | **0** |
| `V1_C1R_PREFLIGHT_PASS` | **否** |
| 正式 V1-C1R | **未执行**（按门禁停止） |

---

## 1. 镜像 / 配置

| 项 | 值 |
|---|---|
| image tag | `gmdisturb:semantic-shadow-v1c0-20260722` |
| image_id | `sha256:e516c78ecc3c8e365763158f1b01ec6effba9aac1290ae0e1f4d1539c2ccf1da` |
| 重建镜像 | **否** |
| 正式 five-stage cfg（未用于本预检） | `five_stage_shadow_legacy_gateway_v1c1.yaml` sha256 `280ab4daad839090a49e7f1bc11e0d13f73b75679b6803ba981d74f9f4b0b073` |
| 正式 semantic cfg（未用于本预检） | `semantic_safety_supervisor_shadow_v1c1.yaml` sha256 `ba473934c8f5a05a0a8e6b688daaba55cf6fe17d59103475427ea2e25e960a49` |

---

## 2. Boot / uptime（预检开始时）

| 项 | 值 |
|---|---|
| boot_id | `c8323be1-3124-4017-9491-92a42b29082f` |
| uptime（开始） | ~49 min（约 14:16 本地） |
| 宿主机重启后新周期 | **是** |

---

## 3. GPU 前后状态

| 时刻 | memory.used | compute apps |
|---|---|---|
| 预检前 | 69 MiB | 无（仅 display G 进程） |
| 120-step 后 | 70 MiB | **无** Isaac/python compute（正常退出） |

Driver `580.159.03`；无残留 Isaac GPU 进程。

---

## 4. Xid 前后差异

过滤：`journalctl -k -b` 中 **`NVRM: Xid`**（排除网卡驱动字符串 `XID 688`）。

| 窗口 | `NVRM: Xid` 行数 |
|---|---|
| Isaac 前 | **0** |
| Isaac 后 | **0** |
| 感知轮询结束后 | **0** |

→ **未**触发 `PRECHECK_BLOCKED_NEW_XID`。

---

## 5. Isaac GPU 稳定性预检

**结果目录：** `results/paper_demo/v1c1r_gpu_stability_preflight_20260722/`

| 门禁 | 结果 |
|---|---|
| exit | **0** |
| PROGRESS | **120** |
| scene_rgb | **ready** `(480,640,3)` |
| ERROR_DEVICE_LOST | **无** |
| GPU pagefault | **无** |
| Traceback | **无** |
| POST | **0** |
| GPU 进程退出 | **是** |
| boot 新增 Xid | **无** |

CLI（本预检）：

```text
--task=gm --headless --enable_cameras --num_envs=1 --max_steps=120
--enable_safety --progress_interval=10
# 未传: --enable_five_stage_shadow / --enable_semantic_supervisor_shadow
# 未传: --network=host（不连接 endpoint）
```

---

## 6. POST 数

**0**（无 five-stage/semantic；无 host network；日志无 18080/18082/`/analyze`/`/ground`/`/track`）。

---

## 7. 与正式 V1-C1R 参数差异（必须注明）

现有调度语义：`max_submissions=0` 表示**不限制**提交，**不能**用来实现 0 POST。  
未改代码；因此本预检：

| 参数 | 正式 V1-C1R（预期） | 本预检 |
|---|---|---|
| `--enable_safety` | yes | **yes** |
| `--enable_cameras` / headless / `max_steps=120` / `num_envs=1` | yes | **yes** |
| 同一镜像 / 场景 / renderer | yes | **yes** |
| `--enable_five_stage_shadow` | yes | **no** |
| `--enable_semantic_supervisor_shadow` | yes | **no** |
| `--network=host` + runtime cfg bind-mount | yes | **no** |
| POST | ≤6（预期） | **0** |

差异原因：在不改代码的前提下，无法用 `max_submissions=0` 关闭提交；关闭 shadow 是唯一合法的 0-POST 路径。

---

## 8. 感知 readiness 时间线（仅 GET）

- 间隔 30 s；最长 10 min；**禁止 POST / 禁止重启远端**
- 产物：`perception_health_poll.jsonl`（21 次）、`perception_poll_summary.json`

| n | 时间 (+08) | HTTP | status | models_loaded |
|---|---|---|---|---|
| 1–21 | 14:18:34 → 14:28:35 | 200 | `warming` | `false` |

全程：`backend_available` 字段缺失；GDINO/SAM2 仅见配置 ID，**未**证明已加载。

VLM（轮询窗口内一次 GET）：HTTP 200，`status=ok`。

→ 判定：**REMOTE_PERCEPTION_NOT_READY**

---

## 9. Tunnel / 监听

- `/tmp/gmrobot-v0b2-tunnel.sock` 存在
- `127.0.0.1:18080` / `18082` 由 ssh 转发监听

---

## 10. 未触碰历史证据

下列文件 sha256 在预检前后一致（见结果目录 `historical_docs_sha256*.txt`）：

- `vlm-v1c1-gpu-failure-audit-2026-07-22.md`
- `vlm-v1c1-isaac-semantic-shadow-run-2026-07-22.md`（FAIL）
- `vlm-v1c1-isaac-semantic-shadow-result-2026-07-22.md`（NOT_RUN）

未覆盖 V1-C1 FAIL 结果目录；未进入 V1-D；未执行正式 V1-C1R。

---

## 11. 停止条件

按任务要求：感知未就绪 → **停止**，提交只读证据，**等待用户另行批准**后方可考虑正式 V1-C1R（且需 perception ready）。
