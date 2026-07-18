# GMDisturb 对抗性审查报告 — 第 1 次 (2026-07-01)

联合仿真框架的全面代码审查，覆盖路径迁移正确性、代码正确性、物理正确性、架构合理性、安全层兼容性。

> **后续审查**:
> - [adversarial-review-2026-07-10-fresh.md](adversarial-review-2026-07-10-fresh.md) — 第 2 次 (17 issues, 11 修复)
> - [adversarial-review-ponytail-2026-07-10.md](adversarial-review-ponytail-2026-07-10.md) — 第 3 次 (ponytail 深度版, 2 CRITICAL 全新)

## 审查范围

- `/root/g1_ur10e_disturbance` — GMDisturb Phase 1 联合仿真环境
- `/root/pressure_mat_repro` — 触觉压力垫复现工程
- `/root/GMRobot` — 被测的 UR10e 安全推理系统
- 审查维度：路径迁移正确性、代码正确性、物理正确性、架构合理性、安全层兼容性

## 问题汇总

共发现 **26 个问题**，按严重度分级：

| 严重度 | 数量 | 关键问题 |
|--------|------|---------|
| 🔴 CRITICAL | 3 | reset 误重置 G1、episode 时长不足、taxel 排列验证缺失 |
| 🟠 HIGH | 3 | 硬编码路径、body 数量文档错误、Tier0 冻结 vs 扰动测试冲突 |
| 🟡 MEDIUM | 9 | 碰撞过滤缺失、replan 延迟、多体包络敏感、VLM 字段未对齐 等 |
| 🟢 LOW | 11 | 文档 typo、代码清理、冗余观测 等 |

## CRITICAL 问题

### C1. `reset_scene_to_default` 错误重置 G1

**位置**: `dual_env_cfg.py` reset_ur10e_scene 事件

**根因**: `mdp.reset_scene_to_default` 重置整个场景的所有实体，包括 G1

**修复**: 删除此事件，仅保留 `reset_ur10e_joints`

### C2. Episode 时长 60s (3000步) 不足

**位置**: `dual_env_cfg.py` `__post_init__` 中 `episode_length_s = 60.0`

**根因**: GMRobot 实测 20 零件需 ~7521 步，加扰动需更多

**修复**: 改为环境变量可配，默认 200s (10000步)

### C3. Taxel 排列置换表丢失

**位置**: `mdp/tactile_obs.py` vs 原始 `pressure_mat_repro/.../observations.py`

**根因**: 迁移时删除了防御性排列表代码，直接假设 PhysX filter 顺序为 row-major

**修复**: Phase 2 端到端空间校准验证；若失败则恢复排列表

## HIGH 问题

### H1. 硬编码绝对路径

所有外部依赖路径硬编码为 `/root/...`，原始 `pressure_mat_repro` 使用包相对路径。改为环境变量 `PRESSURE_MAT_ROOT`、`GMROBOT_ROOT`。

### H2. Body link 数量文档与实际不一致

VARIABLES.md 声称 37 个 body link，实际 G1 29-DOF USD 实测有 37 个。用 smoke test 实际输出修正。

### H3. Tier0 硬 STOP 冻结与扰动测试目标冲突

GMRobot 规定 `dist < 0.13m` 永久 STOP。GMDisturb 的碰撞/推物场景正是要接近到这个距离。通过 GMDisturb 三档距离行为模式 (CAUTIOUS/MODERATE/AGGRESSIVE) 区分耐力测试和边界测试。

## MEDIUM 问题摘要

| # | 问题 | 归属 |
|---|------|------|
| M1 | `last_processed_actions` 引用别名 | GMDisturb 自修 |
| M2 | 双脚同时触地力值叠加（经分析非bug） | 无需修复 |
| M3 | `_OBS_SLOTS` 40个槽位仅20个有零件 | 保留（未来可用） |
| M4 | G1↔UR10e 无碰撞过滤 | GMDisturb 自修 |
| M5 | Replan 触发延迟 vs G1 快速移动 | GMRobot 弱点 W2 |
| M6 | 多体包络过度敏感 | 两边协调 |
| M7 | VLM 字段未对齐 | 两边协调 |
| M8 | workspace 边界未继承 | GMDisturb 自修 |
| M9 | 相机被注释 | GMDisturb Phase 2 启用 |

## LOW 问题摘要

文档 ISAAC 版本标注错误、episode_length_s 不一致、`_PHASE_PERIOD` 私有导入、smoke test 缺空间校准、`git_push.sh` untracked、docstring typo、冗余条件表达式、Part mass 未记录。

## 路径迁移对照

| 组件 | 原始 (pressure_mat_repro) | 迁移后 (g1_ur10e_disturbance) | 状态 |
|------|--------------------------|------------------------------|------|
| `tactile_force_multi_net` | 带排列表 + slab 模式 | 无排列表，无 slab | ⚠️ 排列表待验证 |
| `WalkJointAction` | 包相对路径 | 逻辑一致 | ✅ |
| `root_out_of_mat_bounds` | 包相对路径 | 逻辑一致 | ✅ |
| `G1_927_WALK_CFG` | 包相对路径 | 绝对路径 | 🔴 待修复 |
| 部署 env 配置 | 独立 | 合并到 dual_env_cfg | ✅ |

## 与 GMRobot 文档的 10 项冲突

详见 [gmrobot-weaknesses.md](gmrobot-weaknesses.md) 和 [iteration-plan.md](iteration-plan.md)。


---

## 补充：UR10e 无法上桌的根因与解决方案 (2026-07-04)

