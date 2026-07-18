# GM-SafePick Layer 2：数据驱动安全层

> **定位**：在 Layer 1 积累的日志数据上训练分类器，提供比硬编码规则更精细的安全决策
> **前提**：Layer 1 已跑通，积累了足够数量的人-机交互安全决策样本
> **目标**：减少规则层的假阳性（over-conservatism），保持安全覆盖率不变或提高
> **最后更新**：2026-06-18（**IV-J 批量重训 `20260618_142722`**）

---

## Phase 2+ 融合策略（Tier，非 OR）

实现：[`fusion.py`](../GMRobot/safety/fusion.py)、配置 [`safety_fusion.yaml`](../../../../configs/safety_fusion.yaml)。

| Tier | 条件 | 输出 | ML 可覆盖 |
|:----:|:-----|:-----|:---------:|
| 0 | `dist_ee_human < safe_dist_hard_stop` | STOP | ❌ |
| 1 | `g_rule=STOP`（static）且 dist ≥ hard_stop | STOP 或 ALLOW | ✅ 若 `g_ml=ALLOW` 且 conf > θ |
| 2 | `g_rule=SLOW_DOWN` | SLOW_DOWN | ❌ |

Shadow 日志列：`would_fuse`（Tier）、`would_fuse_or`（legacy OR）、`fusion_tier`。

在线启用：`--enable_layer2_fusion`（需 `--layer2_model_dir`；自动开 shadow 日志）。

### Hybrid 标签（`label_source: hybrid`）

1. `dist < collision_threshold` → **STOP**（真 GT 侵入）
2. warn 区 + `g_rule=STOP` → **STOP**（pseudo-positive，补 STOP 类）
3. `g_rule=STOP` 且 dist ≥ warn → **ALLOW**（规则误停，教 ML 反对规则）
4. `g_rule=SLOW_DOWN` → SLOW_DOWN；否则 ALLOW

训练默认：`configs/safety_layer2_train.yaml`；STOP 行 `oversample_stop_ratio: 3.0`。

---

## 实现进度（Layer 2）

> 本节为 **Layer 2 唯一进度看板**，与代码库同步维护。不含 Layer 1/3 细节。

### 当前状态

| 组件 | 路径 / 入口 | 状态 |
|------|------------|:----:|
| 数据集加载 | [`GMRobot/safety/layer2/dataset.py`](../GMRobot/safety/layer2/dataset.py) | ✅ |
| 特征提取（26 维基础） | [`GMRobot/safety/layer2/features.py`](../GMRobot/safety/layer2/features.py) | ✅ |
| 标签（`g_rule` / `gt_ground_truth`） | [`GMRobot/safety/layer2/labels.py`](../GMRobot/safety/layer2/labels.py) | ✅ |
| Episode 划分 70/15/15 | [`GMRobot/safety/layer2/split.py`](../GMRobot/safety/layer2/split.py) | ✅ |
| 训练（RandomForest 默认） | [`GMRobot/safety/layer2/train.py`](../GMRobot/safety/layer2/train.py) | ✅ |
| 离线评估 | [`GMRobot/safety/layer2/evaluate.py`](../GMRobot/safety/layer2/evaluate.py) | ✅ |
| 推理加载 | [`GMRobot/safety/layer2/predictor.py`](../GMRobot/safety/layer2/predictor.py) | ✅ |
| 融合 Tier（旁路 + 在线） | [`GMRobot/safety/fusion.py`](../GMRobot/safety/fusion.py) | ✅ |
| 融合 OR draft（对比） | [`GMRobot/safety/fusion_draft.py`](../GMRobot/safety/fusion_draft.py) | ✅ |
| 融合配置 | [`configs/safety_fusion.yaml`](../../../../configs/safety_fusion.yaml) | ✅ |
| IV-J 批量采集 | [`scripts/collect_ivj_logs.py`](../../../../scripts/collect_ivj_logs.py) | ✅ |
| Shadow 指标 | [`scripts/report_shadow_metrics.py`](../../../../scripts/report_shadow_metrics.py) | ✅ |
| 训练配置 | [`configs/safety_layer2_train.yaml`](../../../../configs/safety_layer2_train.yaml) | ✅ gt_ground_truth |
| CLI 训练 / 评估 | [`scripts/train_safety_layer2.py`](../../../../scripts/train_safety_layer2.py)、[`scripts/eval_safety_layer2.py`](../../../../scripts/eval_safety_layer2.py) | ✅ |
| 单元测试 | [`tests/test_layer2_*.py`](../../../../tests/)、[`test_fusion.py`](../../../../tests/test_fusion.py) | ✅ |
| **Shadow 旁路** | `--enable_layer2_shadow` | ✅ |
| **在线 Tier 门控** | `--enable_layer2_fusion` | ✅ |

