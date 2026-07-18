# GM-SafePick Layer 3：VLM 推理增强层

> **定位**：安全推理系统的顶层智能，处理 Layer 1/2 无法覆盖的边缘场景——功能性风险、开放集感知、自然语言解释
> **前提**：Layer 1 稳定运行，Layer 2 数据驱动安全覆盖了 80-90% 常见场景
> **架构原则**：非阻塞——VLM 推理不参与 20 Hz 安全门控循环，输出作为辅助决策信息
> **最后更新**：2026-06-22

---

## 1. 职责

根据论文 *Proactive Physical Safety Reasoning for Robot Manipulation* 的五阶段推理管线，VLM 在三个推理阶段中承担以下职责，全部不在 20 Hz 实时决策路径上：

| 阶段 | VLM 职责 | 频率 | 是否阻塞安全门控 |
|:----|:--------|:---:|:--------------:|
| Stage 1 | 场景分析 + 生成开源集 grounding 关键词 | 每 episode 1-2 次 | ❌ 不阻塞 |
| Stage 3 | 风险分类 + 短期后果预测 (1-3s) | 每 1-2s | ❌ 不阻塞 |
| Stage 4 | 自然语言解释 + 策略调整建议 | 按需 | ❌ 不阻塞 |
| Stage 5 | 策略调整（含 `replan`） | 按需 | ❌ 不阻塞；**执行在 Phase 4b** |

**Stage 2（视觉定位）由 Grounding DINO + SAM2 完成，VLM 只负责生成关键词。**

> **Stage 5 与 Motion Replan 分工**：VLM 输出 `suggested_action=replan` 及语义上下文，**不直接修改**状态机轨迹。轨迹变更由独立 **Motion Replan 执行器**（[`GM-SafePick_架构总览.md`](./GM-SafePick_架构总览.md) §6 Phase 4）在异步周期内完成。Phase 4a 几何 replan（L1 warn 触发）可不依赖 VLM。

---

## 2. 感知流水线：Grounding DINO + SAM2

```
VLM Stage 1 输出:
  "unprotected human hand"
  "sharp blade"
  "moving robot arm"
          ↓
   ┌─────────────┐
   │ Grounding   │  ← 给定文本关键词，在全图搜索匹配物体
   │ DINO        │     输出: bounding boxes + 置信度
   └──────┬──────┘
          ↓ (bbox 作为提示)
   ┌─────────────┐
   │ SAM2        │  ← 从 bbox 生成精确分割 mask
   │             │     首帧: 完整推理 (50-100ms)
   │             │     后续帧: 时序追踪 (10-20ms/帧)
   └─────────────┘
          ↓ (mask 作为定位结果)
   安全相关实体的精确像素级位置
```

### Grounding DINO 的作用

| 属性 | 说明 |
|:----|:----|
| 类型 | 开放集目标检测器 |
| 输入 | 图像 + 自然语言文本提示 |
| 输出 | 匹配物体的 bounding box + 置信度 |
| 关键能力 | **不限于预训练类别**（可理解 VLM 动态生成的任意关键词） |
| Why not YOLO | YOLO 只能检测固定类别（"person"、"hand"），无法理解 "unprotected human hand" 这种细粒度概念 |

### SAM2 的作用

| 属性 | 说明 |
|:----|:----|
| 类型 | 通用图像/视频分割模型 |
| 输入 | 提示（bbox、点或 mask）+ 图像/视频帧 |
| 输出 | 像素级分割掩码 |
| 关键能力 | **视频时序传播**——首帧检测后在后续帧中自动追踪 mask，无需逐帧推理 |
| Why not just bbox | 框的精度不够——判断"手指尖是否在运动轨迹上"需要像素级 mask |

### 实际部署策略

由于 Grounding DINO 单帧推理 100-300ms，不能每帧调用：

```text
首帧（或每 100 帧）:
  Grounding DINO full detection      ← 300ms
  SAM2 mask generation               ← 50-100ms

中间帧（99/100 帧）:
  SAM2 temporal propagation          ← 10-20ms → 继续追踪 mask
  (如果传播丢失，触发重新检测)
```

