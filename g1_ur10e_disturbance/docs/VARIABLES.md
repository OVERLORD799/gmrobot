# GMDisturb — 全变量定义参考

> 最后更新: 2026-07-13

> 本文档为 `g1_ur10e_disturbance` 项目所有变量的完整定义。  
> 变量名采用 snake_case，统一前缀约定。

## 变量组实现状态

| 组 | 名称 | 状态 | 采集位置 |
|----|------|------|---------|
| A | G1 运动状态 | ✅ IMPLEMENTED | `g1.data.*` FK + `obs["g1_body"]` |
| B | 扰动行为 | ✅ IMPLEMENTED | `G1DisturbanceController` |
| C | 接触力 | ✅ IMPLEMENTED | `g1_contact_forces` sensor |
| E | 垫子事件 | ✅ IMPLEMENTED | `MatEventDetector` |
| F | 安全响应 | ✅ IMPLEMENTED | f_replan_success, f_replan_failure_reason, f_consecutive_stop_max fully collected in EpisodeMetrics, written to CSV (2026-07-11) |
| G | Episode 汇总 | ✅ IMPLEMENTED | CSV (EpisodeMetrics 33-field) + JSONL (episodes.jsonl) both working via MetricsWriter (2026-07-13) |
| D | 扰动影响 | ✅ IMPLEMENTED | d_stop_caused, d_slow_caused, d_replan_caused, d_knock_off all auto-computed in test_metrics.py record_step() when disturbance_active=True (2026-07-11) |
| H | VLM 决策 | ✅ PARTIAL | h_vlm_action, h_vlm_latency_ms, h_vlm_reason collected (3/14 fields). Remaining 11 fields (arm_state, risk_assessment, disturbance_decision, etc.) are logged in VLM response but not yet extracted to metrics CSV |

> **注**: 本文档中标记为 ❌ 的变量当前不被任何运行脚本采集。数据分析时请以 `/tmp/gmdisturb_phase3.csv` 的实际列头为准。

---

## 一、GMRobot 原有变量（保留不变）

这些变量来自 GMRobot 项目，在联合仿真中继续使用，定义不变。

### 1.1 UR10e 机器人状态

| 变量名 | 类型 | 维度 | 来源 | 说明 |
|--------|------|------|------|------|
| `ur10e_ee_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w` | UR10e 末端执行器世界位置 (x, y, z) |
| `ur10e_ee_vel` | `np.ndarray` | (3,) | 有限差分或 raw | UR10e EE 世界线速度 (vx, vy, vz) |
| `ur10e_ee_quat` | `np.ndarray` | (4,) | FK `body_link_pose_w` | UR10e EE 姿态四元数 (w, x, y, z) |
| `ur10e_joint_pos` | `np.ndarray` | (6,) | `ArticulationData.joint_pos` | UR10e 6 个臂关节角度 (rad) |
| `ur10e_joint_vel` | `np.ndarray` | (6,) | `ArticulationData.joint_vel` | UR10e 6 个臂关节角速度 (rad/s) |
| `ur10e_gripper_state` | `float` | 标量 | 状态机内部 | 夹爪状态：1.0=开，-0.5=闭 |
| `ur10e_gripper_has_object` | `bool` | 标量 | 状态机 + VLM | 夹爪当前是否夹持有物体 |
| `ur10e_current_phase` | `str` | — | `SingleEnvPickAndPlacePolicy._current_phase` | 状态机当前阶段名 |
| `ur10e_current_part_id` | `int` | 标量 | 状态机 | 正在处理的零件编号 (1-20) |

### 1.2 安全门（保留）

| 变量名 | 类型 | 维度 | 来源 | 说明 |
|--------|------|------|------|------|
| `gate_decision` | `GateDecision` | 标量 | `SafetyGate.apply()` | ALLOW=0 / STOP=1 / SLOW_DOWN=2 |
| `gate_alpha` | `float` | 标量 | `SafetyGate` 元数据 | SLOW_DOWN 混合系数 (0.0-1.0) |
| `gate_trigger_rule` | `str` | — | `RuleEngine.evaluate()` | 触发此次决策的规则名 |
| `gate_dist_ee_obstacle` | `float` | 标量 | `EnvelopeEvaluator` | EE → 障碍物最近距离 (m) |

### 1.3 零件追踪（保留）

