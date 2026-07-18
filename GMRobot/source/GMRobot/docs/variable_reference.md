# GMRobot Variable Reference

> 自动生成于 2026-07-01 correctness review F24 修复。每个字段标注语义、生产者、消费者、单位和 deprecated 状态。

---

## 1. 距离字段 (Distance Fields)

GMRobot 中存在 **5 种不同的距离语义**，字段命名历史上存在混乱。本文档是 canonical reference。

### 1.1 核心距离字段

| 字段名 | 语义 | 生产者 | 消费者 | 单位 |
|--------|------|--------|--------|------|
| `dist_min_for_gating` | **门控使用的距离**（canonical field, F24 新增）。envelope gating 开启时等于 `dist_min_envelope`，否则等于 `dist_ee_human` | `RuleEngine.evaluate()` → `GateResult.metadata` | `L1WarnReplanTrigger.update()`, 所有需要与阈值比较的代码 | m |
| `dist_ee_human` | **EE 中心点到手部中心点的欧氏距离**（legacy, 仅用于非 envelope 场景或向后兼容）。点对点，不考虑半径 | `RuleEngine.evaluate()` → `GateResult.metadata` | Layer2 features, 日志, 向后兼容的脚本 | m |
| `dist_min_envelope` | **手部球体表面到最近包络原语表面的最小间隙**。已减去双方半径 | `EnvelopeEvaluator.evaluate()` → `EnvelopeResult.dist_min_envelope` | Rule engine (gating), fusion Tier0, 日志 | m |
| `dist_min_arm` | 手部到臂部原语的最小表面间隙 | `EnvelopeEvaluator.evaluate()` | 日志审计 | m |
| `dist_min_gripper` | 手部到夹爪原语的最小表面间隙 | `EnvelopeEvaluator.evaluate()` | 日志审计 | m |
| `dist_min_held` | 手部到持有物包络原语的最小表面间隙 | `EnvelopeEvaluator.evaluate()` | held_critical 检测, replan strategy, 日志 | m |

### 1.2 距离字段消费规则

```
如果你需要做门控阈值比较:
  → 使用 dist_min_for_gating (canonical)

如果你需要 EE-手点对点距离:
  → 使用 dist_ee_human (但注意: envelope gating 下门控不使用此值)

如果你需要包络审计:
  → 使用 dist_min_envelope / dist_min_arm / dist_min_gripper / dist_min_held

Fallback 优先级（读取时）:
  dist_min_for_gating → dist_min_envelope → dist_ee_human
```

### 1.3 ReplanRequest 距离字段

| 字段 | 语义 | 状态 |
|------|------|------|
| `dist_ee_human` | legacy, 保持向后兼容 | **deprecated** — 新代码请用 `dist_min` |
| `dist_min` | canonical 最小距离 (F24 新增) | **preferred** |
| `dist_min_envelope` | 包络最小距离（独立字段） | active |
| `dist_min_held` | 持有物最小距离（独立字段） | active |

---

## 2. 门控决策字段 (Gate Decision Fields)

| 字段 | 类型 | 语义 | 值域 |
|------|------|------|------|
| `g_t` / `g_rule` | `GateDecision` (int) | 安全门输出 | 0=ALLOW, 1=STOP, 2=SLOW_DOWN |
| `g_ml` | int | Layer2 模型预测 | 0=ALLOW, 1=STOP, 2=SLOW_DOWN |
| `g_ml_confidence` | float | 模型预测置信度 P(predicted class) | [0, 1] |
| `g_ground_truth` | int | 仿真 GT 碰撞标签 | 0=ALLOW, 1=STOP |
| `paper_g_t` | int | 论文二值映射 | 0=STOP, 1=execute (含 SLOW_DOWN) |
| `would_fuse` | int | Tier 融合输出 | 0/1/2 |
| `would_fuse_or` | int | OR 融合（shadow baseline） | 0/1/2 |
| `fusion_tier` | int | 生效的融合层级 | 0=Tier0 hard, 1=Tier1/2 override, None=no override |
| `trigger_rule` | str | 触发 STOP/SLOW 的规则名称 | "static", "ttc", "held_critical", "functional", "workspace", "route_conflict" |

---

## 3. 阈值与配置参数 (Thresholds & Config)

### 3.1 距离阈值 (StaticSafetySubConfig)

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `safe_dist_static` | 0.25 | 静态安全距离（legacy, 已废弃） |
| `safe_dist_hard_stop` | 0.13 | Tier0 硬停止距离。`dist < this` → 立即 STOP |
| `safe_dist_warn` | 0.16 | 告警带距离。`hard_stop ≤ dist < warn` → SLOW_DOWN |
| `safe_dist_slow_far` | None | 远距离告警带（EE 时代 Option A, envelope 下 disabled） |
| `safe_dist_slow_far_envelope` | None | envelope gating 下的远距离告警带 |

**不变量**: `safe_dist_warn >= safe_dist_hard_stop`（config.py F4 修复自动保证）

