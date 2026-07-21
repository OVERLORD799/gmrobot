# GMRobot 五阶段实现 + G1 对抗测试基准扩展：实施规格

> 日期：2026-07-18  
> 文档性质：交给编程 agent 的实施任务书与验收合同  
> 当前状态（2026-07-20）：**Milestone 0 已完成；Milestone 1 的 B0/B1 已完成，B2–B4 待实现；整个论文项目尚未完成**  
> 适用仓库：`GMRobot/`、`g1_ur10e_disturbance/`  
> 论文定位：**仿真系统实现与对抗性评估，不包含真机验证**

---

## 0. 2026-07-20 执行状态（后续 agent 必读）

本节是当前事实源；正文其余章节仍是最终规格。不得因为 B0/B1 已通过而将整个项目标记为完成。

### 0.1 已完成

- P0 验证基础设施：批测入口、Docker、错误退出、manifest、种子闭环、CSV/schema 校验和离线回归测试。
- 扰动 attempt 归因：STOP、SLOW、replan 的来源与事件边沿可审计。
- B0 安全基线：seeds 42/43/44 均完成 20/20，G1 归因 STOP/SLOW/replan 均为 0。
- B1 静态占位：seeds 42/43/44 均完成 20/20，归因 replan 分别为 4/4/7，掉件均为 0。
- B1 事件链合计：`trigger/applied/retreat/redeploy = 15/15/15/15`，未配对事件为 0，trigger→apply 延迟均为 0 step。
- B1 的 15 次 replan 中，12 次为 `held_critical` 硬停恢复路径，3 次为 SLOW 路径；因此 B1 主要证明安全恢复，不等同于稳定的接触前动态预测场景。
- 最终验证镜像：`sha256:0320fd6e9d7c061c48fdb51bf44a738bbee5e6bd469f8e5f2e52c05963ae0ca6`。
- 最终六组汇总：`results_paper_final_0320/final_six_ordered/batch_summary_combined.json`。

### 0.2 尚未完成

- B2 动态横扫及稳定的 hard-stop 前预测/replan 证据。
- B3 功能性误抓。
- B4 与 B1/B2/B3 轨迹完全相同的 shadow/no-enforcement 对照。
- G1 真实左右手 body 触发安全门的场景及分层手臂状态机验收。
- 五阶段视觉链的端到端运行证据、工具/PPE 对照和失败降级实验。
- B0–B3 至少 5 seeds、完整消融、统计区间、统一 overlay 和评审视频。

### 0.3 当前里程碑判定

| 里程碑 | 状态 | 判定 |
|---|---|---|
| Milestone 0：可信测试基础 | 完成 | 可以作为后续实验基础 |
| Milestone 1：可重复代理手基准 | 部分完成 | B0/B1 完成；B2–B4 未完成 |
| Milestone 2：G1 静止真实手臂 | 未完成 | 不得声称真实手臂闭环成立 |
| Milestone 3：五阶段视觉闭环 | 未完成验收 | 代码存在不等于端到端证据成立 |
| Milestone 4：论文结果冻结 | 未开始 | 当前六组不是论文最终实验矩阵 |

下一轮代码 agent 的唯一任务见：`code-agent-b2-b4-instructions-2026-07-20.md`。

---

## 1. 最终目标

本项目的投稿目标定义为：

> 实现论文《Proactive Physical Safety Reasoning for Robot Manipulation》描述的五阶段主动安全推理管线，并扩展一个由 Unitree G1 人形机器人驱动、可重复、可消融的 UR10e 对抗性安全测试基准。

最终交付必须同时证明两件事：

1. **GMRobot 五阶段安全推理闭环成立**：视觉输入能够产生安全实体关键词、定位结果、结构化风险、解释和可执行干预建议。
2. **G1 对抗测试基准成立**：G1 本体、G1 真实手臂或明确标注的 G1 附着代理手能够按确定性轨迹制造静态、动态和机械交互风险，并支持相同扰动下的安全层 A/B/消融实验。

最终系统是 Isaac Lab 仿真研究。不得在代码、文档或视频中声称已经完成真机 UR10e/G1 验证或 sim-to-real 验证。

---

## 2. 已批准的范围与不可擅自变更的决策