| 变量名 | 类型 | 维度 | 来源 | 说明 |
|--------|------|------|------|------|
| `part_positions` | `dict[int, np.ndarray]` | 20×(3,) | FK `body_link_pos_w` | 每个零件的世界位置 |
| `part_on_table` | `np.ndarray` | (20,) bool | Z 轴阈值 | 零件是否仍在桌上 (Z > 0.05) |
| `part_in_gripper` | `int` | 标量 | 状态机 | 当前在夹爪中的零件 ID（-1=无） |
| `part_placed_count` | `int` | 标量 | 状态机 | 已成功放置的零件数 |

### 1.4 重规划（保留）

| 变量名 | 类型 | 维度 | 来源 | 说明 |
|--------|------|------|------|------|
| `replan_triggered` | `bool` | 标量 | `ReplanTrigger` | 是否触发了重规划 |
| `replan_attempts` | `int` | 标量 | 状态机 | 当前零件的重规划尝试次数 |
| `grasp_rewind_count` | `int` | 标量 | 状态机 | 回退次数（撞落恢复） |

---

## 二、新增变量

### A 组 — G1 运动状态

> 替代 GMRobot 原有的 `human_hand_pos/vel`、`human_torso_pos/vel`  
> 所有位置均为世界坐标系 (Isaac Lab env 原点)

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| A01 | `g1_root_pos` | `np.ndarray` | (3,) | `robot_g1.data.root_link_pos_w` | G1 骨盆/根 link 世界位置 |
| A02 | `g1_root_vel` | `np.ndarray` | (3,) | `robot_g1.data.root_lin_vel_w` | G1 根 link 世界线速度 (vx, vy, vz) m/s |
| A03 | `g1_root_ang_vel` | `np.ndarray` | (3,) | `robot_g1.data.root_ang_vel_b` | G1 根 link 角速度（体轴系）rad/s |
| A04 | `g1_root_quat` | `np.ndarray` | (4,) | `robot_g1.data.root_link_pose_w` | G1 根 link 姿态四元数 (w,x,y,z) |
| A05 | `g1_head_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w[head_idx]` | G1 头部世界位置（LiDAR/相机安装点） |
| A06 | `g1_head_vel` | `np.ndarray` | (3,) | FK `body_link_vel_w[head_idx]` | G1 头部世界线速度 |
| A07 | `g1_left_hand_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w[l_wrist_idx]` | G1 左手腕世界位置 |
| A08 | `g1_right_hand_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w[r_wrist_idx]` | G1 右手腕世界位置 |
| A09 | `g1_left_hand_vel` | `np.ndarray` | (3,) | FK `body_link_vel_w[l_wrist_idx]` | G1 左手世界线速度 |
| A10 | `g1_right_hand_vel` | `np.ndarray` | (3,) | FK `body_link_vel_w[r_wrist_idx]` | G1 右手世界线速度 |
| A11 | `g1_left_foot_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w[l_ankle_idx]` | G1 左脚踝世界位置 |
| A12 | `g1_right_foot_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w[r_ankle_idx]` | G1 右脚踝世界位置 |
| A13 | `g1_torso_pos` | `np.ndarray` | (3,) | FK `body_link_pos_w[torso_idx]` | G1 躯干世界位置 |
| A14 | `g1_body_positions` | `np.ndarray` | (37, 3) | `robot_g1.data.body_link_pos_w` | G1 全部 37 个 body link 世界位置（2026-07-04 smoke test 实测确认） |
| A15 | `g1_body_velocities` | `np.ndarray` | (N, 6) | `robot_g1.data.body_link_vel_w` | G1 全部 body link 世界速度（线+角） |
| A16 | `g1_joint_pos` | `np.ndarray` | (29,) | `robot_g1.data.joint_pos` | G1 全部 29 个关节角度 (rad) |
| A17 | `g1_joint_vel` | `np.ndarray` | (29,) | `robot_g1.data.joint_vel` | G1 全部 29 个关节角速度 (rad/s) |
| A18 | `g1_closest_body_to_ee` | `str` | — | 计算 | 距 UR10e EE 最近的 G1 身体部件名 |
| A19 | `g1_closest_body_to_ee_pos` | `np.ndarray` | (3,) | 计算 | 该最近部件的世界位置 → 替代 `human_hand_pos` |
| A20 | `g1_closest_body_to_ee_vel` | `np.ndarray` | (3,) | 计算 | 该最近部件的世界速度 → 替代 `human_hand_vel` |
| A21 | `g1_ur10e_min_distance` | `float` | 标量 | 计算 | G1 任意部件 → UR10e envelope 原语的最小表面距离 (m) |
| A22 | `g1_ur10e_closest_pair` | `tuple[str,str]` | — | 计算 | (`g1_body_name`, `ur10e_envelope_primitive`) |
| A23 | `g1_is_double_support` | `bool` | 标量 | `current_air_time` | G1 是否处于双足支撑期 |
| A24 | `g1_left_foot_air_time` | `float` | 标量 | `left_foot_sensor.data.current_air_time` | 左脚离地持续时间 (s) |
| A25 | `g1_right_foot_air_time` | `float` | 标量 | `right_foot_sensor.data.current_air_time` | 右脚离地持续时间 (s) |
| A26 | `min_surface_distance_m` | `float` | 标量 | 计算 | UR10e end-effector → closest obstacle minimum surface distance (m), output as CSV column in test_metrics.py |