### v1 范围说明

- **标签**：`label_source: gt_ground_truth`（Phase 2 默认）；对照 `g_rule` 自标注。
- **数据过滤**：`min_run_id=20260617_192734`（Phase 1 Isaac 三跑起；须含 `g_ground_truth` 列）。
- **模式**：离线训练 + **shadow 旁路**（`--enable_layer2_shadow` 写 `g_ml`/`would_fuse`，**不改** `g_t`）。
- **融合 draft**：`would_fuse = max_severity(g_rule, g_ml)`，见 [`fusion_draft.py`](../GMRobot/safety/fusion_draft.py)。
- **模型**：默认 `RandomForestClassifier(class_weight=balanced)`；可选 `xgboost`（需 `pip install -e source/GMRobot[safety_train_xgb]`）。
- **当前产物**：`output/safety_models/20260618_142722/` — 15 episodes / 42500 rows / GT STOP=76；test stop_recall=1.0（38 GT STOP 步）。

### 训练记录

| Run ID | Episodes | Rows | GT STOP | test stop_recall | 备注 |
|:-------|--------:|-----:|--------:|-----------------:|:-----|
| `20260617_211615` | 10 | 27576† | 38 | 0.0‡ | Phase 2+ 首版；test 无 GT STOP |
| `20260618_142722` | **15** | **42500** | **76** | **1.0** | +5 IV-J 跑（2026-06-18 批量）；test 含 intrusion×2 |

† train 行数（oversample 后 27576）；‡ 旧 split test=1 ep 无 GT STOP 步。

**IV-J shadow（6 preset）**：新模型 vs `20260617_211615` 指标完全一致（`g_ml` false_stop=0%，intrusion recall=1.0）。汇总见 [`report_ivj_summary.py`](../../../../scripts/report_ivj_summary.py)。

### 目录结构

```text
GMRobot/
├── configs/safety_layer2_train.yaml
├── scripts/train_safety_layer2.py
├── scripts/eval_safety_layer2.py
├── source/GMRobot/GMRobot/safety/layer2/
│   ├── __init__.py
│   ├── dataset.py
│   ├── features.py
│   ├── labels.py
│   ├── split.py
│   ├── train.py
│   ├── evaluate.py
│   ├── predictor.py
│   └── schema.py
├── tests/test_layer2_dataset.py
├── tests/test_layer2_features.py
├── tests/test_layer2_predictor.py
└── output/safety_models/          # model.joblib, feature_schema.json, metrics.json
```

### 运行命令

```bash
cd /root/GMRobot
pip install -e "source/GMRobot[safety_train]" -q

# IV-J 批量采集（headless，每 preset 3000 步）
python scripts/collect_ivj_logs.py --dry-run          # 列出 preset
python scripts/collect_ivj_logs.py --max_steps 3000 # 默认跳过 Phase 1 已采 preset

# GT 标签训练（configs/safety_layer2_train.yaml 已设 gt_ground_truth）
python scripts/train_safety_layer2.py --config configs/safety_layer2_train.yaml

# 离线评估
python scripts/eval_safety_layer2.py --model-dir output/safety_models/<run_name> --split test

# Shadow 旁路 / Tier 在线门控
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_safety \
  --safety_config=configs/safety_layer1_stress.yaml --max_steps=3000 \
  --enable_layer2_shadow --layer2_model_dir=output/safety_models/<run_name>

# Tier 融合驱动门控（非 OR）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_safety \
  --safety_config=configs/safety_layer1_stress.yaml --max_steps=3000 \
  --enable_layer2_fusion --layer2_model_dir=output/safety_models/<run_name>

# 离线 shadow 指标（g_rule / would_fuse / would_fuse_or / g_ml vs GT）
python scripts/report_shadow_metrics.py output/safety_logs/<run_id> \
  --model-dir output/safety_models/<run_name> --output-json output/shadow_metrics.json
```

