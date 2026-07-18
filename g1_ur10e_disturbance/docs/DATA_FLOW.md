# GMDisturb — 数据流定义

> **时效性**: 本文档已与代码同步 (2026-07-13)。若与代码矛盾，以代码为准。
> R7 更新: force_mode / surface_distance 参数, moderate_threshold 0.30→0.55,
> evaluate_safety 新增 dist_min_held, 封套门控默认开启,
> PerPartTester 四阶段协议机, 虚拟手阶段相关半径 (PICK/PLACE 0.08, TRANSIT 0.22),
> DeadlockDetector 三梯级逃逸, VLM 协调管线 (query_coordinate/monitor/scene),
> 零件 Z 追踪 + 29 列逐步 CSV, 死锁逃逸梯级记录。

> 本文档定义变量从 simulaton step 到各控制器再回到 action 的完整生命周期。  
> 配合 `INTERFACES.md`（接口）和 `VARIABLES.md`（变量定义）使用。

---

## 1. 总览：一步仿真中的变量流向

```
env.step(action_20d)
    │
    ├─ PhysX physics step (dt=0.005, ×4 decimation = 0.02s control dt)
    │
    └─ ObservationManager.compute()
         │
         ├─► obs["g1_walker"] ─────────────► g1_walk_controller.get_action() ──► g1_action(12D)
         │
         ├─► obs["tactile"] ────────────────► mat_event_detector.detect_events()
         │
         ├─► obs["ur10e_policy"] ───────────► ur10e_controller.get_action()
         │                                      │
         ├─► obs["ur10e_camera"] ───┐          ├─► ur10e_action(8D)
         │                          │          │
         ├─► obs["safety"] ─────────┤          │
         │                          │          │
         ├─► obs["g1_body"] ───┐    │          │
         │                     │    │          │
         └─► obs["g1_head_     │    │          │
              camera"] ────┐   │    │          │
                           │   │    │          │
         [FK reads from    │   │    │          │
          scene]           │   │    │          │
         robot_g1.data.* ──┤   │    │          │
         robot_ur10e.data.*┼───┘    │          │
         contact_forces.* ─┘        │          │
                                    │          │
         ┌──────────────────────────┘          │
         │                                     │
         │  [R7] PerPartTester ◄─ stage_name ──┤
         │     │                               │
         │     ▼                               │
         │  G1VirtualHand (phase-dependent      │
         │     radius: TRANSIT=0.22,             │
         │     PICK/PLACE=0.08)                  │
         │     │                               │
         │     ▼                               │
         │  [R7] DeadlockDetector               │
         │     (3-tier: jitter→repel→retreat)   │
         │     │                               │
         │     ▼                               │
         │  G1EnvelopeAdapter ◄─────────────────┘
         │     │
         │     ▼
         │  SafetyGate.apply()
         │     │
         │     ▼
         │  safe_ur10e_action(8D)
         │
         │  [R7] G1VLMClient (SSH tunnel → remote VLM)
         │     query / query_scene / query_monitor / query_coordinate
         │     → vlm velocity override / scene strategy / replan hint
         │
         ▼
    Combined Action Assembly:
         g1_action(12D) + safe_ur10e_action(8D) → action_20d
         │
         └─► env.step(action_20d)
```

---

## 2. 逐阶段数据流

### Phase A: 环境步进 → 观测生成

```
Input:  action_20d = [g1_leg(12), ur10e_ee(8)]

env.step(action_20d) 内部:
    1. ActionManager.process_action(action_20d)
       ├─ g1_joint_pos term (dims 0-11)  → WalkJointAction.process_actions()
       │    └─ 12D → 29D mapping → robot_g1.set_joint_position_target()
       └─ ur10e_ee term (dims 12-19) → DiffIKAction.process_actions()
            └─ IK solve → robot_ur10e.set_joint_position_target()

    2. Scene.write_data_to_sim() → writes both articulation targets to PhysX
    3. Sim.step() → PhysX advances 0.02s
    4. Scene.update(dt) → reads both articulation states from PhysX
    5. ObservationManager.compute() → builds obs dict

Output: obs = {
    "g1_walker":     torch.Tensor (1, 588),
    "tactile":       torch.Tensor (1, 32, 32),
    "ur10e_policy":  dict[str, torch.Tensor],
    "ur10e_camera":  dict[str, torch.Tensor],
    "safety":        dict[str, torch.Tensor],
    "g1_body":       dict[str, torch.Tensor],
}
```

### Phase B0: VLM 协调管线（R7 新增）