### B 组 — G1 扰动行为状态

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| B01 | `disturbance_mode` | `str` | — | 控制器 | `"AGGRESSIVE"` / `"MODERATE"` / `"CAUTIOUS"` / `"STUCK"` / `"IDLE"` (v2 距离门控) |
| B02 | `disturbance_phase` | `str` | — | 控制器 | `"idle"` / `"wander"` / `"retreat"` / `"stuck_retreat"` (APPROACH_ARM 枚举存在但从未赋值 — v1 artifact) |
| B03 | `disturbance_scenario` | `str` | — | 启动参数 | 预定义场景名：`"arm_collision"` / `"arm_wave"` / `"constrained_wander"` / `"vlm_explore"` (table_bump/object_push/circulate/combined 已移除 — M5 fix) |
| B04 | `g1_velocity_command` | `np.ndarray` | (3,) | 控制器输出 | 注入 CommandManager 的 (vx, vy, wz) 速度命令 m/s, rad/s |
| B05 | `g1_velocity_actual` | `np.ndarray` | (3,) | `robot_g1.data.root_lin_vel_w` | G1 实际根速度（与 B04 对比→跟踪精度） |
| B06 | `g1_arm_motion` | `str` | — | 控制器输出 | `"none"` / `"wave"` / `"extend_forward"` / `"extend_left"` / `"extend_right"` |
| B07 | `g1_arm_joint_targets` | `dict[str,float]` | 14 键 | 控制器输出 | 手臂 14 个关节的 PD 目标值 (rad)。⚠️ 文档 v1 写 17 (含 waist 3 DOF)，实际代码用 ARM_JOINT_INDICES 仅 14 个 (H3 fix, 2026-07-10) |
| B08 | `g1_arm_joint_torques` | `np.ndarray` | (14,) | `robot_g1.data.applied_torque` | 手臂关节的实际施加力矩 (Nm) |
| B09 | `g1_arm_is_pushing` | `bool` | 标量 | 计算 | 手臂关节力矩 >30Nm → True（正在推实物 vs 空挥） |
| B10 | `g1_fall_detected` | `bool` | 标量 | `root_height < 0.2` | G1 是否已摔倒 |
| B11 | `g1_fall_step` | `int` | 标量 | 记录 | 摔倒发生的步数 |
| B12 | `g1_workspace_x_range` | `tuple[float,float]` | — | 配置 | 允许 G1 活动的 x 范围（默认 0.0, 0.8） |
| B13 | `g1_workspace_y_range` | `tuple[float,float]` | — | 配置 | 允许 G1 活动的 y 范围（默认 -0.5, 0.5） |

