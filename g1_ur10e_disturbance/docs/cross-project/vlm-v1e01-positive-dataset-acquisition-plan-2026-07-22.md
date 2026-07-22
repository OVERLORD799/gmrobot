# V1-E0.1 正样本数据采集可行性设计（2026-07-22）

## 本轮边界

| 项 | 约束 |
|---|---|
| 性质 | **仅设计**；不采集、不跑 Isaac、不启 Docker、不 POST |
| 网络 / VLM / perception | **0** |
| 安全阈值 | **不修改**（warn/hard/TTC/0.85 全冻结） |
| active / 手套 PPE | **否** |
| 历史 FAIL | **不改写**（D1A / D1B GEOMETRY_OVERLAP / D1B-S / D2B 等） |
| 结果目录 | **不创建**实验结果树；本轮仅文档+JSON |

**目标（采集获批后才执行）**：≥2 个独立 dynamic 场景组 + ≥1 个新 functional 场景组；每组 ≥2 帧真实 Isaac RGB；dynamic 后续可真实 SAM2 tracking 验证。

---

## 只读检查结论（10 问）

### 1. 现有 G1 `arm_wave` / wander / 上肢脚本能否复用？

| 资产 | 位置 | 可复用性 | 诚实标注 |
|---|---|---|---|
| `arm_wave` | `g1_disturbance_controller.py` → `ARM_WAVE_PHASES` | **可复用 CLI**（`run_phase3 --scenario arm_wave`） | **不是**关节级挥手；是 **scripted 步行速度相位**（approach/settle/stand/retreat） |
| `arm_collision` | 同上 | 可复用，但更易靠近包络，E0.1 **不推荐**作 ALLOW 窗 | 同上，locomotion |
| `constrained_wander` | 默认随机 wander | 可复用，但随机性差、位移不可复现 | 非 scripted 相位 |
| 上肢关节脚本 | **不存在** | 当前 walk policy（`0121_walk.pt`）**不支持**物理臂关节控制；注释已写明 | 若要真·手腕/前臂关节横向运动 → **需新运行时代码**（非本轮） |

**结论**：Dynamic A 允许复用 `arm_wave`，但论文/manifest 必须标 `motion_source=scripted_g1_locomotion_arm_wave`，**禁止**宣称全身策略或关节挥手。

### 2. 是否需要全身控制？为何 scripted 运动对视觉数据足够？

**不需要全身策略。** 评估目标是 VLM/SAM2 的 **screen-space 动态证据**，不是 G1 策略性能。

- scripted locomotion 已能让 **可见的 G1 躯干/手腕** 在 scene RGB 中产生可测位移；
- SAM2 跟踪的是像素轨迹，不依赖关节 torque 真实性；
- 全身 RL/遥操作会引入不可复现与阈值耦合，违反「scripted 可复现」与「不改阈值」。

关节级 arm script 是 **增强项**（提高「上肢」语义清晰度），**不是** E0.1 硬前置。

### 3. 现有 scene camera 能否同时看到 G1 与 UR10e 任务上下文？

| 环境 | camera | 默认 pose | 共视结论 |
|---|---|---|---|
| GMRobot 单机 | `scene_camera` @ `(0.35,0,2.5)` | 俯视桌面/容器/UR10e | **无 G1**（仅有红球 `human_hand`） |
| Dual `G1-UR10e-Disturbance-v0` | `scene_camera` @ `(1.0,0,3.0)` | hfov≈60°，地面足迹约 x∈[-0.75,2.75] | UR10e+容器 **在视场内**；G1 初值 `(-1.5,0,*)` **在足迹外/边缘** |

**结论**：默认 dual 俯视在 G1 **走近 x≈0 后**可共视；起步帧可能裁切 G1。Dynamic 采集应在 G1 进入足迹后再 dump，或采用独立 camera pose（见下）。

### 4. 是否需要独立 camera pose？

**强烈建议（Dynamic A/B）**：将 dual `scene_camera` 临时改为例如 **`(0.2, 0.0, 3.2)`**（同 rot `(0.7071,0,0.7071,0)`），使 x≈[-1.1,1.5] 覆盖 G1 接近段与 A/B 箱。

