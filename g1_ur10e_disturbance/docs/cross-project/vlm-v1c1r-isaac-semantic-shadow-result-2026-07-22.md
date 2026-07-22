# V1-C1R Isaac semantic shadow replacement validation（2026-07-22）

## 最终判定：**FAIL**

| 项 | 值 |
|---|---|
| reason | **`semantic_bridge_import_ModuleNotFoundError_safety`** |
| Isaac exit | **137**（Traceback 后进程挂起，`docker stop` 收尾） |
| POST | **0** |
| 重跑 / 调参 / 改代码 / 重建镜像 | **否** |
| V1-D | **未进入** |
| 正式配额 | **已消耗**（仅一次） |

根因：启用 `--enable_semantic_supervisor_shadow` 时导入

`GMRobot.shadow.semantic_bridge` → `from safety.semantic_supervisor import …`

在镜像运行路径下触发 **`ModuleNotFoundError: No module named 'safety'`**。  
失败发生在控制循环之前；未提交 five-stage；未执行 cold-start `/ground`。

---

## 1. 镜像 / runtime config

| 项 | 值 |
|---|---|
| image | `gmdisturb:semantic-shadow-v1c0-20260722` |
| image_id | `sha256:e516c78ecc3c8e365763158f1b01ec6effba9aac1290ae0e1f4d1539c2ccf1da` |
| five-stage cfg | `five_stage_shadow_legacy_gateway_v1c1r.yaml` |
| five-stage SHA | `df4e082800aab2bd0d900707be92eee00f7a6c1a60e20bb8c4f7782795de2253` |
| semantic cfg | `semantic_safety_supervisor_shadow_v1c1r.yaml` |
| semantic SHA | `03f64250bd715b0327412fd7808bb82acf6198258d3ab49c9c3db68120773ac6` |
| vs V1-C1 five-stage | 仅 `shutdown_drain_timeout_s: 60.0` + `log_dir`→v1c1r |
| thresholds / interval / max_submissions=2 | **未改** |

---

## 2. 运行前门禁

| 检查 | 结果 |
|---|---|
| 镜像 SHA | 匹配 |
| tunnel / 18080 / 18082 | OK |
| VLM health | HTTP 200，`status=ok` |
| perception health | HTTP 200，`warming` / `models_loaded=false`（方案 A 允许） |
| boot `NVRM: Xid` | **0** |
| 残留 Isaac compute | 无 |

---

## 3. exit / steps / camera / Xid

| 项 | 结果 |
|---|---|
| exit | **137** |
| PROGRESS | **无**（未进入控制环） |
| scene_rgb | 配置表出现 `(480,640,3)`；**未**跑满 120 step |
| DEVICE_LOST / pagefault | **无** |
| Traceback | **有**（见上） |
| Xid 前→后 | **0 → 0** |

---

## 4. POST / pipeline / cold-start

| 项 | 结果 |
|---|---|
| POST 数 | **0**（无顺序、无重试、无第三帧） |
| submitted/processed/logged | **N/A**（未启动调度循环） |
| 两帧 pipeline | **未执行** |
| cold-start ground | **未尝试** |
| health before | `warming` / `models_loaded=false` |
| health after（1× GET） | 仍为 `warming` / `models_loaded=false` |
| warm latency | N/A |

部分产物：`five_stage_shadow_20260722_065907/five_stage_shadow_steps.csv`（空文件，logger 目录已建但无提交）。

---

## 5. Semantic / leakage / drain / session

全部 **未达到可评估状态**（import 失败）：

- session/track continuity：N/A
- advisory / rejection：N/A
- capture/decision/age/geometry gate：N/A
- evaluated vs effective gate：N/A
- control_hash_mismatch：N/A
- semantic / five-stage leakage：N/A
- drain/queue/stale：N/A

---

## 6. 脱敏扫描

无 endpoint 响应落盘；无 raw session / 凭据写入本结果树。

---

## 7. 历史证据未覆盖

未修改/覆盖：

- V1-C1 NOT_RUN / FAIL 文档与结果目录
- Xid 审计、GPU preflight、perception warming 审计

sha256 快照见结果目录 `historical_docs_sha256.txt`。

---

## 8. 结果路径

`results/paper_demo/v1c1r_isaac_semantic_shadow_20260722/`

关键文件：`stdout.txt`、`stderr.txt`、`exit_code.txt`、`run_manifest.json`、health before/after、runtime config 副本。

---

## 9. 后续（本轮不执行）

修复方向（需**另行批准**）：将 `semantic_bridge.py` 的 `safety.*` 导入改为包内相对/绝对可解析路径，重建或热修镜像后**新开**验证轮次。  
本轮按门禁：**不重跑、不改代码、不进 V1-D**。