### C 组 — 接触/交互事件

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| C01 | `g1_contact_forces` | `np.ndarray` | (N, 3) | `contact_forces.data.net_forces_w` | G1 N 个 body 的 3D 净接触力(N)。当前 N=37 | `contact_forces.data.net_forces_w` | G1 **37** 个 body 的 3D 净接触力 (N)（Phase 1 实测） |
| C02 | `g1_contact_force_mags` | `np.ndarray` | (N,) | 计算 | G1 每个 body 的接触力大小 (L2 范数) |
| C03 | `g1_contact_max_force` | `float` | 标量 | 计算 | N 个部件中最大接触力（N 取决于 body 数量） (N) |
| C04 | `g1_contact_max_body` | `str` | — | 计算 | 接触力最大的部件名 |
| C05 | `contact_event_type` | `str` | — | 推理 | `"none"` / `"hand_table"` / `"hand_ur10e"` / `"torso_table"` / `"head_ur10e"` / `"arm_ur10e"` |
| C06 | `contact_event_force` | `float` | 标量 | C03 的值 | 该事件的接触力 (N) |
| C07 | `contact_event_g1_body` | `str` | — | C04 的值 | 事件涉及的 G1 身体部件 |
| C08 | `contact_event_target` | `str` | — | 推理 | 被接触的目标：`"ur10e"` / `"table"` / `"container_a"` / `"container_b"` / `"part_N"` |
| C09 | `ur10e_external_force` | `np.ndarray` | (3,) | `contact_forces` on UR10e | UR10e 臂受到的净外力 (N) |

### D 组 — 扰动效果

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| D01 | `disturbance_step_start` | `int` | 标量 | 记录 | 本次扰动阶段开始的步数 |
| D02 | `disturbance_step_end` | `int` | 标量 | 记录 | 本次扰动阶段结束的步数 |
| D03 | `disturbance_effect` | `str` | — | 推理 | `"none"` / `"safety_stop"` / `"safety_slow"` / `"knock_off"` / `"replan_trigger"` / `"g1_fall"` |
| D04 | `disturbance_effect_latency` | `int` | 标量 | 计算 | 从扰动开始到产生效果的步数（@50Hz） |
| D05 | `knock_off_this_disturbance` | `int` | 标量 | 计数 | 本次扰动击落的零件数 |
| D06 | `knock_off_part_ids` | `list[int]` | — | 匹配 | 被击落的零件 ID 列表 |
| D07 | `d_stop_caused` | `int` | 标量 | EpisodeMetrics | Episode 内扰动导致的 STOP 次数 (2026-07-11) |
| D08 | `d_slow_caused` | `int` | 标量 | EpisodeMetrics | Episode 内扰动导致的 SLOW_DOWN 次数 (2026-07-11) |
| D09 | `d_replan_caused` | `int` | 标量 | EpisodeMetrics | Episode 内扰动触发的重规划次数 (2026-07-11) |
| D10 | `d_knock_off` | `int` | 标量 | EpisodeMetrics | Episode 内扰动击落的零件总数 (2026-07-11) |
| D11 | `protocol_phase` | `str` | — | `_steps.csv` | 每步的 UR10e 协议阶段 (R7) |
| D12 | `protocol_part` | `str` | — | `_steps.csv` | 每步正在处理的零件 ID (R7) |
| D13 | `deadlock_tier` | `float` | 标量 | `_steps.csv` | 死锁升级层级 (0=none, 1/2/3=escalation) (R7) |
| D14 | `replan_strategy` | `str` | — | `_steps.csv` | 重规划策略: `"raise"` / `"lateral"` / `"retreat"` / `"auto"` / `""` (R7) |
| D15 | `replan_raise_m` | `float` | 标量 | `_steps.csv` | 重规划抬升高度 (m) (R7) |
| D16 | `replan_lateral_m` | `float` | 标量 | `_steps.csv` | 重规划横向偏移 (m) (R7) |
| D17 | `vhand_retreated` | `bool` | 标量 | `_steps.csv` | 虚拟手是否已撤退 (R7 deadlock recovery) |
| D18 | `vhand_block_active` | `bool` | 标量 | `_steps.csv` | 虚拟手阻挡是否激活 (R7 deadlock recovery) |
| D19 | `sphere_x` / `sphere_y` / `sphere_z` | `float` | 标量 | `_steps.csv` | 安全球体中心世界坐标 (R7) |

