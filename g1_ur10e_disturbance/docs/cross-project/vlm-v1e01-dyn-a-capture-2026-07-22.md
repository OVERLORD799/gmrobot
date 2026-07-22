# V1-E01-Dyn-A 单场景采集（2026-07-22）

## 1. Verdict

**GEOMETRY_WINDOW_FAIL**（正式门禁未过；**不重跑、不调参、不发 SAM2/VLM**）

| 检查 | 结果 |
|---|---|
| Isaac exit | **0** / steps **0–499**（max_steps=500） |
| camera ready / RGB | **是**（640×480，step 210/280） |
| G1 ROI ≥400 px² | **通过**（投影 body bounds；非红球） |
| centroid displacement ≥40 px | **失败**（≈4.54 px；两帧均在 `stand` 相位） |
| 两帧 hash | **不同** |
| G1 / UR10e 上下文可见 | **是**（人工+投影 ROI） |
| geometry 210–280 全 ALLOW | **失败**（step **213** = `SLOW_DOWN` / `dynamic_ttc_warning`） |
| POST / VLM / perception | **0** |
| Traceback / 新 Xid | **0** / 未见新 Xid |
| motion label | `scripted_g1_locomotion_arm_wave`（**scripted locomotion**，不是关节挥手） |
| SAM2 验证条件 | **不具备**（位移门禁已失败；不做 SAM2） |
| 结果目录 | `**/results/` **已 ignore**；本轮 **未提交** results |
| 历史结果覆盖 | **无** |

根因（诚实）：
1. **几何窗**：窗口内出现 1 次 UR10e 任务内 TTC 预警（与 G1 远场距离无关；窗内 min dist≈0.91 m ≫ warn）。
2. **视觉动态**：capture steps 210/280 均落在 `ARM_WAVE` 的 **stand**（vx=0），屏幕位移不足；非文件名证明问题。

---

## 2. HEAD / worktree

| 项 | 值 |
|---|---|
| branch | `main` |
| HEAD | `1c5c9f809c760e8ea46aebcf3aa1da189529ff30` |
| C1–C6 | 本地未 push（本任务未授权 push） |
| worktree | **脏**（本轮新增 Dyn-A 代码/配置；未 commit） |

---

## 3. Image / config SHA

| 项 | 值 |
|---|---|
| image tag | `gmdisturb:e01-dyn-a-20260722` |
| image Id | `sha256:c609dae18a611e9b703b5d87b3e24ed55cfa3c660d907fbc3c55823e2134b534` |
| created | `2026-07-22T20:15:34+08:00` |
| base（未覆盖） | `gmdisturb:semantic-shadow-v1c0p1-20260722` / `sha256:f81e59ce…` |
| 冻结 B4（未覆盖） | `gmdisturb:b4-p010-20260721` / `sha256:defe95e7…` |
| config | `configs/e01_dyn_a_capture.yaml` |
| config SHA256 | `c8fc9515f654cad9cb1a2da9ea2df041bde99a7be05764906a305d62e1c59e47` |

薄重建：`Dockerfile.e01-dyn-a` FROM `semantic-shadow-v1c0p1`，仅 COPY Dual camera override / `run_phase3` save_camera / 离线分析模块。

---

## 4. 是否新增 camera 代码

**是**（最小、默认关闭）：

- `scene_camera_override.py`：`GMDISTURB_SCENE_CAMERA_OVERRIDE=1` 才启用
- `dual_env_cfg.py`：读取上述 helper；默认仍为 `(1.0,0.0,3.0)`
- Dyn-A 运行时：`pos=(0.2,0.0,3.2)` / `rot=(0.7071,0,0.7071,0)`
- **未修改**冻结 B0–B4 YAML

另：`run_phase3.py` 增加 `--save_camera` / `--camera_save_steps` / body-pose sidecar（0-POST）。

---

## 5. 测试 / smoke

| 项 | 结果 |
|---|---|
| `scripts/test_e01_dyn_a_capture_unit.py` | **PASS**（override 默认关、Dyn-A pose、arm_wave 标签、seed/steps、无 virtual-hand、POST=0、manifest、ROI、geometry、B0–B4 SHA） |
| canonical import | **PASS** |
| 1-step Isaac camera smoke | **exit=0**；`scene_rgb` ready；PNG 有效；POST=0；无 Traceback |

---

## 6. Exit / steps

- Isaac exit=**0**
- max_steps=**500**，steps CSV 行数=**500**（step 0…499）
- 正式 capture **仅一次**（`meta/formal_capture_done.flag`）

---

## 7. RGB 路径 / SHA

