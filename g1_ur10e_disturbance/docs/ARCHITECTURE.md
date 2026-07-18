# GMDisturb — 人形机器人 G1 作为 UR10e 机械臂扰动测试系统

> **时效性**: 本文档已与代码同步 (2026-07-13)。若与代码矛盾，以代码为准。
> **相关**: [doc-audit-2026-07-10.md](cross-project/doc-audit-2026-07-10.md) — 文档 vs 代码差异审计
> R7 更新: 逐零件测试协议、阶段驱动虚拟手、死锁三级逃脱、VLM协同、俯视监控

## Context

两个独立 Isaac Lab 项目合并为一个联合仿真测试框架：

- **压力垫系统** (`pressure_mat_repro`)：Unitree G1 人形机器人在 4m×4m 触觉压力垫上行走
- **GMRobot**：UR10e 机械臂执行 20 个物体的拾放任务，含安全层 + 撞落恢复

**目标**：让 G1 人形机器人成为 UR10e 的"物理对抗测试员"——通过靠近、碰撞、推撞物体等行为，量化测试机械臂的防撞落系统、安全门响应和恢复能力。压力垫作为 ground-truth 传感器记录所有力学事件。

两个项目共用 Isaac Lab 1.3.0 (`isaaclab.*`) + Isaac Sim 4.2.0。

---

## 七个根本问题与解决路径

### 问题 1：两体共存 — 两个机器人在同一个物理世界

**本质**：两个独立的 articulation（G1 29-DOF + UR10e 12-DOF）必须放入同一个 PhysX 场景，不发生 prim 路径冲突或求解器崩溃。

**解决**：Isaac Lab `InteractiveScene` 原生支持多个 `ArticulationCfg`——指定不同的 `prim_path`（`Robot_G1` vs `Robot_UR10e`）。PhysX 对多 articulation 有完整支持。**无架构障碍**。

### 问题 2：盲人走路 — 黑盒行走策略无视觉、无目标导航

**本质**：G1 行走策略是固定 TorchScript 模型。输入 588D 本体感知，输出 12D 腿关节目标。唯一可注入的外部指令是速度命令 `(vx, vy, wz)`。策略无视觉、无碰撞预测。

**解决**：速度命令注入 + FK 位置反馈闭环（dist → 速度映射）。不需要给行走策略加传感器——它不接受视觉输入。FK 提供亚毫米精度、零延迟的位置反馈。

### 问题 3：接触生成 — G1 如何物理触碰 UR10e

**本质**：G1 只有 12 个腿关节被行走策略控制，17 个手臂+腰部关节被动。要产生扰动，必须让 G1 的身体部件碰撞网格与 UR10e 碰撞网格相交。

**解决**：手臂 PD 控制（`set_joint_position_target` 写肩关节前伸+肘关节伸直）+ 身体直接碰撞（走向桌子让躯干接触）。PhysX 自动计算接触力。

### 问题 4：感知鸿沟 — G1 没有功能传感器

**本质**：G1 USD 中有 D435 body、MID-360 body、IMU body，但只是 PhysX 刚体，未挂载功能传感器 prim。

**三条路径**：
- **A. 仿真全知**（默认）：直接用 FK 读所有实体的 3D 位置——零延迟、100% 确定性
- **B. 加装传感器**（可选）：配 `TiledCamera` + `RayCaster` 为功能传感器——LiDAR 提供 360° 3D 点云
- **C. 外部感知**（探索）：场景相机 + VLM / SAM2——有延迟但可发现意外攻击向量

### 问题 5：动作复用 — 两个独立控制器共享一个 env.step()

**本质**：`ManagerBasedRLEnv.step()` 接受一个扁平动作向量。G1 输出 12D + UR10e 输出 8D = 需要合并。

**解决**：Isaac Lab `ActionManager` 按维度拆分。定义两个 `ActionTerm`（各目标不同 articulation），拼接为 20D 向量，ActionManager 自动分发 dims 0-11→G1、dims 12-19→UR10e。

### 问题 6：双向安全 — 两个机器人都会受损

**本质**：接触力是相互的。G1 碰 UR10e → UR10e 受力；UR10e 反作用力 → G1 可能摔倒。

**G1 侧**：步态相位同步（只在双足支撑期出手）+ 接触力紧急制动（>100N → 后退）