### E 组 — 压力垫事件

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| E01 | `mat_event_type` | `str` | — | `MatEventDetector` | `"none"` / `"footstep_left"` / `"footstep_right"` / `"object_drop"` / `"collision_impact"` / `"unknown"` |
| E02 | `mat_event_position` | `tuple[float,float]` | (2,) | `MatEventDetector` | 事件在压力垫世界坐标中的位置 (x, y) m |
| E03 | `mat_event_force` | `float` | 标量 | `MatEventDetector` | 事件簇的总法向力 (N) |
| E04 | `mat_event_area` | `int` | 标量 | `MatEventDetector` | 事件覆盖的 taxel 数量 |
| E05 | `mat_event_step` | `int` | 标量 | 记录 | 事件发生的步数 |
| E06 | `mat_peak_force_this_step` | `float` | 标量 | `MatEventDetector` | 本步 (32,32) 中最大单 taxel 力值 (N) |
| E07 | `mat_object_drop_position` | `tuple[float,float]` | (2,) | `MatEventDetector` | 物体落地位置 (x, y) m |
| E08 | `mat_object_drop_force` | `float` | 标量 | `MatEventDetector` | 物体落地冲击力 (N) |
| E09 | `mat_object_drop_part_id` | `int` | 标量 | 最近邻匹配 | 掉落物体匹配到的零件 ID（-1=无法匹配） |
| E10 | `mat_footstep_sequence` | `list[dict]` | — | `MatEventDetector` | 脚步序列：[{side, pos_xy, force, step}, ...] |

### F 组 — 安全响应增强

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| F01 | `safety_trigger_source` | `str` | — | 扩展 `RuleEngine` | `"static_rule"` / `"ttc_rule"` / `"held_critical"` / `"workspace"` / `"envelope"` |
| F02 | `safety_closest_g1_body` | `str` | — | A18 的值 | 触发安全门的 G1 身体部件名 |
| F03 | `safety_intrusion_step` | `int` | 标量 | 记录 | G1 首次进入 hard_stop 区域 (0.13m) 的步数 |
| F04 | `safety_stop_step` | `int` | 标量 | `SafetyGate` | 安全门实际输出 STOP 的步数 |
| F05 | `safety_latency_steps` | `int` | 标量 | F04 - F03 | 侵入→STOP 响应延迟（步数 @50Hz） |
| F06 | `safety_g1_distance_at_trigger` | `float` | 标量 | 记录 | 触发时 G1 最近部件 → UR10e EE 距离 (m) |
| F07 | `f_replan_success` | `bool` | 标量 | EpisodeMetrics | 最近一次重规划是否成功恢复 (2026-07-11) |
| F08 | `f_replan_failure_reason` | `str` | — | EpisodeMetrics | 最近一次重规划失败原因 (2026-07-11) |
| F09 | `f_consecutive_stop_max` | `int` | 标量 | EpisodeMetrics | Episode 内最大连续 STOP/SLOW 步数（>100 → livelock） (2026-07-11) |

### G 组 — Episode 汇总指标

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| G01 | `episode_outcome` | `str` | — | 推理 | `"all_placed"` / `"g1_fell"` / `"timeout"` / `"all_knocked_off"` |
| G02 | `episode_total_steps` | `int` | 标量 | 计数 | 总仿真步数 |
| G03 | `episode_total_disturbance_attempts` | `int` | 标量 | 计数 | 总扰动尝试次数 |
| G04 | `episode_total_disturbance_hits` | `int` | 标量 | 计数 | 产生效果的扰动次数 (D03 != "none") |
| G05 | `episode_total_safety_stops` | `int` | 标量 | 计数 | 总 STOP 次数 |
| G06 | `episode_total_safety_slows` | `int` | 标量 | 计数 | 总 SLOW_DOWN 次数 |
| G07 | `episode_total_replan_triggers` | `int` | 标量 | 计数 | 总重规划触发次数 |
| G08 | `episode_total_replan_successes` | `int` | 标量 | 计数 | 总重规划成功次数 |
| G09 | `episode_total_knock_offs` | `int` | 标量 | 计数 | 总物体掉落次数 |
| G10 | `episode_parts_completed` | `int` | 标量 | 状态机 | 成功搬运的零件数 (目标 20) |
| G11 | `episode_parts_on_floor` | `int` | 标量 | 计数 | 掉落在地上的零件数 |
| G12 | `episode_g1_fall_count` | `int` | 标量 | 计数 | G1 摔倒次数 |
| G13 | `knock_off_rate` | `float` | 标量 | G11/20 | 撞落率 |
| G14 | `recovery_success_rate` | `float` | 标量 | G08/G07 | 恢复成功率（分母为0时=1.0） |
| G15 | `mean_safety_latency` | `float` | 标量 | mean(F05) | 平均安全门响应延迟（步数） |
| G16 | `intervention_rate` | `float` | 标量 | (G05+G06)/G02 | 干预率（每步被 STOP/SLOW 的比例） |
| G17 | `livelock_rate` | `float` | 标量 | F09>100 的步数/G02 | Livelock 比例 |
| G18 | `disturbance_hit_rate` | `float` | 标量 | G04/G03 | 扰动命中率 |

