# ADR：Phase 3.5 Motion Replan 契约

> **状态**：**已锁定**（2026-06-18；P0 决策 + 接口契约 + AI 部署拓扑）；**§12 增补** 4a v1 用户反馈修订（2026-06-18）  
> **日期**：2026-06-18  
> **决策者**：项目成员（用户确认）  
> **关联**：[架构总览 §6](../GM-SafePick_架构总览.md) · [Layer 3 §3.4](../GM-SafePick_Layer3_VLM推理增强层.md) · [项目进展 §7.5](../GM-SafePick_项目进展与遗留问题.md)

---

## 1. 背景与目标

### 1.1 背景

GM-SafePick Phase 1–2 已完成反应式安全门控（Layer 1/2）：`g_t` 在 50 Hz 循环内输出 `ALLOW` / `SLOW_DOWN` / `STOP`。当 `g_t ≠ ALLOW` 时，状态机 `time_step` 冻结（T7 轨迹时钟），任务轨迹无法推进，形成**活锁（live lock）**。

挡空箱场景（`ivj_static_block_place`）中，人手挡在 B 放置口，夹持 descend 窗口触发大量 `SLOW_DOWN`（~41% 干预率），`time_step` 冻于 ~1771/7521，`outcome` 为 `timeout`——这是 Phase 1 可接受的已知限制，但**不能作为长期交付状态**。

论文 *Proactive Physical Safety Reasoning* 的 Stage 5 `replan` 与本项目的 **Motion Replan 执行器**对齐：在风险存在时**修改路径**绕开危险区，使任务继续推进，而非无限 STOP/hold。

### 1.2 Phase 3.5 目标

Phase 3.5 **不写执行器实现**，仅锁定：

1. Motion Replan 模块与状态机的**接口契约**（`ReplanRequest` / `ReplanHint` / `MotionReplanExecutor`）
2. **触发条件**边界（warn/SLOW 区可触发；Tier0 硬 STOP 不触发）
3. **`time_step` 语义**（replan 后轨迹时钟如何推进）
4. **活锁指标**定义与验收 preset
5. Phase 3（VLM）与 Phase 4a/4b（几何 / VLM 驱动重规划）的**并行边界**
6. Qwen2.5-VL-7B **显卡与部署配置**（支撑 Phase 3 并行启动）

---

## 2. 已锁定决策（P0）

| # | 决策域 | 锁定结论 | 说明 |
|:-:|:------|:---------|:-----|
| P0-1 | **VLM 后端** | **Qwen-only 单后端** | `VLMClient` → 单一 Qwen2.5-VL-7B；专用 VLM server（HTTP/gRPC）**允许**，MVP **不含** `VLMRouter` / Fast-Slow 多模型路由 |
| P0-2 | **Isaac 回归策略** | **短跑、定向回归**（非批量） | 仿真恢复后优先 `ivj_static_block_place` 等单 preset、`--max_steps=3000` 烟测；**不**恢复 `collect_ivj_logs.py` 式批量采集直至 Phase 4a 契约落地 |
| P0-3 | **Replan 触发区** | **仅 warn / SLOW 区**；**Tier0 硬 STOP 不变** | `dist < safe_dist_hard_stop`（默认 0.13 m）→ 永久 STOP/hold，**不**发 replan 请求；replan 仅在 `SLOW_DOWN` 或 warn band 内评估 |

### 2.1 VLM MVP 路径（§7.5 引用）

与 [项目进展 §7.5](../GM-SafePick_项目进展与遗留问题.md) 一致：

| 项 | 结论 |
|:---|:-----|
| MVP 后端 | 单 Qwen 路径：`VLMClient` → Qwen2.5-VL-7B-Instruct |
| 专用 VLM server | 允许（独立进程/机器，HTTP 或 gRPC）；仍为单后端、无 router |
| Fast/Slow 路由 | 推迟为后续分支实验 |
| 理由 | Layer 3 增量价值验证前，降低集成与运维复杂度 |

---

## 3. 接口草案

### 3.1 `ReplanRequest` — 触发侧 → 执行器

异步队列元素；由 L1 warn 监测器或（Phase 4b）VLM Stage 5 产出。**不阻塞** 50 Hz 门控循环。

```python
@dataclass(frozen=True)
class ReplanRequest:
    """Motion Replan 触发请求（Phase 3.5 契约；Phase 4a 实现消费）。"""

    request_id: str              # UUID，幂等与日志关联
    step_index: int              # 仿真步索引（SafetyLogger 对齐）
    task_time_step: int          # 状态机轨迹索引（replan 切入点）
    trigger_source: str          # "l1_warn" | "vlm_stage5"（4b）
    trigger_rule: str            # "static_warn" | "ttc_warn" | "vlm_replan"
    dist_ee_human: float         # 遗留字段名；语义 = dist_min（全包络最近距离，m）— 见 §3.4
    g_rule: int                  # 触发时刻规则输出（预期 SLOW_DOWN=2）
    ee_pos: tuple[float, float, float]
    human_hand_pos: tuple[float, float, float]
    hint: "ReplanHint | None"    # Phase 4a 可为 None（纯几何默认）
    created_at_s: float          # monotonic 时间戳
```

**约束**：

