# 编程 Agent 指令：B2 动态横扫 + B4-Dynamic 同轨迹 Shadow 对照

> 日期：2026-07-20  
> 任务性质：下一轮单一纵向切片  
> 前置状态：M0 完成；B0/B1 三 seeds 最终门禁已通过  
> 禁止范围：G1 真实手臂、PPE/工具、B3、PPO、最终论文批量实验

## 1. 任务目标

实现一个可重复、按 UR10e 语义阶段触发的动态侧向横扫代理场景 B2，并实现使用完全相同扰动定义、但不执行在线安全动作的 B4-Dynamic shadow 对照。该对照只是 B4 中与 B2 配对的动态单元；B1/B3 各自的 B4 配对不在本轮范围内，因此本轮成功也不能把完整 B4 标记为完成。

本切片必须证明：

1. 动态代理在进入 hard-stop 区之前产生可审计的 TTC、预测或 dynamic 风险；
2. B2 的安全系统在 hard-stop 前触发并成功应用 replan；
3. replan 后代理撤离、任务继续且不掉件；
4. B4-Dynamic 保留同一套风险计算和 shadow 决策日志，但不修改 UR10e 动作；
5. B2/B4-Dynamic 的扰动配置、seed 和介入前轨迹前缀可以证明一致。

不要把 B1 的 `held_critical STOP` 改名为 B2，也不要通过扩大 `safe_dist_warn`、手臂长度或代理半径伪造提前量。

## 2. 开工前必须完成的只读检查

先阅读：

- `docs/cross-project/paper-demo-implementation-plan-2026-07-18.md`；
- `docs/cross-project/paper-demo-status-2026-07-20.md`；
- `scenarios.py`、`protocol_vhand.py`、`g1_virtual_hand.py`；
- `scripts/run_phase3.py` 中 scenario hand、动态 warn、replan 和事件记录路径；
- `batch_runner.py` 的 schema 校验与场景 verdict；
- GMRobot `safety/replan/triggers.py` 的 TTC/forecast 分支。

提交代码前先报告：复用路径、必须新增的状态、预计修改文件和不修改的模块。不要先大改 `run_phase3.py`。

## 3. 不可破坏的冻结基线

以下内容视为冻结：

- `paper_scenarios_b0b1/baseline_safe.yaml`；
- `paper_scenarios_b0b1/static_occupancy_proxy.yaml`；
- B0/B1 的安全阈值、spawn、reach/proxy radius；
- `results_paper_final_0320/final_six_ordered/` 全部原始结果；
- B1 的 held-critical 接线和 attempt/recovery 语义；
- 镜像 `sha256:0320fd6e…` 仅作为 B0/B1 证据，不得用新代码覆盖其历史含义。

新改动必须保证现有离线测试继续通过。不得删除任何 `(1)` 备份或旧失败样本。

## 4. B2 场景合同

新增：

```text
paper_scenarios/dynamic_lateral_sweep_proxy.yaml
```

建议另建独立的动态协议类/模块，避免继续把时间线和状态塞入 `run_phase3.py`。允许复用 `ScenarioHand`，但必须扩展为语义阶段驱动，不能只依赖全局秒数。

### 4.1 触发与轨迹

- 仅在 `protocol_phase == TRANSIT` 时启动 attempt；
- 每个 attempt 具有明确 `start_xyz`、`end_xyz`、速度、持续步数和 sweep direction；
- 横扫方向应穿过 UR10e 的未来 transit corridor，而不是追踪当前 EE 后固定保持距离；
- 初始距离必须大于 `safe_dist_hard_stop_active`；
- 代理速度必须由真实位置差分产生并传入 SafetyState，不能在动态场景中继续写零速度；
- 位置、速度和 attempt 生命周期由同一 seed 决定；
- replan applied 后代理进入可审计 retreat；下一次 TRANSIT 才能产生新 attempt；
- 不允许代理产生 PhysX 接触，`proxy_physical_contact_count` 必须为 0。

### 4.2 主动性判定

至少一次有效 B2 事件必须同时满足：

```text
protocol_phase == TRANSIT
gate_at_trigger == SLOW_DOWN
dist_min_for_gating_at_trigger > safe_dist_hard_stop_active
trigger_rule in {ttc, ttc_forecast, dynamic, dynamic_warn}
replan_applied == true
trigger_to_apply_latency_steps >= 0
ttc_at_trigger > 0 或 time_to_risk_steps > 0
```

如果 GMRobot 使用的规范 trigger rule 名称不同，可以保留现有名称，但必须在测试和文档中说明映射。不得把 `held_critical` 计入 B2 的 proactive 成功数。

### 4.3 B2 恢复门

- `trigger → applied → retreat → redeploy` 按 attempt 配对；
- 至少一次 `progress_after_retreat=True`；
- mini 任务完成；最终 20-part 验证也必须完成；
- `d_knock_off=0` 为目标，任何非零值必须报告并停止扩大批次；
- `g1_fell=False`；
- 无 livelock；
- 真实 collision 统计不得清零，代理物理接触单独保持 0。

## 5. B4-Dynamic Shadow/No-enforcement 合同

新增与 B2 共用扰动定义的配置，例如：

```text
paper_scenarios/dynamic_lateral_sweep_proxy_shadow.yaml
```

不要直接使用当前会完全绕过安全评估的 `--no-safety` 语义。实现明确的 enforcement mode，建议：

```text
active  = 评估 + 执行门控/replan
shadow  = 评估 + 记录假想门控/replan，但原样执行 UR10e 动作
off     = 不评估，仅用于调试
```