### 3.2 慢速混合参数 (StaticSafetySubConfig)

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `slow_down_alpha` | 0.3 | 通用 SLOW_DOWN 动作混合系数 |
| `slow_down_alpha_ttc` | None | TTC 触发时的 alpha 覆写（None=使用通用值） |
| `slow_down_alpha_far` | 0.55 | static_far 触发时的 alpha |

### 3.3 TTC 参数 (TTCSubConfig)

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `ttc_threshold` | 0.5 | TTC < 此值 → STOP (s) |
| `ttc_warn_threshold` | 1.5 | TTC < 此值 → SLOW_DOWN (s) |
| `ttc_dist_source` | "envelope" | TTC 距离来源: "envelope" 或 "ee" |
| `ttc_replan_trigger_threshold` | 6 | 动态手部 sweep 的 replan 触发持续步数 |
| `ttc_replan_hand_speed_min` | 0.05 | TTC replan 的最低手部速度 (m/s) |
| `ttc_forecast_replan_threshold` | None | S13 P0 shadow forecast 触发阈值 (s), None=disabled |
| `forecast_dt_fallback_mode` | "skip" | **F3 新增**。sim dt≈0 时的处理: "skip" | "control_dt" |
| `ttc_primitive_vel_mode` | "ee_proxy" | **F2 新增**。原语速度计算: "ee_proxy" | "finite_diff" |

### 3.4 Envelope 参数 (EnvelopeConfig)

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `gating_enabled` | False | 是否用包络距离替代 EE 距离做门控 |
| `arm_link_names` | 6 UR10e links | 臂部原语的 link 名称列表 |
| `arm_link_radius` | 0.05 | 臂部原语球体半径 (m) |
| `fingertip_radius` | 0.035 | 指尖原语球体半径 (m) |
| `held_box_dims_m` | [0.05, 0.05, 0.17] | 持有物包围盒尺寸 (m) |
| `held_box_radius` | None | 手动覆写持有球半径 (None=从 dims 计算) |

### 3.5 Replan 参数 (ReplanSubConfig)

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `lateral_offset_m` | 0.10 | 绕行横向偏移 (m) |
| `detour_stage_duration` | 55 | 绕行阶段持续步数 |
| `trigger_threshold` | 50 | 静态告警持续触发 replan 的步数 |
| `proactive_route_replan_enabled` | False | 路线预测 replan |
| `proactive_route_horizon_steps` | 80 | 路线预测前瞻步数 |
| `proactive_route_warn_gap_m` | 0.19 | 路线预测告警间隙 (m) |
| `proactive_route_hard_gap_m` | 0.13 | 路线预测硬停止间隙 (m) |
| `held_critical_replan_enabled` | False | held_critical 触发 replan |

### 3.6 人体模型参数 (HumanModelSubConfig)

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `hand_radius` | 0.05 | 手部球体半径 (m) |
| `ee_radius` | 0.08 | EE 包络球半径 (m) |
| `torso_radius` | 0.0 | 躯干球体半径 (0=disabled) (m) |
| `torso_offset` | [0, 0, -0.30] | 躯干相对手部中心的偏移 (m) |
| `collision_threshold` | None | 手动覆写碰撞阈值 (None=hand_r+ee_r) |

---

## 4. 运动状态字段 (Kinematic State Fields)

### 4.1 SafetyState

| 字段 | 类型 | 语义 | 维度 |
|------|------|------|------|
| `ee_pos` | np.ndarray | 末端执行器世界位置 | (3,) |
| `ee_vel` | np.ndarray | 末端执行器世界线速度 | (3,) |
| `human_hand_pos` | np.ndarray | 人手部世界位置 | (3,) |
| `human_hand_vel` | np.ndarray | 人手部世界线速度 | (3,) |
| `joint_pos` | np.ndarray | UR10e 关节角度（相对默认姿态） | (6,) |
| `joint_vel` | np.ndarray | UR10e 关节角速度 | (6,) |
| `human_torso_pos` | np.ndarray | 人体躯干世界位置（零长数组=disabled） | (0,) or (3,) |
| `human_torso_vel` | np.ndarray | 人体躯干世界速度 | (0,) or (3,) |
| `sim_time` | float | 物理模拟时间 | s |
| `step_index` | int | 环境步计数 | — |
| `has_torso` | bool (property) | torso 是否启用 | — |

### 4.2 EnvelopePrimitive

| 字段 | 类型 | 语义 |
|------|------|------|
| `primitive_id` | str | 唯一标识 (e.g. "arm:forearm_link", "held:box_center") |
| `group` | str | 分组: "arm", "gripper", "held" |
| `pos` | np.ndarray | 原语中心世界位置 |
| `radius` | float | 原语包络球半径 (m) |

### 4.3 EnvelopeResult

| 字段 | 类型 | 语义 |
|------|------|------|
| `dist_min_envelope` | float | 全包络最小表面间隙 (m) |
| `dist_min_arm` | float\|None | 臂部最小间隙 |
| `dist_min_gripper` | float\|None | 夹爪最小间隙 |
| `dist_min_held` | float\|None | 持有物最小间隙 |
| `closest_primitive_id` | str | 最近原语 ID |
| `closest_primitive_pos` | np.ndarray\|None | 最近原语世界位置 |