- Functional C（GMRobot 单机）：**可保持**现有 `(0.35,0,2.5)`（与 V0-B1/D1B 一致，利于对比）。
- 独立 pose 仅用于 capture YAML/配置覆盖，**不改**冻结物理基线阈值。

### 5. G1 运动与 UR10e 包络最小距离预估

历史 Phase5：`arm_wave` / wander 的 **min_dist ≈ 0.5–0.9 m**（G1 难进 MODERATE）。几何估算（腕/躯干代理 ≈(x,y,0.8)，EE≈(0.75,±0.25,0.2)）：

| G1 位置 | 至 EE 估计 | vs warn 0.16 / hard 0.13 |
|---|---|---|
| 初值 (-1.5,0) | ~2.1–2.3 m | 远场 |
| 走廊外 (0,-0.6) | ~0.9–1.3 m | **≫ warn** |
| 边缘 (0,0) | ~0.7–1.0 m | **≫ warn** |
| 过近 (0.2,0.6) | ~0.8–0.9 m | 仍大，但更易进画面 |

**预估 capture 窗 geometry margin：≥ +0.45 m（相对 warn）**，前提是 G1 不进入 x≳0.3 且不伸入 A↔B 通道。  
注意：Phase5 的 STOP/SLOW **常来自 UR10e 任务内规则/TTC**，非 G1 接近 → 必须用 **逐步几何门过滤**，不能假设「整 episode ALLOW」。

### 6. 可复用的 container / bin / part 资产

| USD | 路径 | E0.1 用途 |
|---|---|---|
| `container.usd` | `GMRobot/.../assets/container.usd` | 默认 A/B（D1B 已用） |
| **`container_full.usd`** | 同目录 | **Functional C 首选**（D1B 文档备选 B，尚未作独立 run） |
| `container_with_grid.usd` / `container_part.usd` | 同目录 | 备选视觉变体 |
| `part/part_5000.usd` | 同目录 | D1B 占用件；C **勿再依赖同一定位语义** |
| 红球 `human_hand` SphereCfg | `gmrobot_env_cfg.py` | Dynamic **禁用**（D1A 教训）；Functional 仅可远场停放、不作证据 |

### 7. 每候选预期 ROI / 位移 / geometry margin

| 候选 | 预期主体 ROI（640×480） | 帧间位移 | geometry margin |
|---|---|---|---|
| Dyn-A | G1 躯干+腕合计 **≥800 px²**（门槛建议 ≥400） | stand 前后或 approach→stand **≥40 px** 质心 | ≥ +0.45 m vs warn |
| Dyn-B | 同上，侧向巡逻时腕/肩 **≥600 px²** | y 向扫过 **≥60 px** | ≥ +0.50 m（更远侧通道外） |
| Func-C | `container_full` box_B **≥2500 px²**；满箱纹理可辨 | 功能正例不要求大位移；两帧可静 | 手远场；窗内 ALLOW（吸 D1B TTC 教训） |

### 8. 新运行时代码 vs 仅 YAML？

| 候选 | 最小改动 |
|---|---|
| Dyn-A | **以 YAML/CLI 为主**：既有 `arm_wave`；建议 **camera pose 覆盖**（小配置或 env 覆盖，非阈值） |
| Dyn-B | **需小代码**：新增 scripted phases（如 `lateral_outside_corridor`）挂到 `SCENARIOS`；或严格约束的 wander seed（弱） |
| Func-C | **需小代码 + YAML**：仿 D1B 增加 `GMROBOT_V1E01_TARGET_FULL=1`，将 `box_B` 指到 `container_full.usd`；手远场 YAML |

纯 YAML **不足以**完成「非红球 G1 dynamic ×2 + 独立于 D1B 的 full-container functional」。

### 9. 每场景预计 Isaac 运行时间

