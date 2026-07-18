# GMDisturb — 测试场景定义

> **时效性**: 本文档已与代码同步 (2026-07-10)。YAML schema 已从 v1 设计更新为
> 实际参数。`constrained_wander` 的 YAML 字段已改为距离门控参数。

> 本文档定义扰动测试场景的 YAML schema 和所有预定义场景。

## 场景执行状态

| 场景 | CLI 支持 | 运行过？ | 备注 |
|------|---------|---------|------|
| `constrained_wander` | ✅ `run_phase3.py` (默认) | ✅ | G1 距离门控随机漫步 |
| `arm_collision` | ✅ `--scenario arm_collision` | ✅ | 冲刺穿越工作区 |
| `arm_wave` | ✅ `--scenario arm_wave` | ✅ | 靠近+挥手+撤退 |
| `table_bump` | ❌ 已移除 | ❌ | M5 fix: phase 定义已删除 |
| `object_push` | ❌ 已移除 | ❌ | M5 fix: phase 定义已删除 |
| `circulate` | ❌ 已移除 | ❌ | M5 fix: phase 定义已删除 |
| `combined` | ❌ 已移除 | ❌ | M5 fix: phase 定义已删除 |
| `wander_vhand_replan` | ✅ `--virtual-hand 0.45 --replan` | ✅ | 虚拟手障碍 + GMRobot 几何重规划 |
| `vlm_explore` | ✅ `--vlm` | ✅ | VLM 管线已端到端跑通 (g1_vlm_client.py) |

---

## 1. 场景 YAML Schema

```yaml
# 场景配置文件结构
# 放在 batch_test_configs/ 目录下

name: "table_bump"           # 场景唯一标识
description: "..."           # 场景描述
mode: "scripted"             # "scripted" | "constrained_wander" | "vlm_guided"

# === G1 行为定义 ===
g1_behavior:
  # 工作空间约束（所有模式共用）
  workspace:
    x_min: 0.0               # G1 root 允许的最小 x 坐标（垫系）
    x_max: 0.8
    y_min: -0.5
    y_max: 0.5

  # 开环脚本模式
  scripted:
    # 阶段序列：按时间顺序执行
    phases:
      - name: "approach"     # 阶段名
        duration_steps: 120  # 阶段持续步数 (@50Hz)
        velocity:
          vx: 0.8            # 前进速度 (m/s), -0.8 ~ 0.8
          vy: 0.0            # 横向速度 (m/s), -0.5 ~ 0.5
          wz: 0.0            # 转向速度 (rad/s), -1.57 ~ 1.57
        arm_motion: "none"   # "none" | "wave" | "extend_forward"
                             # | "extend_left" | "extend_right"
        arm_joints: {}       # 可选：精确指定关节角度，覆盖 arm_motion

      - name: "disturb"
        duration_steps: 150
        velocity:
          vx: 0.0
          vy: 0.0
          wz: 0.0
        arm_motion: "wave"
        arm_joints:
          left_shoulder_pitch_joint: -1.2    # 可选精确值
          left_elbow_joint: 0.5
          # 未指定的关节 → 保持默认

      - name: "retreat"
        duration_steps: 80
        velocity:
          vx: -0.4
          vy: 0.0
          wz: 0.0
        arm_motion: "none"

  # 距离门控调速模式（实际实现）
  distance_gated:
    workspace_x: [0.0, 0.8]            # G1 root 允许的 x 范围
    workspace_y: [-0.5, 0.5]           # G1 root 允许的 y 范围
    cautious_threshold: 0.15            # m — 低于此距离: 撤退
    moderate_threshold: 0.30            # m — 低于此距离: 降速 + 偏置远离
    speed_aggressive: 0.20              # AGGRESSIVE 模式速度乘数 (vx∈[-0.16,0.16])
    speed_moderate: 0.10                # MODERATE 模式速度乘数 (50%)
    speed_cautious: 0.0                 # CAUTIOUS 模式速度乘数 (停)
    resample_interval: 200              # 步数，速度 schedule 重采样间隔
    seed: 42                            # 随机种子 (卡住撤退方向复现)
    # vy 恒为 0: 行走策略仅训练前向运动，横向移动会导致 destabilize

  # VLM 引导模式
  vlm:
    refresh_interval: 200                # VLM 决策刷新间隔（步数）
    prompt_file: null                    # 自定义 prompt 文件路径 (null = 用默认)
    default_velocity: [0.3, 0.0, 0.0]  # VLM 无响应时的默认速度

# === UR10e 安全配置 ===
# 引用 GMRobot 的安全配置
safety:
  config_path: "configs/safety_fusion.yaml"  # 路径相对于 GMROBOT_ROOT
  enable_envelope: true
  enable_layer2: false
  enable_replan: true
  enable_vlm_safety: false                   # GMRobot 自带的 VLM 安全分析
  enable_vlm_grasp_supervisor: false

# === 传感器配置 ===
sensors:
  enable_head_camera: false            # G1 头部 D435 相机
  enable_lidar: false                  # G1 头部 MID-360 LiDAR
  enable_scene_camera: true            # 俯视场景相机
  pressure_mat_resolution: "32x32"     # "32x32" | "64x64"

# === Episode 配置 ===
episode:
  max_steps: 10000                     # 最大仿真步数
  num_parts: 20                        # 搬运零件总数
  record_video: false                  # 是否录制视频
  video_dir: "videos/"                 # 视频输出目录
  seed: 42

# === 输出配置 ===
output:
  step_csv: true                       # 每步 CSV
  episode_json: true                   # 汇总 JSON
  mat_heatmap_video: false             # 压力垫热力图视频
  output_dir: "results/"
```

