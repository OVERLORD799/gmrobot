# V1-D0 真实 semantic positive 场景与 live-window 可行性审计（2026-07-22）

## 结论摘要

| 项 | 判定 |
|---|---|
| V1-C1R-P1 负样本根因 | VLM 两帧均为 **`static`** + 低置信度；supervisor 在 risk_type 门拒掉；**未形成 semantic_key** |
| live-window 失败根因 | `max_steps=120` 墙钟约 **8.7s** 结束，而 cold/排队 pipeline 需 **~20–25s** → 两帧仅在 **shutdown_drain** 落盘 |
| 几何门 | drain 时 `g_rule=2`（SLOW_DOWN）；P1 默认 Layer-1 后期多为 SLOW |
| RGB | **本轮未落盘原始 RGB**（仅结构化日志）；视觉先验可参考 `v0b1_rgb_capture` 同场景俯视图 |
| V1-D1 实施条件 | **有条件具备**：时间窗与 ALLOW 几何可工程化；**最大残差是 VLM 自发产出稳定 dynamic/functional@≥0.85 且同 key**（禁止伪造/synthetic 论文证据） |
| 推荐场景 | **远场走廊手球持续横向运动**（现有 `human_hand` + 新建 IV-J 轨迹 YAML，无新 USD） |
| 本轮 | 只读设计；**不编码、不跑 Isaac、不 POST、不进 active、不进 V1-D1 执行** |

---

## 一、V1-C1R-P1 证据审计

### 1.1 可用产物 / 缺口

| 产物 | 状态 |
|---|---|
| VLM 结构化输出 | 有（`five_stage_shadow_requests.jsonl`×2） |
| keywords / detections / track | 有 |
| semantic decisions | 有（`risk_type_not_allowed`×2） |
| capture / completion / decision | 有 |
| 原始 RGB artifact | **无**（P1 未开 camera dump） |
| 同场景 RGB 先验 | `results/paper_demo/v0b1_rgb_capture_20260721/scene/*.png`（俯视 `scene_rgb`） |

冻结镜像：`gmdisturb:semantic-shadow-v1c0p1-20260722` / `sha256:f81e59ce…de4ddde7c`。

### 1.2 两帧 VLM / perception / rejection

| | Frame0 (`sim_step=0`) | Frame1 (`sim_step=50`) |
|---|---|---|
| risk_type | **static** | **static** |
| risk_confidence | **0.3** | **0.2** |
| suggested_action | slow_down | slow_down |
| affected_entities | robotic arm, device | robotic arm, container |
| spatial_hint | left | above |
| ground detections | 10（非空） | 2（非空） |
| track | `initialized`, track_id=0 | `tracking`, track_id=0 |
| rejection | `risk_type_not_allowed` | `risk_type_not_allowed` |
| logged `semantic_key` | `""`（risk 门前拒绝） | `""` |

假设若通过 risk 门，按 `build_semantic_key` 重算：

- F0: `static|slow_down|device|robotic arm|collision|left`
- F1: `static|slow_down|container|robotic arm|collision|above`
- **不一致**（entities + spatial_hint 均不同）

即便放宽 static（**本设计禁止**），仍会卡在 `min_risk_confidence=0.85` 与 key 一致性。

### 1.3 时间线（P1 实测）

| 量 | 值 |
|---|---|
| control_dt / 名义 50 Hz | 0.02 s/step |
| five-stage `inference_hz` | 1.0 → **interval=50** |
| `queue_size` | 1 |
| 墙钟 ms/step（由 e2e−qwait 反推） | **≈72.2 ms/step** |
| 120 step 纯推进 | **≈8.66 s** |
| Frame0 e2e（cold） | **19561 ms**（ground 13118） |
| Frame1 queue_wait | **15951 ms** |
| Frame1 纯处理（warm） | **5502 ms** |
| drain | started after step 120；elapsed **16.47 s**；`geometry_gate_reason=shutdown_drain` |
| decision | 两帧均在 **sim_step=120** 消费 |

