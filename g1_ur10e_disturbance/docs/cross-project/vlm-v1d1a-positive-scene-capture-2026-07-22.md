# V1-D1A 远场动态正例场景实现与 0-POST RGB/几何采集（2026-07-22）

## 最终判定：**FAIL**

| 项 | 值 |
|---|---|
| reason | **`geometry_not_allow_throughout`** |
| Isaac exit | **0** |
| steps | **280** |
| POST | **0** |
| RGB 两帧 | 有效、hash 不同、proxy **可见**、位移 **82.4 px** |
| geometry | ALLOW=184 / SLOW=67 / STOP=29；`min_margin≈-0.028 m` |
| replan | **0** |
| Xid | **0→0** |
| 2-POST 语义筛选 | **不具备**（几何门禁未过；不发 VLM） |
| 正式 D1 / active | **未进入** |
| 新镜像 | **未构建**（Isaac 仅 bind-mount YAML；沿用 `f81e59ce…`） |

根因：远场横移轨迹在任务推进中仍触发 Layer-1 **`static_warning`** 与 **`dynamic_ttc(_warning)`**（未改 warn/TTC 阈值）。按约束：**不重跑调参刷结果、不发 VLM POST**。

`visual_semantic_risk=low`：proxy 为红色 kinematic 小球；**不得**用文件名 `human_hand` 证明 VLM 能识别人手。

---

## 1. 改动文件

| 路径 | 作用 |
|---|---|
| `GMRobot/configs/ivj_v1d1_far_corridor_motion.yaml` | 远场走廊横移 safety 场景（不改 B0–B4） |
| `GMRobot/source/GMRobot/GMRobot/shadow/v1d1a_capture.py` | 离线 RGB/ROI/manifest/门禁工具 |
| `GMRobot/scripts/build_v1d1a_capture_manifest.py` | 从 PNG+CSV 生成 manifest |
| `GMRobot/scripts/test_v1d1a_far_corridor_capture_unit.py` | 离线单测 |

未改：冻结物理 B0–B4、语义阈值、VLM prompt/模型、远端服务、`gm_state_machine_agent` 控制语义。

---

## 2. 测试结果

| 套件 | 结果 |
|---|---|
| 全部既有 `scripts/test_*unit.py` | **32/32 OK**（含本轮新增） |
| `test_v1d1a_far_corridor_capture_unit.py` | **PASS** |
| 镜像 canonical import smoke | **PASS**（`f81e59ce…`） |
| 1-step 无网络 smoke | exit=0，`g_rule=0`，无 Traceback，无 five-stage/VLM 初始化 |
| 正式 capture 门禁 | **FAIL**（几何） |

---

## 3. image / config / trajectory SHA

| 项 | 值 |
|---|---|
| image | `gmdisturb:semantic-shadow-v1c0p1-20260722` |
| image_id | `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c` |
| safety config SHA | `a807b531fd28bfee1965e1e4ce502c549c9c7faf3d4248b0e4eaf671597a9fe1` |
| trajectory_pose_hash | `1f246437642bccbd6468128c67f32798d8a97d2f952b0c55499f9b964a22c209` |
| 计划帧 | step **0**, **100** |
| seed | agent **无 --seed**；以镜像+config+trajectory hash 锚定 |

轨迹：`start [0.40,-0.55,0.50] → end [0.40,0.55,0.50]`，`duration_steps=200`，半径 0.05 m。

---

## 4. Isaac exit / steps / camera

| 项 | 值 |
|---|---|
| exit | **0** |
| PROGRESS | **280** |
| scene_rgb | ready `(480,640,3)` |
| save_camera | interval=100 → `frame_000000/000100/000200` |
| Traceback / DEVICE_LOST | **无** |

---

## 5. 两帧路径与 SHA

| step | 路径 | SHA-256 |
|---|---|---|
| 0 | `…/scene/frame_000000_env0.png` | `65ec01ad87e6a30b1282c11364810a65e21b08335ecd1c543ac6615a60e90862` |
| 100 | `…/scene/frame_000100_env0.png` | `57480cfbab0849dd7231c1cc185f6e10f7e3123f6efc631218a4946d12c29a88` |

hash **不同**；manifest 含稳定 `frame_id` / `request_id`（UUIDv5）供未来 2-POST 映射同一 RGB。

---

## 6. 可见 ROI / 像素面积 / 位移

| step | visible | pixel_area | centroid_uv | bbox |
|---|---|---|---|---|
| 0 | true | **79** | (402.85, 216.39) | 红球 ROI |
| 100 | true | **390** | (321.19, 227.14) | 红球 ROI |
| 位移 | | | **82.36 px** | ≥25 门禁 |