训练产物包含：`model.joblib`、`feature_schema.json`、`metrics.json`、`train_config.yaml`（配置快照）。

### Phase 1 与训练标签（2026-06-17）

- **主 GT 口径**：Layer 1 GT v1.1 — `collision_threshold = human_hand_radius + ee_radius = 0.13 m`（EE 球 r=0.08 m）。训练时 `label_source=gt_ground_truth` 应使用 Phase 1 之后的新 CSV。
- **审计列**：`g_gt_arm`、`min_dist_arm_links`、`gt_contact` **不得**作为 Layer 2 主标签（仅离线对照，见 [`compare_gt_branches.py`](../../../../scripts/compare_gt_branches.py)）。
- **离线 Layer 1 指标**（与 ML 评估互补）：[`report_safety_metrics.py`](../../../../scripts/report_safety_metrics.py) 输出 false_stop_rate、miss_rate、safety_recall；缺 GT 列时从 `ee_pos`/`human_hand_pos` 重算 v1.1 GT。
- **旧 CSV**：`ee_radius=0` 时代日志与 v1.1 重算可能不一致；重跑 agent 或 `--config` 指定当时 yaml 后再对比。

### 未完成事项

| 优先级 | 事项 | 说明 |
|:------:|------|------|
| P0 | ~~**在线门控集成**~~ | ✅ `--enable_layer2_fusion`（Tier） |
| ~~P1~~ | ~~**Ground truth 标签**~~ | ✅ hybrid + `gt_ground_truth` |
| ~~P1~~ | ~~**IV-J intrusion_positive 重跑**~~ | ✅ `20260618_140502` GT STOP=38；已纳入 `20260618_142722` 重训 |
| P1 | **组合特征默认开启** | `features.include_derived: true` 并评估增益 |
| P2 | **XGBoost 对比实验** | 与 RandomForest 对比 STOP 召回与误停率 |
| P2 | **滑动窗口时序特征** | 文档 §7 时序依赖对策 |

---

## 1. 职责

Layer 2 不替换 Layer 1，而是与之**集成**。最终安全门控采用 **Tier 融合**（非简单 OR）：

- **Tier0**: `dist < safe_dist_hard_stop` → STOP（硬碰撞，不可覆盖）
- **Tier1**: `g_rule=STOP`（static）→ ML 可在高置信度时降级为 ALLOW
- **Tier2**: `g_rule=SLOW_DOWN` → 保持 SLOW_DOWN；ML 不得升级 ALLOW → STOP

详见文档顶部「Phase 2+ 融合策略」及 [`fusion.py`](../GMRobot/safety/fusion.py)。旧 OR 融合（`g_rule ∨ g_ml`）保留为 shadow 对比（`would_fuse_or`）。

---

## 2. 训练数据来源

### 2.1 数据格式

直接从 Layer 1 的日志记录中获取特征和标签。一个典型的样本包含：

```text
特征向量: [ee_pos_x, ee_pos_y, ee_pos_z, ee_vel_x, ee_vel_y, ee_vel_z,
           human_pos_x, human_pos_y, human_pos_z, human_vel_x, human_vel_y, human_vel_z,
           dist_ee_human, ttc, joint_0_pos, joint_1_pos, ..., joint_5_pos,
           joint_0_vel, joint_1_vel, ..., joint_5_vel]

标签: g_ground_truth ∈ {ALLOW=0, STOP=1, SLOW_DOWN=2}
```

### 2.2 标签来源

`g_ground_truth` 的获取有三种方式，按信度排序：