**UR10e 侧**：`G1EnvelopeAdapter` 将 G1 身体部件映射为安全层"障碍物"，复用现有 RuleEngine 阈值（hard_stop=0.13m, warn=0.16m），**零侵入**。

### 问题 7：测量 — 如何量化"发生了什么事"

**解决**：多模态传感器融合——压力垫（脚步+掉落）+ G1 全身接触力（37 体）+ FK（所有实体的 3D 位姿）+ 安全日志（门决策+延迟）。

---

## 架构总览

### 依赖关系：引用，不复制

```
/root/pressure_mat_repro_full/pressure_mat_repro/  ← 只读：提供 G1 cfg、mat USD、MDP、行走策略
/root/GMRobot/                                      ← 只读：提供 UR10e cfg、table/container/part USD、安全层、VLM
/root/g1_ur10e_disturbance/                         ← 新建：统一 env cfg + 引导控制器 + 事件检测 + 指标
```

### 继承关系

```
ManagerBasedRLEnvCfg
  └── DualRobotDisturbanceEnvCfg       (新增)

InteractiveSceneCfg
  └── DualRobotSceneCfg                (新增)
```

### 场景布局

```
        y=2
         |
   (-2,2)├────────────┬────────────┤(2,2)
         │            │            │
         │   G1 行走   │            │
         │   路径 →    │            │
   y=0  ─┤──G1起始───→├──Table───→┤
         │ (-1.5,0)   │ (0.6,0)    │
         │            │ UR10e+容器  │
         │            │            │
   (-2,-2)├────────────┴────────────┤(2,-2)
         |
        y=-2
         x=-2                    x=2
         压力垫 4m×4m 居中于原点
```

| 实体 | Prim Path | 位置 (x, y, z) |
|------|-----------|----------------|
| 压力垫 32×32 | `{ENV_REGEX_NS}/Mat` | (0, 0, 0) |
| G1 人形机器人 | `{ENV_REGEX_NS}/Robot_G1` | (-1.5, 0, 0.8) |
| UR10e 机械臂 | `{ENV_REGEX_NS}/Robot_UR10e` | (0, 0, 0) |
| 桌子 | `{ENV_REGEX_NS}/Table` | (0.6, 0, 0) |
| 容器 A（拾取） | `{ENV_REGEX_NS}/ContainerA` | (0.75, -0.25, 0) |
| 容器 B（放置） | `{ENV_REGEX_NS}/ContainerB` | (0.75, 0.25, 0) |
| 零件 1-20 | `{ENV_REGEX_NS}/Part_{i}` | 容器槽位内 |
| 场景相机 | `{ENV_REGEX_NS}/SceneCamera` | (0.35, 0, 2.5) |

---

## 控制架构

### 动作空间：20 维

```
indices 0-11:  G1 腿部关节目标 (hip_yaw/roll/pitch + knee × 左右) — 12D
indices 12-19: UR10e EE 姿态 (7D) + 夹爪 (1D) — 8D
```

### 观测空间：分组字典

| 组名 | 内容 | 用途 |
|------|------|------|
| `g1_walker` | 588D (6步历史 × 8项) | G1 行走策略输入 |
| `tactile` | (32, 32) Newton | 压力垫分析 |
| `ur10e_policy` | ee_pose + 20×part_pose + 2×box_pose + 40×slot_T | UR10e 状态机输入 |
| `ur10e_camera` | (480, 640, 3) RGB | VLM / 感知 |
| `safety` | ee_vel + joint_pos/vel | 安全层 |
| `g1_body` | G1 肢体追踪（新增） | 安全适配器 |

### 控制循环