提交：`0` → `50`。因 cold 未完成，step 50 提交后第二帧在队列等待 ~16 s；两帧 completion 均晚于 step 120 → **只能在 shutdown flush**。

### 1.4 审计问答

**1. 为何非允许 risk type？**  
场景视觉为机械臂+静态容器/装置；VLM 输出 `risk_type=static`。配置 `reject_static_risk_in_v1=true` 且 `allowed_risk_types=[dynamic,functional]` → `risk_type_not_allowed`。另 confidence 远低于 0.85（未评到该门）。

**2. 两次 semantic_key 是否一致？**  
日志均为空。假设键 **不一致**（见上）。

**3. 若只延长 episode，第二帧预计在哪个 live sim step 到达？**  
保持 P1 冷启动+interval=50：第二帧 completion ≈ step **`⌈25063/72.2⌉≈347`**（随后同一步 poll→enqueue→flush）。  
若 **独立 warm-up 后** 双帧均 warm：completion1 ≈ step **152**（见下节预算）。

**4. 保证两帧都在控制环内完成的最少 max_steps / 墙钟？**  
| 模式 | 第二帧完成 step | +≥50 live | 建议 max_steps | 墙钟（步进+处理，不含 Kit 启动） |
|---|---|---|---|---|
| cold 首帧（不推荐） | ~347 | ≥397 | **≥420** | ~30 s 处理 + ~30 s 步进 |
| **warm 双帧（推荐）** | ~152 | ≥202 | **≥280**（裕度） | ~11 s 处理 + ~20 s 步进 |
| warm + interval=100（减排队） | ~176 | ≥226 | **≥280** | 略增 |

另加 Kit/环境启动 ~20–25 s；drain 仅作收尾保险，**不得**作为 advisory 主路径。

**5. warm 总 pipeline latency？**  
P1 Frame1：`VLM 4799 + ground 473 + track 230 ≈ 5502 ms`（与 e2e−qwait 一致）。  
**预计 warm e2e ≈ 5.0–6.5 s/帧**（含抖动）。

**6. scheduler interval 是否造成第二帧排队？**  
**会。** interval=50、queue_size=1、warm≈5.5 s（≈76 step）时，step 50 提交时 worker 仍忙 → 排队。  
缓解：正式前 warm-up；或 D1 将 `inference_hz=0.5`（interval=100）使第二提交落在首帧完成之后。

**7. 如何避免 advisory 到达时几何门已是 SLOW/STOP？**  
- P1 用 **default** Layer-1，进度样本中后期 **g_rule=2 占优**，drain 时即为 SLOW。
- D1 必须换 **远场轨迹 safety YAML**，使 capture→decision 窗内 `dist ≥ warn` 且 `TTC ≥ ttc_warn` → **ALLOW=0**。
- 避开 `held_critical`、static hard-stop、近场 B2 式 TTC 扫掠。
- 要求 `geometry_gate_reason=geometry_l1`（非 `shutdown_drain`），且 `g_rule=0`。

---

## 二、候选场景（≤3）

### 候选 A（推荐）：远场走廊手球持续横向运动

| 项 | 内容 |
|---|---|
| 资产 | 现有 kinematic **`human_hand`** 红球；UR10e+双容器；**无新 USD** |
| 相机 | 俯视 `scene_rgb`；走廊在 FOV；红球横向穿越应清晰（对比度高） |
| 为何 dynamic | 连续两帧可见位移/朝向变化；通道内运动体 → 期望 `dynamic` + 碰撞类 consequence |
| 几何 ALLOW | 轨迹保持 EE–手距离 **>0.25 m**（高于 warn 0.16），速度使 TTC≥1.5；参考拉远版 `ivj_static_far_observer` / 远场化 `linear_approach` |
| 避混淆 | **非**论文 B1 静态占位；**非** `ivj_dynamic_fast_sweep` 近场 TTC；**非** held 抓取窗；不依赖 B2 TTC 门 |
| 可复现风险 | **VLM 仍报 static/低置信**；两帧 entities/hint 漂移导致 key 不一致 |
| 新资产/脚本 | **仅需新 safety YAML**（轨迹参数）；不改代码/阈值/prompt/模型 |
| 预计 | max_steps≈280；墙钟步进+推理 ~40–60 s（+启动）；**POST=6**（+可选预热 1×ground 不计正式） |