### 问题

UR10e 始终出现在地平面 (z=0) 而非桌面上方，`ArticulationCfg.init_state.pos` 完全无效。

### 根因链

```
ImplicitActuatorCfg（USD 属性优先）
  └─ ArticulationCfg.init_state.pos 被忽略
       └─ UR10e 始终在 USD 默认位置 (0,0,0)
            └─ 试图用 write_root_state_to_sim 移动
                 └─ 视觉网格 + 物理位姿移动到正确高度
                 └─ 但 IK 内部 FK 无法感知新位置
                      └─ IK 算出错误 joint 解（elbow 1.54 vs -0.34）
                           └─ 机械臂伸直/跑到地上
```

### 关键发现

| 组件 | `ImplicitActuatorCfg` | `IdealPDActuatorCfg` |
|------|----------------------|---------------------|
| `init_state.pos` | **忽略**（从 USD 读取） | **生效** |
| `init_state.joint_pos` | 生效 | 生效 |
| G1 (IdealPDActuatorCfg) | N/A | ✅ 位置正确 |
| UR10e (原 ImplicitActuatorCfg) | ❌ 位置不生效 | ✅ 切换后位置生效 |

**但单独 `IdealPDActuatorCfg` 不够**：UR10e USD 文件的视觉网格可能有内部偏移，物理位姿正确但视觉网格仍在 z=0。需要额外使用 `write_root_state_to_sim` 强制同步视觉网格。

### 解决方案

双重保障：

1. **`IdealPDActuatorCfg`**：替换 `ImplicitActuatorCfg`，使 `init_state.pos` 被正确读取 → UR10e 物理位姿上桌
2. **`write_root_state_to_sim`**：首次 reset 事件中强制写入 root state → 视觉网格同步到正确 z

```python
# dual_env_cfg.py 关键代码

# 1. 使用 IdealPDActuatorCfg（非 Implicit）
actuators={
    "shoulder": IdealPDActuatorCfg(
        joint_names_expr=["shoulder_.*"],
        stiffness=1320.0, damping=72.66,
        effort_limit=87.0, velocity_limit=2.175,
    ),
    ...
}

# 2. 首次 reset 时 write_root_state_to_sim 同步视觉网格
def _fix_ur10e_position(env, env_ids):
    if getattr(_fix_ur10e_position, "_done", False):
        return
    robot = env.scene["robot_ur10e"]
    root_state = robot.data.default_root_state.clone()
    root_state[:, 2] = _TABLE_Z  # 只改 z，保留朝向
    robot.write_root_state_to_sim(root_state)
    _fix_ur10e_position._done = True
```

### 桌面高度

`_TABLE_Z = 0.762`（SeattleLabTable 标准 30 英寸）。UR10e、桌子、容器统一使用此高度，策略的 `HOME_POSITION` 和 `_DESK_Z` 以此为基准。

### 验证

```
[GMDisturb] UR10e teleported to z=0.762 (target 0.762)
[run] UR10e base_z=0.762  G1 root_z=0.800
[run] ALL 20 PARTS PLACED at step 8019
```

---

## 补充：UR10e xy 坐标偏移问题与最终修复 (2026-07-05)

### 问题

UR10e 视觉位姿与配置偏差 ~2.5m（x=-1.08, y=2.35），导致 EE 无法到达目标位置。

### 根因链

```
UR10e USD 文件 (ur10e_gripper.usd)
  └─ articulation root 内置偏移 (-1.082, 2.354, 0.000)
       └─ ImplicitActuatorCfg 忽略了 init_state.pos=(0,0,0)
            └─ UR10e 停留在 USD 默认位置，而非配置的 (0,0,0)
                 └─ 距离桌子 (0.6, 0, 0) 和容器 (0.75, ±0.25, 0) ~2.7m
                      └─ IK 目标不可达，EE 轨迹全错
```

### 关键数据

```
UR10e root_pos_w (无修正):  (-1.082, 2.354, 0.000)  ← USD 内置偏移
UR10e root_pos_w (修正后):   (0.000, 0.000, 0.000)  ← 修正到 GMRobot 原生位置
桌子:                         (0.600, 0.000, 0.000)  ← GMRobot 原始位置
容器 A:                       (0.750, -0.250, 0.000)
容器 B:                       (0.750, 0.250, 0.000)
地平面:                       z = -1.05
G1 root:                      (-1.500, 0.000, -0.250)
```

### 修复

```python
def _fix_ur10e_position(env, env_ids):
    """Teleport UR10e root from USD offset to (0,0,0)."""
    root_state = robot.data.root_state_w.clone()
    root_state[:, :3] = torch.tensor([0.0, 0.0, 0.0])
    robot.write_root_state_to_sim(root_state)
```

### 最终布局架构

```
                    z=0 (Isaac Sim viewport grid)
    ┌─────────────────────────────────────────────┐
    │  UR10e (0,0,0)  桌子 (0.6,0,0)  容器 A/B  │  ← GMRobot 原生坐标系
    │                 (0.75, ±0.25, 0)           │
    └─────────────────────────────────────────────┘
    ═══════════════════════════════════════════════  z=-1.05 (地面/垫子)
         G1 (-1.5, 0, -0.25)  ← 行走在垫子上
```

### 已验证

```
EE 追踪精度: target=(0.971, 0.355, 0.130) → ee=(0.971, 0.360, 0.278) ✓
策略完成: time_step=7420, success=True ✓
所有 20 零件搬运周期完成 ✓
```