---

## 3. VLM 的推理任务

### 3.1 Stage 1：场景分析 + Grounding 关键词生成

**输入**：RGB 图像帧 + 系统提示词 prompt

**VLM 需要理解的内容**：

```text
系统提示词核心要求:
1. 识别人类安全状态
   - 是否佩戴防护装备（手套、护目镜）
   - 注意力状态（专注操作 vs 分心）
   - 有无裸露皮肤在危险区域
2. 识别工具/物体状态
   - 物体稳定性（是否倾斜、摇晃）
   - 工具使用方式（是否被正确握持）
   - 潜在危险源（刀片、高温表面）
3. 识别空间关系
   - 人与机器人的相对位置
   - 物体在桌面上是否安全放置
```

**输出**：结构化的 grounding 关键词列表 + 场景摘要

```json
{
  "scene_description": "工人戴手套操作钻床，手臂靠近旋转区域",
  "safety_relevant_entities": [
    {"entity": "gloved hand", "keyword": "gloved hand near drill bit"},
    {"entity": "drill bit", "keyword": "rotating drill bit"},
    {"entity": "bare forearm", "keyword": "bare forearm near chuck"}
  ],
  "combined_query": "gloved hand near drill bit . rotating drill bit . bare forearm near chuck"
}
```

### 3.2 Stage 3：风险分类 + 后果预测

**输入**：场景分析结果 + （可选）Grounding DINO + SAM2 的定位结果

**VLM 需要推理的内容**：

```text
三类风险识别:
1. 静态: 空间关系已经不安全（手在机器人路径上静止不动）
   → "此人站在机器人回退路径上，需要先移开"
2. 动态: 运动将导致不安全（手快速接近夹爪）
   → "1-2 秒内手将接触夹爪，应立即暂停"
3. 功能性: 工具被误用（用扳手敲击而非拧紧）
   → "扳手不应作为锤子使用，可能导致滑脱伤人"
```

**输出**：

```json
{
  "risk_type": "dynamic",
  "confidence": 0.92,
  "affected_entities": ["human_hand", "robot_gripper"],
  "prediction": "hand will contact gripper within 1.5s at current speed",
  "severity": "high"
}
```

### 3.3 Stage 4：自然语言解释

**输入**：风险分析结果

**输出**：人类可读的安全状态描述 + 建议

```json
{
  "explanation": "工人的左手正快速伸向抓取区域。虽然距离还有0.3m，但当前接近速度为0.5m/s，预计1秒内到达。建议立即暂停机器人运动。",
  "suggested_action": "pause",
  "alternative": "slow_down",
  "for_operator": true
}
```

### 3.4 Stage 5：策略调整建议（设计目标 → Phase 4b 执行）

| 建议类型 | 含义 | 适用场景 | 执行方 |
|:--------|:----|:--------|:------|
| pause | 立即停止 | 高风险，即将发生碰撞 | Layer 1/2 门控（20 Hz） |
| slow_down | 减速执行 | 中等风险，需要更谨慎 | Layer 1 门控 |
| replan | 重新规划路径 | 当前路径必定穿过危险区域 | **Motion Replan 执行器**（Phase 4） |
| continue | 继续执行 | 安全评估无异常 | 状态机照常推进 |

**`replan` 是本层的设计输出，不是本层的运行时能力。** VLM 在 ≤2s 内给出结构化建议后，由 Motion Replan 模块消费：

```text
VLM Stage 5 JSON:
  suggested_action: "replan"
  replan_hint: { "raise_approach_m": 0.05, "lateral_offset_m": 0.15, "side": "left" }
          ↓（异步队列，非阻塞门控）
Motion Replan Executor（Phase 4b）
  → 修改 pick_and_place 路点序列 / 插入绕行段
  → 通知状态机从新路点继续（time_step 语义见架构总览 Phase 3.5）
```

Phase 4a **无需 VLM**：Layer 1 `SLOW_DOWN` 或 static 邻近 warn 可直接触发几何 replan（抬高 + 侧偏），作为 Stage 5 的 fallback。