| 候选 | max_steps（建议） | 物理名义 | 墙钟粗估（含 Kit 冷启 ~20–25 s） |
|---|---|---|---|
| Dyn-A | 450–600（覆盖 stand） | ~9–12 s @ 50 Hz | **~45–70 s** |
| Dyn-B | 500–700（双侧向扫） | ~10–14 s | **~50–80 s** |
| Func-C | 280–320（对齐 D1B 捕获节奏） | ~6 s | **~40–60 s** |

合计（串行、单次通过）：**约 3–5 min** Isaac 墙钟；**0 POST**。

### 10. 后续 SAM2 验证 POST 预算（采集后、另批）

采集阶段：**0 POST**。  
验证阶段（仅 dynamic 两组，每组 2 帧）：

| 步骤 | 每组 | 两组合计 |
|---|---|---|
|（可选）ground | 0–1 | 0–2 |
| track_init | 1 | 2 |
| track_step | 1 | 2 |
| **建议上限** | | **≤6 POST**（不含 VLM）；若加 VLM 语义筛另计 |

Functional C：SAM2 非硬门；若做占用旁证最多 +2 POST（可选）。

---

## 推荐 3 候选（2 dynamic + 1 functional）

### 总表

| ID | 类型 | 平台 | 推荐 | 论文可解释性 |
|---|---|---|---|---|
| **E01-Dyn-A** | DYNAMIC | Dual + `arm_wave` | **是** | 高（须标 scripted locomotion） |
| **E01-Dyn-B** | DYNAMIC | Dual + 外侧侧向巡逻 | **是** | 高（无红球/无文件名证据） |
| **E01-Func-C** | FUNCTIONAL | GMRobot + `container_full` | **是** | 高（与 D1B 资产语义正交） |

---

### 候选 E01-Dyn-A — scripted `arm_wave` 远场可见 G1

| 字段 | 设计值 |
|---|---|
| **asset 路径** | Dual：`Robot_G1`（`G1_927_WALK_CFG`）+ UR10e + `container.usd` A/B + `part_5000` 默认布局；**禁用**红球证据 |
| **motion 来源** | `ARM_WAVE_PHASES`（`g1_disturbance_controller.py`）；标签 **`scripted_g1_locomotion_arm_wave`**；非全身策略、非关节挥手 |
| **camera pose** | 建议覆盖：`pos=(0.2, 0.0, 3.2)`，`rot=(0.7071, 0, 0.7071, 0)`；fallback 默认 `(1,0,3)` 但仅在 G1∈足迹后采帧 |
| **seed** | `42`（固定；写入 manifest） |
| **capture steps** | 建议 dump：`210`（settle末）、`280`（stand 中）；interval 对齐；≥2 帧；均须 G1 ROI 达标 |
| **geometry 预检** | 捕获步：`g_rule=ALLOW`；该步 STOP/SLOW/replan=0；G1–EE **≥0.45 m** 相对 warn；不改阈值 |
| **预期 artifact** | `scene/frame_XXXXXX.png`×≥2；`manifest.jsonl`（ROI、质心、位移、motion 标签、SHA）；safety step 摘要 |
| **失败停止条件** | G1 不可辨 / ROI&lt;400 / 位移&lt;40 px / 捕获步非 ALLOW / 误用红球 / 任何 POST |
| **论文可解释性** | **具备**（动态障碍为真实人形机器人进入任务俯视；须披露 scripted walk） |

### 候选 E01-Dyn-B — 走廊外侧接近/离开（无红球）