```
每步：
1. G1 扰动控制器 → 速度命令 + 手臂 PD 目标
2. G1 行走策略推理 (TorchScript, 588→12)
3. 写入 G1 手臂 PD 目标
4. UR10e 状态机 → EE 动作
5. 逐零件测试协议 (--per-part-protocol): PICK→TRANSIT→PLACE→RESET 四阶段循环
   — PICK/PLACE: 手半径 0.08, 跟随 EE, 测试 STOP 响应
   — TRANSIT: 手半径 0.22, 挡运输路径中点, 测试 replan 绕行, TTC 抑制
   — RESET: 手瞬移到 (0,0,2.0), 安全门看到 999m, UR10e 自由完成
   — 阶段超时推进: PICK(900步)→TRANSIT(200步)→超时→RESET(900步)
6. 虚拟手位置覆写 (表面投影 + 阶段驱动半径 + RESET 安全门旁路)
7. 安全门评估 — envelope gating 默认开启, TTC 在 TRANSIT 抑制, dist_min_held 传入
8. 死锁检测+三级逃脱: STOP>30+手<0.1m → 强制RESET; 否则 抖→推→G1退
9. 重规划检查: L1WarnReplanTrigger → raise_high 策略 (raise_approach_m=0.25)
10. 抓取回退检查: Protocol模式阈值0.20m (原0.50m), GRASP_MAX=5, replan不复位计数器
11. VLM 决策 (可选): 头部相机战术 + 俯视相机策略协调 + 零件状态监控
12. 合并动作 → env.step()
13. 压力垫事件 + 零件Z追踪 + 每步19列CSV追踪
14. 推进 UR10e 策略时钟
```

---

## G1 扰动行为

> 📐 **设计参考** — 以下"引导方案总表"和"最优组合：三层混合架构"是 Phase 1 设计阶段的分析产物 (2026-06)。
> 实际实现采用更简单的**距离门控调速**方案 (见下方 §距离门控调速)。
> 11 种方案中，实际使用的: #0 (脚本), #1 (UR10e状态机), #4 (压力垫), #5 (接触力), #7 (FK), #8 (步态相位), #9 (头部相机/VLM)。
> 未使用: #2 (SAM2), #3 (VLM全局推理用场景相机), #6 (关节力矩), #10 (LiDAR)。

### 引导方案总表（11 种）— 设计参考

| # | 方案 | 信号来源 | 延迟 | 确定性 | 新增成本 |
|---|------|---------|------|--------|---------|
| 0 | 开环脚本 | 时间步数 | 0 | 100% | 无 |
| 1 | UR10e 状态机规则 | `policy._current_phase` | 0 | 100% | 无 |
| 2 | SAM2 感知追踪 | 场景相机 | ~30ms | 90% | 感知服务 |
| 3 | VLM 全局推理 | 场景相机 | ~1-2s | 60% | VLM 服务 |
| 4 | 压力垫力反馈 | (32,32) 力图像 | 0 | 100% | 无 |
| 5 | G1 全身触觉 | `net_forces_w` (37体) | 0 | 100% | 无 |
| 6 | G1 关节力矩 | `applied_torque` (29D) | 0 | 100% | 无 |
| 7 | G1 FK 精确定位 | `body_link_pos_w` (37体) | 0 | 100% | 无 |
| 8 | G1 步态相位 | `current_air_time` | 0 | 100% | 无 |
| 9 | G1 头部相机 | 头部 RGB (320×240) | 0 | 100% | 新增 camera prim |
| 10 | G1 头部 LiDAR | 头部 3D 点云 (14400 rays) | 0 | 100% | 新增 ray_caster prim |

### 最优组合：三层混合架构

```
Layer 3 (探索层, ~0.25 Hz):
  方案 3 (VLM全局) + 方案 9 (G1头部相机) — 可选

Layer 2 (战术层, 50 Hz):
  方案 1 (UR10e状态机卡点)
  + 方案 7 (FK距离闭环)
  + 方案 10 (LiDAR 3D空间感知)
  + 方案 6 (关节力矩验证)

Layer 1 (安全/反馈层, 200 Hz):
  方案 5 (全身接触力边界)
  + 方案 8 (步态相位同步)
  + 方案 4 (压力垫事件记录)
```

### 距离门控调速（实际实现，2026-07）

> ⚠️ 本文档早期版本描述了概率状态机 (WANDER↔APPROACH_ARM→RETREAT)，
> 但实际实现采用了更简单可靠的**距离门控调速**方案。以下为实际行为。

G1 在桌面区域工作空间内，按距离自动切换三档行为：