```
Inputs:
    obs["g1_head_camera"]["head_rgb"]       → head_rgb   (H, W, 3) uint8  [tactical view]
    obs["ur10e_camera"]["scene_rgb"]        → scene_rgb  (H, W, 3) uint8  [overhead view]

Process:
    G1VLMClient 提供四种查询模式，通过 SSH 隧道向远端 VLM 服务发送 JPEG 编码图像：

    1. query(image, step, prompt=VLM_NAV_PROMPT)          [tactical, ~0.25 Hz]
       → {"action": "approach"|"retreat"|"circle_left"|"circle_right"|"stand_wave"|"wait",
          "reason": "..."}
       → 结果缓存到下一次查询 (min_interval_s 秒内复用)；
         写入 VLM_ACTION_CMD 映射表驱动 G1 速度。

    2. query_scene(scene_img, step)                        [strategic, ~0.06 Hz]
       → {"strategy": "left"|"right"|"front"|"back"|"continue", "reason": "..."}
       → strategy 覆盖 --approach-side 静态预设，每步更新 disturb._vy_bias / _vx_bias。

    3. query_monitor(scene_img, step)                      [monitor, ~0.06 Hz]
       → {"gripper":..., "container_A_slots":[...], "container_B_slots":[...],
          "fallen_parts": N, "arm_status":..., "note": "..."}
       → 视觉地面真值：确认 pick 成功/检测 knock-off/与协议状态交叉验证。

    4. query_coordinate(scene_img, step)                   [coordinate, ~0.06 Hz]
       → {"hand_action": "block_pick"|"block_transit"|"block_place"|"follow_ee"|"retreat",
          "ur10e_strategy": "raise_high"|"lateral"|"wait"|"continue",
          "hand_target_xy": [x, y] | null, "reason": "..."}
       → hand_action 立即覆写 per_part.attractor_xy；
         ur10e_strategy 注入下一次 replan 触发器的 detour 提示。

Rate limiting:
    min_interval 强制最小查询间隔 (默认 4 s)。 超频调用返回缓存决策。
    query_scene / query_monitor / query_coordinate 共享 scene_interval (默认 16 s)。

Outputs:
    vlm_last_action  → VLM_ACTION_CMD 映射 → (vx, vy, wz) velocity override
    _scene_strategy  → disturb._vy_bias / _vx_bias 偏置
    _vlm_replan_strategy → 注入 ReplanRequest.hint.detour_strategy
```

### Phase B: G1 扰动决策（从 obs → 速度命令）

```
Inputs from obs:
    obs["g1_body"]["g1_root_pos"]       → g1_root_pos    (3,)
    obs["g1_body"]["g1_left_hand_pos"]  → (3,)
    obs["g1_body"]["g1_right_hand_pos"] → (3,)

Inputs from FK (direct scene reads):
    robot_ur10e.data.body_link_pos_w[0, ee_idx] → ur10e_ee_pos (3,)
    contact_forces.data.net_forces_w[0]          → g1_contact_forces (37, 3)
    left_foot_sensor.data.current_air_time       → l_air_time
    right_foot_sensor.data.current_air_time      → r_air_time

Decision flow (depends on mode):

  All modes use the same distance-gated controller (G1DisturbanceController):

    g1_disturbance.update(g1_root_pos, ur10e_ee_pos,
                          force_retreat=..., force_mode=...,
                          contact_forces=..., surface_distance=...)
    │
    ├─ Mode override (R7 C1): force_mode bypasses distance-gated selection
    │   for AGGRESSIVE / MODERATE.  CAUTIOUS (d < cautious_threshold) still
    │   takes precedence as a safety floor.
    │
    ├─ Distance evaluation:
    │   dist = ‖ g1_root_xy − ur10e_ee_xy ‖   (XY plane only)
    │   surface_distance from adapter (virtual-hand surface, not G1 root)
    │   → _effective_dist = surface_distance if available, else XY dist
    │
    ├─ Mode selection (distance-gated, evaluated EVERY step):
    │   if d < 0.15:  mode = CAUTIOUS   → retreat (speed 0.20→0.50 m/s ramp)
    │   elif d < 0.55: mode = MODERATE  → slow (50%) + 30% steer away  (F1 fix: was 0.30)
    │   else:            mode = AGGRESSIVE → full speed random wander
    │
    ├─ Command generation (AGGRESSIVE/MODERATE):
    │   Uses pre-generated deterministic schedule (RandomState(42), 10000 entries).
    │   vy = 0 always — lateral movement destabilises the walk policy.
    │   Resampled every 200 steps with a 50-step stabilisation pause.
    │
    ├─ Stuck detection:
    │   cmd_speed > 0.10 m/s AND actual_speed < 0.02 m/s for 100 steps
    │   → contact-force direction retreat (80 steps)
    │   → fallback: random-direction retreat (seeded RNG)
    │
    ├─ Boundary steer: spring force at workspace edges (skip during retreat/stuck)
    │
    └─ → (vx, vy, wz) velocity command written to module-level buffer

  Scripted mode (scripted_phases provided):
    Same as above, but AGGRESSIVE/MODERATE command is replaced by
    pre-programmed phase velocity.  Distance-gated CAUTIOUS and stuck
    detection still override the script for safety.

  VLM mode:
    Same as above, but AGGRESSIVE/MODERATE command can be overridden
    by cached VLM decision (refreshed every 200 steps).
```

> ⚠️ 早期设计文档描述了概率状态机 (WANDER↔APPROACH_ARM→RETREAT, contact-force-based retreat)。
> 实际实现采用距离门控调速。`APPROACH_ARM` 枚举定义了但从未被赋值。
```

### Phase B2: Per-Part 协议 + 虚拟手（R7 新增）

```
Inputs:
    ur10e.stage_name              → 阶段名称 (如 "descend_to_slot_A_3")
    ur10e_ee_pos                  → UR10e EE 世界坐标 (3,)
    g1_head_pos                   → G1 头部世界坐标 (3,)  [from FK]
    ur10e.is_grasping             → 夹爪状态
    per_part (PerPartTester)       → 协议状态机实例