- `g_rule == STOP` 且触发距离 `< safe_dist_hard_stop`（**读 `dist_min`**，非 EE 点距）→ **禁止**构造 `ReplanRequest`（Tier0 硬 STOP）
- 同一 `task_time_step` 在 `replan_cooldown_steps`（默认 200 步 ≈ 4 s）内至多 1 次请求，防止重规划风暴

### 3.2 `ReplanHint` — 几何 / 语义绕行参数

Phase 4a 使用固定默认；Phase 4b 由 VLM Stage 5 JSON 映射。

```python
@dataclass(frozen=True)
class ReplanHint:
    """绕行建议参数（几何 v0 或 VLM Stage 5 解析结果）。"""

    # 几何 v0 默认（Phase 4a）
    raise_approach_m: float = 0.05    # 抬高接近/抬升高度（相对 APPROACH_HEIGHT）
    lateral_offset_m: float = 0.15    # 横向偏移（绕开 human_hand 安全泡）
    side: str = "auto"                # "left" | "right" | "auto"（auto = 远离人手侧）

    # Phase 4b 扩展（可选）
    semantic_context: str | None = None   # VLM 自然语言理由
    vlm_confidence: float | None = None
```

VLM Stage 5 映射示例（Layer 3 §3.4）：

```json
{
  "suggested_action": "replan",
  "replan_hint": {
    "raise_approach_m": 0.05,
    "lateral_offset_m": 0.15,
    "side": "left"
  }
}
```

### 3.3 `MotionReplanExecutor` — 执行器契约

```python
class MotionReplanExecutor(ABC):
    """修改 pick_and_place 路点序列；与门控并行、非阻塞。"""

    @abstractmethod
    def submit(self, request: ReplanRequest) -> str:
        """入队 replan 请求；返回 request_id。"""

    @abstractmethod
    def poll(self) -> ReplanResult | None:
        """非阻塞取已完成结果（每控制周期或独立线程调用）。"""

    @abstractmethod
    def apply(self, result: ReplanResult, policy: PickAndPlacePolicy) -> None:
        """将新路点序列注入状态机；更新 time_step 语义（见 §5）。"""


@dataclass(frozen=True)
class ReplanResult:
    request_id: str
    status: str                  # "success" | "failed" | "no_op"
    new_trajectory_len: int        # 新路点序列长度
    resume_time_step: int        # replan 后 policy 应从此索引继续
    latency_ms: float
    failure_reason: str | None = None
```

**职责边界**：

| 模块 | 做 | 不做 |
|:-----|:---|:-----|
| Layer 1/2 门控 | STOP / SLOW_DOWN / ALLOW | 修改轨迹 |
| Motion Replan 执行器 | 插入/替换路点段；通知 policy 续跑 | 覆盖 Tier0 STOP |
| VLM Stage 5 | 输出 `replan_hint` 建议 | 直接改 `time_step` 或路点 |

**建议代码路径**（Phase 4a 实现时）：

```
GMRobot/safety/replan/
  types.py          # ReplanRequest, ReplanHint, ReplanResult
  executor.py       # MotionReplanExecutor, GeometryReplanV0
  triggers.py       # L1 warn 监测 → ReplanRequest
```

### 3.4 Replan 距离语义：`dist_min`，非 `dist_ee_human`

> ### ⚠️ 强制契约（与 [Phase 2.5 ADR §3.1](./GM-SafePick_Phase2.5_EnvelopeDecisions.md#31-replan-距离字段11) 一致）
>
> **ReplanRequest** 与 **L1WarnReplanTrigger** 使用的距离 = **`dist_min_envelope`**（腕部 + 双指尖 + 夹持物盒 ↔ 人手球心，取 **min**），**不是** legacy EE 点距离 `dist_ee_human`。

#### 字段映射（2.5b 起）

| 符号 / 列名 | 语义 | Replan 是否读取 |
|:------------|:-----|:---------------:|
| `dist_ee_human`（CSV / metadata 键） | Phase 1–2 **EE 点**距；**遗留列名** | ❌ 仅归档 / Layer 2 对照 |
| `dist_min_envelope`（CSV 新列） | 全包络最近距离 | ✅ **权威日志列** |
| `dist_min`（运行时 gate 读数） | `min(dist_min_envelope, …)` | ✅ **门控 + replan 唯一输入** |
| `ReplanRequest.dist_ee_human` | **字段名遗留**；值 = 触发时刻 **`dist_min`** | ✅ 写入时填 `dist_min` |

实现阶段（[`replan/triggers.py`](../../GMRobot/safety/replan/triggers.py)）：从 `gate_result.metadata["dist_ee_human"]` 读取——**键名 legacy，2.5b 起 RuleEngine 写入 `dist_min`**。

#### 为何 replan 必须读 `dist_min`（不能只读 EE）

1. **shoulder-pass 漏触发**：肩/上臂穿越通道时 EE 距仍可 >0.25 m，EE-only replan 认为「安全区」→ **不触发**；全包络 `dist_min` 因臂段球更早进入 warn 带 → 与门控一致触发 SLOW/replan。
2. **place defer 阈值**：`replan_defer_dist_m=0.15 m`、`tier0_proximity_margin_m=0.02 m`、**place** 窗口 defer 以 **`dist_min`** 为准。**approach / late-approach defer** 有意使用 **`dist_ee_human`**（EE 点距），因 splice 路点 EE-centric；shoulder-pass 时 `dist_min` 更小但 EE 仍在 defer 区外（见 §3.4 defer 表）。
3. **Tier0 对齐**：Tier0 硬 STOP `<0.13 m`、warn `0.13–0.19 m` 在 2.5b 语义改为相对 **`dist_min`**；replan 若仍按 EE 判 defer/禁止，会出现「规则已 STOP/SLOW、replan 仍 submit」分叉。