---

## 2. 预定义场景

### 2.1 `table_bump` — 桌面碰撞测试（已移除）

> ⚠️ 此场景的 phase 定义已从代码中删除 (M5 fix, 2026-07-10)。
> 原因: 无 CLI 执行路径，且 G1 行走策略未训练手臂运动。
> YAML 定义保留在此作为设计参考。
> 需要时从 git history 恢复 `g1_disturbance_controller.py` 中的 `TABLE_BUMP_PHASES`。

```yaml
name: "table_bump"
description: "G1 走向桌子并碰撞，测试桌面振动对零件稳定性的影响"
mode: "scripted"
g1_behavior:
  workspace:
    x_min: -0.5
    x_max: 0.8
    y_min: -0.5
    y_max: 0.5
  scripted:
    phases:
      - name: "approach"
        duration_steps: 100       # 2 秒，从 -1.5 走到 ~ -0.7
        velocity: {vx: 0.8, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "slow_approach"     # 减速靠近
        duration_steps: 60        # 1.2 秒
        velocity: {vx: 0.3, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "bump"
        duration_steps: 50        # 1 秒持续前进（撞桌）
        velocity: {vx: 0.3, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "hold"
        duration_steps: 50        # 停在碰撞位置
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "retreat"
        duration_steps: 60
        velocity: {vx: -0.3, vy: 0.0, wz: 0.0}
        arm_motion: "none"
episode:
  max_steps: 4000                 # 留足 UR10e 操作时间
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
```

### 2.2 `arm_wave` — 动态障碍物挥手

```yaml
name: "arm_wave"
description: "G1 站在工作台前大幅挥手，测试安全门对动态障碍物的响应"
mode: "scripted"
g1_behavior:
  workspace:
    x_min: 0.0
    x_max: 0.6
    y_min: -0.4
    y_max: 0.4
  scripted:
    phases:
      - name: "walk_to_position"
        duration_steps: 140       # ~2.8 秒，到 x≈0.0
        velocity: {vx: 0.6, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "wave_fast"
        duration_steps: 100       # 2 秒快速挥手
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "wave"
      - name: "wave_slow"
        duration_steps: 150       # 3 秒慢速挥手
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "wave"
      - name: "retreat"
        duration_steps: 80
        velocity: {vx: -0.4, vy: 0.0, wz: 0.0}
        arm_motion: "none"
episode:
  max_steps: 5000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
```

### 2.3 `object_push` — 推撞物体（已移除）

> ⚠️ 此场景的 phase 定义已从代码中删除 (M5 fix, 2026-07-10)。
> 原因: 需物理手臂控制，行走策略不支持。YAML 保留作为设计参考。