Process:
    ┌─ PerPartTester.update(stage_name, ee_pos, head_pos, is_grasping)
    │
    │  阶段检测（按优先级，前缀匹配）:
    │    TRANSIT 前缀: "lift_slot_", "move_above_box_with_slot_"
    │    PICK 前缀:    "descend_to_slot_", "grasp_slot_", "close_gripper_slot_"
    │    PLACE 前缀:   "descend_to_box_with_slot_", "open_gripper_to_release_"
    │    RESET 前缀:   "lift_after_releasing_"
    │    replan_ 前缀:  保持当前阶段（不改变 phase）
    │
    │  阶段进入时设置:
    │    PICK:    attractor_xy = ee_pos[:2]                (手跟随 EE)
    │              timeout = 600 steps (12 s 安全网)
    │    TRANSIT: attractor_xy = (pick_xy + place_xy) / 2 + 0.10 m toward G1
    │              timeout = 200 steps (4 s — UR10e 卡住时快速撤退)
    │    PLACE:   attractor_xy = ee_pos[:2]                (手跟随 EE)
    │              timeout = 600 steps
    │    RESET:   attractor_xy = None                       (手撤回 G1 头部)
    │              timeout = 900 steps (18 s — 让 UR10e 自由完成)
    │
    │  超时处理:
    │    PICK → TRANSIT  (正常推进)
    │    TRANSIT → RESET (UR10e 卡住，撤退)
    │    PLACE → RESET   (UR10e 卡住，撤退)
    │    RESET → next part PICK 或保持等待
    │
    └─→ self.attractor_xy 写入 virtual_hand._attractor

    ┌─ G1VirtualHand: 阶段相关半径
    │
    │ 半径设置 (PerPartTester.phase 驱动):
    │   TRANSIT:        radius = 0.22 m  → 表面保持在 warn band (0.13–0.40 m)
    │   PICK / PLACE:   radius = 0.08 m  → 最小球体，手存在但不吞没 EE
    │   RESET:          保持当前半径      (手已撤退)
    │
    │ 手面投影 (surface-point projection):
    │   sphere_center = virtual_hand.position
    │   to_ee = ur10e_ee - sphere_center
    │   surface_point = sphere_center + (to_ee / ||to_ee||) * radius
    │   → adapter.human_hand_pos = surface_point
    │   → adapter.closest_body_distance = max(0, center_dist - radius - ee_radius)
    │
    │ RESET 阶段安全覆写:
    │   if phase == RESET:
    │       adapter.human_hand_pos = (0, 0, 2.0)   ← 远距离安全点
    │       adapter.closest_body_distance = 999.0
    │
    └─→ adapter 状态 → 安全门（Phase F）

Outputs:
    virtual_hand._attractor          → (2,) XY 吸引点
    virtual_hand.radius              → 阶段相关球体半径
    adapter.human_hand_pos           → (3,) 安全门输入
    adapter.closest_body_distance    → surface-corrected 距离
    adapter.closest_body_name        → "virtual_hand" | "protocol_reset"
```

### Phase C: G1 行走策略推理（从 walker obs → 腿动作）

```
Input:
    obs["g1_walker"]  → torch.Tensor (1, 588)

Process:
    g1_walker.set_velocity_command(env, vx, vy, wz)
    │
    │ env.unwrapped.command_manager.get_term("base_velocity").vel_command_b[:] = t
    │ (This writes to the velocity_commands term INSIDE the walker observation group.
    │  The velocity_commands term appears as 3 of the 588 dims.)
    │
    └─ g1_walker.get_action(obs["g1_walker"])
         │
         └─ policy(obs_588) → raw_12d → clip(-100, 100) → g1_action(1, 12)

Output:
    g1_action → torch.Tensor (1, 12)
```

### Phase D: G1 手臂 PD 写入

```
Input:
    arm_targets = {"left_shoulder_pitch_joint": -2.0, ...}

Process:
    _write_g1_arm_joint_targets(env, arm_targets)
    │
    ├─ robot_g1 = env.unwrapped.scene["robot_g1"]
    ├─ current = robot_g1.data.joint_pos_target.clone()[0]  # (29,)
    ├─ for jname, target in arm_targets.items():
    │     jidx = robot_g1.joint_names.index(jname)
    │     current[jidx] = target
    └─ robot_g1.set_joint_position_target(current.unsqueeze(0))

Output:
    Written to PhysX on next scene.write_data_to_sim()
```

### Phase E: UR10e 状态机 → EE 动作

```
Input:
    obs["ur10e_policy"] {"ee_pos": (1,7), "part_*_pos": (1,7), ...}
    (Note: underlying policy discards obs; runs on internal timeline)

Process:
    ur10e_ctrl.get_action(obs, advance=False)
    │
    └─ self._policy.get_action(obs, advance=False)
         │
         └─ SingleEnvPickAndPlacePolicy internals:
              Uses self.time_step + self.user_commands to determine
              current waypoint. Returns 8D np.ndarray.

Output:
    ur10e_action → np.ndarray (8,) = [px, py, pz, qw, qx, qy, qz, gripper]
```

### Phase F: 安全门评估

```
Inputs:
    proposed_ur10e_action  (8,)    from Phase E
    prev_ur10e_action      (8,)    from previous step
    g1_body_obs            dict    from obs["g1_body"] (A01-A25 variables)
    ur10e_ee_pos/vel       (3,)    from FK
    ur10e_joint_pos/vel    (6,)    from obs["safety"]
    arm_link_positions     dict    from FK (UR10e link world positions)