| 方法 | 信度 | 说明 |
|:----|:---:|:----|
| 仿真事后检查 | ⭐⭐⭐⭐⭐ | 检查本步是否有真实的碰撞/侵入（仿真可精确检测） |
| 安全专家标注 | ⭐⭐⭐⭐ | 人工判断录像中该步是否真的危险 |
| Layer 1 规则自标注 | ⭐⭐⭐ | 直接将 `g_rule` 作为标签（但会继承规则的所有偏见） |

**推荐**：第一阶段用 Layer 1 的规则标签自标注，快速搭建 ML 训练管道；**已实现**第二阶段仿真距离法 GT（[`ground_truth.py`](../GMRobot/safety/ground_truth.py)），训练时设 `label_source: gt_ground_truth`。

`label_source` 取值：

| 值 | CSV 列 | 类别 |
|:--|:--|:--|
| `g_rule` | `g_rule` | 0/1/2（ALLOW/STOP/SLOW_DOWN） |
| `gt_ground_truth` / `collision` | `g_ground_truth` 或 `gt_collision` | 0/1（无 SLOW_DOWN） |

### 2.3 数据规模要求

| 阶段 | 样本量 | 场景数 | 说明 |
|:----|:-----:|:-----:|:----|
| 原型 | 1,000+ | 5-10 | 验证 ML 能否学到规则 |
| 正式 | 10,000+ | 50+ | 覆盖多样化场景 |
| 生产 | 50,000+ | 200+ | 充分泛化 |

以 20 Hz 控制频率运行，1 分钟 = 1,200 步。10,000 步约需 8 分钟仿真运行，并不漫长。

---

## 3. 模型选择

### 3.1 候选模型

| 模型 | 推理延迟 | 训练难度 | 可解释性 | 推荐度 |
|:----|:-------:|:-------:|:-------:|:-----:|
| Logistic Regression | <1ms | 低 | ✅ 高（权重可直接解释） | ⭐⭐⭐ |
| Random Forest | <5ms | 低 | ✅ 特征重要性 | ⭐⭐⭐⭐⭐ |
| XGBoost / LightGBM | <10ms | 中 | ✅ SHAP 可解释 | ⭐⭐⭐⭐⭐ |
| 小型 MLP (2-3 层) | <20ms | 中 | ⚠️ 需注意力机制 | ⭐⭐⭐ |
| 深度网络 | >50ms | 高 | ❌ 黑箱 | ⭐ |

**推荐方案**：**Random Forest** 或 **XGBoost**

理由：
- 推理延迟极低（<10ms），远低于 20 Hz 的 50ms 预算
- 对表格数据效果好（不需要图像，特征是数值向量）
- 特征重要性可解释——可以回答"距离和速度哪个对安全决策影响更大"
- 训练成本低，不需要 GPU

### 3.2 特征工程

输入特征可以直接使用 Layer 1 日志中的数值字段：

```text
基础特征：
  - ee_to_human_distance            (连续值)
  - time_to_collision               (连续值)
  - ee_velocity_magnitude           (连续值)
  - human_velocity_magnitude        (连续值)

组合特征：
  - distance * velocity               (动量风险)
  - 1 / (distance + epsilon)          (距离倒数，非线性化)
  - relative_approach_angle          (接近方向)

状态特征：
  - current_task_phase               (抓取/搬运/放置，分类)
  - gripper_state                    (夹爪开/闭)
  - num_remaining_parts              (任务进度)
```

---

## 4. 训练与评估

### 4.1 训练流程

```text
1. 加载 Layer 1 日志，合并所有 episode
2. 提取特征向量（X）和标签（y）
3. 划分训练/验证/测试集（70/15/15），注意按 episode 分割而非随机行分割（避免同 episode 内的时序依赖）
4. 训练分类器
5. 评估: 准确率、精确率、召回率、F1
6. 特别注意: 假阴性（漏判危险）的成本远高于假阳性（误停）
```

### 4.2 评估指标

