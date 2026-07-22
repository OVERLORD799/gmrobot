# V1-C1 Isaac semantic supervisor shadow — 正式运行 FAIL（2026-07-22）

> 此前 `NOT_RUN` 文档保持不变：`vlm-v1c1-isaac-semantic-shadow-result-2026-07-22.md` / `…-status-2026-07-22.json`。

## 最终分类：**FAIL**

**原因：`isaac_gpu_device_lost_before_control_loop`**

- 隧道已由主机侧恢复；两路 health HTTP 成功后启动正式运行（计为一次正式额度）。
- Isaac 在环境 bring-up / 渲染初始化阶段出现 `VkResult: ERROR_DEVICE_LOST`（GPU crash）。
- **未进入** control loop：无 `PROGRESS`、无五阶段提交、无 semantic advisory。
- 挂起容器已停止；`exit_code=137`；**不重跑、不调参**。

### 明确非声称

- 未产生实际控制作用
- 未验证 session continuity / semantic accept
- 非论文五阶段完成

---

## 运行身份

| 项 | 值 |
|---|---|
| 镜像 | `gmdisturb:semantic-shadow-v1c0-20260722` |
| image SHA | `sha256:e516c78ecc3c8e365763158f1b01ec6effba9aac1290ae0e1f4d1539c2ccf1da` |
| five-stage config SHA | `280ab4da…` |
| semantic runtime SHA | `ba473934…`（阈值与 live 一致，仅 log_dir） |
| CLI | `--enable_safety` + `--enable_five_stage_shadow` + `--enable_semantic_supervisor_shadow` |
| 禁旗 | 未传 `--enable_vlm` / `--enable_replan` |

---

## 门禁摘要

| 项 | 值 |
|---|---|
| exit | **137**（GPU crash 后中止） |
| PROGRESS | **无** |
| camera ready | 未确认（崩溃于 bring-up） |
| POST | **0** |
| submitted/processed/logged | **N/A** |
| semantic advisories | **0** |
| Traceback | 无（Vulkan DEVICE_LOST） |
| 重试 | **0** |
| 远端修改 | 无 |
| 凭据 | 仅隧道恢复读取；未写入项目文件/命令历史明文 |

运行前感知 health 仍为 `warming` / `models_loaded=false`（HTTP 仍成功）；崩溃发生在本地 GPU，非远端 POST。

---

## 产物

`g1_ur10e_disturbance/results/paper_demo/v1c1_isaac_semantic_shadow_20260722/`

含 stdout/stderr/exit_code、config snapshots、run_manifest。无 five-stage/semantic JSONL（未到达）。

## 正确表述

**正式 V1-C1 已启动但因本地 GPU DEVICE_LOST 在控制环前失败；无 POST、无语义控制副作用；证据已保留且不重跑。**
