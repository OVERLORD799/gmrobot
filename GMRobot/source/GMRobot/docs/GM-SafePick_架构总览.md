# GM-SafePick 安全推理系统 — 架构总览

> **本项目**：GM-SafePick — 基于 Isaac Lab 的机器人拾放平台，远期目标为人机协作安全评估
> **本文档面向**：AI 阅读者（架构理解、跨层接口对齐、后续开发决策）
> **文档约定**：避免具体文件/库/函数名，必要时以相机文档的命名风格为准
> **最后更新**：2026-07-01（代码审计 F1–F8 修复，VLM CSV 列更新）
> **项目进展与遗留问题**：[GM-SafePick_项目进展与遗留问题.md](./GM-SafePick_项目进展与遗留问题.md)（**唯一跨层进度看板**）

---

## 1. 项目目标

在一个 UR10e 机械臂执行拾放任务的仿真环境中，构建**主动式物理安全推理系统**。系统需要在 20 Hz 控制循环内实时判定机械臂动作是否安全，并逐步扩展推理能力以覆盖更复杂的安全场景。

引用论文：*Proactive Physical Safety Reasoning for Robot Manipulation*（Interim Report），定义了**三层安全框架 + 三类物理风险**：

| 风险类型 | 描述 | 示例 |
|:--------|:----|:----|
| 静态 | 无运动状态下的空间冲突 | 人手静止在机器人工作半径内 |
| 动态 | 由运动和时序产生的风险 | 人手快速进入末端轨迹 |
| 功能性 | 工具使用或机械交互不当 | 未戴手套操作旋转钻头 |

---

## 2. 系统架构：三层安全推理

采用**递进叠加式**架构，三层按推理能力和延迟成本分层：

```
监控层面：

  20 Hz 实时决策循环（永久在线）
  ┌──────────────────────────────────────┐
  │ Layer 1: 规则安全层                   │ ← 始终启用
  │  输入：机器人和人类位姿状态             │
  │  输出：g_t ∈ {ALLOW, STOP, SLOW}     │
  │  延迟：< 1ms                          │
  └──────────────────┬───────────────────┘
                     ↓
  ┌──────────────────────────────────────┐
  │ Layer 2: 数据驱动安全层               │ ← Layer 1 数据就绪后启用
  │  输入：obs + action + layer1_outcome  │
  │  输出：g_t（ensemble 融合）            │
  │  延迟：< 50ms                         │
  └──────────────────┬───────────────────┘
                     ↓
  ┌──────────────────────────────────────┐
  │ Layer 3: VLM 推理增强层              │ ← 前两层稳定后启用
  │  输入：RGB 图像 + 文本 prompt         │
  │  输出：非阻塞风险预测 + 解释           │
  │  频率：~1 Hz                          │
  └──────────────────────────────────────┘

最终安全门控（Phase 1–3，反应式）：
  g_t = g_rule ∨ g_ml    →  任一报停即停 / 减速
  g_vlm  →  非阻塞辅助决策 + 操作员提示

运动重规划（Phase 3.5/4，主动式）：
  L1/L2 warn 或 VLM Stage 5 replan  →  Motion Replan 执行器
  输出：修改后的轨迹路点（抬高接近 + 横向偏移），替代纯 STOP/hold
```

### 反应式 vs 主动式

| 模式 | 代表模块 | 行为 | 阶段 |
|:----|:--------|:----|:----|
| **反应式** | Layer 1/2/3 门控 | 检测风险 → STOP / SLOW_DOWN / 告警 | Phase 1–3（当前） |
| **主动式** | Motion Replan | 检测风险 → **修改路径**绕开危险区，任务继续推进 | Phase 3.5/4（规划） |

- Layer 1/2 提供**实时否决**（< 50 ms），是永久在线的安全底线。
- Layer 3 提供**语义理解与解释**（~1 Hz），不阻塞门控循环。
- Motion Replan 提供**轨迹级规避**，对齐论文 Stage 5 `replan`；执行在 Phase 4，与 VLM 推理解耦（Phase 4 v0 无需 VLM）。