#### 触发逻辑中的距离（与 §4.2 一致）

```text
dist := gate_result.metadata["dist_ee_human"]   # 键名 legacy；值 = dist_min（2.5b+）

IF g_rule == SLOW_DOWN
   AND dist >= safe_dist_hard_stop              # warn / TTC-warn / static_far 区
   AND sustained_slow_steps >= replan_trigger_threshold:
     EMIT ReplanRequest(..., dist_ee_human=dist)   # 字段名 legacy，值 = dist_min

IF g_rule == STOP AND dist < safe_dist_hard_stop:
     # Tier0 — NO replan（dist 为 dist_min）
     PASS
```

**defer 距离口径**（[`triggers.py`](../../GMRobot/safety/replan/triggers.py)）：

| 窗口 | 比较量 | 说明 |
|:-----|:-------|:-----|
| `place` | **`dist_min`**（`dist_f`） | 与 Tier0 / warn 带一致；held-critical 另判 `dist_min_held` |
| Tier0 邻近 / `in_place_window` | **`dist_min`** | `dist_f < hard_stop + margin` |
| `approach` / `defer_late_approach` | **`dist_ee_human`**（EE 点距） | **有意例外**：splice 路点 EE-centric；shoulder-pass 时 `dist_min` 可更小而 EE 仍在 defer 区外 → 避免过早 wait-hold |

触发阈值、sustained SLOW、Tier0 禁止 replan、写入 `ReplanRequest.dist_ee_human` 仍一律用 **`dist_min`**（`dist_f`）。

---

## 4. 触发条件

### 4.1 距离与规则分区（默认 preset）

> **距离口径**：下表 `dist` = **`dist_min`**（2.5b+）；Phase 2.5a 审计期门控仍 EE 口径，replan 契约已按 2.5b 锁定。

| 分区 | 条件 | `g_rule` | Replan |
|:-----|:-----|:---------|:------:|
| **Tier0 硬 STOP** | `dist < 0.13 m` | `STOP` | ❌ **禁止** |
| **warn band（静态警戒带）** | `0.13 m ≤ dist < 0.19 m` | `SLOW_DOWN` | ✅ 可触发 |
| **安全区** | `dist ≥ 0.19 m` | `ALLOW` | ❌ 无需 |
| **TTC warn** | `ttc < ttc_warn_threshold` 且 `dist ≥ 0.13 m` | `SLOW_DOWN` | ✅ 可触发 |
| **TTC 硬 STOP** | `ttc < ttc_threshold` | `STOP` | ❌ **禁止**（非 warn） |

> **Tier0 语义**：`safe_dist_hard_stop`（0.13 m）与 GT v1.1 `collision_threshold` 对齐；此区内**任何** replan 请求均被丢弃，门控保持 STOP/hold。持续 Tier0 STOP 导致的活锁**不能**靠 replan 消解，只能等人手移开或任务中止——这是安全底线。

### 4.2 触发逻辑（Phase 4a v0）

```text
ON each control step (50 Hz):
  dist := metadata["dist_ee_human"]   # legacy 键名；2.5b+ 值 = dist_min

  IF g_rule == SLOW_DOWN
     AND dist >= safe_dist_hard_stop    # warn / TTC-warn / static_far 区（dist_min）
     AND sustained_slow_steps >= replan_trigger_threshold:   # 默认 50 步 ≈ 1 s
       EMIT ReplanRequest(trigger_source="l1_warn", dist_ee_human=dist, ...)

  IF g_rule == STOP AND dist < safe_dist_hard_stop:
       # Tier0 — 仅 STOP/hold，NO replan（dist 为 dist_min）
       PASS
```

**「持续 STOP」澄清**：架构总览早期草稿曾写「持续 STOP → replan 信号」。**本 ADR 锁定**：仅 **Tier0 以外的 SLOW/warn** 可触发 replan。`g_rule == STOP` 且 `dist < 0.13 m` 时，无论持续多久，**均不触发** replan。

### 4.3 Phase 4b 扩展触发

VLM `vlm_suggested_action == "replan"` 且 `g_t == ALLOW` 时，可额外提交 `ReplanRequest(trigger_source="vlm_stage5")`。VLM 建议**不能**降级 Tier0 STOP。

---

## 5. `time_step` 语义

### 5.1 当前行为（Phase 1–2）

```text
advance_mask = (g_t == ALLOW)
policy.advance_time_steps(advance_mask)
```

- `ALLOW`：`time_step += 1`
- `SLOW_DOWN` / `STOP`：`time_step` **冻结**（T7）

### 5.2 Replan 后行为（Phase 4a 目标）