---

## 5. 时间/预测字段

| 字段 | 类型 | 语义 | 单位 |
|------|------|------|------|
| `ttc` | float | 恒定速度假设下的碰撞时间 | s |
| `approach_rate` | float | 手部接近速率 (正=接近) | m/s |
| `ttc_forecast_s` | float | 基于距离变化斜率的预测 TTC | s |
| `hand_radial_approach_rate` | float | 手部沿 EE-手方向的径向速率分量 | m/s |
| `dist_min_slope_rate` | float | 包络最小距离的变化率 | m/s |
| `time_to_risk_steps` | float | W13 TTR 模型预测的碰撞步数 | steps |
| `predictive_replan_trigger` | str | W13 预测性 replan 触发标记 | — |

---

## 6. Replan 相关字段

| 字段 | 类型 | 语义 |
|------|------|------|
| `ReplanRequest.request_id` | str | UUID |
| `ReplanRequest.trigger_source` | str | "l1_warn", "route_forecast", "vlm_stage5_replan", "w13_predictive_ttr" |
| `ReplanRequest.trigger_rule` | str | "static_warn", "ttc", "held_critical", "route_conflict", "ttc_forecast", "vlm_replan", "predictive_ttr" |
| `ReplanRequest.ee_pos` | tuple[float,float,float] | EE 位置 (触发时刻) |
| `ReplanRequest.human_hand_pos` | tuple[float,float,float] | 手部位置 (触发时刻) |
| `ReplanRequest.hand_speed_mps` | float\|None | 手部速率 (触发时刻) |
| `ReplanResult.status` | str | "success" |
| `ReplanResult.post_replan_advance_until` | int | 绕行后加速推进的 task_time_step 上限 (-1=不加速) |
| `DetourPlan.strategy` | DetourStrategy | "raise_then_lateral", "lateral_first", "retreat_then_arc" |
| `DetourPlan.raise_m` | float | 抬高量 (m) |
| `DetourPlan.lateral_m` | float | 横向偏移量 (m) |
| `DetourPlan.retreat_m` | float | 后退量 (m) |

---

## 7. Part Tracker 字段

| 字段 | 类型 | 语义 |
|------|------|------|
| `PartRecord.status` | PartStatus | PENDING → PICKED → IN_TRANSIT → PLACED / DROPPED / SKIPPED |
| `PartRecord.rewind_count` | int | 重抓取尝试次数 |
| `PartRecord.vlm_retry_count` | int | VLM 触发重试次数 |
| `PartTransportReport.success_rate` | float | 放置成功率 = placed/(attempted) |

---

## 8. Layer 2 Feature 维度 (30 base + 5 derived = 35 total)

### Base features (30 dims)
```
indices  0- 2: ee_pos_x, ee_pos_y, ee_pos_z
indices  3- 5: ee_vel_x, ee_vel_y, ee_vel_z
indices  6- 8: human_hand_pos_x, human_hand_pos_y, human_hand_pos_z
indices  9-11: human_hand_vel_x, human_hand_vel_y, human_hand_vel_z
index     12: dist_ee_human
index     13: dist_min_envelope
index     14: dist_min_arm
index     15: dist_min_gripper
index     16: dist_min_held
index     17: ttc
indices 18-23: joint_0_pos ... joint_5_pos
indices 24-29: joint_0_vel ... joint_5_vel
```

### Derived features (5 dims, optional)
```
ee_velocity_magnitude, human_velocity_magnitude, momentum_risk,
inv_distance, relative_approach_angle
```

---

## 9. Kalman Filter 状态 (HandTrajectoryFilter)

状态向量 (9D): `[x, y, z, vx, vy, vz, ax, ay, az]`

| 参数 | 默认值 | 语义 |
|------|--------|------|
| `dt` | 0.02 | 控制周期 (s) |
| `process_noise` | 1.5 | 过程噪声 (m/s²/√Hz) |
| `meas_noise_3d` | 0.02 | L1 3D 观测噪声标准差 (m) |
| `meas_noise_2d` | 0.05 | SAM2 2D 观测噪声标准差 (m) |
| `prediction_horizons_s` | [0.2, 0.5, 1.0] | 预测时域 |

---

## 10. 特定常量

| 常量 | 值 | 语义 |
|------|-----|------|
| `HELD_CRITICAL_STOP_M` | 0.10 | held box 紧急停止距离 (m) |
| `HUMAN_HAND_RADIUS_M` | 0.05 | 手部球体半径 (m) |
| `EE_DEFAULT_RADIUS_M` | 0.08 | EE 包络球默认半径 (m) |
| `WORKSPACE_Z_MAX_M` | 0.75 | 工作空间 Z 上限 (m) |
| `HELD_TIGHT_DIST_M` | 0.12 | held box 紧张距离阈值 (m) |
| `Z_HEADROOM_LATERAL_FIRST_M` | 0.08 | lateral_first 策略的最小 Z 余量 (m) |
| `HAND_SPEED_FAST_MPS` | 0.15 | 手部快速移动阈值 (m/s) |
