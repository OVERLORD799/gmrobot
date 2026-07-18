# GM-SafePick 自动调参 — 需求规格

> **定位**：定义安全系统自动参数优化的待实现能力、数据需求与设计决策
> **面向**：项目成员与 AI 阅读者（调参方案设计参考）
> **最后更新**：2026-06-30
> **状态**：需求已定义，待实现

---

## 1. 背景

当前安全系统有 18 个可调参数（距离阈值、TTC 阈值、减速系数、重规划几何参数等），分布在 `configs/safety_layer1.yaml` 和 `configs/safety_fusion.yaml` 中。手动调参依赖"跑 Isaac → 看指标 → 改 YAML → 再跑"的循环，每次迭代约 15 分钟（多场景则更长）。

自动调参的目标：在给定场景集合上，自动搜索最优参数组合，使安全系统在满足硬约束（零漏判）的前提下最小化误停和任务干扰。

---

## 2. 待建设的四个能力

### 2.1 离线参数重放脚本

**解决的问题**：评估参数太慢。

当前评估一组参数需要跑完整 Isaac 仿真（~15 分钟/场景，需 GPU）。实际上 L1 规则引擎是纯数学函数——给定 `ee_pos`、`human_hand_pos`、速度等输入和一组阈值参数，输出 `g_t`。这些输入已经全部记录在已有 CSV 日志中。

**离线重放**：拿一份已有 CSV，用新参数重新跑规则引擎，比较输出的 `g_t_replay` 和 CSV 中的 GT 标签，算出 false_stop_rate、miss_rate、safety_recall——完全无需 Isaac，一份 8000 行 CSV 重放不到 1 秒。

**待实现**：

```bash
# 单参数扫描
python scripts/replay_params_on_csv.py output/safety_logs/<run_id>/ \
  --sweep safe_dist_hard_stop=0.10,0.13,0.16 \
  --sweep slow_down_alpha=0.10,0.18,0.30 \
  --output output/param_sweep_results.json

# 多场景聚合评分
python scripts/param_search.py \
  --runs output/safety_logs/<run_id_far> output/safety_logs/<run_id_block> \
  --config configs/tuning/search_space.yaml \
  --scoring configs/tuning/scoring.yaml \
  --output output/param_search_best.json
```

**关键设计点**：

- L1 重放只需要 `SafetyState` 的输入字段（EE 位姿/速度、人手位姿/速度、关节角），这些在 CSV 中都有
- L2 fusion 也可重放：`g_rule`（重放值）+ `g_ml`（已有模型推理）→ Tier fusion → `would_fuse`
- 不能重放的部分：VLM 输出、perception 输出、replan 的轨迹修改效果——这些依赖实时仿真状态
- 输出格式：每个参数组合 → 一组指标（false_stop_rate, miss_rate, recall, intervention_rate）

### 2.2 统一评分函数

**解决的问题**：多指标无法自动比较。

当前 `report_safety_metrics.py` 输出多个独立指标（intervention_rate、false_stop_rate、miss_rate、safety_recall）。不同参数组合在这些指标上各有优劣——没有统一的数字就无法自动排名。

**评分函数将多个指标合并为一个单值**。公式模板：

```python
def score(metrics: dict, scenario_weight: float) -> float:
    # 硬约束：不满足直接淘汰（返回 -inf）
    if metrics["safety_recall"] < HARD_RECALL_THRESHOLD:  # e.g. 0.99
        return float("-inf")
    if metrics["miss_rate"] > HARD_MISS_LIMIT:            # e.g. 0.01
        return float("-inf")

    # 软指标加权求和
    s = (
        SAFETY_WEIGHT  * metrics["safety_recall"]
        + EFFICIENCY_WEIGHT * (1.0 - metrics["false_stop_rate"])
        + COMPLETION_WEIGHT * metrics.get("task_completion_ratio", 0.0)
        + SMOOTHNESS_WEIGHT * (1.0 - metrics.get("livelock_ratio", 0.0))
    )
    return scenario_weight * s
```

**待定义**（见 §3）：

- 各指标的权重（`SAFETY_WEIGHT` 等）
- 硬约束阈值（recall 必须 ≥ 多少才算合格）
- 是否需要惩罚项（如 `livelock_ratio > 0.5` 扣分）

### 2.3 参数搜索空间

**解决的问题**：不知道从哪里开始尝试。

18 个参数如果用盲目网格搜索，组合爆炸。需要：