Process:
    safety_gate.apply(...)
    │
    ├─ g1_adapter.update(g1_articulation, ur10e_ee_pos)
    │   ├─ Read G1 body positions from FK (body_link_pos_w)
    │   ├─ Compute distance from each G1 body part → UR10e EE
    │   ├─ closest = argmin(distance)
    │   └─ Stores human_hand_pos, human_hand_vel, human_torso_pos, human_torso_vel
    │
    ├─ g1_adapter.build_safety_state(policy_obs, safety_obs, step_index, sim_time)
    │   └─ Build SafetyState from adapter fields + UR10e obs (ee_vel, joint_pos, joint_vel)
    │
    ├─ adapter.evaluate_safety(state,
    │       held_object_active=ur10e.is_grasping,
    │       dist_for_gating=adapter.closest_body_distance,  # surface-corrected (R7 C2: gating always enabled)
    │       dist_min_held=adapter.closest_body_distance if grasping else None)  # R7 H5: enables held-critical STOP
    │   └─ GateResult(g_t=ALLOW|STOP|SLOW_DOWN, reason=..., metadata={dist_ee_human, ttc, ...})
    │
    └─ safety_gate.apply(result, proposed_ur10e_action, prev_ur10e_action)
         ├─ ALLOW      → return proposed_ur10e_action.copy()
         ├─ STOP       → return prev_ur10e_action.copy()
         └─ SLOW_DOWN  → return prev + alpha * (proposed - prev)

Output:
    safe_ur10e_action  → np.ndarray (8,)
    gate_result        → GateResult
```

### Phase F2: 死锁检测与三梯级逃逸（R7 新增）

```
Inputs:
    ur10e_ee_pos                  → UR10e EE 世界坐标 (3,)
    adapter.human_hand_pos        → 虚拟手面位置 (3,)
    virtual_hand._attractor       → 吸引点 XY (2,)
    adapter.closest_body_distance → surface-corrected 距离 (float)
    consecutive_gate_count        → 连续 STOP 步数
    per_part is not None          → 是否有活跃的 per-part 协议

Process:
    DeadlockDetector.update(ee_pos, hand_pos, attractor_xy,
                            hand_dist_surface, consecutive_gate_count,
                            has_active_part)

    死锁判定（三个条件必须全部满足）:
      1. consecutive_gate_count > 50        (时间条件 — 持续 STOP)
      2. EE 位置方差 < 0.001 m² over 窗口   (空间冻结算子)
      3. 手-EE 面距离方差 < 0.0001 m²       (距离稳定算子)

    强制 RESET（独立于死锁检测）:
      IF has_active_part AND consecutive_gate_count > 30
         AND hand_dist_surface < 0.10:
        → per_part.state.phase = Phase.RESET
        → 清除滑动窗口

    三梯级逃逸:
      L1 — JITTER:
        hand_offset = uniform(-0.05, 0.05, 3), Z 轴阻尼 ×0.2
        → 直接加到 adapter.human_hand_pos
        → 如果手刚好卡在门控阈值边界，微扰可以解除死锁

      L2 — REPEL:
        hand_offset = repel(hand_pos, ee_pos, 0.50 m)
        → 将手沿 EE→手 方向推开 0.5 m
        → 激活迟滞冷却: 手必须保持在 hysteresis_dist (0.30 m) 以外
          hysteresis_steps (30 steps) 才能再次靠近

      L3 — G1 RETREAT:
        g1_retreat_velocity = (-0.50, 0, 0) m/s
        → inject_disturbance_velocity() 强制 G1 后退
        → virtual_hand._attractor = (0.5, 0.0)
        → virtual_hand._local_xy = (0, 0)  (手重置到头部)
        → tier 重置为 0, 窗口清空, 迟滞激活

    梯级衰减:
      不死锁时: tier = max(0, tier - 0.05)  (缓慢衰减)
      再次死锁时: tier = min(tier + 1.0, 3.0)  (递增)

    Hysteresis 冷却:
      激活后 (L2/L3), 手必须保持在 hysteresis_dist 以外连续 hysteresis_steps_req 步。
      如果手漂移回来 → 计数器重置。
      冷却期间持续排斥手 (attractor push + hand push)。

Outputs:
    action dict:
        tier             → int (0=normal, 1=jitter, 2=repel, 3=g1_retreat)
        hand_offset      → np.ndarray | None  — 加到手位置
        attractor_xy_add → np.ndarray | None  — 加到 virtual_hand._attractor
        force_reset      → bool               — per-part RESET 触发
        g1_retreat_velocity → np.ndarray | None — L3 速度注入
    → CSV 列: deadlock_tier (int)
```

### Phase G: 压力垫事件检测

```
Inputs:
    obs["tactile"]              → torch.Tensor (1, 32, 32)  [from ObservationManager]
    g1_root_pos                 → np.ndarray (3,)            [from FK]
    g1_left_foot_pos            → np.ndarray (3,)            [from FK]
    g1_right_foot_pos           → np.ndarray (3,)            [from FK]
    ur10e_ee_pos                → np.ndarray (3,)            [from FK]
    part_positions              → dict[name→(3,)]            [from FK]

Process:
    mat_detector.detect_events(tactile_img, g1_root_pos, ...)
    │
    ├─ _find_clusters(img, threshold=5.0)
    │   └─ scipy.ndimage.label → [{mask, centroid_xy, total_force, area}, ...]
    │
    ├─ _classify_cluster(each cluster):
    │   ├─ centroid near g1_left_foot_pos (<0.3m)  → "footstep_left"
    │   ├─ centroid near g1_right_foot_pos (<0.3m) → "footstep_right"
    │   ├─ centroid in workspace x∈[0.3,1.0]        → "collision_impact"
    │   └─ else                                      → "unknown"
    │
    └─ _detect_transients(current_img, prev_img):
         ├─ diff = current - prev
         ├─ mask = diff > 10.0
         ├─ small clusters (area ≤ 4) in workspace → "object_drop"
         └─ match to nearest part via part_positions → part_id

