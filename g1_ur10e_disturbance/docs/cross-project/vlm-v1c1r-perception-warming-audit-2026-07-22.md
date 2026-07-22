# V1-C1R-P2 远端 perception `warming` 只读审计（2026-07-22）

## 分类：**LAZY_LOAD_EXPECTED**（置信度 **high**）

`status=warming` / `models_loaded=false` 在**无 POST**时会**永久保持**，这是远端 `app.py` 的设计行为，不是加载失败、也不是卡死。

本轮：**POST=0**；未改远端；未 restart；未读凭据；未跑 Isaac / V1-C1R。

---

## 1. 连接

| 项 | 结果 |
|---|---|
| ControlMaster | `/tmp/gmrobot-v0b2-tunnel.sock`（既有，pid 复用） |
| 只读 remote shell | **OK**（`BatchMode` + ControlPath） |
| 新建 tunnel / 读 `.github_token` | **否** |
| 报告中的 host/密码 | **未写入** |

---

## 2. 服务 / 进程 / 监听

| 项 | 值 |
|---|---|
| `supervisord ctl … status perception-service` | EXIT **0**，但 **无输出**（yaml 中**无** `[program:perception-service]`；由 `startup_service`/`start.sh` 拉起） |
| 监听 | `127.0.0.1:8082` → `python` **PID 465** |
| cwd | `/root/gpufree-data/perception-service` |
| 启动时间 | **2026-07-22 12:43:40 +08**（本机重启后周期；elapsed ~2h+） |
| VLM | PID **494**，cwd `vlm-service`，同刻启动；8080 监听 |
| 本轮 POST | **无**（自本次进程起 access log 尾部主要为 `GET /health`） |

---

## 3. GPU / 显存（远端 L40S）

| 项 | 值 |
|---|---|
| GPU | NVIDIA L40S |
| Total / Used / Free | **46068 / 8136 / 37322 MiB** |
| Util | 0% |
| compute-apps | pid `260197` **[Not Found]**，8058 MiB（陈旧映射；当前 `ps` 无该 PID） |
| 结论 | **非** `GPU_RESOURCE_BLOCKED`；空闲 ~37 GiB，足以叠加 GDINO+SAM2（历史同机已成功 ground） |

---

## 4. Health（远端本机 **一次** GET）

```text
curl --max-time 10 http://127.0.0.1:8082/health
→ HTTP 200
{"status":"warming","models_loaded":false,
 "gdino_model_id":"IDEA-Research/grounding-dino-base",
 "sam2_checkpoint":"sam2.1_hiera_small.pt","gpu":"NVIDIA L40S"}
```

无 `backend_available` 字段（代码未返回）。

---

## 5. 日志摘要

| 文件 | size / mtime | 要点 |
|---|---|---|
| `supervisor.out.log` | ~220 KB / 持续更新 | 历史大量 `POST /ground|track` **200**；近期多为 `GET /health` |
| `supervisor.err.log` | ~7.8 MB / 12:43 | 多次 Uvicorn startup；当前 PID 段 **无** Traceback/OOM/FileNotFound |
| `server.log` | 旧（6-28） | **历史** import/`bind` 失败（与当前进程无关） |

当前进程启动后：见 Uvicorn “Application startup complete”，**无** “GDINO/SAM2 load begin/complete” 日志——与 lazy 设计一致（启动不加载）。

历史成功加载痕迹：err 中曾有 GroundingDINO `FutureWarning`（说明曾经执行过模型路径）；`server.log` 旧 Traceback **不**代表当前状态。

---

## 6. Lazy-load 控制流（代码证据）

`app.py`（mtime 2026-06-23，只读全文核对）：

1. `_gdino_model = None` / `_sam2_predictor = None` 初始值。
2. `lifespan` 注释：*“Lazy load on first /ground to keep VLM startup unaffected.”*；startup **不**调用加载。
3. `/health`：`loaded = (_gdino_model is not None and _sam2_predictor is not None)` → 否则 `status=warming`。
4. `_ensure_models()`：在 **`POST /ground`** 与 **`POST /track`** 入口调用；`threading.Lock` 双检锁；**无**后台预热线程。
5. 加载失败：未写入 health 异常字段；会以请求异常/500 暴露（无持久 `load_error`）。
6. `/track` **不**要求先 `/ground`，但同样会触发 `_ensure_models()`。
7. Checkpoint：`SAM2_CHECKPOINT=.../sam2.1_hiera_small.pt` **可读**（~176 MiB）；HF hub 已有 `models--IDEA-Research--grounding-dino-base`（~892 MiB）；`sam2.1_hiera_s.yaml` 在 conda site-packages 存在。