| 指标 | 含义 | 目标值 |
|:----|:----|:-----:|
| 准确率 (Accuracy) | 全部正确决策比例 | >95% |
| 安全召回率 (Safety Recall) | 危险场景中被正确拦截的比例 | >99%（宁可误停也不错放） |
| 假阳性率 (False Positive) | ALLOW 中被误判为 STOP 的比例 | <5%（人机协作频繁误停导致任务不可用） |
| F1-score (STOP class) | 精确率和召回率的调和平均 | >0.9 |

**非对称损失函数建议**：训练时对假阴性（漏判）给予 10 倍于假阳性的惩罚权重。

### 4.3 与 Layer 1 的 A/B 对比

| 对比项 | Layer 1 (Baseline) | Layer 1 + Layer 2 |
|:------|:-----------------:|:-----------------:|
| 干预率 | 基准值 | 应 < 基准值（减少误停） |
| 安全召回率 | 基准值 | 应 ≥ 基准值（不降低安全性） |
| 成功率下降 | 基准值 | 应 < 基准值（任务受安全约束的影响更小） |

---

## 5. 集成方式

### 5.1 安全门控融合

```text
IF g_rule == STOP:
    g_t = STOP                    # 规则已经判定危险，直接 STOP
ELSE:
    IF g_ml == STOP:
        g_t = STOP                # 规则没发现，但 ML 发现
    ELSE:
        g_t = ALLOW               # 双方都认为安全
```

### 5.2 置信度门限（可选增强）

```text
IF g_ml_confidence > RISK_CONFIDENCE_THRESHOLD:
    g_t = g_ml                    # ML 很有把握时，覆盖规则
ELIF g_ml_confidence > WARN_CONFIDENCE_THRESHOLD:
    g_t = SLOW_DOWN               # ML 有疑虑时，减速
ELSE:
    g_t = g_rule                  # ML 不确定时，退回规则决策
```

### 5.3 与未来 Motion Replan 的融合（Phase 4+）

当前融合仅产出 `g_t ∈ {ALLOW, STOP, SLOW_DOWN}`。Phase 4 起，L2 中等置信 warn **可改为触发 replan 请求**而非 SLOW_DOWN，与架构总览 Phase 4a 对齐：

```text
IF g_rule == STOP OR g_ml == STOP (high conf):
    g_t = STOP
ELIF g_ml_warn OR g_rule == SLOW_DOWN:
    emit replan_request          # → Motion Replan 执行器（非门控）
    g_t = ALLOW or SLOW_DOWN     # 策略待 Phase 4 联调
ELSE:
    g_t = ALLOW
```

L2 仍不直接修改轨迹；replan 由独立执行器消费。VLM Stage 5 `replan` 走并行通道（见 Layer 3 §5.4）。

---

## 6. 生命周期

### 6.1 初始阶段（无 ML）

系统只跑 Layer 1，以收集足够训练数据。

### 6.2 训练阶段

数据量足够后，离线训练 ML 分类器。这个阶段 Layer 2 不参与安全门控，只在旁路运行做对比评估。

### 6.3 集成阶段

验证 ML 在测试集上的安全召回率达到要求后，将 Layer 2 接入安全门控流。

### 6.4 迭代更新

随着新场景数据积累，定期重新训练 ML 模型。建议的更新频率：每新增 10,000 个样本重新训练一次，或遇到模型在测试集上表现明显退化时触发。

---

## 7. 局限性与边界

| 局限 | 说明 | 对策 |
|:----|:----|:----|
| 分布外场景 | ML 无法处理未见过的人机交互模式 | 保留 Layer 1 作为 fallback，Layer 3 在后期处理 |
| 时序依赖 | 单步特征不足以表达序列模式 | 可引入滑动窗口特征（上 5 步的距离变化趋势） |
| 标注噪声 | 仿真碰撞检查可能不完美 | 仿真世界中碰撞检测是精确的，此问题小 |
| 类别不平衡 | STOP 样本远少于 ALLOW（99:1+） | 重采样（过采样 STOP）或非对称损失 |
| 无视觉输入 | 无法感知物体材质、防护装备等视觉线索 | 这本身就是 Layer 3 要做的事，Layer 2 不解决 |