### 候选 B：容器口功能性阻塞（手球挡 B 口远缘）

| 项 | 内容 |
|---|---|
| 资产 | 同上 + 静态 `box_B` |
| 相机 | B 口可见，但俯视对“阻塞”语义弱 |
| 为何 functional | 阻挡放置/通道功能 |
| 几何 ALLOW | 若手距 EE 仍远可 ALLOW；但易被 VLM 标 **static**，或贴近触发 static SLOW |
| 避混淆 | 易滑向论文 B1 / `ivj_static_block_place` |
| 风险 | functional 标签不稳定；与 static 难分 |
| 新脚本 | 需新 YAML |
| POST | 6 |

### 候选 C：持件轨迹交叉趋势（远场掠过未来路径）

| 项 | 内容 |
|---|---|
| 资产 | `human_hand` + 任务 carry 段 |
| 相机 | 可见，但需对齐 task_ts |
| 为何 dynamic | 与未来 EE 路径交叉趋势 |
| 几何 ALLOW | 必须 **早于** TTC warn；一旦进 `ivj_dynamic_fast_sweep` 类近场 → 违反“不依赖 B2 TTC”且几何易非 ALLOW |
| 风险 | 与 Layer-1 TTC / 论文 B2 **高混淆**；时间耦合紧 |
| POST | 6 |

### 对比与推荐

| | A 远场横移 | B 功能阻塞 | C 路径交叉 |
|---|---|---|---|
| 零新 USD | ✓ | ✓ | ✓ |
| ALLOW 可控性 | **高** | 中 | 低 |
| 避 B1/B2/held | **好** | 偏差 | 差 |
| VLM dynamic 概率 | 中 | 低 | 中高但危险 |
| **推荐** | **是（最小最稳）** | 备选 | 不推荐作 D1 |

**推荐方案 = 候选 A。**

---

## 三、live-window 设计（草案，不执行）

### 3.1 参数建议

| 参数 | 建议值 | 说明 |
|---|---|---|
| image | `gmdisturb:semantic-shadow-v1c0p1-20260722` (`f81e59ce…`) | 冻结 |
| max_steps | **280** | 覆盖 warm 第二帧 ~152 + ≥50 live + 裕度 |
| capture/submit | step **0**, **50**（保持 interval=50）或 **0**, **100**（`inference_hz=0.5` 减排队） | 默认先 **0/50 + warm-up** |
| max_submissions | **2** | 不变 |
| shutdown_drain_timeout_s | **60** | 仅收尾；advisory 不得依赖 drain |
| 独立 warm-up | **需要** | 正式计时前 1× perception `/ground`（或等价）使 `models_loaded=true`；**不计入**正式 6 POST；**不**伪造 VLM |
| 阈值/risk allowlist/prompt/模型 | **不改** | 约束 |
| seed | agent **无 --seed**；记录 boot/镜像/config SHA 作复现锚点 | — |
| 任务阶段 | 早期 transport/approach；手球远场连续运动，**避开 grasp held 窗** | — |
| 几何 ALLOW 窗 | 全程目标 `g_rule=0`；至少覆盖两帧 decision step ±10 | safety=`ivj` 远场 YAML |
| 结果目录 | `results/paper_demo/v1d1_isaac_semantic_positive_shadow_20260722/` | **不覆盖** P1 |
| five-stage cfg | `configs/five_stage_shadow_legacy_gateway_v1d1.yaml` | 仅 log_dir（+可选 hz） |
| semantic cfg | `configs/semantic_safety_supervisor_shadow_v1d1.yaml` | 仅 log_dir；阈值同 P1 |
| safety cfg | `configs/ivj/ivj_v1d1_far_corridor_motion.yaml`（待建） | 仅轨迹/距离 |

### 3.2 预计 capture → completion → decision

假设：**预热完成** + interval=50 + ~72 ms/step：