- 每个参数的**物理合理范围**（如 `safe_dist_hard_stop` 的搜索下限是机械臂+手的球体半径和，上限是工作空间跨度）
- 高优先级参数列表（对行为影响最大的 5-6 个）
- 固定不变的参数（已校准或影响极小）

**当前可调参数清单**：

| 参数 | 当前值 | 单位 | 物理含义 | 调参优先级 | 建议搜索范围 |
|:------|:-----|:----|:-----|:----:|:-----|
| `safe_dist_hard_stop` | 0.13 | m | 低于此距离强制 STOP | **P0** | 0.08–0.20 |
| `safe_dist_warn` | 0.16 | m | hard_stop 到此值为 SLOW_DOWN 带 | **P0** | 0.13–0.25 |
| `safe_dist_slow_far` | 0.35 | m | 远场减速带（包络门控下） | P1 | 0.25–0.50 |
| `ttc_threshold` | 0.5 | s | TTC 低于此值 → STOP | **P0** | 0.30–0.80 |
| `ttc_warn_threshold` | 1.5 | s | TTC 低于此值 → SLOW_DOWN | P1 | 0.80–2.50 |
| `slow_down_alpha` | 0.18 | — | 静态 SLOW_DOWN 动作混合系数 | P1 | 0.05–0.40 |
| `slow_down_alpha_ttc` | 0.15 | — | TTC 触发时的动作混合系数 | P1 | 0.05–0.40 |
| `slow_down_alpha_far` | 0.55 | — | 远场减速的动作混合系数 | P2 | 0.20–0.70 |
| `replan_lateral_offset_m` | 0.10 | m | 绕行横向偏移量 | P2 | 0.05–0.25 |
| `replan_detour_stage_duration` | 55 | steps | 绕行段持续时间 | P2 | 30–80 |
| `gripper_boost_extra_closed` | 0.12 | — | 额外夹紧量 | P2 | 固定 |
| `gripper_boost_vel_threshold` | 0.22 | m/s | 触发夹紧的速度阈值 | P2 | 固定 |
| `ee_radius` | 0.08 | m | EE 球体包络半径 | P2 | 固定（标定值） |
| `human_hand_radius` | 0.05 | m | 人手球体半径 | P2 | 固定（标定值） |
| `safe_dist_static` | 0.25 | m | 遗留字段（已由 dual-threshold 替代） | — | 不变 |

> P0 = 对安全/效率平衡影响最大，优先搜索。P1 = 有明显影响。P2 = 已标定或影响微小，固定不变。

**Layer 2 fusion 参数**（`configs/safety_fusion.yaml`）：

| 参数 | 当前值 | 优先级 | 说明 |
|:------|:-----|:----:|:-----|
| `ml_override_theta` | 0.65 | P1 | ML 置信度门槛，低于此值不降级 |

**待定义**（见 §3）：是否需要调整上述优先级和搜索范围。

### 2.4 场景权重

**解决的问题**：优化目标对齐真实需求。

同一组参数在不同场景下表现不同。远场观察场景（far_observer）上误停率为 0 的参数，可能在挡空箱场景（block_place）上漏判严重。如果不加权，平均分会被步数最多的场景主导。

**场景权重决定了"对谁优化"**。例如 block_place 占 40% 意味着：宁可让 far_observer 上多误停几次，也不能在 block_place 上漏判。

**IV-J 场景集**：

| Preset | 风险类型 | 步数 | 任务应完成 | 建议权重 | 核心指标 |
|:------|:-----|:----:|:---------:|:----:|:-----|
| `ivj_static_far_observer` | 低风险基线 | ~7500 | ✅ | 10% | false_stop_rate → 0 |
| `ivj_static_block_place` | 静态挡箱（生产） | ~7500 | ❌ (无replan) | **35%** | miss_rate = 0, task_ts |
| `ivj_static_shoulder_pass` | 静态肩部通道 | ~3000 | ❌ | 15% | false_stop_rate ↓ |
| `ivj_dynamic_fast_sweep` | 动态快扫 | ~3000 | ❌ | **25%** | recall = 1.0, false_stop ≤ 5% |
| `ivj_intrusion_positive` | 正样本侵入 | ~3000 | ❌ | 15% | recall = 1.0, miss = 0 |

**待定义**（见 §3）：是否需要调整上述权重分配。

---

## 3. 待用户确认的决策

以下决策涉及安全哲学和业务优先级，需用户定义：

### 3.1 硬约束

| 决策 | 选项 A | 选项 B | 推荐 |
|:------|:-----|:-----|:----:|
| 漏判容忍度 | 零容忍：miss_rate 必须为 0 | 允许极少量漏判（<1%）以换取更低的误停率 | A — 安全系统底线 |
| 召回率门槛 | safety_recall = 1.000 | recall ≥ 0.99 即可 | A — 但需注明 GT 标签本身有口径误差 |