Output:
    mat_events → list[MatEvent]
```

### Phase H: 指标记录

```
Inputs:
    All variables from Phases B-G (see VARIABLES.md)

Process:
    metrics.record_step(
        step, sim_time,
        g1_state,           # A01-A25 → extracted from obs + FK
        g1_disturbance,     # B01-B13 → from controller internal state
        contact_events,     # C01-C09 → from contact_forces.data + C05 inference
        disturbance_effects,# D01-D06 → computed from cross-referencing
        mat_events,         # E01-E10 → from mat_detector.detect_events()
        safety_state,       # F01-F09 → from safety_gate.apply() result
        vlm_state,          # H01-H14 → from g1_vlm_client (None if VLM not enabled)
    )
    → StepRecord dataclass

    # Cross-reference logic for D-group (disturbance effects):
    # D-group is NOT IMPLEMENTED (see VARIABLES.md).  When implemented:
    if gate_result.g_t in (STOP, SLOW_DOWN) and disturb.mode == DisturbanceMode.CAUTIOUS:
        disturbance_effect = "safety_stop" / "safety_slow"
        latency = current_step - disturbance_start_step

    if any mat_event.type == "object_drop":
        disturbance_effect = "knock_off"
        # M2: part_id matching not yet implemented (MatEvent has no part_id field)
        # knock_off_part_ids.append(mat_event.part_id)

    # ── Per-step tracking CSV (R7: 29 columns, written every log interval) ──
    # Written to {output_csv}_steps.csv, one row per logged step.
    # Columns:
    #   1. step                         — simulation step
    #   2-4. ee_x, ee_y, ee_z           — UR10e EE world position
    #   5-7. hand_x, hand_y, hand_z     — virtual hand surface position (or real hand)
    #   8. hand_dist_surface            — adapter.closest_body_distance (surface-corrected)
    #   9. g1_body_dist                 — real G1 body-EE distance (before virtual hand override)
    #   10. gate                        — gate decision (ALLOW / STOP / SLOW_DOWN / NONE)
    #   11. gate_trigger                — gate reason string
    #   12. stage                       — ur10e.stage_name
    #   13. parts_placed                — cumulative parts placed
    #   14. replan_count                — cumulative replan events
    #   15. replan_strategy             — replan detour strategy (auto / raise_high / lateral / …)
    #   16. replan_raise_m              — cumulative raise height (m)
    #   17. replan_lateral_m            — cumulative lateral offset (m)
    #   18. grasp_rewinds               — grasp rewind attempt count
    #   19. carry_aborted               — bool: grasp carry aborted
    #   20. min_part_z                  — lowest part Z (m); 0.0 if no parts tracked
    #   21. parts_below_table           — count: parts with Z < -0.5 m (knocked off)
    #   22. deadlock_tier               — current escape tier (0=normal, 1=jitter, 2=repel, 3=G1 retreat)
    #   23. vhand_retreated             — bool: virtual hand currently retreated
    #   24. vhand_block_active          — bool: virtual hand active and not retreated
    #   25-27. sphere_x, sphere_y, sphere_z — virtual hand sphere centre (or 0 if no vhand)
    #   28. protocol_phase              — PerPartTester phase (pick / transit / place / reset / none)
    #   29. protocol_part               — current part index (1-based, 0 if no protocol)

    # Part Z tracking (R7: columns 20-21):
    #   Each log interval iterates all part_*_pos keys in obs["ur10e_policy"].
    #   min_part_z = min(all part Z values), 99.0 sentinel → 0.0.
    #   parts_below_table = count of parts with Z < -0.50 m (fallen below table edge).
    #   Used to detect knock-off events without relying on pressure mat transient detection.

Output:
    StepRecord appended to internal list
    → at episode end → EpisodeSummary → CSV + JSON
    → _steps.csv: per-log-interval row (29 columns) flushed each write
```

---

## 3. 变量→控制器 映射表

| 变量组 | 消费者 |
|--------|--------|
| A (G1运动状态) | `g1_disturbance_controller` (root_pos), `safety_adapter` (all), `mat_event_detector` (foot_pos), `G1VirtualHand` (head_pos → sphere centre) |
| B (G1扰动行为) | `scripts/run_phase3.py` (logging), `test_metrics` (recording) |
| C (接触/交互) | `g1_disturbance_controller` (max_force → retreat trigger), `safety_adapter` (envelope), `test_metrics` |
| D (扰动效果) | `test_metrics` (computed, not read) |
| E (压力垫事件) | `test_metrics` (recording), `mat_event_detector` (internal) |
| F (安全响应) | `scripts/run_phase3.py` (clock advance), `test_metrics` (latency), `DeadlockDetector` (consecutive_gate_count) |
| G (Episode汇总) | `batch_runner` (aggregation) |
| H (VLM决策) | `test_metrics` (recording), `batch_runner` (diversity stats), `G1DisturbanceController` (velocity override) |
| R7 (PerPart协议) | `PerPartTester` → `G1VirtualHand._attractor` + `virtual_hand.radius`, `DeadlockDetector` (force_reset gate) |
| R7 (死锁逃逸) | `DeadlockDetector` → `adapter.human_hand_pos` (jitter/repel), `inject_disturbance_velocity` (L3 retreat), `per_part.state.phase` (force RESET) |
| R7 (VLM协调) | `G1VLMClient.query_coordinate` → `per_part.attractor_xy` + replan strategy; `query_scene` → `disturb._vy_bias/_vx_bias`; `query_monitor` → cross-validation log |
| R7 (逐步CSV) | `_track_fh` (29 columns per log interval), `PerPartTester.phase/part_index`, `DeadlockDetector tier`, `min_part_z` + `parts_below_table` |

### 关键数据流：R7 PerPart 协议 → 虚拟手 → 安全层

```
ur10e.stage_name ──────────────────────┐
                                       │