```yaml
name: "object_push"
description: "G1 靠近容器并伸手推物，测试防撞落系统（夹爪加固/回抓）"
mode: "scripted"
g1_behavior:
  workspace:
    x_min: 0.0
    x_max: 0.6
    y_min: -0.4
    y_max: 0.4
  scripted:
    phases:
      - name: "approach"
        duration_steps: 130       # 走到 x≈0.1
        velocity: {vx: 0.6, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "extend_and_push_left"
        duration_steps: 150       # 3 秒伸手推左容器
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "extend_left"
        arm_joints:
          left_shoulder_pitch_joint: -2.0
          left_elbow_joint: 0.0
      - name: "extend_and_push_right"
        duration_steps: 150       # 3 秒伸手推右容器
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "extend_right"
        arm_joints:
          right_shoulder_pitch_joint: -2.0
          right_elbow_joint: 0.0
      - name: "retreat"
        duration_steps: 80
        velocity: {vx: -0.4, vy: 0.0, wz: 0.0}
        arm_motion: "none"
episode:
  max_steps: 6000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
  enable_replan: true
```

### 2.4 `arm_collision` — 运输途中碰撞

```yaml
name: "arm_collision"
description: "在 UR10e 运输零件途中 G1 穿越工作空间，测试安全门 STOP 响应延迟"
mode: "scripted"
g1_behavior:
  workspace:
    x_min: -0.3
    x_max: 0.8
    y_min: -0.5
    y_max: 0.5
  scripted:
    phases:
      - name: "wait_for_transit"
        duration_steps: 200       # 等 UR10e 开始运作（~4 秒）
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "fast_approach"
        duration_steps: 60        # 快速冲向工作空间
        velocity: {vx: 0.8, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "collision_zone"
        duration_steps: 80        # 在工作空间中穿行
        velocity: {vx: 0.3, vy: 0.2, wz: 0.0}
        arm_motion: "extend_forward"
      - name: "retreat"
        duration_steps: 80
        velocity: {vx: -0.5, vy: 0.0, wz: 0.0}
        arm_motion: "none"
episode:
  max_steps: 5000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
  enable_replan: true
```

### 2.5 `circulate` — 反复靠近/撤退（已移除）

> ⚠️ 此场景的 phase 定义已从代码中删除 (M5 fix, 2026-07-10)。
> 原因: 无 CLI 执行路径。YAML 保留作为设计参考。

```yaml
name: "circulate"
description: "G1 靠近→撤退→靠近，重复 3 次，测试安全门迟滞和 livelock"
mode: "scripted"
g1_behavior:
  workspace:
    x_min: -0.5
    x_max: 0.6
    y_min: -0.4
    y_max: 0.4
  scripted:
    phases:
      - name: "approach_1"
        duration_steps: 80
        velocity: {vx: 0.6, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "retreat_1"
        duration_steps: 60
        velocity: {vx: -0.5, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "approach_2"
        duration_steps: 80
        velocity: {vx: 0.6, vy: 0.1, wz: 0.0}
        arm_motion: "none"
      - name: "retreat_2"
        duration_steps: 60
        velocity: {vx: -0.5, vy: -0.1, wz: 0.0}
        arm_motion: "none"
      - name: "approach_3"
        duration_steps: 80
        velocity: {vx: 0.7, vy: -0.1, wz: 0.0}
        arm_motion: "extend_forward"
      - name: "retreat_3"
        duration_steps: 60
        velocity: {vx: -0.5, vy: 0.0, wz: 0.0}
        arm_motion: "none"
episode:
  max_steps: 8000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
```

### 2.6 `combined` — 全栈压力测试（已移除）

> ⚠️ 此场景的 phase 定义已从代码中删除 (M5 fix, 2026-07-10)。
> 原因: 需物理手臂控制，行走策略不支持。YAML 保留作为设计参考。

```yaml
name: "combined"
description: "行走→挥手→推物→撤退，全部执行"
mode: "scripted"
g1_behavior:
  workspace:
    x_min: -0.3
    x_max: 0.6
    y_min: -0.4
    y_max: 0.4
  scripted:
    phases:
      - name: "approach"
        duration_steps: 140
        velocity: {vx: 0.6, vy: 0.0, wz: 0.0}
        arm_motion: "none"
      - name: "wave"
        duration_steps: 100
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "wave"
      - name: "push_left"
        duration_steps: 100
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "extend_left"
      - name: "push_right"
        duration_steps: 100
        velocity: {vx: 0.0, vy: 0.0, wz: 0.0}
        arm_motion: "extend_right"
      - name: "forward_push"
        duration_steps: 100
        velocity: {vx: 0.2, vy: 0.0, wz: 0.0}
        arm_motion: "extend_forward"
      - name: "retreat"
        duration_steps: 80
        velocity: {vx: -0.4, vy: 0.0, wz: 0.0}
        arm_motion: "none"
episode:
  max_steps: 8000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
  enable_replan: true
```