→ **无 POST 时 warming 永久**；**首次 `/ground`（或 `/track`）触发加载**。

---

## 7. 必答问题

| # | 问题 | 答 |
|---|---|---|
| 1 | 无 POST 时 warming 是否永久？ | **是**（by design） |
| 2 | 首次 `/ground` 是否触发加载？ | **是**（`_ensure_models()`）；`/track` 亦可 |
| 3 | lazy 首次 ground 附加延迟？ | 历史探针（health 仍 warming 后 ground）墙钟 **~7.5 s**（`latency_ms≈7313`）；warm 后 V0-C3 ground 阶段约 **0.45–0.5 s** → 粗估冷加载开销 **~7 s 量级**（非本轮实测） |
| 4 | 15 s drain 是否够？ | 客户端 `timeout_s=300` 足够单次冷 ground。`shutdown_drain_timeout_s=15` 仅约束**收尾等待**；冷加载落在首帧、且历史 ~7.5 s 时通常够用，但余量薄。**建议 A 方案将 drain ≥ 60 s** |
| 5 | 正式 pipeline 能否兼做 warm-up 且不增第 7 POST？ | **能**（方案 A）：首帧 `ground` 计入既有 ≤6 |
| 6 | 是否需单独批准 warm-up POST？ | **非必须**；若要隔离延迟变量可选方案 B |
| 7 | 真实加载失败/OOM/缺 ckpt/import？ | **当前进程：无证据**；ckpt/HF cache 可读；旧 `server.log` 失败已过时 |
| 8 | L40S 显存能否同跑 VLM+GDINO+SAM2？ | **是**（free ~37 GiB；历史同机成功） |

---

## 8. 判定与方案（不执行）

### 分类排除

| 候选 | 结论 |
|---|---|
| MODEL_LOAD_IN_PROGRESS | 否（无后台加载） |
| MODEL_LOAD_FAILED | 否（当前无失败字段/Traceback） |
| SERVICE_STALE_STATE | 否（监听正常、health 200、设计态 warming） |
| GPU_RESOURCE_BLOCKED | 否（显存充足） |
| INSUFFICIENT_EVIDENCE | 否（源码+行为一致） |

### 方案对比（仅建议）

| | **A. 正式首帧 ground 兼 warm-up** | **B. 单独 1× warm-up POST** |
|---|---|---|
| POST | 正式仍 **≤6** | warm-up **+1**，正式另计 **≤6** |
| 审计 | 首帧 ground 延迟含加载，需在报告注明 | 正式延迟更“干净” |
| drain | **建议 ≥60 s**（相对现 15 s） | 正式可维持 15 s（模型已热） |
| 远端修改 | **不需要** | **不需要**（仅多一次批准 POST） |

**推荐：A**（POST 预算紧、代码已证明 lazy、历史冷 ground ~7.5 s 成功），正式前将 `shutdown_drain_timeout_s` 提到 **≥60**（属配置变更，**需用户批准**后改 runtime cfg，本轮不做）。  
若论文要把首帧 latency 当可比指标，改选 **B**。

**不得**再把运行前 `models_loaded=true` 作为 V1-C1R 硬前置。

---

## 9. 只读命令与退出码（摘要）

| 命令 | EXIT |
|---|---|
| `ssh -o ControlPath=/tmp/gmrobot-v0b2-tunnel.sock …` remote shell | 0 |
| `supervisord ctl … status perception-service` | 0（空输出） |
| `pgrep -af gpufree-data/perception-service` | 1（模式过窄；实际 PID 经 `ss`/`ps` 确认） |
| `ss -ltnp` + awk `:8082` | 0 |
| `nvidia-smi` / query-compute-apps / query-gpu | 0 |
| `curl … http://127.0.0.1:8082/health`（1× GET） | 0 / HTTP 200 |
| `stat`/`tail`/`sed`/`grep` logs & `app.py`/`start.sh` | 0 |
| `test -r` SAM2 ckpt | 0 |
| 本轮 POST | **0** |

---

## 10. 是否需要远端修改

**否**（当前结论下）。重启/下载/改配置均**不需要**；若选 A 仅改**本地** runtime drain（待批）。

---

## 11. 产物

- `docs/cross-project/vlm-v1c1r-perception-warming-audit-2026-07-22.md`
- `docs/cross-project/vlm-v1c1r-perception-warming-audit-2026-07-22.json`

未覆盖 V1-C1 FAIL / NOT_RUN / Xid / V1-C1R-P 文档。未执行 V1-C1R。