---

## 4. VLM 模型选型指标

VLM 必须满足以下指标才能适配此项目：

| 指标 | 要求 | 说明 |
|:----|:----|:----|
| 推理延迟 | ≤2s（目标 ≤1.5s） | 从图像输入到结构化输出 |
| JSON 输出一致率 | >95% | 输出必须通过 schema 校验 |
| 场景理解 F1 | >0.85 | 在安全场景 VQA 测试集上 |
| 显存占用 | ≤8-16GB | 与 Isaac Sim 共享 24GB 显存 |
| 关键词召回率 | >85% | VLM 生成的关键词被 Grounding DINO 成功检测的比例 |
| 零样本能力 | ✅ | 不依赖微调即可适应安全场景 |

**推荐配置**：7B 级 VLM + 4-bit 量化（如 Qwen2.5-VL-7B 4-bit AWQ 或 GPT-4o API）

> **MVP 已锁定（2026-06-18）**：Phase 3 先实现 **Qwen-only 单后端**（`VLMClient` → Qwen2.5-VL-7B）；专用 VLM server（HTTP/gRPC）可用，但 MVP **不含** `VLMRouter`/Fast-Slow 多模型路由（后续分支实验）。详见 [项目进展 §7.5](./GM-SafePick_项目进展与遗留问题.md)。早期 GPT-4o vs Qwen 对比见 [归档：VLM 模型选型讨论](./adr/archive/GM-SafePick_VLM模型选型讨论.md)。

---

## 5. 与 Layer 1/2 的集成

### 5.1 架构关系

```text
┌─────────────────────────────────────────────────┐
│             20 Hz 安全门控循环                     │
│  Layer 1 (Rules) → g_rule                        │
│  Layer 2 (ML)    → g_ml                          │
│  g_t = g_rule ∨ g_ml                             │ ← 实时
└──────────────────────┬──────────────────────────┘
                       │ (不阻塞)
                       ▼
┌─────────────────────────────────────────────────┐
│          ~1 Hz VLM 推理循环（并行）               │
│  Stage 1: 场景分析 → 关键词 → GDINO+SAM2         │ ← 异步
│  Stage 3: 风险预测                               │
│  Stage 4: 解释生成                               │
│  Stage 5: 策略建议（含 replan）                   │
└──────────────────────┬──────────────────────────┘
                       │ replan 建议（非门控路径）
                       ▼
┌─────────────────────────────────────────────────┐
│     Motion Replan 执行器（Phase 4，独立模块）      │
│  v0: L1 warn → 几何绕行                          │
│  4b: 消费 VLM Stage 5 replan_hint               │
└─────────────────────────────────────────────────┘
```

### 5.2 VLM 输出与安全门控的关系

| 维度 | 20 Hz 门控 | VLM 输出 |
|:----|:---------:|:--------:|
| 决策者 | Layer 1/2 | VLM（建议性质） |
| 执行方式 | 强制执行（stop/slow） | 告警提示 + 可选的覆盖 |
| 优先级 | 永远优先 | 仅在 g_t=ALLOW 时参考 |
| 延迟容忍 | < 50ms | < 2s |

### 5.3 VLM 宕机时的安全状态

**Layer 3 被设计为可降级组件**。如果 VLM OOM、API 超时或量化溢出：

```text
IF VLM unavailable:
    Layer 1/2 继续工作           ← 安全不降级
    仅 VLM 增强功能不可用         ← 关闭解释/功能性风险检测/开放集感知
    Motion Replan v0 仍可工作     ← Phase 4a 仅依赖 L1 warn，不依赖 VLM
```

### 5.4 三条反馈通道

Layer 3 产出按用途分流（详见架构总览 §3）：

| 通道 | 消费者 | 说明 |
|:----|:------|:----|
| VLM → L2 蒸馏 | Layer 2 训练管道 | 边缘场景软标签 / 难例挖掘 |
| VLM → L1 规则半自动 | `safety_layer1.yaml` | 解释中提取候选阈值，人工审核后合入 |
| VLM / L1 → Motion Replan | Motion Replan 执行器 | `replan` 建议或 L1 warn；**与门控并行、独立执行** |