PerPartTester.update()                 │
  ├─ 阶段检测 (前缀匹配)               │
  │   PICK: descend_to_slot_*, etc.    │
  │   TRANSIT: lift_slot_*, etc.       │
  │   PLACE: descend_to_box_with_*, etc│
  │   RESET: lift_after_releasing_*    │
  │   replan_*: 保持当前阶段           │
  ├─ timeout: PICK 600 / TRANSIT 200   │
  │           PLACE 600 / RESET 900    │
  └─► attractor_xy ─────────────────────┤
                                       │
G1VirtualHand                          │
  ├─ _attractor = attractor_xy         │
  ├─ radius = 0.22 (TRANSIT)           │
  │         = 0.08 (PICK/PLACE)        │
  │         = unchanged (RESET)        │
  ├─ .step(dt, head_pos, ee_z)         │
  └─► sphere_center ───────────────────┤
                                       │
surface_point projection:              │
  to_ee = ur10e_ee - sphere_center     │
  surface = sphere_center              │
         + (to_ee/|to_ee|) * radius    │
                                       ▼
                              adapter.human_hand_pos = surface_point
                              adapter.closest_body_distance =
                                  max(0, |to_ee| - radius - ee_radius)

                              IF phase == RESET:
                                  human_hand_pos = (0,0,2.0)
                                  closest_body_distance = 999.0
                                       │
                                       ▼
                              SafetyGate (Phase F)
```

### 关键数据流：R7 死锁检测 → 三梯级逃逸

```
DeadlockDetector.update(ee_pos, hand_pos, attractor_xy,
                         hand_dist_surface, consecutive_gate_count,
                         has_active_part)

  条件检查 (每条都单独评估):
    ┌─────────────────────────────────────────────────────┐
    │ FORCE RESET: STOP>30 + dist<0.10 + has_active_part  │
    │   → per_part.phase = RESET, 窗口清空                │
    └─────────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────────┐
    │ DEADLOCK: STOP>50 + ee_var<0.001 + dist_var<0.0001  │
    │   → tier = min(tier+1, 3), 执行当前梯级             │
    └─────────────────────────────────────────────────────┘

  L1 JITTER:  hand_offset = ±5 cm random → adapter.human_hand_pos += offset
  L2 REPEL:   hand_offset = push 0.50 m away from EE → hysteresis 30 steps active
  L3 RETREAT: inject_disturbance_velocity(-0.50, 0, 0), hand reset to head

  非死锁时: tier = max(0, tier - 0.05)  缓慢衰减
  Hysteresis: dist > 0.30 m 持续 30 steps 才能解除 L2/L3 冷却
```

### 关键数据流：G1 到 UR10e 安全层 (无虚拟手时)

```
robot_g1.data.body_link_pos_w[0, head_idx] ──┐
robot_g1.data.body_link_pos_w[0, l_hand_idx] ─┤
robot_g1.data.body_link_pos_w[0, r_hand_idx] ─┤
robot_g1.data.body_link_pos_w[0, torso_idx] ──┤
... (all 7 tracked body parts)                │
                                               ├─► G1EnvelopeAdapter
robot_ur10e.data.body_link_pos_w[0, ee_idx] ──┘    │
                                                     ├─ closest G1 body → EE = human_hand_pos
                                                     ├─ g1_root_pos = human_torso_pos
                                                     └─► SafetyState
                                                          │
                                                          ▼
ur10e FK arm_link_positions ─────────────────────► EnvelopeEvaluator.evaluate()
                                                          │
                                                          ▼
                                                    RuleEngine.evaluate()
                                                          │
                                                    ┌─────┴─────┐
                                                    │  distance  │
                                                    │  < 0.13?   │──STOP──► SafetyGate.apply()
                                                    │  < 0.16?   │──SLOW──► prev+α*(prop-prev)
                                                    │  else      │──ALLOW─► proposed
                                                    └───────────┘

注: 当 --virtual-hand 启用时，adapter.human_hand_pos 被 Phase B2 中的
surface_point 覆写；G1 body FK 读取仅用于 g1_root_pos / g1_body_dist (grasp
disturbance 检测) 和视觉调试棍。
```

### 关键数据流：压力垫 → 事件分类

```
ContactSensor (left_foot)  ─┐
    .data.force_matrix_w    │
ContactSensor (right_foot) ─┤
    .data.force_matrix_w    ├─► tactile_force_multi_net() ─► obs["tactile"] (1,32,32)
    .data.net_forces_w      │       (per-taxel calibration
                            │        + foot summation          ┌──────────────────┐
robot_g1.data              │        + Pasternak smear)         │ MatEventDetector │
    .body_link_pos_w ───────┤                                  │                  │