- **空间约束**：G1 root 坐标限制在 `x∈[0.0, 0.8]`, `y∈[-0.5, 0.5]`（桌子前方 0.8m×1m 区域）。接近边界时产生恢复偏置
- **AGGRESSIVE (>0.30m)**：全速随机游走。速度由确定性 schedule 生成（`RandomState(42)`），vx∈[-0.16, 0.16] m/s。**vy 恒为 0**——G1 行走策略仅训练前向运动，横向运动会 destabilize 机器人
- **MODERATE (0.15-0.30m)**：降速至 AGGRESSIVE 的 50%，叠加远离 UR10e 的 30% 偏置转向
- **CAUTIOUS (<0.15m)**：触发撤退。撤退速度按距离紧急度线性斜坡：0.20 m/s（阈边界）→ 0.50 m/s（0.05m 以内）
- **卡住检测**：命令速度 >0.10 m/s 但实际速度 <0.02 m/s 持续 100 步 → 接触力方向撤退 80 步（fallback: 随机方向）
- **撤退/卡住期间跳过边界偏置**：避免将 G1 推回 UR10e 方向造成振荡

### G1 传感器安装体（USD 已验证）

| USD Body | 真实传感器 | 可挂载功能 prim |
|----------|-----------|---------------|
| `Bd435` | Intel RealSense D435 深度相机 | `TiledCamera` → RGB |
| `bmid360` | Livox MID-360 LiDAR | `RayCaster` → 3D 点云 |
| `Bhead` | 头部刚体 | 相机/LiDAR 的父级 frame |
| `2imu` | BMI055 IMU | 读 `body_com_acc_w` |

---

## 安全层适配

核心思路：**最小侵入**。GMRobot 的 RuleEngine / EnvelopeEvaluator / SafetyGate 完全不动。

`G1EnvelopeAdapter` 将 G1 身体部件的 FK 位置映射到 `SafetyState.human_hand_pos`。

- **TRACKED_BODIES** (8 体, 日志/监控用): 头、躯干、双肩、双肘、双手腕
- **SAFETY_BODIES** (3 体, 安全门用): 头 + 双手腕。W3 fix (2026-07-10) — 躯干/肩膀/肘部的大半径会过早触发 SLOW_DOWN，已从安全门候选中排除
- 取距离 UR10e EE **最近**的 SAFETY_BODY 作为 `human_hand_pos`
- 距离计算为**表面距** (中心距 - 身体半径 - EE半径)，而非中心距
- 现有阈值（hard_stop=0.13m, warn=0.16m）直接生效

---

## 测试指标

### GMRobot 原有（保留不变）

UR10e EE 状态、关节状态、安全门决策、20 零件追踪、安全日志 CSV

### 新增 8 组变量（详见 `docs/VARIABLES.md`）

| 组 | 内容 | 数量 |
|----|------|------|
| A — G1 运动状态 | root/head/hands/feet 的 FK 位置+速度（替代 kinematic hand/torso） | ~20 |
| B — G1 扰动行为 | 扰动阶段、速度命令、手臂目标、摔倒标志 | ~10 |
| C — 接触/交互事件 | 37 体接触力、接触部件、UR10e 最近距离 | ~10 |
| D — 扰动效果 | 扰动生效步数、击落零件数、效果延迟 | ~6 |
| E — 压力垫事件 | 事件类型、位置、力值、面积 | ~8 |
| F — 安全响应增强 | 触发源、延迟步数、最近 G1 部件 | ~6 |
| G — Episode 汇总 | 结局、总扰动次数、成功率、综合指标 | ~12 |
| H — VLM 决策日志（可选） | VLM 输出 JSON、延迟、决策效果 | ~6 |

---

## 实施阶段

| Phase | 目标 | 状态 | 关键产出 |
|-------|------|------|---------|
| 1 | 场景组装 | ✅ 完成 | `dual_env_cfg.py` |
| 2 | G1 行走控制 + UR10e 拾放 | ✅ 完成 | `g1_walk_controller.py`, `ur10e_controller.py`, `run_phase2.py` |
| 3 | 扰动注入 + 安全层集成 | ✅ 完成 | `g1_disturbance_controller.py`, `safety_adapter.py`, `run_phase3.py` |
| 3.1 | 卡住检测 + 脚本化场景 | ✅ 完成 | 速度误差检测, 接触力撤退, `arm_collision`, `arm_wave` |
| 4 | 手臂控制 + 虚拟手 | ✅ 完成 | `g1_arm_controller.py` (物理手臂受行走策略限制不启用), `g1_virtual_hand.py` (虚拟手替代) |
| 5 | 场景批量执行 + 弱点验证 | ✅ 完成 | [phase5-batch-results.md](findings/phase5-batch-results.md) (2026-07-11) — 4 场景对比, F1-F4 发现 |
| 5R | 重规划集成 (--replan) | ✅ 完成 | `GeometryReplanV0`, `L1WarnReplanTrigger`, `--replan` CLI flag, `_get_replan_imports` loader — 已随 Phase 5 验证通过 |
| 6 | VLM 引导 + 主动感知 | ✅ 完成 | `g1_vlm_client.py` (VLM 管线端到端跑通), 头部相机已集成 |
| 7 | 批量回归 + CI 集成 | ✅ 完成 | `batch_runner.py` (2026-07-11) |