| step | path | SHA256 |
|---|---|---|
| 210 | `.../scene/frame_000210_env0.png` | `0d63919e62acc547696b95f28c404bf0158f6f1484ae5778439a5d5a2e6aa783` |
| 280 | `.../scene/frame_000280_env0.png` | `d2bc91da585e364f2bf5b409514cb9328f3abae84a648d9e0a31b9f863430823` |

结果根目录：`g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_a_capture_20260722/`（workspace `results/paper_demo/...` 为 symlink）。

---

## 8. G1 ROI 与来源

| step | roi_area_px² | centroid_uv | 来源 |
|---|---|---|---|
| 210 | ≈4574 | ≈(273.6, 339.6) | **`projected_g1_body_points`**（torso/head/shoulders/elbows/wrists） |
| 280 | ≈4395 | ≈(277.7, 337.6) | 同上 |

未使用颜色阈值；未启用 virtual-hand 红球。

---

## 9. Centroid displacement

≈ **4.54 px**（阈值 ≥40）→ 视觉动态门禁失败。
两帧 G1 root ≈ `(-0.396,-0.281)` → `(-0.414,-0.258)`，均在 **stand**。

---

## 10. Camera pose

```json
{"override_enabled": true, "pos": [0.2, 0.0, 3.2], "rot": [0.7071, 0.0, 0.7071, 0.0]}
```

---

## 11. Motion phase / 标签

| 项 | 值 |
|---|---|
| CLI scenario | `arm_wave` |
| motion_source | **`scripted_g1_locomotion_arm_wave`** |
| step 210 phase | `stand`（settle 结束边界后） |
| step 280 phase | `stand` |
| 禁止表述 | 未使用「G1关节挥手 / 上肢控制策略 / 全身控制策略 / PPO全身策略」 |

---

## 12. Geometry 210–280 分布

| 指标 | 值 |
|---|---|
| n_steps | 71 |
| ALLOW | 70 |
| SLOW_DOWN | **1**（step **213**，`dynamic_ttc_warning: 0.791s`） |
| STOP | 0 |
| replan | 0 |
| dist_min / mean / max | 0.906 / 0.944 / 0.971 m |
| capture steps gate | 210=ALLOW，280=ALLOW；TTC 未在两帧触发 |

正式门禁按窗口全 ALLOW → **GEOMETRY_WINDOW_FAIL**。

---

## 13. 完整 episode gate 摘要

| gate | count |
|---|---|
| ALLOW | 493 |
| STOP | 5（steps 85,93,115,126,147；均为早期 `dynamic_ttc`） |
| SLOW_DOWN | 2（150, 213） |

早期 STOP/SLOW 单独报告；**不隐藏**。正式 Dyn-A 数据门禁以 210–280 为准。

---

## 14. POST=0 证明

见 `meta/post_count_proof.json`：`VLM: OFF`、无 VLMClient/PerceptionClient 初始化、capture 命令无 `--vlm`/`--virtual-hand`、POST=0。

---

## 15. Xid 前后

`meta/xid_before_capture.txt` / `xid_after_capture.txt`：`nvidia-smi -q -d Xid` 不可用；`dmesg` 未见新 `NVRM: Xid`。

---

## 16. 历史资产未覆盖

- 未改写 D1A/D1B/D2B 结果树
- 未覆盖镜像 `defe95e…` / `f81e59ce…`
- B0–B4 `paper_scenarios/*.yaml` SHA 校验通过（单测）

---

## 17. git diff / status

本轮新增/修改（未 commit、未 push）：

- `g1_ur10e_disturbance/scene_camera_override.py`
- `g1_ur10e_disturbance/e01_dyn_a_capture.py`
- `g1_ur10e_disturbance/dual_env_cfg.py`（camera override 接线）
- `g1_ur10e_disturbance/scripts/run_phase3.py`（save_camera）
- `g1_ur10e_disturbance/scripts/test_e01_dyn_a_capture_unit.py`
- `g1_ur10e_disturbance/scripts/analyze_e01_dyn_a_capture.py`
- `g1_ur10e_disturbance/scripts/run_e01_dyn_a_capture.sh`
- `g1_ur10e_disturbance/configs/e01_dyn_a_capture.yaml`
- `g1_ur10e_disturbance/docker/Dockerfile.e01-dyn-a`
- 本文档 + JSON

详见 `results/.../meta/git_status.txt` / `git_diff_stat.txt`。

---

## 停止边界

- **不**执行 SAM2 两帧验证
- **不**执行 VLM 筛选
- **不**执行 Func-C / Dyn-B
- **不** push
- **不**调参重跑本 capture

若后续另批授权：可讨论是否先改 capture step（避开纯 stand）或先采 Func-C；**不得自动连跑**。