### 5.5 CSV 预留字段（`vlm_*`）

与 Layer 1 逐步日志按 `step_index` 对齐；VLM 异步结果前向填充：

| 列名 | 类型 | 说明 |
|:----|:----|:----|
| `vlm_risk_type` | string | static / dynamic / functional / none |
| `vlm_severity` | string | low / medium / high |
| `vlm_suggested_action` | string | pause / slow_down / replan / continue |
| `vlm_confidence` | float | 0–1 |
| `vlm_explanation` | string | 自然语言摘要 |
| `vlm_stage` | int | 最近完成阶段 1/3/4/5 |
| `vlm_latency_ms` | float | 推理耗时 |

Layer 3 未启用时列为空，不影响 Layer 1/2 管道。

---

## 6. Layer 3 的增量价值

| 场景 | Layer 1/2 表现 | Layer 3 增量 | 重要程度 |
|:----|:-------------:|:------------:|:-------:|
| 人手靠近机械臂 | ✅ 正确拦截（距离/TTC 规则） | ➕ 给出原因："手正从右侧快速接近" | 低（补充性） |
| 工具未正确握持 | ❌ 无法检测（规则无法覆盖） | ✅ 检测并停止："扳手角度不当，可能滑脱" | **高** |
| 罕见物体进入场景 | ❌ 训练数据未包含此物体 | ✅ 零样本检测并评估风险 | **高** |
| 操作员询问"为什么停了" | ❌ 只能返回距离值 | ✅ "因为你裸露的前臂靠近了旋转区域" | 中 |
| 安全日志分析 | ❌ 只有数值 | ✅ 结构化 JSON 解释，可汇入报告 | 中 |

---

## 7. 成功标准

Layer 3 引入后应满足：

1. VLM 能在 ≤2s 内完成一次完整的场景分析 + 风险预测
2. 功能性风险场景至少有 80% 被 VLM 正确识别（Layer 1/2 为 0%）
3. VLM 宕机不影响 Layer 1/2 的 20 Hz 安全门控
4. Grounding DINO + SAM2 的感知召回率 >85%（VLM 关键词 → 物体检测）
5. 系统在所有场景下的安全指标不弱于仅运行 Layer 1/2 的情况（回归不退化）
6. Stage 5 `replan` JSON 可被 Motion Replan 执行器解析（Phase 4b 联调项；本层不实现执行）

### 与 Motion Replan 的依赖关系

| 阶段 | Layer 3 职责 | Motion Replan 职责 |
|:----|:------------|:------------------|
| Phase 3 | Stage 1/3/4 + Stage 5 **建议输出** | 无 |
| Phase 3.5 | 稳定 `replan` schema | 接口与触发契约设计 |
| Phase 4a | 可选旁路 | L1 warn → 几何 replan（无 VLM） |
| Phase 4b | Stage 5 → `replan_hint` | 消费 VLM 建议并修改轨迹 |

### 7.1 人手轨迹预测（S13）→ Phase 4b 路线图

Layer 3 **不单独实现**手运动预报，但与感知栈、L1 TTC、Motion Replan 共同构成 **S13** 模块（详见 [项目进展 §3.8.4](./GM-SafePick_项目进展与遗留问题.md#384-s13-人手轨迹预测phase-4b-预测式-replan)）。当前 VLM Stage 3 输出风险类别与自然语言后果，**缺少**结构化 `time_to_contact_s` / `approach_direction`；SAM2 `/track`（S9）与 L1 `human_hand_vel` 外推（P0）将先行补齐 0.5–2 s 视界。P2 起 VLM JSON 映射至 [`ReplanHint`](./adr/GM-SafePick_Phase3.5_MotionReplan契约.md) 与 [`replan/strategy.py`](../GMRobot/safety/replan/strategy.py) 策略选择，最终在包络侵入前触发 held-aware 预测式 splice（Phase 4b），与 S7 TTC Option C（包络相对速度）互补。