```text
1. 触发时刻：g_rule == SLOW_DOWN，time_step 冻结于 T0（与现行为一致）
2. MotionReplanExecutor 异步计算新路点序列：
     - 在当前 stage（如 DESCEND→B）插入抬高 + 侧偏绕行段
     - 生成 new_time_stamps，resume_time_step = T0（或 T0+1，实现时二选一并单测锁定）
3. apply() 注入 policy：
     - 替换自 T0 起的后续路点
     - time_step 设为 resume_time_step
4. 后续步进：
     - 若新路点使 dist 脱离 warn band → g_rule 恢复 ALLOW → time_step 正常推进
     - 若仍 SLOW_DOWN 但路径已抬高 → 允许在 SLOW 下继续推进 time_step（**Phase 4a 待决细项**，见 §12）
```

**设计原则**：replan 的目的是让任务**继续推进**而非永久 hold。Phase 4a 最低验收：`ivj_static_block_place` 上 `task_time_step` 最终超过 replan 前冻结点，且 `outcome` 优于 `timeout@1771/7521`。

### 5.3 日志字段

replan 事件写入 SafetyLogger 扩展列（Phase 4a 增列）：

| 列名 | 说明 |
|:-----|:-----|
| `replan_request_id` | 关联请求 |
| `replan_status` | success / failed / no_op |
| `replan_resume_time_step` | 续跑索引 |

---

## 6. 活锁指标定义

| 指标 | 定义 | 采集 |
|:-----|:-----|:-----|
| **max_consecutive_stop_steps** | 单 episode 内 `g_t == STOP` 的最长连续步数 | `report_safety_metrics.py` 扩展 |
| **max_consecutive_slow_steps** | 单 episode 内 `g_t == SLOW_DOWN` 的最长连续步数 | 同上 |
| **time_step_stall_ratio** | `(step_counter - task_time_step) / step_counter` | 衡量轨迹滞后 |
| **task_progress_ratio** | `task_time_step / task_time_step_max` | outcome 代理 |
| **replan_success_rate** | `status==success` 的 replan 数 / 总 replan 请求数 | Phase 4a 起 |
| **post_replan_collision_rate** | replan 后 100 步内 GT STOP 占比 | Phase 4a 起 |

**活锁判定（挡空箱）**：Phase 4 前 baseline — `ivj_static_block_place` run `20260617_192734`：`max_consecutive_slow_steps` 对应长时间 SLOW 块，`task_progress_ratio ≈ 1771/7521 ≈ 0.24`，`outcome = timeout`。

**Phase 4a 验收目标（草案）**：

- `task_progress_ratio ≥ 0.80`（单零件周期内完成 B 放置段）
- `max_consecutive_stop_steps` 不劣于 baseline（Tier0 行为不变）
- `replan_success_rate ≥ 0.90`（几何 v0）

---

## 7. `vlm_*` 列名约定

### 7.1 当前 Logger 预留列（Phase 3 前）

[`logger.py`](../../GMRobot/safety/logger.py) 已写入空默认值：

| 列名 | 类型 | 说明 |
|:-----|:-----|:-----|
| `vlm_risk_class` | string | static / dynamic / functional / none |
| `vlm_confidence` | float | 0–1 |
| `vlm_suggested_action` | pause / slow_down / replan / continue |
| `vlm_model_id` | string | 如 `Qwen2.5-VL-7B-Instruct-awq` |
| `rgb_frame_path` | string | 异步推理所用帧路径 |

### 7.2 Layer 3 目标 schema（Phase 3 扩展时增列）

与 [Layer 3 §5.5](../GM-SafePick_Layer3_VLM推理增强层.md) 对齐，**前向填充**至下一步 VLM 结果：

| 列名 | 类型 | 说明 |
|:-----|:-----|:-----|
| `vlm_risk_type` | string | 与 `vlm_risk_class` 同语义；**Phase 3 实现时统一为 `vlm_risk_type`**，`vlm_risk_class` 作别名 deprecate |
| `vlm_severity` | string | low / medium / high |
| `vlm_explanation` | string | 自然语言摘要 |
| `vlm_stage` | int | 最近完成阶段 1/3/4/5 |
| `vlm_latency_ms` | float | 端到端推理耗时 |

**约定**：VLM 异步结果按 `step_index` 对齐；未推理步留空。`vlm_suggested_action == "replan"` 仅作日志与 Phase 4b 队列输入，**不**直接进入 50 Hz 门控。

---

## 8. 验收 preset

**主验收场景**：`ivj_static_block_place`

| 项 | 值 |
|:---|:---|
| 配置 | [`configs/ivj/ivj_static_block_place.yaml`](../../../../configs/ivj/ivj_static_block_place.yaml) |
| 叙事 | 挡空箱 — 人手挡 B 放置口，descend 窗口 SLOW/干预 |
| 参考 run | `20260617_192734`（干预率 41%，`time_step` 冻于 1771） |
| Phase 3.5 离线验收 | 接口类型定义 + 单元测试（mock policy）；**无需 Isaac** |
| Phase 4a Isaac 验收 | 短跑 `--max_steps=3000`，对比活锁指标（§6） |

```bash
# Phase 4a 烟测命令模板（定向短跑，非批量）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config=configs/ivj/ivj_static_block_place.yaml \
  --max_steps=3000 --progress_interval=500
```

---