### 2.1 已批准范围

- 保留虚拟手，作为主要的确定性、可重复扰动源。
- 启用 G1 真实手臂，优先实现“走到位 → 站稳 → 伸手/横扫 → 回缩 → 撤退”。
- 不以完整 whole-body control 策略作为投稿前依赖。
- 保留工具、手套/PPE和开放集物体场景，用于功能性风险与语义风险展示。
- 主定量实验使用可重复的脚本轨迹；VLM 不能决定实验是否可复现。
- G1 真实手臂主要用于定性视频、几何门控和有限的零件扰动实验。
- 不恢复 G1↔UR10e PhysX 碰撞响应作为默认模式；默认研究的是接触前主动安全。
- 不计划真机实验。

### 2.2 明确非目标

以下工作不得阻塞本实施计划：

- 训练新的 G1 全身行走和双臂协同策略。
- 实现通用 humanoid MPC/WBC 框架。
- 证明真实碰撞力、真实材料属性或人体伤害模型。
- 证明真实相机到世界坐标的标定迁移。
- 让 G1 完成精细工具操作或灵巧手抓取。
- 将 VLM 放入 50 Hz 硬实时安全回路。
- 用单次演示代替多种子统计实验。

### 2.3 论文主张边界

允许的主张：

- 仿真中的接触前风险检测、门控和轨迹调整。
- 三类风险的受控场景覆盖。
- 五阶段管线的模块化实现与端到端证据。
- G1 驱动的对抗性扰动基准和消融评估。
- VLM/GDINO/SAM2作为低频语义增强，规则层作为实时安全兜底。

禁止的主张：

- G1 与 UR10e 的真实物理碰撞已经被验证。
- 当前 PPO 已学会论文所述拾放任务。
- 当前系统已经完成真机部署。
- 工具/PPE只有图片识别时，声称已经完成物理功能性干预。
- 虚拟手被描述为 G1 真实手部。

---

## 3. 当前已确认的基础

### 3.1 可复用实现

- `g1_arm_controller.py`
  - 已实现14自由度手臂关节目标。
  - 已有 `none`、`wave`、`extend_forward`、`extend_left`、`extend_right` 原语。
  - 已有1秒 smoothstep 缓启动和关节限位。
- `scripts/run_phase3.py`
  - 已在 `env.step()` 前调用 `arm_ctrl.apply()`。
  - 已有 root tilt 超阈值自动收臂逻辑。
  - 已有虚拟手、逐零件协议、场景手、VLM相机和replan接线。
- `dual_env_cfg.py`
  - G1行走动作只写12个腿关节，保留手臂/腰部目标。
  - 有头部相机和全局场景相机。
- GMRobot
  - Layer 1距离/TTC/包络规则。
  - Layer 2训练、预测和融合模块。
  - VLM结构化输出、GDINO/SAM2客户端及日志字段。
  - 几何replan、VLM replan、手轨迹Kalman和time-to-risk模块。
  - 静态、动态、侵入和functional misgrasp场景配置。

### 3.2 当前仍不能作为论文证据的内容

- 历史 `/tmp/gmdisturb_phase5` 等结果不可用于论文；当前可信结果必须来自仓库内 manifest/CSV。
- 当前可信 B1 结果来自明确标注的 `scripted_virtual_hand`，不是 G1 真实手部。
- G1↔UR10e PhysX碰撞响应默认被过滤。
- Phase 5文档中的高STOP/SLOW不能证明是G1本体造成。
- 当前PPO环境只有`is_alive`奖励，没有论文四项shaped reward。
- B2/B3/B4、真实手臂和五阶段视觉闭环尚无通过最终验收的结果。
- 2026-07-20 曾出现一次连续复用容器启动 Isaac 时的 CUDA illegal memory access；该失败运行已保留但未计入六组结果。长批次优先每个 episode 使用新容器。

---

## 4. 目标系统结构