### 2.7 `constrained_wander` — 约束随机游走

```yaml
name: "constrained_wander"
description: "G1 在工作台区域受限随机游走，通过距离门控调速靠近 UR10e（默认模式）"
mode: "constrained_wander"
g1_behavior:
  workspace:
    x_min: 0.0
    x_max: 0.8
    y_min: -0.5
    y_max: 0.5
  distance_gated:
    workspace_x: [0.0, 0.8]            # G1 root 允许的 x 范围
    workspace_y: [-0.5, 0.5]           # G1 root 允许的 y 范围
    cautious_threshold: 0.15            # m — 低于此距离: 撤退 (CAUTIOUS)
    moderate_threshold: 0.30            # m — 低于此距离: 降速 + 偏置远离 (MODERATE)
    speed_aggressive: 0.20              # AGGRESSIVE 模式速度乘数
    speed_moderate: 0.10                # MODERATE 模式速度乘数 (AGGRESSIVE的50%)
    speed_cautious: 0.0                 # CAUTIOUS 模式速度乘数 (停)
    resample_interval: 200              # 步数，速度 schedule 重采样间隔
    seed: 42                            # 随机种子 (可复现)
    # vy 恒为 0: G1 行走策略 (0121_walk.pt) 仅训练前向运动
    # 横向移动会 destabilize 机器人导致摔倒
    # y 轴变化来自边界偏置 (_boundary_steer) 和远离偏置 (_steer_away)
    # 卡住检测 (stuck detection):
    #   命令速度 >0.10 m/s 且实际速度 <0.02 m/s 持续 100 步
    #   → 接触力方向撤退 80 步 (fallback: 随机方向)
episode:
  max_steps: 10000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
```

### 2.8 `wander_vhand_replan` — 虚拟手障碍 + 几何重规划

```yaml
name: "wander_vhand_replan"
description: "G1 虚拟手障碍侵入 UR10e 安全包络，触发几何重规划。测试 UR10e 路径重规划能力。"
mode: "constrained_wander"
g1_behavior:
  workspace:
    x_min: 0.0
    x_max: 0.8
    y_min: -0.5
    y_max: 0.5
  distance_gated:
    workspace_x: [0.0, 0.8]
    workspace_y: [-0.5, 0.5]
    cautious_threshold: 0.15
    moderate_threshold: 0.30
    speed_aggressive: 0.20
    speed_moderate: 0.10
    speed_cautious: 0.0
    resample_interval: 200
    seed: 42
  virtual_hand:
    enabled: true
    offset_z: 0.45                    # 虚拟手 z 偏移 (m)，模拟 G1 手部高度
    pursuit_mode: true                # 虚拟手追踪 UR10e EE
    # pursuit_mode 激活 block-retreat-reblock 循环:
    #   1. block:  虚拟手进入安全包络 → 触发 STOP/SLOW_DOWN
    #   2. retreat: 持续触发 → L1WarnReplanTrigger 检测 → GeometryReplanV0 注入绕行航点
    #   3. reblock: UR10e 重规划后恢复运动 → 虚拟手再次侵入 → 循环
episode:
  max_steps: 10000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
  enable_replan: true                 # 必须启用 --replan
```

> **测试目标**: 验证 GMRobot 在 G1 虚拟手持续侵入安全包络时的路径重规划能力。
> 虚拟手通过 `pursuit_mode` 持续追踪 UR10e EE，形成 block-retreat-reblock 循环，
> 测试 GeometryReplanV0 绕行航点注入和 L1WarnReplanTrigger 的持续 SLOW_DOWN 检测。

### 2.9 `vlm_explore` — VLM 自适应探索