## 9. Phase 3 / 4a 并行边界

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 3（Layer 3 VLM）              Phase 3.5（本 ADR）      │
│  ─ VLMClient → Qwen 7B              ─ 接口/触发契约（本文）   │
│  ─ GDINO + SAM2                     ─ 活锁指标定义           │
│  ─ vlm_* 列填入                     ─ time_step 语义设计      │
│  ─ Stage 5 JSON 输出（不执行）       ─ 无执行器代码            │
│  可并行 ────────────────────────────────────────────────────│
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 4a（几何 replan，无 VLM）                               │
│  ─ 实现 MotionReplanExecutor v0                              │
│  ─ 消费 L1 warn → ReplanRequest                              │
│  ─ Isaac 短跑验收 ivj_static_block_place                     │
│  依赖：Phase 3.5 契约锁定 ✅                                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 4b（VLM 驱动 replan）                                   │
│  ─ 消费 vlm_suggested_action=replan + ReplanHint             │
│  依赖：Phase 4a 基线 + Layer 3 Stage 5 稳定输出               │
└─────────────────────────────────────────────────────────────┘
```

| 可并行 | 必须串行 |
|:-------|:---------|
| Phase 3 VLM 推理层 ∥ Phase 3.5 契约文档/类型 | 4a 依赖 3.5 接口 |
| Phase 3 `vlm_*` 日志 ∥ 4a 几何执行器编码 | 4b 依赖 4a + Stage 5 |
| Qwen 部署验证 ∥ replan 单元测试 | Isaac 批量采集推迟到 4a 后 |

---

## 10. Qwen 7B 显卡与部署配置

> 来源：[VLM 模型选型讨论（归档）](./archive/GM-SafePick_VLM模型选型讨论.md)、[Layer 3 §4](../GM-SafePick_Layer3_VLM推理增强层.md)、[AI 服务器部署 §1–§6](../GM-SafePick_AI服务器部署.md)

### 10.1 模型与量化

| 配置 | 显存占用 | 推理延迟（640×480 单帧） | 推荐场景 |
|:-----|:--------:|:----------------------:|:---------|
| FP16 | ~16 GB | ~1.5 s | 专用 VLM 服务器、无 Sim 同卡 |
| 4-bit GPTQ | ~8 GB | ~1.0 s | 同机部署备选 |
| **4-bit AWQ（推荐）** | **~8 GB** | **~0.8 s** | MVP 默认；满足 ≤2 s 论文指标 |

**模型 ID**：`Qwen/Qwen2.5-VL-7B-Instruct`（HuggingFace）

### 10.2 推荐显卡规格

| 部署模式 | 最低显卡 | 推荐显卡 | 说明 |
|:---------|:---------|:---------|:-----|
| **专用 VLM 服务器** | RTX 3090 24GB | **RTX 4090 24GB** | VLM 独占一卡；Sim 在另一进程/机器 |
| **同机 Sim + VLM** | RTX 4090 24GB | RTX 4090 24GB | Sim headless ~8–12 GB + VLM AWQ ~8 GB ≈ 16–20 GB |
| **开发/CI CPU offload** | 无独显 | — | `device_map="auto"` + CPU offload；延迟 5–15 s，仅离线/蒸馏 |

### 10.3 部署拓扑（已锁定）

**MVP 锁定拓扑**：**Isaac 本地（Sim 节点）+ AI 专用服务器（VLM 推理）** — 对应下表拓扑 **C**。

| 角色 | 节点 | 进程 | GPU 负载 |
|:-----|:-----|:-----|:---------|
| **Sim** | 本地 / gpufree（Isaac Lab） | `gm_state_machine_agent.py` | Isaac headless ~8–12 GB；**不加载 VLM 权重** |
| **VLM** | **AI 专用服务器**（见 §10.6） | Qwen 7B AWQ +（Phase 3 后续）GDINO + SAM2 | L40S 48 GB 独占推理栈 |
| **通信** | Sim → AI server | HTTP/gRPC（`VLMClient` 远程 backend） | ~1 Hz 异步；**不阻塞** 50 Hz 门控 |

| 拓扑 | 进程布局 | 通信 | MVP 适用 |
|:-----|:---------|:-----|:--------:|
| **A. 同进程同卡** | Isaac + VLM 单 Python | 内存直传 | ❌ 显存紧张，仅本地烟测 |
| **B. 同机双进程** | Sim GPU0 + VLM GPU0 或 GPU1 | HTTP/gRPC localhost | ⚠️ 备选 |
| **C. 专用 VLM 服务器** | Sim 本地；VLM 在独立 GPU 节点 | HTTP/gRPC 局域网 | ✅ **MVP 默认** |

```text
拓扑 C（Isaac 本地 + AI 专用服务器，MVP 锁定）:

  ┌──────────────────────────┐      HTTP POST /analyze       ┌──────────────────────────┐
  │  本地 / Sim 节点            │  ─── RGB + prompt + meta ──►  │  gm-ai-server             │
  │  Isaac Sim 8–12 GB       │  ◄── JSON (Stage 1–5) ─────   │  120.209.70.195:30481     │
  │  VLMClient 无本地权重      │                               │  L40S 48 GB               │
  │  SafetyLogger vlm_* 写入   │                               │  Qwen2.5-VL-7B AWQ ~8 GB  │
  └──────────────────────────┘                               │  (+ GDINO/SAM2 Phase 3b)  │
                                                               └──────────────────────────┘