```text
                    ┌──────────────────────────────┐
                    │ Isaac Lab scene RGB / video │
                    └──────────────┬───────────────┘
                                   │
             ┌─────────────────────▼─────────────────────┐
             │ Stage 1: VLM scene summary + keywords     │
             └───────────┬──────────────────────┬────────┘
                         │                      │ parallel
             ┌───────────▼──────────┐  ┌────────▼─────────────┐
             │ Stage 2: GDINO+SAM2  │  │ Stage 3: risk +      │
             │ bbox/mask/tracking   │  │ 1-3 s consequence    │
             └───────────┬──────────┘  └────────┬─────────────┘
                         └──────────────┬────────┘
                                        │
                           ┌────────────▼────────────┐
                           │ Stage 4: explanation    │
                           └────────────┬────────────┘
                                        │
                           ┌────────────▼────────────┐
                           │ Stage 5: stop/slow/     │
                           │ replan/alert suggestion │
                           └────────────┬────────────┘
                                        │ advisory
             ┌──────────────────────────▼──────────────────────────┐
             │ 50 Hz runtime: L1 + optional L2 → SafetyGate       │
             │ ALLOW / SLOW_DOWN / STOP + GeometryReplan          │
             └──────────────────────────┬──────────────────────────┘
                                        │
             ┌──────────────────────────▼──────────────────────────┐
             │ UR10e scripted or validated PPO pick-and-place     │
             └─────────────────────────────────────────────────────┘

  G1 benchmark side:
  locomotion policy → STABILIZE → physical arm / attached proxy → RETRACT
```

VLM和感知服务允许低频、异步、失败降级。L1必须始终能够在没有VLM的情况下独立运行。

---

## 5. P0：先修复验证基础设施

在P0全部通过前，不得生成新的论文结果表。

### 5.1 修复批测入口

目标文件：

- `batch_runner.py`
- `batch_test_configs/*.yaml`
- `scripts/run_batch.py`

必须修复：

1. 从`paths.py`显式导入`CONDA_PREFIX`，或删除手动覆盖，不能引用未定义变量。
2. YAML中配置名与CLI场景名分离：
   - `name`只用于run id。
   - 新增/使用`scenario: arm_collision|arm_wave|...`。
   - 不得把`arm_collision_safety`传给`--scenario`。
3. `wander_no_safety.yaml`必须显式产生`--no-safety`。
4. `safety.enable_envelope: false`不得被误解释为“无安全层”。
5. 子进程成功必须同时满足：
   - return code为0；
   - CSV存在且非空；
   - CSV包含预期schema；
   - 日志中无`Traceback`、`Failed to startup`、`ModuleNotFoundError`；
   - 至少完成一个仿真step。
6. 所有批测输出写到仓库下可配置目录，例如：
   - `results/paper_demo/<run_id>/`
   - 不得把唯一证据只写到`/tmp`。
7. 每次结果必须保存：
   - 实际CLI命令；
   - YAML快照；
   - git revision或源码hash；
   - Python/Isaac/driver/GPU版本；
   - stdout/stderr；
   - step CSV；
   - episode summary JSON；
   - 随机种子。

### 5.2 修复冒烟测试

目标文件：

- `scripts/smoke_test.sh`
- `scripts/smoke_test_dual.py`

要求：

- `--per-part-protocol`使用时必须显式传`--virtual-hand 0.45`或立即报参数错误。
- `--replan`在没有安全层或障碍源时应立即报错。
- Python异常必须令脚本返回非0。
- 测试应分成：
  - `scene_smoke`：场景加载和100步；
  - `safety_smoke`：产生至少一次可归因STOP/SLOW；
  - `replan_smoke`：产生至少一次applied replan且任务时钟继续；
  - `arm_smoke`：站立伸手、回缩且不摔倒。
- 修复错误/过期的root z提示与断言说明。

### 5.3 对齐离线单测合同

当前已观察到以下失败：

- `scripts/test_gt_fusion_envelope_unit.py`
- `scripts/test_replan_unit.py`
- `scripts/test_safety_logger_vlm_unit.py`

处理规则：

1. 不得为了让测试通过而盲目恢复旧行为。
2. 对每个失败先写一行“当前设计真值”：
   - Fusion：ML为STOP且置信度高于阈值时是否允许降级？
   - Replan：持件、快速手部逼近且上方空间充足时，raise还是retreat优先？
   - Logger：新增结构化字段是否属于正式schema？
3. 根据论文安全语义更新代码或测试。
4. replan策略必须增加回归测试，验证不会因`RAISE_HIGH`覆盖而增加持件掉落。