> **注 1**: Phase 4 的 G1ArmController 受行走策略限制（0121_walk.pt 未训练手臂运动），物理手臂运动会破坏平衡。当前用 `--virtual-hand` 模式进行安全门测试。

### 未完工清单（2026-07-11 审计，同日全部修复）

| # | 模块 | 缺失项 | 位置 | 状态 |
|---|------|--------|------|------|
| D | 扰动效果指标 | `d_stop_caused`/`d_slow_caused`/`d_replan_caused`/`d_knock_off` | `test_metrics.py:38-41` | ✅ **已修复** |
| H | VLM 决策日志 | H01-H14 变量 → metrics 接线 | `VARIABLES.md §H` | ✅ **已修复** |
| F | 安全响应 F07-F09 | replan 成功/失败/连续 STOP | `VARIABLES.md §F` | ✅ **已修复** |
| G | Episode 汇总 | JSON 输出 | `VARIABLES.md §G` | ✅ **已修复** |
| B7 | batch_runner | `batch_runner.py` 类 | `INTERFACES.md:24` | ✅ **已修复** |
| M2 | MatEvent part_id | 掉落物体 → 最近邻零件匹配 | `mat_event_detector.py:49` | ✅ **已修复** |
| A8 | ARM_JOINT_INDICES | 运行时校验 | `g1_arm_controller.py:23` | ✅ **已修复** |

**全部 13 个未完工项已清零。** 仅 Phase 5（批量场景执行）属运维性质，代码已就绪可直接挂机跑。

---

## 技术风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| G1 摔倒（盲走+桌子碰撞） | 🔴 | 安全距离 35cm；低速 bump (0.3 m/s)；摔倒=有效结果 |
| UR10e 时间线 livelock（反复 STOP） | 🔴 | episode 超时 20000 步；记录 livelock 指标；安全门冷却 |
| Isaac Lab 版本 (1.3 vs 2.3) | 🔴 | 必须用 1.3.0 环境 |
| G1 手臂扭矩不足 | 🟡 | 变体配置提升刚度至 150 |
| 触觉图像信号重叠 | 🟡 | 空间分离 + 时间差分 |
| VRAM | 🟢 | 单 env ~1GB |
| USD 命名冲突 | 🟢 | 不同 prim path |

---

## 扰动策略

> ⚠️ 早期设计文档描述了三种"逐步增加智能"的策略（纯随机 / 有偏随机 / VLM引导）。
> 实际实现了不同的三档方案。以下为实际可用模式。

### 模式 1：距离门控随机游走【默认 — `constrained_wander`】

```
每步:
    dist = ‖ G1_root_xy − UR10e_ee_xy ‖
    
    if   dist > 0.30:  mode = AGGRESSIVE  → 全速随机, 确定性 schedule
    elif dist > 0.15:  mode = MODERATE    → 半速 + 30% 偏置远离 UR10e
    else:              mode = CAUTIOUS    → 按紧急度撤退 (0.20→0.50 m/s)
    
    + 边界弹簧力 (workspace x∈[0,0.8], y∈[-0.5,0.5])
    + 卡住检测 (100 步无位移 → 接触力方向撤退)
```

- 随机游走为确定性 schedule（`RandomState(42)`, 10000 步预生成）
- **vy 恒为 0**：行走策略 (0121_walk.pt) 仅训练前向运动，横向运动会 destabilize
- 效率：中等（G1 主要在 x 轴中线上运动，需较长时间偶然接近 UR10e）
- 覆盖面：中等（y=0 中线覆盖，容器 A/B 分别在 y=-0.25/+0.25，需边界偏置才能偶尔偏转）
- 配置：5 个距离/速度参数