### H 组 — VLM 决策日志（仅 VLM 模式启用）

| # | 变量名 | 类型 | 维度 | 来源 | 说明 |
|---|--------|------|------|------|------|
| H01 | `vlm_decision_json` | `dict` | — | VLM HTTP 响应 | VLM 原始输出 JSON |
| H02 | `vlm_arm_state` | `str` | — | VLM JSON 解析 | VLM 判断的 UR10e 状态：`"idle"` / `"approaching_pick"` / `"grasping"` / `"transiting"` / `"placing"` / `"recovering"` |
| H03 | `vlm_gripper_has_object` | `bool` | 标量 | VLM JSON 解析 | VLM 判断夹爪是否持有物体 |
| H04 | `vlm_risk_assessment` | `str` | — | VLM JSON 解析 | `"safe"` / `"caution"` / `"danger"` |
| H05 | `vlm_disturbance_action` | `str` | — | VLM JSON 解析 | VLM 决定的扰动动作 |
| H06 | `vlm_velocity_command` | `dict` | {"vx","vy","wz"} | VLM JSON 解析 | VLM 输出给 G1 的速度命令 |
| H07 | `vlm_arm_motion` | `str` | — | VLM JSON 解析 | VLM 输出的手臂动作 |
| H08 | `vlm_reasoning` | `str` | — | VLM JSON 解析 | VLM 的决策理由 |
| H09 | `vlm_latency_ms` | `float` | 标量 | 计时 | VLM 推理耗时 (ms) |
| H10 | `vlm_decision_step` | `int` | 标量 | 记录 | VLM 做出该决策时的步数 |
| H11 | `vlm_effective` | `bool` | 标量 | 关联分析 | 该 VLM 决策后 100 步内是否触发了安全门 |
| H12 | `vlm_decision_count` | `int` | 标量 | 计数 | VLM 决策总次数 |
| H13 | `vlm_unique_actions` | `int` | 标量 | 去重计数 | VLM 输出不同扰动动作的种类数 |
| H14 | `vlm_effective_rate` | `float` | 标量 | 有效数/总数 | VLM 决策有效率 |

---

## 三、变量索引（按用途检索）

### 3.1 替代关系：GMRobot human → G1

| GMRobot 原有 | → GMDisturb 替代 |
|-------------|-----------------|
| `human_hand_pos` | → `g1_closest_body_to_ee_pos` (A19) |
| `human_hand_vel` | → `g1_closest_body_to_ee_vel` (A20) |
| `human_torso_pos` | → `g1_root_pos` (A01) 或 `g1_torso_pos` (A13) |
| `human_torso_vel` | → `g1_root_vel` (A02) |

### 3.2 G1 扰动控制器输入变量

| 控制层 | 输入变量 |
|--------|---------|
| Layer 2 战术 (1+7+10+6) | `ur10e_current_phase` + `ur10e_ee_pos` + `g1_closest_body_to_ee_pos` + `g1_arm_joint_torques` |
| Layer 1 安全 (5+8+4) | `g1_contact_max_force` + `g1_contact_max_body` + `g1_is_double_support` + `mat_event_type` |
| Layer 3 探索 (3+9) | `vlm_*` (H01-H14) + scene camera RGB |

### 3.3 批量测试输出变量（CSV 列）

#### Episode summary CSV (`EpisodeMetrics._CSV_FIELDS`, 33 列)

每轮测试一行，包含 G 组全部 18 个指标 + D/F/H 组实现变量：