P0验收：

```bash
cd /home/czz/GMrobot/GMRobot
python scripts/test_rule_engine_unit.py
python scripts/test_envelope_unit.py
python scripts/test_gt_fusion_envelope_unit.py
python scripts/test_replan_unit.py
python scripts/test_safety_logger_vlm_unit.py
python scripts/test_safety_logger_perception_unit.py
python scripts/test_safety_logger_replan_unit.py
```

全部必须返回0。

---

## 6. P1：建立可信的G1对抗基准

### 6.1 扰动源必须显式分类

每步CSV新增或确认以下字段：

- `disturbance_source`
  - `none`
  - `g1_body`
  - `g1_physical_hand_left`
  - `g1_physical_hand_right`
  - `g1_attached_proxy`
  - `scripted_virtual_hand`
- `disturbance_scenario`
- `disturbance_phase`
- `disturbance_active`
- `disturbance_attempt_id`
- `closest_g1_body`
- `dist_min_g1_body`
- `dist_min_proxy`
- `gate_trigger_source`
- `replan_trigger_source`

`d_stop_caused`不能继续仅依据“disturbance_active且同一步STOP”计数。必须使用attempt窗口归因：

1. 扰动进入预定义激活阶段，创建`attempt_id`。
2. 在该attempt时间窗内首次出现STOP/SLOW/replan，记录一次因果事件。
3. 同一attempt连续50步STOP不得计为50次独立成功。
4. GMRobot内部workspace/TTC事件若与当前扰动几何无关，不能记入G1成功。

### 6.2 确定性场景协议

新增独立场景schema，建议目录：

```text
paper_scenarios/
  baseline_safe.yaml
  static_occupancy_proxy.yaml
  dynamic_lateral_sweep_proxy.yaml
  functional_misgrasp_proxy.yaml
  g1_stationary_arm_reach.yaml
  g1_stationary_arm_sweep.yaml
  ppe_gloved_tool.yaml
  ppe_bare_hand_tool.yaml
```

每个场景必须定义：

- seed；
- UR10e任务阶段或触发条件；
- 扰动源；
- 起点、终点、速度、持续时间；
- 期望风险类型；
- 期望门控范围；
- 是否允许物理接触；
- 是否期望replan；
- pass/fail阈值；
- 最大episode时间。

不得只依赖全局仿真时间触发动态手。优先支持按UR10e语义阶段触发：

- `approach`
- `grasp`
- `transit`
- `place`
- `reset`

### 6.3 基准场景

#### B0：安全基线

- G1远场静止或安全巡游。
- UR10e完成相同拾放任务。
- 预期：无G1归因STOP/replan，任务完成。

#### B1：静态占位

- 代理手进入放置区并静止。
- 预期：static风险，STOP或SLOW；撤回后任务恢复。

#### B2：动态横扫

- UR10e transit阶段，代理手侧向穿过未来路径。
- 必须包含“尚未进入hard stop但预测有冲突”的时间窗。
- 预期：dynamic风险、预测或TTC提前干预、replan applied。

#### B3：功能性误抓

- 抓取闭合附近扰动零件或制造位置偏差。
- 预期：functional风险、停止/重抓/解释、最终恢复或明确失败。

#### B4：相同轨迹无安全基线

- 与B1/B2/B3使用完全相同的轨迹和seed。
- 关闭全部在线安全门，但保留shadow评估和日志。
- 用于量化碰撞代理、掉件和任务差异。

---

## 7. P2：G1真实手臂的分层控制

### 7.1 架构原则

不得把G1真实手臂实现重构为完整WBC项目。使用现有行走策略和14自由度手臂PD叠加，但用阶段状态机隔离高风险组合。

建议新增：

- `g1_arm_scenario_controller.py`
- 或在`g1_arm_controller.py`中新增独立的状态机类，但不要把场景调度塞进纯轨迹函数。

推荐状态：

```text
WALK_APPROACH
  → DECELERATE
  → STABILIZE
  → ARM_EXTEND / ARM_SWEEP / TOOL_PRESENT
  → ARM_HOLD
  → ARM_RETRACT
  → STABILIZE_AFTER
  → RETREAT / DONE
```

### 7.2 状态转换条件