### 模式 2：脚本化场景【`--scenario arm_collision | arm_wave`】

预编程的速度时间线，用于可复现的安全门压力测试。

- `arm_collision`：冲刺穿越 UR10e 工作空间 → 验证 STOP 响应
- `arm_wave`：靠近 + 挥手 + 撤退 → 验证动态障碍物检测

`table_bump`、`object_push`、`circulate`、`combined` 场景的 phases 已定义
但**尚无 CLI 执行路径**（依赖物理手臂控制或 CLI 接线）——代码中以 `🔲 Planned` 标记。

### 模式 3：VLM 引导【`--vlm`】

```
每 4 秒 (200 步 @ 50Hz):
    G1 头部相机 (D435, 320×240 RGB) → VLM 服务 → 决策 JSON
    → 速度命令 (vx, vy, wz) + 手臂动作
```

- 实现位于 `g1_vlm_client.py`（非 `g1_vlm_disturbance.py`）
- 效率：高（VLM 自适应选择攻击角度）
- 覆盖面：高
- 延迟：~1-2 秒 per 决策

### 推荐开发路径
1. 日常回归：距离门控随机游走（默认模式）
2. 安全门边界测试：脚本化场景 (`arm_collision`, `arm_wave`)
3. 弱点发现：VLM 引导
4. 固化为脚本 → A/B 对比

---

## MatEventDetector 分类算法详述

### 步骤 1：连通分量检测
```python
img = tactile_image[0].cpu().numpy()  # (32, 32)
binary = img > 5.0  # Newton threshold
clusters = scipy.ndimage.label(binary)
# 每个 cluster → {mask, centroid(row,col), total_force(sum), area(count)}
```

### 步骤 2：空间分类
```
对每个 cluster:
    world_xy = taxel_to_world(centroid_row, centroid_col)
    
    if dist(world_xy, g1_left_foot_pos) < 0.3:
        → "footstep_left"
    elif dist(world_xy, g1_right_foot_pos) < 0.3:
        → "footstep_right"
    elif force > 50 and 0.3 < world_xy[0] < 1.0:
        → "collision_impact"
    else:
        → "unknown"
```

### 步骤 3：瞬态检测（物体掉落）
```python
diff = current_img - previous_img
transient_clusters = label(diff > 10.0)
# 小面积（≤4 taxels）、高力（>10N）、在工作区（x∈[0.3,1.0], y∈[-0.5,0.5]）
for c in transient_clusters:
    if c.area <= 4 and c.total_force > 10 and 0.3 < c.world_x < 1.0:
        → "object_drop"
        # 🔲 零件匹配待实现:
        # part_id = argmin(dist(c.world_xy, part_positions))
```

### taxel → 世界坐标转换
```
pitch_x = MAT_SIZE_X / COLS = 4.0 / 32 = 0.125 m
pitch_y = MAT_SIZE_Y / ROWS = 4.0 / 32 = 0.125 m
world_x = (col - COLS/2) * pitch_x  # col 0 → -2.0m, col 31 → +1.875m
world_y = (row - ROWS/2) * pitch_y
```

---

## 关键依赖文件清单