| 字段 | 设计值 |
|---|---|
| **asset 路径** | 同 Dual G1+UR10e+标准容器零件；**禁止** `human_hand` 红球作动态证据 |
| **motion 来源** | **新建** scripted phases（建议名 `lateral_outside_corridor`）：在 x≤0、\|y\| 扫过通道外侧接近→离开；**不得**用文件名/不可见 proxy |
| **camera pose** | 与 Dyn-A 相同独立 pose，保证侧向全程入画 |
| **seed** | `43`（与 A 独立场景组） |
| **capture steps** | 例：侧向中点与折返点各 1 帧（具体步号在接线后由相位表锁定，设计预留 `t0/t1`） |
| **geometry 预检** | 捕获窗 ALLOW；G1 保持在 A↔B 通道外；margin **≥ +0.50 m**；STOP/SLOW/replan=0 |
| **预期 artifact** | 同 A；manifest 显式 `geometry_allow=true`、`proxy_type=none`、`evidence=g1_upper_body_rgb` |
| **失败停止条件** | 红球入证据链 / 位移不足 / 进入通道导致 margin 崩塌 / 与 Dyn-A 同 run 邻帧 |
| **论文可解释性** | **具备**（「任务走廊外动态接近」；与 A 运动原语正交） |

### 候选 E01-Func-C — `container_full` 目标箱不可用（≠ D1B）

| 字段 | 设计值 |
|---|---|
| **asset 路径** | `box_B` → **`container_full.usd`**；`box_A` 仍 `container.usd`；零件保持默认 A 槽（**不**启用 `GMROBOT_V1D1B_FUNCTIONAL_BLOCK`）；手远场停放（同 D1B 思想，非证据） |
| **motion 来源** | 无动态证据要求；UR10e 名义 pick/place 策略；手 `hold` 远场 |
| **camera pose** | GMRobot 默认 `(0.35, 0, 2.5)`（与 D1B 可比，但 **独立 run/目录/seed**） |
| **seed** | `51` |
| **capture steps** | `100`、`200`（节奏对齐 D1B，但 **禁止**写入 D1B 结果树；新 run id） |
| **geometry 预检** | 吸取 D1B：捕获窗 **必须全程 ALLOW**（延长远场/延后早期 TTC 敏感段，**不**改 warn/hard 数值）；STOP/SLOW/replan=0 |
| **预期 artifact** | RGB×≥2；manifest：`blocker_asset=container_full.usd`、`scene_group=e01_func_c`、`independent_of=d1b` |
| **失败停止条件** | 与 D1B 同 run/邻帧组 / 仍用 part@B@10 作为主证据 / 几何窗非 ALLOW / POST≠0 |
| **论文可解释性** | **具备**（「放置目标容器视觉上已满/不可用」；资产组合与 D1B 零件占用正交） |

---

## 硬门禁（采集执行时）

1. G1 或功能物体在 scene RGB 中清晰可识别
2. ROI ≥ 预设最低值（上表）
3. dynamic：screen displacement 明显
4. capture 窗口 geometry=ALLOW
5. STOP/SLOW/replan=0（捕获步）
6. 不修改安全阈值
7. 不使用手套/PPE
8. 不发送 VLM/perception POST
9. 不运行 active 控制
10. 不改写历史失败结果

---

## 明确不选 / 降级项

| 项 | 原因 |
|---|---|
| D1A 红球横向扫 | `visual_semantic_risk=low`；禁止作 dynamic 正例 |
| 复用 D1B 邻帧扩组 | 违反「新 functional 独立场景组」 |
| `ivj_functional_misgrasp` | 手入近场 → 几何/STOP 风险高 |
| 宣称 `arm_wave`=关节挥手 | 与代码事实不符 |
| 仅 YAML、无 Dyn-B phases / Func-C USD 开关 | 无法满足独立性与非红球约束 |

---

## 获批后最小接线清单（本轮不做）

1. Dual camera pose 覆盖配置
2. `SCENARIOS["lateral_outside_corridor"]=...`
3. `GMROBOT_V1E01_TARGET_FULL` + `ivj_v1e01_target_container_full.yaml`
4. 0-POST capture runner（复用 D1A/D1B dump 模式）
5. 离线 ROI/位移/geometry 门禁脚本

---

## 本轮状态

| 项 | 值 |
|---|---|
| 判定 | **DESIGN_READY_AWAITING_CAPTURE_APPROVAL** |
| POST / Isaac / Docker | **0** |
| 推荐投入顺序 | Dyn-A → Func-C → Dyn-B（B 依赖小代码） |
| 下一步 | **停止**；待用户决定是否投入采集 |