#### WALK_APPROACH → DECELERATE

- G1到达预定站立区域；或
- G1 root到目标点距离小于可配置阈值。

#### DECELERATE → STABILIZE

- 速度命令已经平滑降为0；
- 禁止一步从运动速度跳为0后立即伸手。

#### STABILIZE → ARM动作

至少同时满足：

- root线速度低于阈值；
- root角速度低于阈值；
- tilt低于阈值；
- 双脚接触持续N步；
- 状态持续稳定N步。

阈值必须进入YAML，不得全部硬编码。

#### 任意ARM状态 → ARM_RETRACT

满足任一条件立即回缩：

- tilt超过warning阈值；
- root角速度超过阈值；
- 单脚/双脚接触丢失；
- G1 root z跌出正常范围；
- 手臂或桌面距离低于自身安全阈值；
- 状态超时；
- 用户/场景触发abort。

#### ARM_RETRACT → RETREAT

- 关节误差回到默认姿态容差内；
- G1重新稳定。

### 7.3 真实手臂动作原语

保留现有动作，并新增面向论文的最小原语：

- `reach_left_hand`
- `reach_right_hand`
- `lateral_sweep_left_to_right`
- `lateral_sweep_right_to_left`
- `hold_tool_pose`
- `retract_safe`

要求：

- 使用连续位置、速度和加速度轮廓；
- 不允许阶段切换造成关节目标突变；
- 支持幅度、周期、最大关节速度配置；
- 默认只动单臂；双臂动作必须单独验证；
- 不控制腰部关节，腰部继续由行走策略管理；
- 每步记录目标、实际关节角、最大误差、tilt和足部接触。

### 7.4 G1手部几何真值

不得用头部位置代表真实手臂位置。真实手臂场景必须读取：

- `left_wrist_*`/实际左手body；
- `right_wrist_*`/实际右手body；
- 对应速度；
- 对应球/胶囊包络半径。

将真实手body通过`G1EnvelopeAdapter`输入GMRobot，`closest_body`必须能够区分左右手。

### 7.5 真实手臂验收

每个动作至少5个seed，满足：

- G1不触发fall termination；
- 动作过程中tilt不超过批准阈值，或超限后能成功回缩；
- 无瞬时关节目标跳变；
- 双脚接触稳定率达到预设阈值；
- 至少一个场景由真实手body而非虚拟手触发安全门；
- 撤手后UR10e任务可继续；
- 视频中明确标注“physical G1 arm / collision response filtered”。

---

## 8. P3：五阶段视觉管线与工具/PPE场景

### 8.1 统一结构化schema

VLM输出至少包含：

```json
{
  "scene_summary": "...",
  "keywords": ["bare human hand", "robot gripper", "power tool"],
  "risk_type": "static|dynamic|functional|none",
  "risk_confidence": 0.0,
  "affected_entities": ["..."],
  "predicted_consequence": "...",
  "prediction_horizon_s": 1.5,
  "explanation": "...",
  "suggested_action": "continue|slow_down|stop|replan|alert",
  "spatial_hint": "left|right|above|retreat|none"
}
```

要求：

- JSON解析失败必须显式记录，不得静默补成`static`。
- 本地部署脚本不能硬编码所有实际结果为`static/slow_down`。
- server版本、prompt版本和schema版本写入日志。
- VLM关键词必须真正传给GDINO，而不是始终使用固定prompt。
- Stage 2结果必须能关联到Stage 1请求id。
- SAM2 track必须记录跨帧track id和丢失状态。
- Stage 3必须有结构化后果和预测视界，不仅是自然语言描述。

### 8.2 工具和PPE场景

实现至少一对受控对照：

- `ppe_gloved_tool`：G1手部或代理手带手套，工具姿态正确。
- `ppe_bare_hand_tool`：无手套，手靠近危险工具工作端或姿态错误。

资产可以是仿真模型、材质切换或明确可见的附着物。重点是保证：

- 相机视角中差异可见；
- 关键词不同；
- 检测/分割结果可见；
- 风险分类和建议产生可解释差异；
- 同一场景除PPE/工具状态外保持一致。

如果该场景只产生VLM解释和operator alert，论文中称为“语义功能性风险识别”。只有实际改变UR10e动作时，才能称为“闭环功能性风险干预”。