robot_ur10e.data           │    g1_foot_positions ────────────►│ _classify_       │
    .body_link_pos_w ───────┤    ur10e_ee_pos ────────────────►│   cluster()      │
                            │    part_positions ──────────────►│                  │
part FK positions ──────────┘                                  │ _detect_         │
                                                                │   transients()   │
                                                                └────────┬─────────┘
                                                                         │
                                                                         ▼
                                                                  list[MatEvent]
                                                                  ├─ footstep_left/right
                                                                  ├─ object_drop_N
                                                                  └─ collision_impact
```

---

## 4. 一步完整时序

```
Step N:
  t=0.000  env.step(action_20d from previous iteration)
              │
  t=0.005  [Physics sub-step 1] + contact sensor update
  t=0.010  [Physics sub-step 2]
  t=0.015  [Physics sub-step 3]
  t=0.020  [Physics sub-step 4] + articulation state read + observation compute
              │
           obs dict available
              │
  t=0.021  [CPU] Read obs, FK, contact forces
  t=0.022  [CPU] VLM query (tactical + scene + monitor + coordinate, async-rate-limited)
  t=0.023  [CPU] G1 disturbance decision (G1DisturbanceController.update → vx,vy,wz)
  t=0.024  [CPU] G1 walking policy inference (torch.jit forward)
  t=0.025  [CPU] G1 arm PD target write
  t=0.026  [CPU] UR10e state machine → proposed action
  t=0.027  [CPU] PerPartTester.update → phase detect → attractor_xy
  t=0.028  [CPU] G1VirtualHand.step() → phase-dependent radius → surface projection
  t=0.029  [CPU] G1EnvelopeAdapter → SafetyState → RuleEngine → SafetyGate
  t=0.030  [CPU] DeadlockDetector.update → jitter / repel / retreat (if deadlocked)
  t=0.031  [CPU] MatEventDetector.detect_events()
  t=0.032  [CPU] Replan check + grasp-rewind check + UR10e clock advance
  t=0.033  [CPU] TestMetrics.record_step() + per-step CSV write (if log interval)
  t=0.034  [CPU] torch.cat([g1_action, safe_ur10e_action]) → action_20d
              │
  t=0.035  Next env.step(action_20d)
              │
Step N+1: ...
```

总 CPU 时间预算：~14ms per step at 50 Hz → 有 6ms 余量。
注: VLM 查询通过 min_interval 限速，大部分步骤跳过 HTTP 往返（返回缓存），因此实际 VLM
开销接近零；仅在查询步额外 +1-2s 网络延迟，不在 0.02s 控制循环内。

---

## 5. Episode 生命周期

```
INIT:
    env.reset()
    g1_disturbance = create_controller(mode)
    ur10e_ctrl = UR10eControllerAdapter()  → creates SingleEnvPickAndPlacePolicy()
    safety_gate = IntegratedSafetyGate(config)
    mat_detector = MatEventDetector()
    metrics = DisturbanceTestMetrics(scenario, config)
    virtual_hand = G1VirtualHand(...)          # R7: optional, --virtual-hand
    per_part = PerPartTester(user_commands)     # R7: optional, --per-part-protocol
    deadlock_detector = DeadlockDetector()      # R7: optional, with virtual hand
    vlm_client = G1VLMClient()                  # R7: optional, --vlm / --vlm-scene / etc.

    episode_outcome = None
    step = 0

LOOP (while not terminated and step < max_steps):
    Phase A → Phase B0(VLM) → Phase B(disturbance) → Phase C(walking)
    → Phase D(arm PD) → Phase E(UR10e)
    → Phase B2(PerPart + VirtualHand) → Phase F(SafetyGate)
    → Phase F2(DeadlockDetection) → Phase G(MatEvents)
    → ReplanCheck + GraspRewind + ClockAdvance
    → Phase H(Metrics + per-step CSV)
    → action assembly → env.step(action_20d)
    → step += 1
    → check termination

TERMINATION CONDITIONS:
    1. UR10e: all 20 parts placed → episode_outcome = "all_placed"
    2. G1: root_height < 0.2m       → episode_outcome = "g1_fell"
    3. Step limit exceeded           → episode_outcome = "timeout"
    4. All parts on floor            → episode_outcome = "all_knocked_off"
    5. G1 walked off mat             → episode_outcome = "out_of_bounds"

EPISODE END:
    summary = metrics.build_episode_summary()
    metrics.save_step_csv(f"{output_dir}/steps_{run_id}.csv")
    metrics.save_episode_json(f"{output_dir}/episode_{run_id}.json")
    print(summary)
```

---

## 6. G1 ARM_JOINT_NAMES 常量

```python
# g1_arm_controller.py — ARM_JOINT_INDICES (14 joints, no waist)
# The actual arm controller controls 14 DOF: 7 left arm + 7 right arm.
# Waist joints (waist_roll/yaw/pitch) are NOT controlled by the arm controller
# because the walk policy (0121_walk.pt) manages them as part of locomotion.
ARM_JOINT_INDICES = [11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]