```

**Phase 3 安装分期**（AI 服务器）：

| 阶段 | 组件 | 优先级 | 说明 |
|:----:|:-----|:------:|:-----|
| **3a** | Qwen2.5-VL-7B-Instruct 4-bit AWQ + FastAPI `/analyze` | **P0** | MVP；本 ADR 会话优先完成 |
| **3b** | Grounding DINO + SAM2 | P1 | Qwen smoke test 通过后安装；与 Layer 3 感知链对齐 |

### 10.6 AI 专用服务器（gm-ai-server）

> **凭证**：SSH 别名 `gm-ai-server`（`~/.ssh/config`）；密码存于 `/root/.github_token` 文件末尾 — **禁止提交 git**。

| 项 | 值 |
|:---|:---|
| **Host** | `root@120.209.70.195:30481`（alias: `gm-ai-server`） |
| **GPU** | NVIDIA L40S **48 GB**（检测：`nvidia-smi`） |
| **OS** | Ubuntu **22.04** |
| **驱动** | **580.x**（与 CUDA 12.x PyTorch 匹配） |
| **RAM** | **1 TB**（文档推荐 ≥64 GB；当前远超） |
| **Python** | **3.11**（conda env `vlm` 或等价 venv） |
| **推理栈** | Qwen2.5-VL-7B-Instruct **4-bit AWQ**；后续 GDINO + SAM2 |
| **服务 URL** | `http://120.209.70.195:8080/analyze`（内网/localhost 已验证；外网 8080 待 gpufree 防火墙放行） |

**Sim 侧 `VLMClient` 配置（Phase 3）**：

```yaml
# configs/vlm_client.yaml（示意）
backend: remote_http
base_url: "http://120.209.70.195:8080"
endpoint: "/analyze"
model_id: "Qwen2.5-VL-7B-Instruct-awq"
timeout_s: 5.0
```

**安全约束**：

- 服务器凭证、API key **不得**写入仓库；仅本地 `~/.ssh/config` + `/root/.github_token`
- VLM 服务建议绑定内网或防火墙白名单；MVP 阶段可 `0.0.0.0` + 端口限制

详细安装步骤与 smoke test 记录见：[GM-SafePick_AI服务器部署.md](../GM-SafePick_AI服务器部署.md)（ADR 附录 A）。

### 10.4 环境依赖（示例）

```bash
pip install transformers accelerate qwen-vl-utils pillow
# AWQ 量化（按选型）
pip install autoawq   # 或 vllm --quantization awq
```

| 项 | 要求 |
|:---|:-----|
| GPU 驱动 | 容器内 `nvidia-smi` 可见 |
| 磁盘 | ≥ 50 GB（Sim 缓存 + 权重 ~15 GB） |
| Python | 3.11（`env_isaaclab`） |
| 推理频率 | ~1 Hz（非 50 Hz 门控路径） |

### 10.5 显存不足回退策略

1. **4-bit AWQ**（首选，约 8 GB）
2. **降低 `--num_envs`**，缩减 Sim 显存
3. **双进程分卡**：Sim GPU0、VLM GPU1
4. **CPU offload**：可运行但延迟显著上升；仅用于离线标注/蒸馏，不用于在线 ~1 Hz 循环

---

## 11. 开放问题 / 后续分支

| # | 问题 | 状态 | 分支 |
|:-:|:-----|:----:|:-----|
| O1 | SLOW_DOWN 下 replan 后是否允许 `time_step` 推进？ | 待 4a 实验 | 方案 A：仅 ALLOW 推进；方案 B：replan 后 SLOW 也推进 |
| O2 | `resume_time_step = T0` vs `T0+1` | 待 4a 单测 | 与 T7「STOP 不跳零件」联动验证 |
| O3 | `replan_cooldown_steps` 最优值 | 待 4a 调参 | 默认 200 步 |
| O4 | **`VLMRouter` / Fast-Slow 多模型** | **后续分支** | 小模型 ~1 Hz 常驻 + 大模型按需；非 MVP |
| O5 | GPT-4o API 后端 | 备选 | 网络可达时作对照实验，非 MVP 主路径 |
| O6 | `vlm_risk_class` → `vlm_risk_type` 列名统一 | Phase 3 实现时 | 见 §7.2 |
| O7 | Isaac 批量 `collect_ivj_logs.py` 恢复时机 | Phase 4a 契约落地后 | 与 P0-2 短跑策略相对 |
| O8 | AI 服务器 VLM 服务端口与 TLS | Phase 3 联调时 | 默认 HTTP 8080；生产可加 reverse proxy |
| O9 | GDINO + SAM2 与 Qwen 同机显存预算 | Phase 3b | L40S 48 GB 充裕；安装顺序 Qwen → GDINO → SAM2 |

---

## 12. Phase 4a v1 用户反馈与修订（2026-06-18）

> **背景**：4a v0（`--enable_replan`）在 `ivj_static_block_place` 实机/仿真短跑中，夹爪保持闭合已修复，但出现**放置区外落件**、**检测偏晚**、**抬升过快**三类新问题。本节在 **不推翻** §2–§6 契约的前提下，锁定 v1 设计修订与实现优先级。

### 12.1 问题确认（v0 观测）

