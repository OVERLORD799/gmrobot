# V1-D1B 功能性阻塞正例——0-POST RGB/几何采集（2026-07-22）

## 最终判定：**GEOMETRY_OVERLAP**

| 项 | 值 |
|---|---|
| reason | **`capture_live_window_not_allow`** |
| Isaac exit | **0** / steps **280** / POST **0** |
| 世界坐标阻塞 | **成立**（`part_20 @ B@10` ∈ container B AABB） |
| 投影 ROI | target/blocker 可见；blocker⊂target ROI（fraction=1.0） |
| geometry 窗 [0,150] | ALLOW 125 / SLOW 24 / STOP 2 → **失败** |
| 全剧 | ALLOW 254 / SLOW 24 / STOP 2 |
| min margin vs warn | **+0.328 m**（距离裕度正，但仍有 **TTC** 触发） |
| 2-POST 筛选 | **不具备** |
| 重跑调参 / VLM / 正式 D1 | **否** |

### 历史边界（保留）

| 项 | 状态 |
|---|---|
| V1-D1A FAIL | **保留未覆盖**（`v1d1a_far_corridor_capture_20260722/`） |
| D1A 原因 | `geometry_not_allow_throughout` + `visual_semantic_risk=low`（红球） |
| 本轮 | **未**改 D1A warn/半径/轨迹/阈值 |

---

## 1. 资产候选与选择

| ID | 组合 | 可识别性 | 碰撞 | 几何风险 | 占用语义 | 结论 |
|---|---|---|---|---|---|---|
| A | `part_5000.usd`→`B@10` + `container.usd` box_B + 远场停手 | 工业零件/绿箱清晰 | 零件有 rigid；L1 **不看零件** | 手须远离 | **明确 occupied slot** | **选用** |
| B | `container_full.usd` 替换 box_B | 「满箱」强 | 同箱类 | 手须远离 | 强 | 备选（首次接线风险） |
| C | 红球挡 B（FAR block_place） | 低（primitive） | L1 看手 | 早期可 ALLOW | 弱且 D1A 禁区 | **否决** |

**选择 A**：零新 USD；语义不是红球；世界坐标可证明 blocker∈B。

**非 NO_SEMANTIC_ASSET**：现有零件/容器足够可识别；仅需 opt-in 重定位（`GMROBOT_V1D1B_FUNCTIONAL_BLOCK=1`）。

场景语义：「当前 EE–手距离仍大，但目标放置区 B 已被现有零件占用 → 功能性阻塞风险」。

---

## 2. 改动文件

| 路径 | 说明 |
|---|---|
| `GMRobot/configs/ivj_v1d1b_functional_blockage.yaml` | 远场静止手；阈值未放宽 |
| `.../gmrobot_env_cfg.py` | opt-in：`PART_LOCATIONS[19]="B@10"` |
| `shadow/v1d1b_capture.py` | 阻塞度量/ROI/manifest |
| `scripts/build_v1d1b_capture_manifest.py` | 离线 manifest |
| `scripts/test_v1d1b_functional_blockage_capture_unit.py` | 单测 |

运行：bind-mount YAML+env_cfg + `-e GMROBOT_V1D1B_FUNCTIONAL_BLOCK=1`；**未新建镜像 tag**（`f81e59ce` 未覆盖）。

---

## 3. 测试结果

| 项 | 结果 |
|---|---|
| 全部 `test_*unit.py` | **33/33 OK** |
| D1B unit | **PASS** |
| canonical / 1-step smoke | exit=0，`g_rule=0`，POST=0 |
| capture 门禁 | **GEOMETRY_OVERLAP** |

---

## 4. image / config / layout SHA

| 项 | 值 |
|---|---|
| image | `gmdisturb:semantic-shadow-v1c0p1-20260722` / `sha256:f81e59ce…de7c` |
| safety cfg SHA | `4f6fe11502bdbfc97ccbf179ad4a182ef096004e79a1ca3c2dbf06d28f9a9c12` |
| env_cfg SHA（host） | `a52d025313b1183977986d7a6c7550ecb06e17d7835df156b3670d19cbd93841` |
| scene_layout_hash | `be113b6045e87a3182aa1bef3760f47a6b2199c0b0ece627fd8f9547b8a76f7f` |
| blocker | `part/part_5000.usd` @ `B@10` ≈ `(0.75, 0.215, 0.17)` |
| hand park | `(0.25, -0.75, 0.60)`（**非**语义证据） |
| seed | agent 无 `--seed` |

---

## 5–7. Isaac / RGB

| 项 | 值 |
|---|---|
| exit / steps | **0** / **280** |
| RGB | `scene/frame_000000_env0.png` / `frame_000100_env0.png` |
| SHA | `39eb1853…8e8b` / `3fdafcbb…fe11`（不同） |
| 相机 | 俯视 `scene_rgb` 640×480 uint8；UR10e + 双绿箱可见 |

---

## 8–9. ROI / 阻塞关系

| step | blocker∈B (AABB) | blocker ROI area | target visible | screen overlap fraction |
|---|---|---|---|---|
| 0 | **true** | 361 | true | **1.0** |
| 100 | **true** | 361 | true | **1.0** |

确定性指标：`aabb_containment_container_B` + `blocker_fraction_inside_target_roi`。

---

## 10–13. 几何 / gate / live steps

| 项 | 值 |
|---|---|
| warn/hard/ttc | **0.16 / 0.13 / 0.5**（未改） |
| margin 分布 | min **0.328** / p50 **0.420** / max **0.867** |
| 窗内 gate | STOP **2** + SLOW **24**（早期 **`dynamic_ttc*`**，对手球速度） |
| STOP/SLOW/replan 全剧 | 2 / 24 / **0** |
| post_capture_live_steps | **180**（≥50 满足，但几何窗已失败） |

---

## 14–16. POST / leakage / Xid

- POST=**0**（无 five-stage/semantic/VLM 初始化）
- leakage 全 **0**；`control_hash_mismatch_count=0`
- Xid **0→0**

---

## 17. 是否具备 2-POST VLM-only 筛选

**否**（`GEOMETRY_OVERLAP`）。虽世界坐标阻塞成立且 RGB 含箱/零件上下文，capture live 窗未全程 ALLOW → 按门禁停止，不发 VLM。

---

## 18. git diff --stat（tracked）

```
 .../gmrobot_env_cfg.py |   5 +
 (+ 历史未提交的 perception/vlm/agent 等变更；本轮另增 D1B YAML/工具/单测 untracked)
 10 files changed, 616 insertions(+), 80 deletions(-)
```

---

## 结果路径

`results/paper_demo/v1d1b_functional_blockage_capture_20260722/`  
文档：`docs/cross-project/vlm-v1d1b-functional-blockage-capture-2026-07-22.md` + `.json`

## 停止声明

**不执行 2-POST 筛选；不运行正式 D1；不调阈值重跑；不进入 active 控制。**