**当前实现状态**：系统仅支持 STOP/hold + SLOW_DOWN，**无路径修改**；持续 STOP 时 `time_step` 冻结（活锁），Phase 1 可接受，**须在 Phase 4 前解决**。

---

## 3. 数据流与依赖关系

```
 仿真环境（20Hz tick）
     │
     ├─→ privileged obs: 机器人关节、末端位置、零件位姿
     ├─→ 视觉观测: RGB 图像（通过场景相机，10Hz）
     └─→ 人类模型: 人手/躯干位置（仿真体内插或轨迹生成）
             │
             ▼
   ┌─────────────────────────────┐
   │ Layer 1                     │  ← 规则引擎
   │   dist < THRESH → STOP      │
   │   TTC < THRESH → SLOW_DOWN  │
   └──────────┬──────────────────┘
              │ 每步记录:
              │ (obs, g_t, outcome)
              ▼
   ┌─────────────────────────────┐
   │ 数据积累                    │  ← 按 episode 归档
   │ 格式: 结构化表格             │
   │ 每行: 一个安全决策步          │
   └──────────┬──────────────────┘
              │ 达到足够样本后
              ▼
   ┌─────────────────────────────┐
   │ Layer 2                     │  ← 训练 ML 分类器
   │  输入: 积累的特征             │
   │  输出: 更精细的决策边界       │
   └──────────┬──────────────────┘
              │ 覆盖 80-90% 常见场景
              ▼
   ┌─────────────────────────────┐
   │ Layer 3                     │  ← VLM 处理边缘场景
   │  输入: RGB 图像 + 场景文本    │
   │  感知: Grounding DINO + SAM2│
   │  覆盖: 功能性风险 + 解释     │
   └──────────┬──────────────────┘
              │ Stage 5 replan 建议（Phase 4b）
              ▼
   ┌─────────────────────────────┐
   │ Motion Replan（Phase 3.5/4） │  ← 轨迹规避，非门控层
   │  触发: L1 warn / VLM replan  │
   │  v0: 几何重规划（抬高+侧偏）   │
   │  4b: 执行 VLM 策略建议       │
   └─────────────────────────────┘
```

### CSV 日志字段（Layer 1 + 预留 Layer 3）

Layer 1 每步写入结构化表格；Layer 3 启用后**追加**以下预留列（同一步对齐 `step_index`）：

| 字段 | 类型 | 说明 |
|:----|:----|:----|
| `vlm_risk_type` | string | static / dynamic / functional / none |
| `vlm_risk_class` | string | VLM 风险等级：safe / low / medium / high / error |
| `vlm_suggested_action` | string | pause / slow_down / replan / continue |
| `vlm_confidence` | float | 0–1 |
| `vlm_explanation` | string | 自然语言摘要（截断至 500 字符） |
| `vlm_keywords` | string | VLM 生成的感知关键词（分号分隔） |
| `vlm_model_id` | string | 模型标识符 |
| `vlm_parse_ok` | 0/1 | 服务端 JSON 解析是否成功 |
| `rgb_frame_path` | string | 对应 RGB 帧路径 |

