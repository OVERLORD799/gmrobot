# ADR：Phase 2.5 全包络门控决策

> **状态**：**已锁定**（2026-06-18）  
> **日期**：2026-06-18  
> **决策者**：项目成员（用户确认）  
> **关联**：[项目进展 §7.6](../GM-SafePick_项目进展与遗留问题.md) · [Layer 1 规则安全层](../GM-SafePick_Layer1_规则安全层.md) · [Phase 3.5 Replan 契约](./GM-SafePick_Phase3.5_MotionReplan契约.md)

---

## 1. 背景

Phase 1–2 门控与 GT 主标签基于 **EE 点 + `ee_radius=0.08 m`** 球体距离。挡空箱（`ivj_static_block_place`）审计显示：臂段 FK 与 EE GT 在 **45.5%** 行不一致——肩/上臂穿越人手通道时 EE 距离仍大于 0.19 m，规则 **ALLOW**、全速执行。

Phase 2.5 将门控距离从 EE-only 扩展为 **全几何包络 `dist_min`**（腕部 + 双指尖 + 夹持物盒），分两步交付：**2.5a 审计对照** → **2.5b 门控切换**。

---

## 2. 已锁定决策（12 项）

| # | 决策域 | 锁定结论 | 说明 |
|:-:|:------|:---------|:-----|
| 1 | **全包络门控** | **是** | 以 `dist_min`（全包络最近距离）门控；先 **2.5a** 审计日志，再 **2.5b** 切换 `RuleEngine` 读 `dist_min` |
| 2 | **GT v1.2** | 与 **2.5b 门控同日切换** | 主标签改用全包络；**保留 v1.1 列一阶段**供 Layer 2 对照与 `compare_gt_branches` 复现 |
| 3 | **Gripper 包络** | MVP **双指尖球** | 左右指尖各 `r ≈ 3–4 cm`；无独立 TCP 球除非后续标定需要 |
| 4 | **夹持物** | MVP **固定盒 5×5×17 cm** | 仅在 `gripper_closed` 窗口附加；**`block_place` 为 P0** 验收场景 |
| 5 | **参考点** | `wrist_3` + **双指尖** | 不单独引入 tool center，除非夹爪几何证明需要 |
| 6 | **Tier0 阈值** | **不变** | `safe_dist_hard_stop=0.13 m`、`safe_dist_warn=0.19 m`（语义改为相对 `dist_min`） |
| 7 | **Preset 口径** | **生产=全包络**；**stress=EE-only** | 分开跑、分开报告；stress 故意高干预，不得与生产 preset 混比 |
| 8 | **Layer 2 重训** | **2.5b 之后（2.5c）** | 按 [Layer 2 §3.6](../GM-SafePick_Layer2_数据驱动安全层.md) 用新 GT/特征重训 |
| 9 | **PhysX contact** | **仅审计** | 不接 Tier0；kinematic hand 下 `gt_contact=unknown` 可接受 |
| 10 | **VLM** | **不进门控 OR** | 日志 / 蒸馏 / 操作员告警 only |
| 11 | **Replan 距离字段** | **新列 `dist_min_envelope`**；replan 读 **`dist_min`**；**保留 `dist_ee_human` 遗留列** | 详见 §3.1 |
| 12 | **位姿来源** | **Isaac `body_link_pos_w` 优先**，FK 回退 | 详见 §3.2 |

---

## 3. 详细理由（#11、#12）

### 3.1 Replan 距离字段（#11）

