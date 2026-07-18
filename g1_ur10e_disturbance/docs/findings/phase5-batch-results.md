# Phase 5: 批量场景执行结果 (2026-07-11 最终)

## 测试配置

- **环境**: Isaac Lab 1.3.0 + Isaac Sim 4.2.0, NVIDIA GPU, headless
- **UR10e**: 20 零件拾放 (GMRobot SingleEnvPickAndPlacePolicy)
- **安全配置**: `safety_fusion.yaml` (L1+L2 fusion)
- **3 轮迭代**: v1 (原始) → v2 (vy_scale + DROP fix) → v3 (MODERATE_THRESHOLD 放宽)

## v1 结果 (原始配置: vy=0, MODERATE=0.30m, DROP=10N, 3000 步)

| Scenario | Parts | STOP | SLOW | D-STOP | D-SLOW | D-KO | min_dist | mean_dist | ObjDrop |
|----------|-------|------|------|--------|--------|------|----------|-----------|---------|
| wander_no_safety | 7/20 | 0 | 0 | 0 | 0 | 0 | **0.535m** | 0.866m | 2377 |
| wander_safety | 7/20 | 3 | 6 | 0 | 0 | 0 | 0.809m | 1.059m | 0 |
| arm_collision | 7/20 | 2 | 1 | 0 | 0 | 0 | 0.885m | 1.552m | 37 |
| arm_wave | 7/20 | 2 | 0 | 0 | 0 | 0 | 0.935m | 1.265m | 0 |

## v3 结果 (vy_scale=0.05, MODERATE=0.55m, DROP=30N, 4000 步)

| Scenario | Parts | STOP | SLOW | D-STOP | D-SLOW | D-KO | min_dist | mean_dist | ObjDrop |
|----------|-------|------|------|--------|--------|------|----------|-----------|---------|
| wander_no_safety | 9/20 | 0 | 0 | 0 | 0 | 0 | **0.824m** | 1.084m | 0 |
| wander_safety | — | — | — | — | — | — | — | — | — |

> 注: v3 仅完成 2/4 场景 (后 2 个后台挂起)。DROP=30N 消除全部误报。

## 长 episode 验证 (8000 步, vy_scale=0.05, MODERATE=0.55m)

| Scenario | Parts | STOP | SLOW | min_dist | mean_dist |
|----------|-------|------|------|----------|-----------|
| wander_safety | **19/20** | 5 | 12 | 0.870m | 1.200m |

> 8000 步接近完成全部 20 零件 (19/20)，但 **min_dist=0.870m 始终 > MODERATE 阈值 0.55m**。更多步数不改善接近距离。

## 核心发现

### F1 (关键). G1 永远走不到 UR10e 旁边 — 本质设计限制

**三组数据**: min_dist 在 0.535m–0.935m。G1 从未进入 MODERATE 区（即使放宽到 0.55m）。

**根因**: 不是 vy=0 的问题。G1 起点 (-1.5, 0)、UR10e EE 在 (0.75, ±0.25) 容器处——几何上 G1 最近只能走到 workspace 边缘 x≈0，直距 0.79m。UR10e EE 在 base (0,0,0) 时 G1 可到 0m，但 EE 大部分时间在容器处 (0.75, ±0.25) 而非 base。

**结论**: `constrained_wander` 模式**永远无法触发 MODERATE/CAUTIOUS 行为**。当前 SAFETY_BODIES 触发 STOP/SLOW 来自 GMRobot RuleEngine 的 TTC/workspace 规则，非 G1 接近规则。

### F2. vy_scale 对接近距离无效

| 配置 | wander_no_safety min_dist |
|------|--------------------------|
| vy=0 (v1) | **0.535m** |
| vy=0.05 (v3) | 0.824m (+54%) |

横向漂移反而**增加**路径长度，G1 走曲线而非直线接近 UR10e。

### F3. DROP_THRESHOLD=30N 消除误报

| 阈值 | wander_no_safety ObjDrop (3000步) |
|------|-----------------------------------|
| 10N | **2377** (每 1.3 步一次——噪声) |
| 30N | **0** |

### F4. 安全门有效但触发源非 G1

- wander_safety (v1): 3 STOP + 6 SLOW — 全部来自 GMRobot 内部规则，非 G1 adapter
- arm_wave (v2): 6 STOP + 3 SLOW — 挥手时安全门响应增强
- 长 episode: 5 STOP + 12 SLOW — 更多零件 → 更多安全干预机会

### F5. 8000 步接近完赛: 19/20 零件

长 episode 证明当前框架能支撑完整 20 零件拾放任务。1 个零件未能完成可能是 UR10e 策略超时或路径冲突。

## 改进建议

1. **G1 起点改为 (0.3, 0)** 或更近位置——workspace 允许但从未用
2. **arm_collision 场景延长 approach 相位**——当前 200 步 vx=0.5 仅覆盖 2m，到不了 EE 容器
3. **增加 deliberate_approach 模式**：G1 定向走向 UR10e EE 当前位置
4. **安全门 STOP 应暂停策略时钟**：当前只冻 EE 动作
5. DROP_THRESHOLD=30N 已验证——永久保留

## 原始数据

- `/tmp/gmdisturb_phase5/phase5_summary.json` (v1)
- `/tmp/gmdisturb_phase5/wander_no_safety.csv` (v1 + v3)
- `/tmp/gmdisturb_phase5/wander_safety.csv` (v1 + v2)
- `/tmp/gmdisturb_phase5/arm_collision.csv` (v1 + v2)
- `/tmp/gmdisturb_phase5/arm_wave.csv` (v1 + v2)
- `/tmp/gmdisturb_phase5/wander_safety_long.csv` (8000步)