```yaml
name: "vlm_explore"
description: "VLM 分析 G1 头部相机 RGB 后自适应决定扰动行为"
mode: "vlm_guided"
g1_behavior:
  workspace:
    x_min: 0.0
    x_max: 0.8
    y_min: -0.5
    y_max: 0.5
  vlm:
    # SSH tunnel to remote VLM (config/default.yaml vlm.ssh section)
    # ssh:
    #   host: "120.209.70.195"
    #   port: 30481
    #   user: "root"
    #   password: "..."           # temporary dev server
    # VLM service endpoint
    host: "localhost"
    port: 8080
    # Query settings
    interval: 200                 # 步数，VLM 查询间隔
    min_interval_s: 2.0           # 秒，最小查询间隔 (rate limit)
    # VLM 使用对抗性测试 prompt (见代码 VLM_NAV_PROMPT)
    # VLM 输出: {"action": "approach"|"retreat"|"circle_left"|..., "reason": "..."}
    # 动作映射 (vlm.actions):
    #   approach → (0.25, 0, 0), retreat → (-0.20, 0, 0),
    #   circle_left → (0.10, 0, 0.3), circle_right → (0.10, 0, -0.3),
    #   stand_wave → (0, 0, 0), wait → cached
episode:
  max_steps: 10000
safety:
  config_path: "configs/safety_fusion.yaml"
  enable_envelope: true
sensors:
  enable_head_camera: true        # VLM 需要 G1 头部相机
```

---

## 3. 批量测试配置

```yaml
# batch_test_configs/batch_safety_comparison.yaml
# 跨安全配置的对比批量测试

batch_name: "safety_config_comparison"
description: "对比不同安全配置下 G1 扰动效果"
repeat: 3                         # 每种配置重复 3 次

scenarios:
  - scenario: "constrained_wander"
    safety_configs:
      - "configs/safety_layer1.yaml"       # 仅 L1
      - "configs/safety_fusion.yaml"       # L1 + L2 fusion
      - null                                # 无安全层（baseline）

  - scenario: "arm_wave"
    safety_configs:
      - "configs/safety_layer1.yaml"
      - "configs/safety_fusion.yaml"
      - null

  - scenario: "arm_collision"
    safety_configs:
      - "configs/safety_layer1.yaml"
      - "configs/safety_fusion.yaml"

output:
  comparison_table: "results/comparison.md"
  aggregate_json: "results/batch_summary.json"
```

---

## 4. VLM 默认 Prompt

```python
# G1_VLM_DEFAULT_PROMPT
# Used by G1VLMDisturbanceController when no custom prompt file is provided

G1_VLM_DEFAULT_PROMPT = """You are a robotic testing agent controlling a Unitree G1 humanoid robot.
The G1 stands on a 4m×4m tactile pressure mat (origin at center, mat extends ±2m in x and y).
A UR10e robotic arm is performing pick-and-place operations on a table at x=0.6, y centered.
Two containers (A at y=-0.25, B at y=0.25) hold small parts.

Your job: generate disturbance behaviors to TEST the arm's safety and recovery capabilities.

Analyze the camera image and respond in JSON:
{
    "arm_state": "idle" | "approaching_pick" | "grasping" | "transiting" | "placing" | "recovering",
    "arm_ee_position_estimate": {"x": float, "y": float, "z": float},
    "gripper_has_object": true | false,
    "risk_assessment": "safe" | "caution" | "danger",
    "disturbance_decision": {
        "action": "approach_table" | "retreat" | "stand_wave_arms" | "reach_toward_arm" | "reach_toward_container_A" | "reach_toward_container_B" | "walk_past" | "wait",
        "velocity_command": {"vx": float, "vy": float, "wz": float},
        "arm_motion": "none" | "wave" | "extend_forward" | "extend_left" | "extend_right",
        "reasoning": "brief explanation of why this action was chosen"
    }
}

Strategy guidelines:
- If arm is TRANSITING with object in gripper: approach and try to collide — tests knock-off defense
- If arm is GRASPING a part: reach toward that container — tests grasp stability
- If arm is IDLE: walk past at moderate speed — tests idle safety gate
- If arm just RECOVERED from knock-off: wait 2 seconds then try again — tests recovery robustness
- If arm STOPPED (frozen): retreat slightly and approach from different angle — tests replan
- Vary your approach: don't always walk straight — sometimes circle, sometimes fast, sometimes slow
- Prioritize safety: never command velocity > 0.8 m/s or angular > 1.5 rad/s
"""
```