### 3.2 评分权重

需要定义安全 vs 效率的相对重要性：

- `SAFETY_WEIGHT`（召回率）建议 0.50
- `EFFICIENCY_WEIGHT`（1−误停率）建议 0.30
- `COMPLETION_WEIGHT`（任务完成比例）建议 0.15
- `SMOOTHNESS_WEIGHT`（1−活锁比）建议 0.05

### 3.3 场景权重

见 §2.4 的建议权重。确认或调整。

### 3.4 搜索方法与预算

| 决策 | 选项 |
|:------|:-----|
| 搜索算法 | 网格搜索（粗→细） / 贝叶斯优化 / 随机搜索 |
| 搜索预算 | 总迭代次数上限（如 100 次评估） |
| 最终验收 | 搜索结束后是否需要跑一次带 VLM + perception 的完整 Isaac 集成测试？ |

---

## 4. VLM 在调参中的角色

VLM（Qwen2.5-VL-7B）**不参与参数搜索本身**，原因：

1. **非连续参数空间**：VLM 的行为由 prompt 文本和模型权重决定，没有"改数字"式的连续参数可以搜索。改一个 prompt 词可能输出完全不变的 JSON，也可能从 "continue" 变成 "replan"，不可预测。
2. **每次推理输出不完全一致**：同一张图跑两次可能给出不同的 risk_type 和 confidence，无法用确定性的评分函数衡量。
3. **推理延迟高**：一次 VLM 调用 ~1s，无法在参数搜索中批量评估。

**VLM 在调参流程中的实际作用**：

| 阶段 | VLM 角色 | 说明 |
|:------|:-----|:-----|
| **参数搜索前** | 天花板标定 | 在选定场景上跑带 VLM 的基线，识别 L1/L2 覆盖不到的盲区（功能风险、语义误判），确定 L1 阈值优化的边界——"这些场景 VLM 也救不了，得从规则层解决" |
| **参数搜索中** | 不参与 | 只使用 L1 + L2 offline 重放（速度快、确定性高） |
| **参数搜索后** | 最终验收 | 用最优 L1/L2 参数跑一次带 VLM 的完整集成测试（Isaac 全模块 3000 步），验证：VLM 不会在新阈值下误触发；VLM 能覆盖的参数盲区是否可接受 |
| **长期迭代** | 标签蒸馏 | VLM 识别的边缘场景作为软标签喂给 L2 重训，使 L2（可调参模型）学到更精细的决策边界 |

---

## 5. 实现路线图

```
Phase T1: 离线重放脚本
  └─ replay_params_on_csv.py：单 CSV + 参数扫描 → 指标矩阵
  └─ 验证：和 Isaac 在线结果对比（同一参数下离线重放 vs 在线 g_rule 一致率应 ≈100%）

Phase T2: 评分与搜索
  └─ 实现评分函数（基于用户确认的权重）
  └─ 多场景聚合 + 网格/贝叶斯搜索
  └─ 输出：最优参数组合 + 各场景指标

Phase T3: Isaac 验收
  └─ 用最优参数跑一次完整集成测试（全部模块）
  └─ 对比优化前后的指标变化
```

---

## 6. 与相关文档的链接

| 文档 | 角色 |
|:------|:-----|
| [GM-SafePick_架构总览.md](./GM-SafePick_架构总览.md) | 三层安全架构定义 |
| [GM-SafePick_Layer1_规则安全层.md](./GM-SafePick_Layer1_规则安全层.md) | L1 可调参数规格 |
| [GM-SafePick_Layer2_数据驱动安全层.md](./GM-SafePick_Layer2_数据驱动安全层.md) | L2 fusion 参数与 Tier 策略 |
| [GM-SafePick_Layer3_VLM推理增强层.md](./GM-SafePick_Layer3_VLM推理增强层.md) | VLM 角色与能力边界 |
| [GM-SafePick_项目进展与遗留问题.md](./GM-SafePick_项目进展与遗留问题.md) | IV-J 场景库与指标基线 |
| [adr/GM-SafePick_Phase2.5_EnvelopeDecisions.md](./adr/GM-SafePick_Phase2.5_EnvelopeDecisions.md) | 包络门控参数决策 |
| [adr/GM-SafePick_Phase3.5_MotionReplan契约.md](./adr/GM-SafePick_Phase3.5_MotionReplan契约.md) | Replan 几何参数 ADR |