> ### ⚠️ 强制契约：Replan 语义 = `dist_min`，不是 `dist_ee_human`
>
> **ReplanRequest**、**L1WarnReplanTrigger**、Tier0 defer（`replan_defer_dist_m`）、place 窗口 wait-hold —— **全部**以 **`dist_min_envelope`**（腕部 + 双指尖 + 夹持物盒取 min）为距离输入。
>
> | 读者须知 | 说明 |
> |:---------|:-----|
> | **字段名** | `ReplanRequest.dist_ee_human`、`metadata["dist_ee_human"]` 为 **遗留列名**，2.5b 起 **填入 `dist_min`**，**禁止**再按 EE 点距离解释 |
> | **为何不能读 EE** | shoulder-pass 时 EE 仍 >0.19 m 但臂段已侵入 → EE-only replan **漏触发**；place defer 阈值在 EE 口径下 **过早/过晚**；与 2.5b 门控 **分叉** |
> | **权威来源** | 运行时 `dist_min` ← `min(dist_min_envelope, …)`；CSV 新列 `dist_min_envelope`；详见 [Phase 3.5 ADR §3.4](./GM-SafePick_Phase3.5_MotionReplan契约.md#34-replan-距离语义dist_min-非-dist_ee_human) |
>
> 违反本契约 = replan 与 Tier0 门控 **口径不一致**，挡空箱/肩穿越场景会复现 Phase 1 已知 bug。

#### 为何新增列而非重命名 `dist_ee_human`

1. **历史 CSV 可复现性**：Phase 1–2 已积累大量 run（IV-J、Layer 2 训练集 `20260618_142722` 等）。列名 `dist_ee_human` 在 26 维特征、`compare_gt_branches.py`、离线指标脚本中硬编码。重命名会破坏旧 run 的对照与论文复现链。
2. **Layer 2 特征维度**：`layer2/features.py` 以 `dist_ee_human` 为输入之一；2.5c 重训前需 **双列并存** 做 A/B，而非原地替换。
3. **Phase 4a 阈值标定**：`replan_defer_dist_m=0.15 m` 等参数在 EE 口径短跑上标定；全包络切换后数值可能偏移，需用 `dist_min_envelope` 重新标定——保留 EE 列可量化偏移量。

#### 为何 replan 必须读 `dist_min`（全包络）

1. **Tier0 / defer 语义**：`dist < 0.13 m` 硬 STOP、`replan_defer_dist_m=0.15 m` 推迟 replan 的前提是 **最近人体–机器人几何距离**。肩/上臂侵入时 EE 仍可达 0.25 m+，EE-only replan 会 **漏触发** 或 **错误 defer**，复现 shoulder-pass 类 bug（审计 45.5% 分歧行的根因类别）。
2. **与门控一致**：2.5b 起 `RuleEngine` 用 `dist_min`；replan 若仍读 `dist_ee_human`，会出现「规则已 SLOW、replan 认为安全」的分叉。

#### 过渡契约（双写 + 语义分裂）

| 字段 | 语义 | 消费者 |
|:-----|:-----|:-------|
| `dist_ee_human` | EE 点 ↔ `human_hand` 球心（**遗留**，日志/ Layer 2 对照） | CSV 归档、2.5c 前 L2 特征、历史报告 |
| `dist_min_envelope` | 全包络 ↔ 人手最近距离（**权威**，2.5b+） | `RuleEngine`、`L1WarnReplanTrigger`、GT v1.2 |
| `dist_min`（运行时） | `min(dist_min_envelope, …)` 的 gate 读数；CSV 列名见实现 | 门控 + replan **唯一**距离输入 |

**ReplanRequest**（[Phase 3.5 ADR §3.1](./GM-SafePick_Phase3.5_MotionReplan契约.md)）在 2.5b 修订：`dist_ee_human` 字段保留名但 **填入 `dist_min`**，或新增 `dist_min` 并标记 `dist_ee_human` deprecated——实现阶段以代码注释 + 本 ADR 为准。

---

### 3.2 位姿来源（#12）

#### 问题：FK 与仿真真值偏差

- 当前审计分支用 **DH FK + 平移对齐（yaw 无关）** 估计 6 个臂段球心。
- `ivj_static_block_place` 上 **45.5%** 行 `g_gt_arm ≠ g_ground_truth(EE)`：肩/前臂在通道内时 FK 球与 Isaac 刚体位姿明显偏移。
- **夹爪指尖** 需四元数旋转；DH 无指关节模型，无法可靠近似双指尖球。

#### 决策：Isaac 优先，FK 回退

| 来源 | 用途 | 理由 |
|:-----|:-----|:-----|
| **`robot.data.body_link_pos_w`**（+ 指尖 link） | 仿真门控、GT v1.2、日志 | 与 PhysX 刚体一致；50 Hz 读 ~14 body **开销可忽略** |
| **FK** | 单元测试、无 Isaac 的真机离线回放 | 不依赖 sim API；已知偏差，**不得**作为 Tier0 唯一来源 |

#### 错误位姿 → 错误 `dist_min` 的风险

- FK 偏差可使肩段 **实际侵入** 而 `dist_min` 仍 > 0.19 m → **漏 STOP**。
- 或 FK 夸大距离 → **误 STOP** / 误 replan defer。
- 因此 2.5b 门控 **禁止** 仅用 FK 作为生产路径。

---

## 4. 交付分期

```
Phase 2.5a（审计）
  └─ 日志列：dist_min_envelope, gripper/held-object 贡献分解（可选）
  └─ compare_gt_branches 扩展：EE vs envelope vs arm FK
  └─ 门控仍读 dist_ee_human（行为不变）

Phase 2.5b（门控切换）
  └─ RuleEngine + replan + GT v1.2 读 dist_min
  └─ 阈值 0.13 / 0.19 不变（语义切换）
  └─ v1.1 列保留一阶段

Phase 2.5c（Layer 2）
  └─ 特征改用 dist_min_envelope；重训 + shadow + 在线 A/B
```

---

## 5. Preset 策略（#7）

| 类别 | 距离口径 | 代表 preset | 报告 |
|:-----|:---------|:------------|:-----|
| **生产** | 全包络 `dist_min` | `safety_layer1.yaml`、`ivj_static_block_place` | 主验收 / IV-J 主表 |
| **Stress** | EE-only（故意） | `safety_layer1_stress.yaml` | 单独 stress 表，标注 EE 口径 |

---

## 6. 远场速度过快 — 控制链、调查与 interim 缓解（2026-06-18）

本节用自然语言说明 **50 Hz 安全环** 中速度如何被（或未被）限制，以及 block_place 远场全速 transit 的根因与缓解路径。实现以 [`rule_engine.py`](../../GMRobot/safety/rule_engine.py)、[`gate.py`](../../GMRobot/safety/gate.py)、[`configs/safety_layer1.yaml`](../../../../configs/safety_layer1.yaml) 为准。

### 6.1 当前控制链（Phase 1 → interim）

整条链路在 `gm_state_machine_agent.py` 每步执行：**policy 出 proposed → RuleEngine 判 g_rule → SafetyGate 混合 → 写 executed → advance_mask 决定是否推进 time_step**。

#### 6.1.1 `rule_engine.py` — 静态距离带 + TTC

规则按 **STOP > SLOW_DOWN > ALLOW** 优先级取最严决策。距离带（默认 preset，`dist` 当前仍为 EE 点距，2.5b 切换为 `dist_min`）：

| 距离区间 | 决策 | `trigger_rule` | 备注 |
|:---------|:-----|:---------------|:-----|
| `dist < 0.13 m` | **STOP** | `static` | Tier0 硬停 |
| `0.13 ≤ dist < 0.19 m` | **SLOW_DOWN** | `static` | 近场警戒带 |
| `0.19 ≤ dist < safe_dist_slow_far`（若启用） | **SLOW_DOWN** | **`static_far`** | 远场警戒带（interim） |
| `dist ≥ slow_far` 或未启用远场带 | **ALLOW** | — | 无静态干预 |

TTC 规则（与静态 **独立叠加**，取更严）：

- `ttc < 0.5 s` → STOP（`trigger_rule=ttc`）
- `0.5 s ≤ ttc < 1.5 s` → SLOW_DOWN
- TTC 计算基于 EE 相对人手 **径向接近速率**；**横向/切向运动** 时 `approach_rate ≤ 0` → TTC=∞，**不触发**

SLOW_DOWN 时 metadata 写入 `slow_down_alpha`：近场 `static`/`ttc` 用 `slow_down_alpha=0.3`；远场 `static_far` 用 `slow_down_alpha_far=0.55`（**更大 α = 向 proposed 靠拢更多 = 减速更轻**）。

#### 6.1.2 `gate.py` — α 动作混合

```text
STOP      → executed = prev_action（完全 hold）
SLOW_DOWN → executed = prev + α × (proposed − prev)
ALLOW     → executed = proposed（全速跟随轨迹）
```

α 来自 `gate_result.metadata["slow_down_alpha"]`，缺省回退 `SafetyConfig.slow_down_alpha`。**仅 SLOW_DOWN 步** 生效；ALLOW 步 proposed 原样通过。

#### 6.1.3 `pick_and_place_policy.py` — 轨迹与 proposed

状态机按 `time_stamps` 插值关节目标，**本身不做速度缩放**。`get_action(..., advance=False)` 每步给出下一目标；速度完全由相邻路点间距 × 是否 ALLOW 决定。

#### 6.1.4 T7 — `time_step` 与 SLOW 冻结

`advance_mask = (g_t == ALLOW)`（replan 例外见 Phase 4a）。**SLOW_DOWN / STOP 时 `time_step` 不推进**——轨迹「卡」在当前路点索引，靠 gate 的 α 混合在原地减速，**不会**跳到下一路点。因此：

- 近场 SLOW：time_step 冻结 + α=0.3 → 明显减速感
- 远场 ALLOW：time_step 正常推进 + executed=proposed → **policy 全速**

#### 6.1.5 控制链小结（远场 dist ≥ 0.19 m，interim 关闭时）

```text
RuleEngine → ALLOW（static 与 TTC 均不触发）
    ↓
SafetyGate → executed = proposed（无混合）
    ↓
advance_mask = True → time_step += 1
    ↓
下一 proposed 仍全幅 → ee_vel 可达 policy 上限
```

### 6.2 调查结论（block_place 日志）

**数据来源**：`20260618_22*` 等 `ivj_static_block_place` runs；筛选 `dist ≥ 0.19 m` 且 `g_rule=ALLOW` 的步。

| 指标 | 观测值 |
|:-----|:-------|
| `ee_vel` 均值 | **0.19–0.29 m/s** |
| `ee_vel` 峰值 | **2.24 m/s** |
| 场景特征 | 人手在场（`human_enabled=true`），EE 几何仍较远，臂横向穿越 B 通道 |

含义：在 **Tier0 warn 带之外**，系统认为「安全」并 **ALLOW 全速**；操作员体感为「人还在旁边，臂却很快」。

### 6.3 根因分析

1. **双阈值语义**：`safe_dist_warn=0.19 m` 将 0.19 m 外定义为无静态干预区；与 GT v1.1 碰撞阈值 0.13 m 之间留 6 cm 缓冲，但 **缓冲外 = 全速**。
2. **TTC 盲区**：TTC 只对 **相向** 运动敏感。挡空箱中臂沿 Y 向横移、人手相对 EE 切向运动时，TTC 常为 ∞，**无法**补位 static ALLOW 的空档。
3. **policy 无 cap**：轨迹层无 `v_ee_max`；gate 仅在 SLOW 时混合，ALLOW 时不限速。
4. **（2.5b 后加剧风险）**：EE-only 距离在 shoulder-pass 可 **高估** 安全距离；全包络 `dist_min` 切换后，同一物理姿态可能落入 SLOW 带——远场策略需在 **dist_min 口径** 下重测（见选项 D）。

### 6.4 Interim 缓解（**Option A 已批准**，锁定至 2.5b 决策点）

> **状态（2026-06-18）**：用户锁定 **Option A** 为生产 interim 策略，**直至 Phase 2.5b 门控切换日**再复评 B/C/D。2.5a 审计期门控仍读 `dist_ee_human`；`static_far` 已接入生产 preset。

在 **不改变 Tier0 硬阈值 0.13 / 0.19 m** 前提下，新增第三段 **远场警戒带**：

| 参数 | `SafetyConfig` 默认 | 生产 preset（`safety_layer1.yaml`、`ivj_static_block_place.yaml`） | 语义 |
|:-----|:-------------------|:----------------------------------------------------------------|:-----|
| `safe_dist_slow_far` | `null`（关闭） | **0.35 m** | 当 `0.19 ≤ dist < 0.35` → SLOW_DOWN |
| `slow_down_alpha` | 0.3 | 0.3 | 近场 static/ttc 混合系数 |
| `slow_down_alpha_far` | 0.55 | **0.55** | 远场 `static_far` 混合系数（更轻减速） |

**代码路径**（[`rule_engine.py`](../../GMRobot/safety/rule_engine.py) L52–58, L95–99）：

- 命中远场带 → `g_t=SLOW_DOWN`，`metadata["trigger_rule"]="static_far"`，`metadata["slow_down_alpha"]=slow_down_alpha_far`
- [`gate.py`](../../GMRobot/safety/gate.py) 读取 metadata α 做混合
- **副作用**：远场 SLOW 同样 **冻结 time_step**（T7 不变），周期时间可能略增

**单元测试**：[`scripts/test_rule_engine_unit.py`](../../../../scripts/test_rule_engine_unit.py) — `test_static_far_slow_when_enabled` / `test_static_far_disabled_allows`。

### 6.5 长期策略选项（2.5b 决策点复评）

> Option A 已作为 interim 批准；下表供 **2.5b 后** 用 `dist_min` 峰值速度数据驱动选择。

| 选项 | 做法 | 优点 | 缺点 |
|:-----|:-----|:-----|:-----|
| **A（当前 interim，已批准）** | `slow_far=0.35 m`，`α_far=0.55`；0.19–0.35 m 轻度 SLOW | 改动最小；不碰 Tier0；已接入生产 preset | 0.35 m 外仍 ALLOW 全速；α=0.55 减速有限，峰值仍可能 >1 m/s |
| **B** | 扩大远场带（如 0.5 m）或降低 `α_far`（如 0.4） | 人手在场时更保守；更易压峰值速度 | 更多步 time_step 冻结；周期时间上升；需 Isaac 回归干预率 |
| **C** | `human_enabled` 时全局 `v_ee_cap`（与距离无关） | 简单可预期；覆盖 TTC 盲区 | 需改 policy 或 gate 后处理；可能拖慢正常无手任务；与 Layer 1「距离分级」哲学不一致 |
| **D** | 2.5b 全包络门控后，用 **`dist_min`** 重标定 `slow_far` / `α_far` | 与 envelope 语义一致；shoulder-pass 远场可能 **更早** 进入 SLOW | 依赖 2.5b 完成 + Isaac 短跑；阈值需重新标定 |

### 6.6 推荐工作流

```text
Phase 2.5a（当前）
  └─ 门控仍 EE 口径；生产 preset 已启用选项 A（static_far）
  └─ 审计 CSV：对比 dist_ee_human vs dist_min_envelope vs ee_vel 分布

Phase 2.5b（门控切换）
  └─ RuleEngine 读 dist_min；复跑 block_place 3000 步
  └─ 重测：ALLOW 步 ee_vel 峰值、static_far 触发占比、干预率

决策点
  └─ 若 dist_min 下峰值仍 >1 m/s → 考虑 B（扩带/降 α）或 D（dist_min 重标定）
  └─ 若干预率过高 → 收窄 slow_far 或提高 α_far
  └─ 若需「人在场即限速」→ 评估 C（与产品安全策略对齐）
```

**当前立场**：**Option A 锁定至 2.5b**；2.5a 审计 **同时保留 A** 作为 baseline；2.5b 后用 **dist_min** 峰值速度数据驱动 B/D 选择（C 需产品对齐）。

---

## 7. 实现状态（Phase 2.5a，2026-06-18）

| 组件 | 状态 | 说明 |
|:-----|:----:|:-----|
| `GMRobot/safety/envelope.py` | ✅ | `EnvelopeEvaluator`：6 臂段 + 双指尖 + 夹持物盒；Isaac `body_link_pos_w` 优先、FK 回退 |
| CSV 新列 | ✅ | `dist_min_envelope`, `dist_min_arm`, `dist_min_gripper`, `dist_min_held`, `closest_primitive_id`；保留 `dist_ee_human` |
| `gm_state_machine_agent.py` | ✅ | 2.5a 审计列；2.5b **门控读 `dist_min_envelope`**（`gating_enabled`） |
| `pick_and_place_policy.is_carrying_object` | ✅ | gripper closed 窗口驱动 held 原语 |
| 单元测试 | ✅ | `scripts/test_envelope_unit.py` |
| 2.5b 门控切换 | ✅ | `RuleEngine` / replan / GT v1.2 读 `dist_min`；生产 preset `envelope.gating_enabled: true` |

---

## 8. 未办事项（Open items，2026-06-18）

> 代码与单元测试已完成；下列项依赖 **Isaac 节点空闲** 或后续工程迭代。进展看板：[项目进展 §3.8](../GM-SafePick_项目进展与遗留问题.md#38-本会话未办事项2026-06-18)。

| # | 项 | 阶段 | 状态 | 说明 |
|:-:|:---|:-----|:----:|:-----|
| O1 | Isaac 2.5b 烟测 | 2.5b | ⏳ | `scripts/accept_block_place_replan.sh`；`ivj_static_block_place` 3000 步；**节点并发仿真占用，待空闲重试** |
| O2 | 速度策略 Option A/D 复评 | 2.5b 决策点 | ⏳ | `dist_min` 口径下 ALLOW 步 `ee_vel` 峰值、`static_far` 占比；据 O1 日志在 B/D 间选择（§6.5–6.6） |
| O3 | Layer 2 重训 | **2.5c** | ⏳ | 新特征 `dist_min_envelope` 等；GT v1.2 标签；依赖 O1 采集日志 |
| O4 | Part 5 replan 用户视觉验收 | 4a v1 | ⏳ | 基线 `20260618_211219`；O1 通过后用户重验放置区 / wait-hold |
| O5 | TTC 口径 | 工程 | 🔶 | TTC 仍用 EE 速度 + `dist_min` 距离；中等优先级；O1 后评估 |
| O6 | `dist_ee_human_gt` 列名 | 工程（可选） | ⏳ | rename 或 dual-write `dist_min_gt` 提升日志清晰度 |
| O7 | held box 位姿精化 | 工程 | ⏳ | tool axis offset、quaternion；改善 `dist_min_held` |
| O8 | Layer 3 VLM 联调 | Phase 3 | ⏳ | Isaac `--enable_vlm` + tunnel `18080` → gm-ai-server `:8080` |
| O9 | GDINO / SAM2 | Phase 3b | ⏳ | AI server 待装；Qwen MVP 已完成 |
| O10 | Git push | 交付 | ✅ | 23 commits 已推送（`a3a2be5`…`cb330bc`）；token URL 经 `gh-proxy.org` |

**决策点更新**：Option A 自 2.5b 代码落地日起进入 **O2 复评窗口**；O1 完成前维持 Option A 为生产 interim。

---

## 9. 变更日志

| 日期 | 内容 |
|:-----|:-----|
| 2026-06-18 | **§8 Open items**：2.5b 烟测阻塞、2.5c 重训、速度策略复评、TTC/列名/held 位姿等待办 |
| 2026-06-18 | **Phase 2.5b 门控切换**：`envelope.gating_enabled`、RuleEngine/GT v1.2/fusion/replan 读 `dist_min_envelope`；stress 仍 EE-only |
| 2026-06-18 | **Phase 2.5a 实现**：`envelope.py` 审计日志、CSV 新列、Option A 锁定至 2.5b；§7 实现状态 |
| 2026-06-18 | §3.1 replan dist_min 强制 callout；§6 控制链与速度策略详述（中文） |

---

*冲突时以本 ADR + 代码为准；Tier0 阈值变更须单独 ADR 修订。*