### 8.3 延迟与降级

记录：

- VLM总延迟；
- GDINO延迟；
- SAM2初始化和track延迟；
- 从风险首次可见到L1首次干预的时间；
- 从风险首次可见到VLM结果的时间；
- VLM超时时实时层采取的行为。

VLM失败不得阻塞50 Hz回路。错误时允许保守replan/alert，但必须有cooldown，不能每个缓存周期重复触发永久活锁。

---

## 9. P4：PPO处理策略

PPO不是G1基准第一阶段的阻塞项，但论文如果保留“PPO行为策略”主张，必须完成以下工作。

### 9.1 必须实现的奖励

- `r_approach`
- `r_lift`
- `r_hover`
- `r_success`

同时补充：

- 成功终止；
- 超时终止；
- 目标零件/目标容器观测；
- episode随机化；
- checkpoint评估入口。

### 9.2 PPO验收

- checkpoint不是仅证明训练循环能运行。
- 至少报告5个seed的任务成功率。
- 与脚本策略在无安全和有安全条件下分别比较。
- 若PPO无法达到可用成功率：
  - 论文平台演示继续使用脚本策略；
  - 将PPO描述为训练接口/未来工作；
  - 不把PPO checkpoint作为已学会拾放的证据。

---

## 10. 论文实验矩阵

### 10.1 系统消融

对B0–B3每个场景至少5个seed，使用完全相同扰动轨迹运行：

| 组 | L1 | L2在线融合 | VLM/GDINO/SAM2 | Replan |
|---|---:|---:|---:|---:|
| A0 | 否（shadow日志保留） | 否 | 否 | 否 |
| A1 | 是 | 否 | 否 | 否 |
| A2 | 是 | 是 | 否 | 是 |
| A3 | 是 | 是 | 是 | 是 |
| A4 | 是 | 否 | 是 | 是 |

如果Layer 2在线融合仍导致任务严重回归，必须如实保留失败结果，并将生产配置限定为L1 + replan + Layer 2 shadow。

### 10.2 核心指标

- risk recall / precision / F1；
- false positive rate；
- 首次干预提前量；
- `min_surface_distance_m`；
- STOP/SLOW持续时间；
- intervention rate；
- replan trigger/applied/success rate；
- post-replan collision proxy rate；
- task success rate；
- completion steps/time；
- part drop/knock-off/recovery rate；
- max consecutive stop和livelock ratio；
- VLM/GDINO/SAM2 latency；
- keyword→detection recall；
- 风险类别混淆矩阵；
- 按`disturbance_source`拆分的归因事件数。

### 10.3 统计要求

- 每种设置至少5个seed，建议10个。
- 报告均值、标准差和95%置信区间。
- 明确区分控制step、策略step和wall-clock时间。
- 不得把forward-filled VLM日志行数当作VLM调用次数。
- VLM调用次数按唯一request id或唯一frame id统计。
- 同时保留失败episode，禁止只报告成功run。

---

## 11. 评审演示脚本

最终视频建议为4–6分钟，使用同一布局和统一overlay。

### 11.1 Overlay内容

- 左上：RGB画面 + GDINO bbox + SAM2 mask。
- 右上：Stage 1关键词、risk type、confidence、predicted consequence。
- 左下：`dist_min`、TTC、预测轨迹、风险首次可见时间。
- 右下：ALLOW/SLOW/STOP/REPLAN、当前replan策略、任务阶段。
- 底部状态条：扰动源、场景名、seed、是否启用物理碰撞响应。

### 11.2 演示顺序

1. B0安全基线：系统不误报。
2. B1静态占位：停止后恢复。
3. B2动态横扫：接触前预测并绕行。
4. B3误抓：识别、重抓和恢复。
5. PPE工具对照：相同几何、不同语义风险。
6. G1真实手臂：走到位、站稳、伸手、触发、回缩。
7. 15–20秒消融表：无安全 vs 完整系统。

每次出现虚拟手时画面必须显示`G1-attached proxy`或`scripted virtual hand`。每次出现真实G1手臂时显示`physical G1 arm; G1-UR10e collision response filtered`。

---

## 12. 推荐实施顺序与完成门