| 用途 | 文件路径 | 导入方式 |
|------|----------|---------|
| G1 机器人 ArticulationCfg | `pressure_mat_deploy/robot_cfg.py::G1_927_WALK_CFG` | `from pressure_mat_deploy.robot_cfg import G1_927_WALK_CFG` |
| G1 行走 MDP 观察 | `pressure_mat_deploy/mdp/observations.py::tactile_force_multi_net` | `from pressure_mat_deploy.mdp.observations import tactile_force_multi_net` |
| G1 行走 MDP 动作 | `pressure_mat_deploy/mdp/walk_action.py::WalkJointActionCfg` | `from pressure_mat_deploy.mdp.walk_action import WalkJointActionCfg` |
| 压力垫 USD (32×32) | `pressure_mat_deploy/data/tactile_mat_32x32_4m.usd` | 文件路径 |
| G1 USD | `pressure_mat_deploy/data/g1_29dof_modified_new_91.usd` | 文件路径 |
| G1 行走策略 | `policy/0121_walk.pt` | `torch.jit.load()` |
| UR10e ArticulationCfg | `gmrobot/gmrobot_env_cfg.py::UR10E_CFG` | `from gmrobot.gmrobot_env_cfg import UR10E_CFG` |
| 容器/零件 USD 路径 | `gmrobot/gmrobot_env_cfg.py::{CONTAINER_USD,PART_USD}` | `from gmrobot.gmrobot_env_cfg import CONTAINER_USD, PART_USD` |
| UR10e 状态机 | `GMRobot/scripts/pick_and_place_policy.py::SingleEnvPickAndPlacePolicy` | `from pick_and_place_policy import SingleEnvPickAndPlacePolicy` |
| 安全层 RuleEngine | `GMRobot/safety/rule_engine.py::RuleEngine` | 通过 `safety_adapter.py` 间接使用 |
| 安全层 SafetyGate | `GMRobot/safety/gate.py::SafetyGate` | 通过 `safety_adapter.py` 间接使用 |
| 安全层 EnvelopeEvaluator | `GMRobot/safety/envelope.py::EnvelopeEvaluator` | 通过 `safety_adapter.py` 间接使用 |
| 安全层 SafetyState | `GMRobot/safety/types.py::SafetyState` | 通过 `safety_adapter.py` 间接使用 |
| 安全层 SafetyConfig | `GMRobot/safety/config.py::SafetyConfig` | 通过 `safety_adapter.py` 间接使用 |
| VLM 客户端 | `GMRobot/vlm/client.py::VLMClient` | `from GMRobot.vlm.client import VLMClient` |
| 安全配置 YAML | `GMRobot/configs/safety_fusion.yaml` | 文件路径 |

---

## 验证方案

## 测试策略：每阶段必须验证，不能等最后

**核心原则：Phase N 的测试不过，Phase N+1 不开始。**

原因：Phase 1（场景组装）是整个项目的基础——两个 articulation 共存、body name 列表、contact sensor shape 等。如果这些在 Phase 1 不验证，Phase 4 发现不匹配，所有依赖 FK 和 contact forces 的代码都得改。

### 每阶段测试清单

| Phase | 测试脚本 | 核心验证项 | 通过标准 |
|-------|---------|-----------|---------|
| 1 | `smoke_test_dual.py` | 场景加载、body_names、contact_forces shape | 无崩溃；`net_forces_w.shape==(1,37,3)`；两机器人不穿透 |
| 2 | `test_g1_walk.py` | G1 行走策略推理 | root_pos 向前移动；`obs["g1_walker"].shape==(1,588)`；`g1_action.shape==(1,12)` |
| 3 | `test_ur10e_sequence.py` | 20 零件完整拾放 | 4000 步无崩；20 零件全部完成 |
| 4 | `test_scenarios.py` | 每个扰动场景 | 时间线匹配（开环）/ 不出 workspace（随机）/ JSON 格式（VLM） |
| 5 | `test_safety_gate.py` | 安全门触发 | dist<0.13m→STOP；dist<0.16m→SLOW_DOWN |
| 6 | `test_mat_events.py` | 垫事件分类 | 交叉验证准确率 >90% |
| 7 | `batch_runner.py` | 批量测试 | 无超时/崩溃；汇总 JSON 产出 |

### Phase 1 特别验证清单

Phase 1 决定了后续所有工作的基础。以下必须打印验证：

```
□ robot_g1.body_names → 确认 37 个 body link 名称
□ robot_ur10e.body_names → 确认 UR10e body 名称  
□ robot_g1.joint_names → 确认 29 个关节名称
□ g1_contact_forces.data.net_forces_w.shape → 必须是 (N, 16, 3)
□ 两个 articulation 不互相穿透 → 物理稳定
□ 压力垫 taxel filter → ContactSensor 无路径警告
```

### Phase 1 验证

**注意：以下内容属于测试策略范畴，在 Phase 实施时执行。**
```
smoke_test_dual.py:
1. 加载 G1-UR10e-Disturbance-v0
2. 打印 robot_g1.body_names → 验证 37 个 body link 名称
3. 打印 robot_ur10e.body_names → 验证 UR10e body 名称
4. 运行 100 步空动作（两个机器人都输出 default action）
5. 验证: 无崩溃、两个 articulation 都有 joint_pos 更新
6. 验证: contact_forces.data.net_forces_w.shape == (1, 16, 3)
```