| # | 用户报告 | v0 根因（代码/参数） | 严重度 |
|:-:|:---------|:---------------------|:------:|
| F1 | 遇手后上抬，零件仍夹持但**落在箱外** | `splice_replan_detour` 横向偏移 `lateral_offset_m=0.15` **无放置槽位约束**；rejoin 虽回原轨迹，绕行中间点可偏离 `place_pos` | P0 |
| F2 | 检测**不敏感**，临近放置才触发再突然上抬 | `replan_trigger_threshold=50`（≈1 s 持续 SLOW）；warn 带 `0.13–0.19 m` 在 descend 末段才稳定进入；无**预警**态 | P1 |
| F3 | **上抬速度过快**，有伤人风险 | 绕行三段各 `DETOUR_STAGE_DURATION=40` 与常态 stage 同速；`post_replan_advance` 在 SLOW 下仍推进 `time_step`；place 段仍用全幅 `raise_approach_m=0.05` | P0 |

**已知已修复（简述）**：descend 窗口 replan 时 detour 路点保持 `gripper_closed`（`test_detour_during_descend_keeps_gripper_closed`）— 不再复述 gripper 回归细节。

### 12.2 用户建议 → 设计映射

| 用户建议 | v1 设计响应 |
|:---------|:------------|
| **1. 约束放置** — 方块只能进指定区域 | 引入 **placement zone**：以当前 `place` stage 的 `slot_*_T` 中心为锚，XY 容许盒 `±place_zone_radius_m`（默认 **0.08 m**）；`open_gripper` 前校验 EE XY ∈ zone，否则 **禁止开爪** 并 wait-hold |
| **2. 三阶段运输** — 分阶段限制避障幅度 | **TransportPhase** 三分：`transit`（搬运/抬升）/ `approach`（`move_above_box`）/ `place`（`descend`→`open`）；每阶段独立 `max_raise_m`、`max_lateral_m`、`detour_duration`（place 段最保守） |
| **3. 不可避免则停等** — 非激进逃逸 | **place 窗口**或 `dist → Tier0` 时：**推迟几何 replan**，改为 `WAIT_HOLD`（`time_step` 冻结可接受）；仅当 `dist ≥ hard_stop + margin` 且非 place 窗口才允许全幅绕行；Tier0 仍 **STOP only**（§4.1 不变） |

### 12.3 三阶段运输模型（v1 默认参数草案）

| 阶段 | 覆盖 stage（policy） | `max_raise_m` | `max_lateral_m` | `detour_duration`（步） | 策略 |
|:-----|:---------------------|:-------------:|:---------------:|:-----------------------:|:-----|
| **transit** | `lift_*`、`move_above_{pick}`、通道搬运 | 0.06 | 0.15 | 40 | 允许全幅侧偏绕手 |
| **approach** | `move_above_box_with_*` | 0.04 | 0.10 | 50 | 中等抬高，横向受限 |
| **place** | `descend_to_box_with_*`、`open_gripper_*` | **0.02** | **0.05** | **60** | 最小抬升、槽位内 clamp；优先 wait-hold |

**place 段额外约束**：

- 横向绕行点 **clamp** 至 `place_pos ± place_zone_radius_m`
- `open_gripper` 触发前：`validate_placement(ee_xy, slot_xy, radius)` → 失败则 hold，**不**开爪
- 若 `dist_min < hard_stop + 0.02 m` 且处于 place 窗口 → **不 splice**，`WAIT_HOLD` 等人手撤离（`dist_min` 为全包络最近距离；字段/日志键可能仍为 `dist_ee_human`）

### 12.4 触发与速度修订

| 项 | v0 | v1 目标 |
|:---|:---|:--------|
| 持续 SLOW 触发阈值 | 50 步 | **30 步**（≈0.6 s）触发 replan；**15 步** 仅日志/预警（`replan_early_warn_steps`，不 splice） |
| SLOW 门控 | `slow_down_alpha=0.3` 全局 | 绕行窗口内叠加 **detour_slow_alpha=0.15**（config 可选）；place 段禁止 `post_replan_advance` 加速 |
| 不可避免 | 一律抬高+侧偏 | place/Tier0 邻近 → **STOP + wait**；transit 才允许几何绕行 |

### 12.5 实现清单（P0 / P1）

#### P0 — 下一迭代必做

| ID | 任务 | 触点 |
|:---|:-----|:-----|
| P0-A | `TransportPhase` 判定 + 阶段化 `ReplanHint` | `executor.py`、`pick_and_place_policy.stage_name_at_step` |
| P0-B | place 段 `raise/lateral` 缩减 + `detour_duration` 加大 | `executor.py`、`ReplanHint` 默认 |
| P0-C | 横向绕行 **placement zone clamp** | `splice_replan_detour(..., place_target_xy, place_zone_radius_m)` |
| P0-D | place 窗口 / Tier0 邻近 **defer replan → wait-hold** | `triggers.py` + agent 循环（不 submit 或 `status=wait_hold`） |
| P0-E | `open_gripper` 前 **placement validity** | policy 或 executor 在 place stage 门禁 |
| P0-F | Isaac 短跑回归：`ivj_static_block_place` + 落点是否在 B 槽位（人工/日志 XY） | `accept_block_place_replan.sh` 扩展 |

#### P1 — 体验与可观测性