### Milestone 0：可信测试基础（已完成）

- P0全部完成。
- 单测全绿。
- 宿主或Docker至少一个环境可以可靠运行scene smoke。
- 失败能返回非0。

### Milestone 1：可重复代理手基准（部分完成：B0/B1）

- B0–B4场景可运行。
- A/B使用相同轨迹。
- 归因字段可以证明干预来源。
- 生成第一版5-seed结果。

### Milestone 2：G1静止真实手臂（未完成）

- 完成分层状态机。
- 真实左右手body进入安全适配器。
- 站立伸手和横扫通过稳定性验收。

### Milestone 3：五阶段视觉闭环（未完成验收）

- Stage 1→2请求链可追踪。
- Stage 3具备结构化预测。
- Stage 4解释可复核。
- Stage 5建议可触发有限、可恢复的动作调整。
- PPE工具对照通过。

### Milestone 4：论文结果冻结（未开始）

- 完成全部消融、多seed统计和视频。
- 保存运行环境和配置快照。
- 文档与代码语义一致。
- 不再用历史`/tmp`结果填论文表格。

只有前一个Milestone完成，才能将下一个Milestone标记为“论文可用”。“代码存在”“CLI存在”“一次run成功”均不等于Milestone完成。

---

## 13. 编程agent工作规则

1. 先修P0，再实现新场景。
2. 每次只完成一个可验收的纵向切片，避免同时重构GMRobot和GMDisturb核心。
3. 保留现有用户改动；不要删除`(1)`副本，除非用户单独授权清理。
4. 所有新阈值进入YAML并记录默认值依据。
5. 新日志字段必须同步：writer、reader、分析脚本、文档和测试。
6. 不允许安全模块异常后静默退化为无安全运行。
7. 不允许用“最终任务完成”推断中间风险干预正确。
8. 不允许把压力垫全部激活计为物体掉落；必须区分脚步、静置零件和高能冲击。
9. 每个修复都必须附最小回归测试。
10. 任何与本规格冲突的架构扩大必须先请求用户批准。

---

## 14. 编程 agent 首轮任务清单（历史，已完成）

首轮只提交P0和B0/B1最小切片：

1. 修复`batch_runner.py`未定义变量。
2. 修复batch YAML场景名映射。
3. 修复真正的no-safety baseline。
4. 修复smoke缺少virtual-hand参数和错误退出码。
5. 对齐3组失败的离线单测并写清设计真值。
6. 新增运行manifest和仓库内结果目录。
7. 新增`disturbance_source`、`attempt_id`和`gate_trigger_source`最小字段。
8. 实现B0安全基线和B1静态代理手场景。
9. 各运行3个快速seed，证明批测和归因链可用。
10. 向用户提交：改动摘要、测试输出、两个场景结果表、仍未解决的问题。

截至 2026-07-20，上述首轮任务已经完成并通过 B0/B1 各 3 seeds 的最终门禁。后续 agent 不得重复实现、重新调参或覆盖这批结果。下一轮任务以独立任务书 `code-agent-b2-b4-instructions-2026-07-20.md` 为准。

首轮禁止：

- 训练WBC；
- 大规模改写`run_phase3.py`；
- 直接生成论文最终数字；
- 在P0未通过时实现PPE或PPO；
- 恢复G1↔UR10e物理碰撞作为默认设置。

---

## 15. 最终Definition of Done

项目只有同时满足以下条件，才可向论文评审组展示为“完整系统”：

- 五阶段每一阶段都有代码路径、运行日志和可视证据。
- 静态、动态、功能性风险各有至少一个可重复场景。
- 至少一个场景由G1真实手body触发安全门。
- 虚拟手和真实手在日志/视频中明确区分。
- A/B和消融批测入口通过测试且结果可复跑。
- 至少5个seed并报告方差。
- VLM失败时实时安全层继续工作且不会活锁。
- replan后任务能够继续，且掉件率没有因策略选择显著恶化。
- PPO若被称为行为策略，必须具有论文奖励和任务成功证据；否则明确标为接口/未来工作。
- 所有论文数字可追溯到仓库内保存的manifest、配置和原始CSV。
- 局限性中明确说明仿真、碰撞过滤、代理手和无真机验证。