### Phase 2 验证
```
1. G1 加载 0121_walk.pt 策略
2. 注入 vx=0.5 速度命令，运行 200 步
3. 验证: G1 root_pos 从 (-1.5,0) 向前移动
4. 验证: obs["tactile"] 显示脚步力聚类
5. 验证: obs["g1_walker"].shape == (1, 588)
6. 验证: g1_action.shape == (1, 12)
```

### Phase 3 验证
```
1. UR10e 运行完整 20 零件拾放序列
2. G1 静止在 (-1.5, 0)
3. 验证: 全部 20 零件无干扰完成
4. 验证: obs["ur10e_policy"] key 映射正确
5. 验证: ur10e_action.shape == (8,)
```

### Phase 4 验证
```
1. 逐个场景运行（table_bump, arm_wave, object_push, arm_collision, circulate, combined）
2. 录视频确认 G1 行为
3. 开环模式: 验证速度命令时间线精确匹配
4. 约束随机模式: 运行 5 分钟，验证 G1 不走出 workspace
5. VLM 模式: 运行 5 分钟，验证 VLM JSON 格式正确
```

### Phase 5 验证
```
1. G1 走向 UR10e → 验证距离 <0.13m 时触发 STOP
2. G1 挥手靠近 → 验证距离 <0.16m 时触发 SLOW_DOWN
3. G1 碰撞 UR10e → 验证 GateResult.g_t == STOP, reason 含 "static"
4. 安全日志 CSV → 验证 g1_closest_body_to_ee 字段正确
```

### Phase 6 验证
```
1. 预录已知事件（手动标注脚步、掉落）
2. 运行 MatEventDetector
3. 交叉验证: 分类准确率 >90%
4. 瞬态检测: 掉落事件延迟 <5 步
```

### Phase 7 端到端测试
```bash
./isaaclab.sh -p scripts/run_disturbance_test.py \
    --task G1-UR10e-Disturbance-v0 \
    --mode constrained_wander \
    --safety_config configs/safety_fusion.yaml \
    --num_steps 10000 \
    --output results/

./isaaclab.sh -p scripts/run_disturbance_test.py \
    --batch batch_test_configs/ \
    --output results/
```

---

## 布局架构 (2026-07-05 最终版)

### 坐标系

采用 GMRobot 原生坐标系：除地面外的所有元素位于 z=0，地面和压力垫下移到 z=-1.05。

```
世界坐标系 (Isaac Sim):
  z=0      — UR10e, 桌子, 容器, 零件 (GMRobot 原生)
  z=-1.05  — 地平面, 压力垫
  z=-0.25  — G1 root (垫子上方 0.8m)

  UR10e base:         (0.000, 0.000, 0.000)
  SeattleLabTable:    (0.600, 0.000, 0.000)   rot=90°绕z
  Container A (满):   (0.750, -0.250, 0.000)
  Container B (空):   (0.750, 0.250, 0.000)
  G1 root:            (-1.500, 0.000, -0.250)

  UR10e → 桌子距离:   0.6m
  UR10e → 容器A距离:  ~0.79m (可达范围内)
```

### UR10e 配置

直接使用 GMRobot 原版 `UR10E_CFG` (via `vendored/ur10e_cfg.py`).
`ImplicitActuatorCfg` 忽略 `init_state.pos`——UR10e USD 文件内置 root 偏移
(-1.08, 2.35, 0) 会被 `_fix_ur10e_position` 事件通过 `write_root_state_to_sim`
修正到 (0, 0, 0)。

### 关键设计决策

| 决策 | 结论 | 原因 |
|------|------|------|
| 执行器类型 | ImplicitActuatorCfg | IdealPDActuatorCfg 会破坏 FK 链路 |
| UR10e z | 0 (GMRobot 原生) | 非零 z 会导致 IK 发散 |
| root 位置修正 | write_root_state_to_sim | init_state.pos 被 ImplicitActuatorCfg 忽略 |
| 地面位置 | z=-1.05 | 复制 GMRobot 布局，桌面高于视口网格 |
| G1 位置 | z=-0.25 | 地面 -1.05 + 行走高度 0.8 |