| ID | 任务 | 触点 |
|:---|:-----|:-----|
| P1-A | `replan_early_warn_steps=15` 写日志列 `replan_warn` | `triggers.py`、`SafetyLogger` |
| P1-B | `replan_trigger_threshold` 50→30（可配置） | `ReplanTriggerConfig`、preset yaml |
| P1-C | `detour_slow_alpha` 与 place 段禁用 `post_replan_advance` | `gate.py` / agent |
| P1-D | 活锁指标增 `placement_out_of_zone_count` | §6 指标表 |

### 12.6 v0 → v1 验收标准增补

在 §6 Phase 4a 草案基础上增加：

- **放置正确性**：首周期 B@1 落件 EE XY 与 `slot_B_1_T` 偏差 ≤ `place_zone_radius_m`（代理指标，非物理零件计数）
- **安全体感**：place 段绕行 Z 速度 ≤ transit 段 50%（由 `detour_duration` 与 `max_raise_m` 保证）
- **wait-hold**：挡空箱场景中，至少 1 次 episode 在 place 窗口选择 wait 而非箱外 lateral（日志可辨）

**Isaac 短跑记录（2026-06-18，`ivj_static_block_place`，3000 sim steps，`--enable_replan`）**

| run_id | final task_ts | vs ref 1771 | post-1771 空中开爪 | outcome | 备注 |
|:-------|:-------------:|:-----------:|:------------------:|:--------|:-----|
| `20260618_191251` | **1935** | PASS | 0 | collision | 末 200 步 task_ts 冻结 @1935 + g_rule=SLOW（wait-hold）；无 post-1771 open_gripper 尝试 |
| `20260618_185254`（中间版） | 1874 | PASS | 0 | timeout@1874 | `stage_sequence` 未同步导致误触发 placement hold，已修复 |

单元测试：`python scripts/test_replan_unit.py`（8 cases）全部通过。

### 12.7 开放问题更新（承接 §11）

| # | 问题 | v1 倾向 |
|:-:|:-----|:--------|
| O1 | SLOW 下 replan 后推进 `time_step` | **分阶段**：transit/approach 可推进（方案 B）；**place 禁止** |
| O10 | wait-hold 与 Tier0 STOP 边界 | `dist < hard_stop` → STOP；`hard_stop ≤ dist < hard_stop+0.02` 且在 place → wait-hold |
| O11 | `place_zone_radius_m` 标定 | 默认 0.08 m；随 slot 几何与零件尺寸调参 |

### 12.8 held-aware 多策略绕行增补（2026-06-22）

**动机**：目视 fast_sweep v2 @ step 640 — 默认先抬升再横移时，held 盒外廓扫向人手 → 打件（gripper 仍闭合）。v1 路点仅 EE-centric。

**契约增补**：

- `ReplanRequest` 扩展 `dist_min_held`、`dist_min_envelope`、`closest_primitive_id`、`hand_speed_mps`（触发侧从 `GateResult.metadata` 填入）。
- `DetourStrategy`：`raise_then_lateral` | `lateral_first` | `retreat_then_arc`；`GeometryReplanV0.apply()` 调用 `select_detour_strategy()` 后传入 `splice_replan_detour`。
- place 且 `dist_min_held < 0.10 m` → **defer** 几何 splice（wait-hold），与 §12.3 place 最保守策略一致。
- **插入阶段**：transit/carry/lift 首选；approach 受限；place/descend 避免。

**验收**：`test_replan_unit.py`；block_place S1 `REF_TIME_STEP=2015` 默认策略不变；fast_sweep knock-off 需 Isaac GUI 复验（不宣称 Part 1 已修复）。

---

## 13. 参考

| 文档 | 内容 |
|:-----|:-----|
| [GM-SafePick_架构总览.md](../GM-SafePick_架构总览.md) | Phase 3.5/4 路线图 |
| [GM-SafePick_Layer3_VLM推理增强层.md](../GM-SafePick_Layer3_VLM推理增强层.md) | Stage 5、`vlm_*`、replan 分工 |
| [GM-SafePick_项目进展与遗留问题.md](../GM-SafePick_项目进展与遗留问题.md) | §7.5 VLM MVP、P0-4 活锁 |
| [GM-SafePick_VLM模型选型讨论（归档）](./archive/GM-SafePick_VLM模型选型讨论.md) | 2026-06-15 Qwen vs API 对比记录 |
| [GM-SafePick_VLM替换状态机技术方案（归档）](./archive/GM-SafePick_VLM替换状态机技术方案.md) | 早期 VLM 替换探索（未采用） |

---

## 附录 A. AI 服务器部署（摘要）

完整步骤见 [GM-SafePick_AI服务器部署.md](../GM-SafePick_AI服务器部署.md)。

| 步骤 | 内容 |
|:----:|:-----|
| 1 | SSH `gm-ai-server`；验证 `nvidia-smi`、磁盘、Ubuntu 22.04 |
| 2 | `conda create -n vlm python=3.11` |
| 3 | PyTorch + CUDA（匹配驱动 580.x） |
| 4 | `transformers accelerate qwen-vl-utils pillow` + AWQ 权重 |
| 5 | Smoke test：单图推理 |
| 6 | FastAPI stub：`POST /analyze` → JSON |
| 7 | Sim 侧 `VLMClient` 指向 `base_url` |

---

*本 ADR 已锁定 Phase 3.5 契约；Phase 4a 实现时接口变更须同步更新本文与架构总览 §6。*