结论：视觉上 proxy **已真实渲染进 scene RGB**；frame0 面积偏小但仍可检出。

---

## 7. proxy 轨迹与速度（计划帧）

| step | world_pos | world_vel (m/s) |
|---|---|---|
| 0 | (0.40, -0.55, 0.50) | (0, 0.275, 0) |
| 100 | (0.40, 0.00, 0.50) | (0, 0.275, 0) |

---

## 8. geometry 最小距离 / 阈值 / margin

| 项 | 值 |
|---|---|
| safe_dist_warn / hard | **0.16 / 0.13**（未改） |
| ttc / ttc_warn | **0.5 / 1.5**（未改） |
| frame0 dist_ee_proxy | 0.800 m（margin +0.640） |
| frame100 dist_ee_proxy | 0.421 m（margin +0.261） |
| **全剧 min margin vs warn** | **-0.028 m**（失败） |

非 ALLOW 主因样本：`static_warning`（dist≈0.13–0.14）、`dynamic_ttc_warning` / `dynamic_ttc`。中段还出现 grasp knock 日志（task 物理碰触），进一步破坏「全程远场 ALLOW」假设。

---

## 9. gate 分布

| ALLOW | SLOW_DOWN | STOP | replan |
|---|---|---|---|
| 184 | 67 | 29 | **0** |

计划提交帧 step0/100 当时 `g_rule=0`，但**全程**不满足 ALLOW。

---

## 10. STOP / SLOW / replan

- attributed STOP steps: **29**
- attributed SLOW steps: **67**
- replan: **0**（未开 `--enable_replan`）

---

## 11. POST=0 证明

- 未传 `--enable_vlm` / `--enable_perception` / `--enable_five_stage_shadow` / `--enable_semantic_supervisor_shadow`
- stdout 无 `five-stage shadow enabled` / `semantic supervisor shadow enabled` / client 初始化
- `post_count_proof.json`：`post_count=0`，network hints=`[]`
- leakage 在 capture-only 下按约定记 **全 0**（无 shadow worker）

---

## 12. leakage / hash

| 项 | 值 |
|---|---|
| five-stage leakage×5 | **0**（未启用） |
| semantic leakage×5 | **0**（未启用） |
| control_decision_hash | 每帧记录于 manifest（geometry 快照） |
| control_hash_mismatch | N/A（无 semantic bridge） |

---

## 13. Xid 前后

**0 → 0**

---

## 14. 是否具备进行 2-POST 语义筛选

**否。**

虽 RGB artifact 与可见性基本可用，但几何门禁失败 → 按 V1-D0/D1A 约束 **不得**进入 VLM 筛选；保留证据，停止。

后续若另批批准，需重新设计更远/更慢/避开 EE 工作包络的轨迹（仍禁止伪造 VLM、禁止放宽阈值、禁止刷跑）。

---

## 15. git diff --stat（tracked）

```
 GMRobot/configs/perception_client.yaml             |   1 +
 GMRobot/configs/vlm_client.yaml                    |   3 +
 GMRobot/deploy/ai_server/vlm_service.py            | 119 +++++-----
 GMRobot/scripts/gm_state_machine_agent.py          | 249 +++++++++++++++++++++
 GMRobot/source/GMRobot/GMRobot/__init__.py         |  14 +-
 .../source/GMRobot/GMRobot/perception/__init__.py  |  20 +-
 .../source/GMRobot/GMRobot/perception/client.py    | 101 ++++++++-
 GMRobot/source/GMRobot/GMRobot/vlm/__init__.py     |  35 ++-
 GMRobot/source/GMRobot/GMRobot/vlm/client.py       | 149 ++++++++++--
 9 files changed, 611 insertions(+), 80 deletions(-)
```

本轮新增（untracked）：`ivj_v1d1_far_corridor_motion.yaml`、`shadow/v1d1a_capture.py`、`build_v1d1a_capture_manifest.py`、`test_v1d1a_far_corridor_capture_unit.py`、本结果文档/JSON、结果树。

---

## 结果路径

`g1_ur10e_disturbance/results/paper_demo/v1d1a_far_corridor_capture_20260722/`

含：`scene/*.png`、`manifest/capture_manifest.json`、`manifest/capture_manifest.frames.jsonl`、`safety_logs/`、stdout/stderr、xid、post_count_proof。

未覆盖 V1-C1R-P1 结果树。

---

## 停止声明

**不进行 VLM POST；不运行完整 D1；不进入 active 控制；不重建镜像；不重跑调参。**