要求：

- B4-Dynamic 使用与 B2 相同场景定义、seed、sweep 参数和随机流；
- 记录 `safety_enforcement_mode`；
- 区分 `shadow_gate_decision`、`shadow_replan_would_trigger` 与实际 applied；
- shadow 下 `d_stop_caused/d_slow_caused/d_replan_caused` 的“实际执行计数”必须为 0；
- 另设 `shadow_*` 计数，不能把 shadow 决策冒充实际干预；
- 保存 `disturbance_trajectory_id`，其来源应是规范化场景参数 + seed 的稳定 hash；
- B2/B4-Dynamic 在首个 B2 干预之前的 commanded proxy trajectory 必须逐步一致，增加自动比较测试；
- B4-Dynamic 不要求故意制造真实碰撞，但必须报告最小距离、shadow 风险和任务/掉件结果，禁止预设结论。

## 6. 必需的日志与指标

在现有 writer、reader、manifest、事件和测试中同步增加或确认：

- `safety_enforcement_mode`；
- `disturbance_trajectory_id`；
- `sweep_attempt_id`、`sweep_progress`、`sweep_velocity_xyz`；
- `dist_min_for_gating`、`dist_min_envelope`、`dist_min_held`；
- `safe_dist_hard_stop_active`、`safe_dist_warn_active`；
- `ttc_at_trigger` 或规范等价字段；
- `time_to_risk_steps`（若可用）；
- `pre_hard_stop_replan_count`；
- `shadow_gate_decision`、`shadow_replan_would_trigger`；
- actual 与 shadow 的 STOP/SLOW/replan attempt 计数；
- trigger→apply latency 和首次干预提前量。

不得用 forward-fill 伪造事件持续时间。事件字段为空时必须清除旧值。

## 7. Batch verdict

在 `batch_runner.py` 中新增独立 B2/B4-Dynamic verdict，不得复用只检查“有任意 STOP/SLOW”的 B1 判定。

B2 PASS 至少要求：

- 任务完成；
- `pre_hard_stop_replan_count >= 1`；
- 至少一个非 held-critical 的动态/TTC replan；
- 完整恢复链；
- `progress_after_retreat=True`；
- 无未配对 event；
- 无 G1 fall、无代理物理接触、无 Traceback/schema 错误。

B4-Dynamic PASS 表示“动态对照执行有效”，不是“完整 B4 已完成”或“系统更安全”，至少要求：

- shadow 评估实际运行；
- shadow 至少识别一次与 B2 同源的风险；
- actual applied STOP/SLOW/replan 为 0；
- 轨迹 ID 与对应 B2 相同；
- 子进程和 schema 有效；
- 结果无论任务成功或失败都必须保留，不能用任务失败自动删除对照。

## 8. 单元与集成测试

至少新增以下测试：

1. 动态 sweep 仅在 TRANSIT 边沿启动；
2. 同 seed 轨迹 bit-identical，不同 seed 的允许变化受配置控制；
3. 非零 hand velocity 与位置差分一致；
4. attempt 只在 inactive→active 递增；
5. retreat/redeploy 不重复计数；
6. held-critical 不计入 B2 proactive 指标；
7. hard-stop 后触发不计入 `pre_hard_stop_replan_count`；
8. active/shadow 共用 trajectory ID 和干预前轨迹；
9. shadow 决策不修改 UR10e action/clock；
10. shadow 事件不进入 actual attribution；
11. B2/B4-Dynamic verdict 正反例；
12. 新字段 writer/reader/schema 一致。

原有 P0、B1 attribution、protocol、seed、spawn、reach/proxy 和 batch runner 测试必须全部通过。

## 9. 仿真验证顺序

严格按以下顺序执行，前一步失败不得扩大运行：

```text
离线单测
→ 新镜像 build + image ID 记录
→ scene smoke
→ B2 1-attempt/1-part seed42
→ B2/B4-Dynamic 配对 mini seed42
→ B2 8-part seed42
→ B2/B4-Dynamic 各 3 seeds
```

本轮禁止直接跑 5-seed 最终消融。每个 episode 使用独立新容器，避免连续重启 Isaac 的 CUDA 上下文问题。

## 10. 停止条件

出现以下任一情况立即停止并报告，不得靠继续调阈值掩盖：

- 只能在 hard-stop 后触发；
- 只能通过抬高 `safe_dist_warn` 或扩大 proxy radius 触发；
- hand velocity 与轨迹不一致；
- B2/B4-Dynamic 的 seed 或轨迹前缀不一致；
- shadow 模式实际改变了 UR10e action；
- 任务卡死、掉件、G1 倾倒或事件无法配对；
- 新镜像无法复现 mini；
- 需要修改冻结的 B0/B1 配置或结果。

若预测/TTC 路径本身缺少必要数据，先报告最小接口缺口和两个备选方案，由用户审批后再扩展 GMRobot 核心。

## 11. 交付格式

完成后只提交：

1. 改动文件清单；
2. 设计语义和实际 trigger rule 映射；
3. 离线测试命令与计数；
4. 镜像完整 SHA；
5. B2/B4-Dynamic 配对结果表；
6. 轨迹一致性证据；
7. proactive 提前量、事件配对、任务和掉件指标；
8. 所有失败样本与未解决问题；
9. 明确说明 B2 是否完成、B4-Dynamic 配对单元是否完成；不得把完整 B4 或 M1 标记为完成。

不得写“项目完成”；本任务成功后最多声明“B2 与 B4-Dynamic 配对单元完成”。