| 事件 | sim_step（估） | 墙钟偏移 |
|---|---|---|
| submit0 | 0 | 0 |
| complete0 / live decision0 | **~76** | ~5.5 s |
| submit1 | 50 | ~3.6 s |
| complete1 / live decision1 | **~152** | ~11.0 s |
| post-advisory live | 153→**≥202** | — |
| stop | **280** | — |

`geometry_gate_reason` 必须为 **`geometry_l1`**；`result_age_s`≪`max_result_age_s=2.0`（同一步 poll+flush）。

首条过 risk 门后多为 `consistency_pending`；第二条同 key → **`accepted=true`**，`evaluated_semantic_gate=SLOW_DOWN`，`effective_control_gate=ALLOW`。

### 3.3 POST 预算

| 阶段 | POST | 计入正式≤6？ |
|---|---|---|
| 可选独立 warm-up ground | 1 | **否**（预检，需在 runbook 标明） |
| 正式 frame0 | VLM+ground+track_init | 3 |
| 正式 frame1 | VLM+ground+track_step | 3 |
| **正式合计** | **6** | 是 |
| 重试/第三帧 | 0 | 禁止 |

---

## 四、V1-D1 门禁草案

### 硬门禁（任一失败 → FAIL，不重试调参伪造）

1. Isaac exit=0；PROGRESS=`max_steps`；无 Traceback/ModuleNotFound；无 DEVICE_LOST/pagefault；boot 无新 Xid
2. POST≤6；顺序两帧三段；无重试/第三帧
3. `submitted=processed=logged=2`；两帧 `pipeline_ok=true`；detections 非空；track 连续
4. **`synthetic=false`**（两条）
5. 至少一条 **`accepted=true`**；另一条可为 `consistency_pending` 或亦 accepted
6. 两条计入一致性的结果 **`semantic_key` 相同且非空**
7. accepted 条：`risk_type∈{dynamic,functional}`；`confidence≥0.85`；`suggested_action=slow_down`
8. accepted 决策：`geometry_gate=ALLOW`（0）；`geometry_gate_reason=geometry_l1`（**非** shutdown_drain）
9. `evaluated_semantic_gate=SLOW_DOWN`；`effective_control_gate=ALLOW`（shadow 隔离）
10. **`advisory_processed_during_live_loop=true`**（decision_sim_step < max_steps，且 reason≠shutdown_drain）
11. **`post_advisory_live_steps≥50`**（最后一次 live advisory 的 decision_sim_step 之后仍推进 ≥50）
12. `control_hash_mismatch_count=0`；semantic leakage 五项=0；five-stage leakage 五项=0
13. drain_complete；pending_end=0；dropped=0；worker 停；脱敏泄漏=0
14. **task/progress 不因 shadow 改变**（无 semantic 导致的 gate/action/clock/replan 副作用）
15. 不覆盖 V1-C1R-P1；不修改冻结 B0–B4；无关节/力矩直控

### 软观察（不单独否决，但写入报告）

- cold/warm latency 分列
- VLM 两帧 keywords 稳定性
- ALLOW 窗内 g_rule 时间序列

---

## 五、是否具备实施条件

| 维度 | 状态 |
|---|---|
| 镜像 / canonical import | 具备（P1 PASS） |
| live-window 时间预算 | 具备（warm-up + max_steps≥280） |
| ALLOW 几何工程化 | 具备（远场 IV-J YAML） |
| 阈值不放宽 / 无伪造 | 设计遵守 |
| **VLM 自发正例** | **残差风险（主不确定项）** |
| 总体 | **CONDITIONAL_GO**：可进入 V1-D1 **实施准备**（写 YAML/runbook），但正式跑需另批；若 VLM 持续 static → 记 FAIL 并停，不调阈值、不 synthetic 充数 |

---

## 六、git diff --stat（审计时点）

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

本轮仅新增本设计文档/JSON；**未改代码、未跑实验**。

---

## 七、停止声明

V1-D0 审计完成。**不编码、不运行 Isaac、不发送 POST、不进入 active control、不执行 V1-D1。**