> **注意**：`vlm_severity`、`vlm_stage`、`vlm_latency_ms` 为论文早期规范字段，当前 Logger **尚未实现**；实际写入的列以上表为准。详见 [项目进展与遗留问题 §6](./GM-SafePick_项目进展与遗留问题.md#6-safetylogger-字段实况含-vlm_-核查)。

VLM 列以**最近一次异步推理结果**前向填充至下一步。

### 三条反馈通道（Layer 3 产出分流）

| 通道 | 方向 | 用途 | 阶段 |
|:----|:----|:----|:----|
| **蒸馏** | VLM → Layer 2 | 边缘场景标签/软标签，扩充训练集 | Phase 3+ |
| **规则半自动** | VLM → Layer 1 | 从解释中提取候选阈值/关键词，人工审核后写入 YAML | Phase 3+ |
| **运动策略** | VLM / L1 → Motion Replan | `replan` 或 L1 warn 触发轨迹修改；**独立执行器**，不经 20 Hz 门控 | Phase 4 |

### Ground truth 与审计分支

| 分支 | 角色 | 说明 |
|:----|:----|:----|
| **主 GT（v1.1）** | 训练/评估默认 | EE 球（r=0.08 m）↔ `human_hand` 球心距离法；`collision_threshold=0.13 m` |
| **审计分支 A** | 可选对照 | PhysX contact（kinematic hand → 常为 `unknown`） |
| **审计分支 B** | 可选对照 | UR10e 臂段 link 最小距离（FK 或 Isaac link pose） |

审计分支用于**标定与回归对照**，不作为 Layer 2 主标签源；避免与 v1 距离 GT 混用导致指标口径不一致。

---

## 4. 相机进度报告

> 基于《GM-SafePick：添加相机 — 技术方案》（2026-06-15）

### 状态：技术方案已完成，待实施

| 维度 | 当前状态 |
|:----|:--------|
| 方案设计 | ✅ 完成（TiledCameraCfg，640×480 RGB，10Hz） |
| 相机类型 | TiledCameraCfg（支持多环境并行渲染） |
| 安装位置 | 桌面左上方俯视，pos=(0.6, 0.0, 0.8)，俯视向下 |
| 观测接口 | `obs["camera"]["scene_rgb"]` 暴露给下游模块 |
| 性能影响 | 预估 200 Hz → 150-180 Hz（单相机） |
| 依赖参数 | 运行需 `--enable_cameras` 参数 |

### 相机在安全层中的角色

| 层 | 是否需要相机 | 用途 |
|:--|:----------:|:----|
| Layer 1 | ⚠️ 可选 | 用 privileged obs 做距离计算，不需要图像 |
| Layer 2 | ⚠️ 可选 | 可用特权特征训练，也可用视觉特征 |
| Layer 3 | ✅ **必需** | VLM 需要 RGB 图像输入进行场景理解和安全推理 |

### 实施建议

- 相机配置在 Layer 1 之前或同期完成（它和规则逻辑无关，但后续层依赖它）
- 当前方案预留了 `obs["camera"]["scene_rgb"]` 接口，任何后续模块无需改相机配置即可消费
- 若 Layer 1 急于推进，相机可稍后接入——Layer 1 对 privileged obs 的依赖不阻塞

---

## 5. 三层能力边界与覆盖

| 能力 | Layer 1 | Layer 2 | Layer 3 |
|:----|:------:|:------:|:-------:|
| 静态空间冲突 | ✅ 精准（硬阈值） | ✅ 更精准（可学习） | ✅ 但太慢 |
| 动态 TTC 评估 | ⚠️ 手动调参 | ✅ 自动学习 | ✅ 好 |
| 功能性风险 | ❌ 无法规则化 | ⚠️ 需大量标注 | ✅ 零样本 |
| 开放集检测 | ❌ 写死类别 | ❌ 写死类别 | ✅ GDINO + SAM2 |
| 解释生成 | ❌ 只能输出距离值 | ❌ 只能输出概率值 | ✅ 自然语言 |
| 轨迹重规划 | ❌ 仅 STOP/hold | ❌ 仅门控 | ❌ 仅建议（Stage 5） |
| 永远在线 | ✅ 20 Hz | ✅ 20 Hz | ❌ ~1 Hz |

> **轨迹重规划**由独立 **Motion Replan** 模块承担（Phase 4），不属于 L1/L2/L3 任一层；L3 Stage 5 仅输出 `replan` 建议。

### 三层不是替代关系，是互补叠加：

- **20 Hz 实时决策走 Layer 1/2**，任何一层否决即停止
- **~1 Hz VLM 分析走 Layer 3**，不阻塞 20 Hz 循环，输出辅助建议
- **轨迹规避走 Motion Replan**（Phase 4），与门控并行；v0 由 L1 warn 触发，4b 消费 VLM Stage 5
- Layer 3 宕机 → 安全不降级（Layer 1/2 仍在工作）

---

## 6. 路标概览

> **当前阶段（2026-06-17）**：**Phase 1 完成，Phase 2 预备**。Phase 1 已签收：GT v1.1、双阈值 static、审计分支 log-only、IV-J registry v0.1、离线指标脚本、Isaac 回归三跑（`192734`/`193244`/`193713`）。Layer 2 离线管道已就绪，在线融合待 Phase 2。
>
> **详细进展、指标表与遗留问题** → [GM-SafePick_项目进展与遗留问题.md](./GM-SafePick_项目进展与遗留问题.md)

```
Phase 0 ✅ 基本完成
  └─ 相机接入（方案已定，运行需 --enable_cameras）
  └─ 仿真人类模型（human_hand 球体 + 轨迹控制器）

Phase 1 ✅ 完成
  └─ Layer 1 规则安全层（50 Hz；双阈值 static + TTC）
  └─ GT v1.1（ee_radius 包络）+ 审计分支 log-only
  └─ IV-J 场景 registry v0.1（6 preset）
  └─ 离线指标：report_safety_metrics / compare_gt_branches
  └─ 已知限制：纯 STOP/hold 活锁；20 零件物理 success 未接

Phase 2（进行中预备）
  └─ Layer 2 ML 分类器离线训练 ✅；在线 g_rule ∨ g_ml 集成 ⏳
  └─ A/B：Layer 1 vs Layer 1+2 干预率与误停率
  └─ 标签源：gt_ground_truth（主）/ g_rule（对照）

Phase 3（前两层稳定后）
  └─ Layer 3 VLM 推理 + GDINO + SAM2（Stage 1/3/4）
  └─ 功能性风险 + 自然语言解释；非阻塞 ~1 Hz
  └─ Stage 5 replan **仅作设计输出**；执行归 Phase 4b
  └─ CSV `vlm_*` 列规范已定、Logger 待实现；三条反馈通道中的蒸馏/规则半自动启动

Phase 3.5（Motion Replan 预备，Layer 3 可并行）
  └─ 定义 Motion Replan 模块接口与触发契约
  └─ L1 SLOW_DOWN / 持续 STOP → replan 请求信号（设计）
  └─ 活锁指标：连续 STOP 步数、任务完成率（挡空箱场景）
  └─ 与状态机轨迹时钟集成方案（replan 后 time_step 如何推进）

Phase 4a — Motion Replan v0（几何重规划，无需 VLM）
  └─ 触发：Layer 1 warn（TTC SLOW_DOWN 或 static 邻近区）
  └─ 策略：抬高接近高度 + 横向偏移（绕开 human_hand 安全泡）
  └─ 目标：消解活锁，任务在风险存在时仍可完成
  └─ 指标：replan 成功率、replan 后碰撞率、成功率下降（非仅 STOP 召回）
  └─ 挡空箱 preset：长期需 replan 成功而非单纯 STOP 拦截

Phase 4b — VLM 驱动重规划（论文 Stage 5 → 执行器）
  └─ VLM Stage 5 输出 suggested_action=replan → Motion Replan 执行器
  └─ VLM 非阻塞；执行器在独立周期内修改路点序列
  └─ 可选：复杂场景（功能性风险、多障碍）语义级路径调整
  └─ 依赖：Phase 4a 几何 replan 基线 + Layer 3 Stage 5 稳定输出
```

### 轨迹规避路线图（与论文对齐）

| 论文阶段 | 本项目映射 | 执行时机 |
|:--------|:----------|:--------|
| Stage 1–4 | Layer 3 VLM 感知与解释 | Phase 3 |
| Stage 5 `replan` | VLM 建议 + **Motion Replan 执行器** | Phase 4b（建议）/ 4a（几何 fallback） |
| 实时门控 $g_t$ | Layer 1/2 STOP/SLOW | Phase 1–2（当前） |

Phase 1–3 的 L1/L2/L3 工作是 Motion Replan 的**前置条件**（数据、门控、语义），不构成偏离。

---

## 7. 关键指标（论文定义）

| 指标 | 定义 | 测量方式 |
|:----|:----|:--------|
| 干预率 | `g_t == STOP` 次数 / 总步数 | 每 episode 统计 |
| 干预时长 | 连续 STOP 步数 | 分布统计（平均/最大） |
| 成功率下降 | 有安全约束 vs 无安全约束的任务完成率差 | A/B 对比运行 |
| 安全覆盖率 | 危险场景中被正确拦截的比例 | 需要 ground truth 标定 |

---

## 8. 决策要点

| # | 决策 | 当前结论 | 依据 |
|:-|:----|:--------|:----|
| 1 | 先做规则层还是直接上 VLM？ | **先做规则层** | VLM 延迟与 20 Hz 不匹配；规则层提供 baseline |
| 2 | Layer 1 是否需要相机？ | **不需要** | privileged obs 已提供位置信息 |
| 3 | Grounding DINO + SAM2 何时引入？ | **Layer 3** | 开放集检测能力在 Layer 1/2 无需求 |
| 4 | 仿真人类模型如何实现？ | **球体/胶囊体** | 简单碰撞体 + 预定轨迹，不做完整骨骼动画 |
| 5 | Layer 1 数据能否复用？ | **可以，专门设计为 Layer 2 训练源** | 每步记录 `(obs, action, g_rule, outcome)` |
| 6 | 轨迹重规划何时做？ | **Phase 3.5 设计 / Phase 4 实现** | Phase 1–3 仅 STOP/hold；活锁 Phase 1 可接受 |
| 7 | Phase 4 v0 是否需要 VLM？ | **不需要** | L1 warn 触发几何 replan（抬高+侧偏） |
| 8 | Stage 5 replan 谁执行？ | **Motion Replan 执行器**（Phase 4b） | VLM 只输出建议，不直接改轨迹 |
| 9 | 挡空箱场景长期指标？ | **replan 成功率 + 任务完成** | 非仅 STOP 召回；见 Phase 4a |
| 10 | GT 主标签 vs 审计？ | **v1 距离法为主** | PhysX / 臂段碰撞作审计分支，非主 GT |
| 11 | Phase 3 VLM MVP 后端？ | **Qwen-only 单后端（`VLMClient`）；无 `VLMRouter`** | 先证明 Layer 3 增量价值；Fast/Slow 多模型路由为后续分支实验 — [项目进展 §7.5](./GM-SafePick_项目进展与遗留问题.md) |

---

## 9. 文档索引

| 文档 | 角色 |
|:-----|:-----|
| [项目进展与遗留问题](./GM-SafePick_项目进展与遗留问题.md) | **进度看板 SSOT**、run ID、P0/P1 开放项 |
| [Layer 1 / 2 / 3](./GM-SafePick_Layer1_规则安全层.md) | 各层规格与验收 |
| [远程运行指南](./GM-SafePick_远程运行指南.md) | headless/VNC、§6 资产路径 |
| [AI 服务器部署](./GM-SafePick_AI服务器部署.md) | gm-ai-server、SSH 隧道、VLM/感知烟测 |
| [添加相机技术文档](./GM-SafePick_添加相机技术文档.md) | 相机接口契约 |
| [adr/](./adr/) | 已锁定契约（Phase 2.5 / 3.5）与 [archive/](./adr/archive/) 历史讨论 |
| [论文中文翻译](./Proactive%20Physical%20Safety%20Reasoning%20for%20Robot%20Manipulation%20中文翻译与术语解析.md) | 术语对齐 |
| [任务迁移与架构解耦分析](./GM-SafePick_任务迁移与架构解耦分析.md) | 迁移到其他操作任务的可行性、工作量和接口契约 |
| [自动调参需求规格](./GM-SafePick_自动调参需求规格.md) | 离线重放、评分函数、搜索空间、场景权重 — 待实现 |