# Corresponding joint names (14 total):
# Left arm (7):
#   left_shoulder_pitch_joint  (idx 11)
#   left_shoulder_roll_joint   (idx 12)
#   left_shoulder_yaw_joint    (idx 15)
#   left_elbow_joint           (idx 16)
#   left_wrist_roll_joint      (idx 19)
#   left_wrist_pitch_joint     (idx 20)
#   left_wrist_yaw_joint       (idx 21)
# Right arm (7):
#   right_shoulder_pitch_joint (idx 22)
#   right_shoulder_roll_joint  (idx 23)
#   right_shoulder_yaw_joint   (idx 24)
#   right_elbow_joint          (idx 25)
#   right_wrist_roll_joint     (idx 26)
#   right_wrist_pitch_joint    (idx 27)
#   right_wrist_yaw_joint      (idx 28)

# ⚠️ 历史: v1 设计包含 waist 3 DOF (共 17 关节)，但实际实现仅控制手臂 14 DOF。
# 腰部关节由行走策略管理，手臂控制器不干预。
```

---

## 7. G1_LEG_INDICES 常量

```python
# Indices within the 29-DOF articulation that are controlled by the walking policy
# The remaining indices (not listed) are arm + waist joints
G1_LEG_INDICES_IN_29: list[int] = [0, 1, 3, 4, 6, 7, 9, 10, 13, 14, 17, 18]

# Corresponding joint names:
# left_hip_pitch_joint     (idx 0)
# right_hip_pitch_joint    (idx 1)
# left_hip_roll_joint      (idx 3)
# right_hip_roll_joint     (idx 4)
# left_hip_yaw_joint       (idx 6)
# right_hip_yaw_joint      (idx 7)
# left_knee_joint          (idx 9)
# right_knee_joint         (idx 10)
# left_ankle_pitch_joint   (idx 13)
# right_ankle_pitch_joint  (idx 14)
# left_ankle_roll_joint    (idx 17)
# right_ankle_roll_joint   (idx 18)
```

---

## 8. 常用 FK 读取模式

```python
# G1: 获取身体部件索引 (在 __init__ 中做一次)
robot_g1 = env.unwrapped.scene["robot_g1"]
g1_body_names = robot_g1.body_names  # list of 37 body names

hand_link_names = ["left_wrist_pitch_link", "right_wrist_pitch_link"]
g1_hand_body_ids, _ = robot_g1.find_bodies(hand_link_names, preserve_order=True)
# → g1_hand_body_ids = [idx_left, idx_right]

# G1: 每步读取位置
g1_body_pos = robot_g1.data.body_link_pos_w[0, g1_hand_body_ids]  # (2, 3)
g1_left_hand_pos = g1_body_pos[0].cpu().numpy()
g1_right_hand_pos = g1_body_pos[1].cpu().numpy()

# UR10e: 获取 EE 索引
robot_ur10e = env.unwrapped.scene["robot_ur10e"]
ee_body_ids, _ = robot_ur10e.find_bodies("wrist_3_link")
ee_idx = ee_body_ids[0]

# UR10e: 每步读取
ur10e_ee_pos = robot_ur10e.data.body_link_pos_w[0, ee_idx].cpu().numpy()  # (3,)

# Contact forces: 每步读取
contact_forces = env.unwrapped.scene["g1_contact_forces"]
net_forces = contact_forces.data.net_forces_w[0]  # (16, 3)
force_mags = net_forces.norm(dim=-1)  # (16,)
max_force = force_mags.max().item()
max_body_idx = force_mags.argmax().item()
max_body_name = g1_body_names[max_body_idx]
```

---

## 9. 路径常量

```python
# === Project paths ===
PROJECT_ROOT = "/root/g1_ur10e_disturbance"
PRESSURE_MAT_ROOT = "/root/pressure_mat_repro_full/pressure_mat_repro"
GMROBOT_ROOT = "/root/GMRobot"

# === Robot USD paths ===
G1_USD_PATH = f"{PRESSURE_MAT_ROOT}/isaac_lab_task/pressure_mat_deploy/data/g1_29dof_modified_new_91.usd"
UR10E_USD_PATH = f"{GMROBOT_ROOT}/source/GMRobot/GMRobot/assets/ur10e_2f/ur10e_gripper.usd"

# === Mat USD paths ===
MAT_32x32_USD = f"{PRESSURE_MAT_ROOT}/isaac_lab_task/pressure_mat_deploy/data/tactile_mat_32x32_4m.usd"
MAT_64x64_USD = f"{PRESSURE_MAT_ROOT}/isaac_lab_task/pressure_mat_deploy/data/tactile_mat_64x64_4m.usd"

# === Walking policy ===
G1_WALK_POLICY_DEFAULT = f"{PRESSURE_MAT_ROOT}/policy/0121_walk.pt"

# === Scenes ===
TABLE_USD = "{ISAAC_NUCLEUS_DIR}/Props/Mounts/SeattleLabTable/table_instanceable.usd"
CONTAINER_USD = f"{GMROBOT_ROOT}/source/GMRobot/GMRobot/assets/container.usd"
PART_USD = f"{GMROBOT_ROOT}/source/GMRobot/GMRobot/assets/part/part_5000.usd"
DIVIDER_USD = f"{GMROBOT_ROOT}/source/GMRobot/GMRobot/assets/container/GM_Container_Slim_Divider_Sim.usd"

# === Safety configs ===
SAFETY_LAYER1 = f"{GMROBOT_ROOT}/configs/safety_layer1.yaml"
SAFETY_FUSION = f"{GMROBOT_ROOT}/configs/safety_fusion.yaml"

# === VLM ===
VLM_CONFIG = f"{GMROBOT_ROOT}/configs/vlm_client.yaml"
```