| 字段 | 说明 |
|------|------|
| `episode_id` | Episode 编号 |
| `total_steps` | 总仿真步数 |
| `policy_steps` | 策略实际执行步数 |
| `parts_placed` | 成功搬运零件数 |
| `parts_total` | 总零件数 |
| `task_completed` | 是否完成全部搬运 |
| `g1_fell` | G1 是否摔倒 |
| `g1_root_z_min` | G1 根 link 最低 Z 值 |
| `g1_root_z_final` | G1 根 link 最终 Z 值 |
| `tier0_stop_count` | Tier0 STOP 次数 |
| `slowdown_count` | SLOW_DOWN 次数 |
| `replan_count` | 重规划次数 |
| `stuck_count` | 卡住次数 |
| `d_stop_caused` | 扰动导致 STOP 次数 |
| `d_slow_caused` | 扰动导致 SLOW_DOWN 次数 |
| `d_replan_caused` | 扰动触发重规划次数 |
| `d_knock_off` | 扰动击落零件数 |
| `footstep_count` | 脚步事件数 |
| `collision_count` | 碰撞事件数 |
| `object_drop_count` | 物体掉落事件数 |
| `min_g1_ur10e_distance_m` | G1-UR10e 最小距离 (m) |
| `min_surface_distance_m` | EE-障碍物最小表面距离 (m) |
| `mean_g1_ur10e_distance_m` | G1-UR10e 平均距离 (m) |
| `last_gate_decision` | 最后安全门决策 |
| `last_gate_trigger` | 最后触发规则 |
| `last_gate_distance` | 最后触发距离 (m) |
| `last_closest_body` | 最后最近部件名 |
| `f_consecutive_stop_max` | 最大连续 STOP 步数 |
| `f_replan_success` | 最后重规划是否成功 |
| `f_replan_failure_reason` | 最后重规划失败原因 |
| `h_vlm_action` | VLM 决策动作 |
| `h_vlm_latency_ms` | VLM 延迟 (ms) |
| `h_vlm_reason` | VLM 决策理由 |

#### Per-step tracking CSV (`_steps.csv`, 29 列)

每次 `run_phase3.py` 同步输出，每步一行，用于重规划策略对比和死锁分析：

| 字段 | 说明 |
|------|------|
| `step` | 步数 |
| `ee_x, ee_y, ee_z` | UR10e EE 世界位置 |
| `hand_x, hand_y, hand_z` | 虚拟手世界位置 |
| `hand_dist_surface` | 虚拟手-障碍物表面距离 (m) |
| `g1_body_dist` | G1 最近部件-UR10e EE 距离 (m) |
| `gate` | 安全门决策 |
| `gate_trigger` | 触发规则名 |
| `stage` | 策略阶段 |
| `parts_placed` | 已放置零件数 |
| `replan_count` | 累计重规划次数 |
| `replan_strategy` | 重规划策略 (D14) |
| `replan_raise_m` | 抬升高度 (D15) |
| `replan_lateral_m` | 横向偏移 (D16) |
| `grasp_rewinds` | 抓取回退次数 |
| `carry_aborted` | 搬运中止次数 |
| `min_part_z` | 零件最低 Z 值 |
| `parts_below_table` | 低于桌面的零件数 |
| `deadlock_tier` | 死锁层级 (D13) |
| `vhand_retreated` | 虚拟手撤退标志 (D17) |
| `vhand_block_active` | 虚拟手阻挡标志 (D18) |
| `sphere_x, sphere_y, sphere_z` | 安全球体中心 (D19) |
| `protocol_phase` | 协议阶段 (D11) |
| `protocol_part` | 当前零件 (D12) |

#### Batch runner JSONL (`episodes.jsonl`)

`scripts/run_batch.py` 汇总输出，每行一个 episode 的 JSON 对象（`EpisodeMetrics.to_json_dict()`），与 episode CSV 字段一一对应。

---

## 四、数据类型约定

| Python 类型 | 用于 |
|------------|------|
| `np.ndarray` | 所有多维数值数据 |
| `float` | 标量浮点 |
| `int` | 标量整数（步数、计数） |
| `bool` | 布尔标志 |
| `str` | 枚举/分类标签 |
| `dict[str, float]` | 关节目标字典（键=关节名，值=弧度） |
| `list[int]` | ID 列表 |
| `list[dict]` | 事件序列 |
| `tuple[float, float]` | 2D 位置 |
| `tuple[str, str]` | 身体部件对 |

所有 `np.ndarray` 默认 `dtype=np.float32`（与 Isaac Lab 一致）。

所有世界坐标相对于 Isaac Lab env 原点（压力垫中心 = (0, 0, 0)）。
