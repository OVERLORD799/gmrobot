# GM-SafePick Layer 1：规则安全层

> **跨层进度看板**：[GM-SafePick_项目进展与遗留问题.md](./GM-SafePick_项目进展与遗留问题.md)（Phase 状态、遗留问题、Isaac run ID 汇总）
>
> **定位**：安全推理系统的第一道防线，永远在线，提供 **50 Hz** 实时安全门控（`control_dt = 0.02 s`）
> **设计原则**：简单、可预测、可量化、可扩展
> **面向**：AI 阅读者与实现者
> **最后更新**：2026-06-17（**Phase 1 ✅** + Isaac 回归 `192734`/`193244`/`193713`：GT v1.1、双阈值、gt_branches 列、离线指标）

---

## 待办与进度（Layer 1）

> 本节为 **Layer 1 唯一进度看板**，与代码库同步维护。不含 Layer 2/3。  
> 单元测试 T1/T8 已通过（6 + 3 项）；仿真验收 T2–T7 见下表。

### 未完成事项

| 优先级 | 事项 | 说明 |
|:------:|------|------|
| ~~P0~~ | ~~**修复后 Isaac 回归（T7）**~~ | ✅ 短跑 [`20260617_141625`](../../../../output/safety_logs/20260617_141625/episode_0000.csv)；全序列 [`20260617_143655`](../../../../output/safety_logs/20260617_143655/episode_0000.csv) / T6 B 组 [`20260617_151222`](../../../../output/safety_logs/20260617_151222/episode_0000.csv) |
| ~~P0~~ | ~~**A/B baseline（T6）**~~ | ✅ 2026-06-17 成对全序列：A 无 `--enable_safety` 成功率 **100%**（`time_step` 1:1，≈7521 steps）；B 有安全层成功率 **100%**、干预率 **0%**、成功率下降 **0%** |
| ~~P0~~ | ~~**workspace 重标定**~~ | ✅ `workspace.x: [0.45, 1.05]`（EE transit x_min≈0.528）；旧 `x_min=0.55` 导致 97.9% workspace STOP |
| ~~P0~~ | ~~**三项指标定稿**~~ | ✅ T6 B 组锁定：**干预率 0%**、`slow_down_rate≈1.34%`（101 步 SLOW_DOWN）、`mean_stop_duration_steps=0`、**成功率下降 0%**（A/B 均 `is_success()`） |
| P1 | **人类轨迹场景库（IV-J）** | ✅ v0.1：[`configs/ivj/`](../../../../configs/ivj/) 6 preset + [`registry.yaml`](../../../../configs/ivj/registry.yaml)；原 stress/ttc 保留 |
| ~~P1~~ | ~~`human_trajectory` 调参~~ | ✅ workspace 重标定 + 多 preset（挡空箱默认 / stress / TTC；远场低干预轨迹见 141625/143655 历史跑） |
| ~~P1~~ | ~~阈值与 workspace 标定~~ | ✅ 双阈值 `safe_dist_hard_stop` / `safe_dist_warn` + GT v1.1 `ee_radius: 0.08` |
| ~~P1~~ | ~~**`outcome` ground truth**~~ | ✅ v1.1 距离法 GT + episode `outcome`；非 success 时附加 `@task_time_step/expected` 代理 |
| P1 | **GT 扩展（PhysX / 多刚体）** | 审计分支 A/B 已 log-only（[`gt_branches.py`](../GMRobot/safety/gt_branches.py)）；主 GT 仍为 EE 球 ↔ hand 球 |
| P1 | **物理任务 success 语义** | `is_success()` ≠ 20 零件物理放置；CSV 含 `task_time_step`/`task_time_step_max` 代理；parts 计数留 Phase 1 余量 |
| P2 | **`human_torso` 胶囊体** | §4.1 可选躯干，未实现（当前仅 `human_hand` sphere） |
| P2 | **Isaac 短序列集成脚本** | 无 `A@1→B@1` + 安全层的一键验证入口（缩短 T2–T7 手工回归） |
| P2 | **Parquet 稳定产出** | `SafetyLogger.flush()` 仅在 import `pandas` 成功时写 `.parquet`；未作为固定交付物 |

### 已完成事项

| 组件 | 路径 / 入口 | 状态 |
|------|------------|:----:|
| 规则引擎 + 门控 + 日志 + 指标 | [`GMRobot/safety/`](../GMRobot/safety/) | ✅ |
| 环境：`human_hand` + `obs["safety"]` | [`gmrobot_env_cfg.py`](../GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py)、[`safety_obs.py`](../GMRobot/tasks/manager_based/gmrobot/mdp/safety_obs.py) | ✅ |
| Agent 集成 | [`gm_state_machine_agent.py`](../../../../scripts/gm_state_machine_agent.py)：`--enable_safety`、`--safety_config`、**`--max_steps`**、**`--progress_interval`**；全序列 `is_success()` 后自动退出 | ✅ |
| 状态机轨迹时钟 | [`pick_and_place_policy.py`](../../../../scripts/pick_and_place_policy.py)：`get_action(advance=False)` + 仅 ALLOW 时 `advance_time_steps` | ✅ |
| 配置 | [`configs/safety_layer1.yaml`](../../../../configs/safety_layer1.yaml)（挡空箱/双阈值默认）、[`configs/ivj/`](../../../../configs/ivj/)（IV-J v0.1）、stress/ttc preset | ✅ |
| GT 审计分支 | [`gt_branches.py`](../GMRobot/safety/gt_branches.py) + [`compare_gt_branches.py`](../../../../scripts/compare_gt_branches.py) | ✅ log-only |
| 离线指标 | [`report_safety_metrics.py`](../../../../scripts/report_safety_metrics.py) | ✅ |
| T7 验证脚本 | [`tests/verify_t7_trajectory_clock.py`](../../../../tests/verify_t7_trajectory_clock.py)（合成 + 可选 `--csv`） | ✅ |
| 单元测试 T1 / T8 | [`tests/test_rule_engine.py`](../../../../tests/test_rule_engine.py)（6 项）、[`tests/test_policy_trajectory_clock.py`](../../../../tests/test_policy_trajectory_clock.py)（3 项） | ✅ |
| 依赖 | [`setup.py`](../setup.py) 已声明 `PyYAML` | ✅ |

### 验收状态（§14）

| # | 项 | 状态 |
|---|-----|:----:|
| T1 | 规则引擎单元测试（6 项） | ✅ |
| T2 | 人手远离 → 干预率 ≈ 0 | ✅ 短跑 + **全序列 0% STOP**（20260617_141625 / 20260617_143655） |
| T3 | 人手进静态区 → STOP + static | ✅ stress 3000 steps [`20260617_153055`](../../../../output/safety_logs/20260617_153055/episode_0000.csv)：干预率 **38.8%**、STOP **1165** 步 **100% static**、step≥250 人手 `[0.72,0,0.18]` 后 dist&lt;0.25 m 即 STOP |
| T4 | 人手快接近 → TTC STOP | ✅ TTC preset 3000 steps [`20260617_153911`](../../../../output/safety_logs/20260617_153911/episode_0000.csv)：**TTC STOP 11** + **TTC SLOW_DOWN 70**（`trigger_rule=ttc`）；step 800 fast sweep 首条 TTC STOP（ttc=0.492 s、dist=0.74 m）；T7 PASS |
| T5 | ee 出 workspace → STOP | ✅ 单元 `test_workspace_violation`（T1）；Isaac 修复后短跑/全序列/T3/T4 **0% workspace STOP** 误报 |
| T6 | `--enable_safety` A/B + 指标打印 | ✅ A 100% / B 100%，成功率下降 **0%**；B 干预率 0%、`slow_down_rate≈1.34%`（[`20260617_151222`](../../../../output/safety_logs/20260617_151222/episode_0000.csv)） |
| T7 | STOP 恢复不跳零件（修复后回归） | ✅ 单元/合成 + Isaac 短跑/**全序列 CSV PASS**（20260617_141625 / 20260617_143655；STOP 块内 proposed 变化 0） |
| T8 | 轨迹时钟单元测试（3 项） | ✅ |

### 已知限制（实现语义）

- **`is_success()`**：状态机轨迹索引走完即判成功，**不等于** 20 个零件物理放置完成；重度 STOP 下成功率指标可能失真。
- **活锁机制**（2026-06-17 短跑确认）：`advance_mask` 仅 `ALLOW` 为真；`STOP`/`SLOW_DOWN` 时 `policy.time_step` 不增 → `is_success()` 永不到达。`step_counter`（仿真步）仍递增，但任务轨迹冻结。Phase 1 可接受；**长期由 Motion Replan（架构总览 Phase 4）通过路径绕行消解**，而非无限 STOP/hold。挡空箱 preset 长期指标应包含 replan 后任务完成率，非仅 STOP 召回。
- **98% STOP 根因（20260617_135454，修复前）**：双重配置问题，**非 agent 逻辑 bug**。
  1. **workspace 误报（主因，97.9%）**：`x_min=0.55` 过紧；HOME→A@1 transit 时 EE x≈0.528–0.544 被判 `workspace_boundary_violation` → `time_step` 在 step≈63 冻结。
  2. **static 误报（workspace 修复后仍 ~80%）**：`start_pos [0.45,-0.35,0.18]`（env 默认）距 EE transit 仅 **≈0.25 m**，触发 `static_collision`；低干预 preset 应使用远场观察位 `[0.35,-0.55,0.50]`。
- **修复后短跑（20260617_141625）**：`workspace.x: [0.45,1.05]` + 远场 `start_pos/end_pos` → **干预率 0%**，`slow_down_rate≈3%`，`time_step` 2909/3000 env steps，T7 PASS。
- **修复后全序列（20260617_143655）**：A@1→B@1 完整 20 零件轨迹，7521 env steps（`is_success()` @ step_counter≈7500）；**干预率 0%**（0 STOP）、`slow_down_rate≈1.3%`（101 步 TTC SLOW_DOWN）、`mean_stop_duration=0`；`verify_t7_trajectory_clock.py --csv` PASS（SLOW_DOWN 块内 `action_proposed` 不变、恢复无跳点）。仿真约 10 min + reset 启动 ~1 min。
- **T6 A/B baseline（20260617_151222）**：成对全序列（**当时** yaml 为远场低干预轨迹，非当前挡空箱 preset）；**A 组**（无 `--enable_safety`）`is_success()` ✅，`time_step` 与 `step_counter` 1:1（≈7521 steps）；**B 组**（`--enable_safety`）`is_success()` ✅，7521 env steps，`time_step` 449→7399（SLOW_DOWN 致 122 步滞后）；**成功率下降 0%**（A 100% − B 100%）；B 组 **干预率 0%**、`slow_down_rate≈1.34%`、`mean_stop_duration=0`；T7 CSV PASS。日志：`/tmp/isaac_ab_baseline.log`、`/tmp/isaac_ab_safety.log`。**注**：`is_success()` = 轨迹索引走完，非 20 零件物理放置。
- **CSV 流式写入**：`SafetyLogger` 每 `flush_interval=50` 步追加写盘；长跑中 CSV 持续增长（不再仅在 episode 结束一次性落盘）。
- **首次集成样例**（修复轨迹时钟**之前**）：[`output/safety_logs/20260616_214132/episode_0000.csv`](../../../../output/safety_logs/20260616_214132/episode_0000.csv)，7420 步，STOP 77.6%；**不可**作为修复后 baseline。T7 分析：STOP 块内 `action_proposed` 变化 5858 次（时钟未冻结，会跳零件）。
- **stress preset 77.6% STOP 根因**（旧 `human_trajectory`）：`end_pos [0.72,0,0.18]` 位于 A↔B 共享通道桌面高度；step≥250 后人手常驻该点，而 EE 在容器间 transit/descend 时距人手 **< safe_dist_static (0.25 m)** → **100% static 规则**（非 TTC）。
- **T3 stress 实测（20260617_153055）**：`--max_steps 3000`、`safety_layer1_stress.yaml`；**干预率 38.8%**（1165 STOP + 65 SLOW_DOWN / 3000）、**STOP 100% → trigger_rule=static**（0 workspace）；step 250 后人手到位 `[0.72,0,0.18]`，首条 static STOP @ step_index=1921（dist=0.246 m）；dist&lt;0.25 m 的 1079 步 **全部 STOP+static**；`time_step` 冻结于 1770（活锁，success_rate=0）；T7 内联校验 STOP 块内 `action_proposed` 变化 **0**。全序列历史对照 [`20260616_214132`](../../../../output/safety_logs/20260616_214132/episode_0000.csv) STOP **77.6%**（7420 steps）；3000 步短跑干预率偏低因 EE 尚未多次穿越通道 + STOP 冻结轨迹。
- **T4 TTC stress 实测（20260617_153911）**：`--max_steps 3000`、`safety_layer1_ttc.yaml`（`start_step=800`、`duration_steps=25`、远场→`[0.55,0,0.30]` 快速 sweep）；**干预率 70.4%**（2112 STOP + 70 SLOW_DOWN / 3000），其中 **TTC 规则 81 步**（**STOP 11** + **SLOW_DOWN 70**，占干预步 **3.7%**；TTC 子集内 STOP/SLOW_DOWN **13.6% / 86.4%**）；step 800 首条 **TTC STOP**（ttc=0.492 s、dist=0.74 m ≥ safe_dist_static）；steps 800–818 全为 `trigger_rule=ttc`（dist 0.74→0.36 m）；step 825 后 ALLOW。余下 **2101 static STOP** 因 sweep 终点靠近 EE 通道、人手常驻后 EE transit 进入 0.25 m 泡（预期副作用，非 T4 主判据）；**0 workspace STOP**；`time_step` 冻结于 818；`verify_t7_trajectory_clock.py --csv` PASS（STOP/SLOW_DOWN 块内 proposed 变化 **0**）。日志：`/tmp/isaac_t4_ttc.log`。
- **T5 workspace 签收（2026-06-17）**：`tests/test_rule_engine.py::test_workspace_violation` PASS（EE 越界 → `trigger_rule=workspace` STOP）；Isaac 修复后各轮（141625 / 143655 / 153055 / 153911 / 151222）**workspace STOP 均为 0**（`x_min=0.45` 覆盖 transit 弧）。

### Phase 1 Isaac 回归（GT v1.1 / 双阈值 / gt_branches，2026-06-17 19:27–19:37）

三条 **3000 env steps** 短跑（`--headless --enable_cameras --enable_safety --max_steps=3000 --progress_interval=500`），生成带 Phase 1 CSV 列的新日志；离线脚本：

```bash
python scripts/compare_gt_branches.py --config <preset.yaml> output/safety_logs/<run_id>/
python scripts/report_safety_metrics.py --config <preset.yaml> output/safety_logs/<run_id>/
```

**CSV 列签收**（三跑均 3000 行）：`g_ground_truth`、`dist_ee_human_gt`、`min_dist_arm_links`、`g_gt_arm`、`gt_contact`（本批 **100% `unknown`**，kinematic hand 无 PhysX contact）、`task_time_step`/`task_time_step_max`；`g_rule` 双阈值行为：**0=ALLOW / 1=STOP / 2=SLOW_DOWN**。

| Preset | Run ID | CSV | intervention_rate | stop_rate | slow_down_rate | false_stop_rate | miss_rate | safety_recall | outcome |
|--------|--------|-----|------------------:|----------:|---------------:|----------------:|----------:|:-------------:|---------|
| 挡空箱默认 `safety_layer1.yaml` | `20260617_192734` | [`episode_0000.csv`](../../../../output/safety_logs/20260617_192734/episode_0000.csv) | **41.0%** | 0% | **41.0%** | **0%** | **0%** | N/A（GT STOP 0 步） | `timeout@1771/7521` |
| IV-J 远场低干预 `ivj_static_far_observer.yaml` | `20260617_193244` | [`episode_0000.csv`](../../../../output/safety_logs/20260617_193244/episode_0000.csv) | **4.3%** | 0% | **4.3%** | **0%** | **0%** | N/A | `timeout@2872/7521` |
| T3 stress `safety_layer1_stress.yaml` | `20260617_193713` | [`episode_0000.csv`](../../../../output/safety_logs/20260617_193713/episode_0000.csv) | **41.0%** | **38.8%** | 2.2% | **38.8%**（1165 步；主 GT 无 STOP 步） | **0%** | N/A | `timeout@1770/7420` |

**`compare_gt_branches.py`（臂段审计 vs EE GT）**：default **45.5%** 行 `g_gt_arm` 与 EE GT 不一致；IV-J far **1.3%**；stress **0%**（臂段未触发 STOP）。EE GT 重算 mismatch **0%**（三跑）。

**`g_rule` 分布（步级）**：default **1771 ALLOW + 1229 SLOW_DOWN**（`time_step` 冻于 1771）；IV-J **2872 ALLOW + 128 SLOW_DOWN**；stress **1770 ALLOW + 1165 STOP + 65 SLOW_DOWN**（与 T3 历史 [`20260617_153055`](../../../../output/safety_logs/20260617_153055/episode_0000.csv) 同量级 static STOP）。

仿真日志：`/tmp/run_layer1_default.log`、`/tmp/run_ivj_far.log`、`/tmp/run_stress.log`。单跑 wall time ≈4.5 min（含 headless 启动）；无 reset 挂起。


### 运行命令（Isaac Lab）

```bash
source /root/activate_isaaclab.sh
cd /root/GMRobot
pip install -e source/GMRobot -q

# Baseline（A/B 对照组，无安全层；默认 --enable_safety 关闭）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras

# Layer 1 安全门控（实验组）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config=configs/safety_layer1.yaml
# --safety_config 可省略，默认加载 configs/safety_layer1.yaml

# 短跑回归（推荐先跑，验证 time_step 推进与干预率）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config=configs/safety_layer1.yaml \
  --max_steps=3000 --progress_interval=500

# 单元测试（无需 Isaac Sim）
python tests/test_rule_engine.py
python tests/test_policy_trajectory_clock.py

# T7 验收（合成 agent 循环 + 可选 CSV 分析）
python tests/verify_t7_trajectory_clock.py
python tests/verify_t7_trajectory_clock.py --csv output/safety_logs/<run>/episode_0000.csv

# 挡空箱 / 高干预默认 preset（当前 safety_layer1.yaml）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config=configs/safety_layer1.yaml

# T3 static stress（~38%+ 干预 @ 3000 steps）
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config=configs/safety_layer1_stress.yaml --max_steps=3000

# T4 TTC stress
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  --enable_safety --safety_config=configs/safety_layer1_ttc.yaml --max_steps=3000
```

- **须** `--enable_cameras`：env 已配相机，否则 `reset()` 可能失败（§4.2）。首次 `env.reset()` 在 headless+相机下可能耗时数分钟。
- 日志：`/root/GMRobot/output/safety_logs/{YYYYMMDD_HHMMSS}/episode_*.csv`；**流式追加**（每 50 步 flush），长跑中 CSV 持续增长。
- 进度：`[PROGRESS] step_counter=… time_step=… g_rule=…` 每 `--progress_interval` 步打印（默认 500）；`g_rule`：0=ALLOW，1=STOP，2=SLOW_DOWN。
- Episode 结束打印 `[INFO]: Safety metrics: {...}`（仅 `--enable_safety` 且 `is_success()`）。

---

### 文档层级

| 优先级 | 文档 | 角色 |
|:------:|------|------|
| 1 | [`README.md`](../../../README.md) | 场景、8 维动作、任务流程 |
| 2 | [`GM-SafePick_添加相机技术文档.md`](./GM-SafePick_添加相机技术文档.md) | 相机与 `policy`/`camera` 观测权威定义 |
| 3 | **本文** | Layer 1 规则安全层实现规格 |
| 4 | [`GM-SafePick_架构总览.md`](./GM-SafePick_架构总览.md) | 三层架构与路标 |
| — | [`GM-SafePick_项目进展与遗留问题.md`](./GM-SafePick_项目进展与遗留问题.md) | 跨层进度、回归摘要、P0/P1/P2 |

> 与 README / 相机文档重合的接口（`ee_pos`、8 维动作、50 Hz、`scene_rgb`）**以上述文档为准**；本文仅引用，不重定义。

---

## 0. 控制频率（项目权威值）

```
sim.dt = 1/200 s，decimation = 4  →  control_dt = 0.02 s  →  50 Hz
```

- Layer 1 安全门控在**每个** `env.step()` 前执行（**50 Hz**），**不**改为论文 interim report 的 20 Hz。
- 论文 20 Hz 为真机 / 报告参考；仿真采用更高频过采样，安全判定更密。
- TTC 与差分速度**必须**使用 `control_dt = 0.02`；禁止硬编码 `0.05` 或 20 Hz。
- 配置项 `control_frequency` 默认 **50**（与 [`gmrobot_env_cfg.py`](../GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py) 一致）。

---

## 1. 职责

在 **50 Hz** 控制循环中，基于**硬编码规则**对状态机提议的 **8 维动作**（见 README §5）进行安全判定。规则安全层不包含任何可学习组件，只依赖阈值和物理公式。**不消费** `obs["camera"]["scene_rgb"]`（见相机文档 §5）。

**输入**：

| 数据 | 来源 | 用途 |
|:----|:----|:----|
| 末端执行器位姿 | `obs["policy"]["ee_pos"]`（7D：xyz + quat，取 `[:3]`） | 距离 / TTC |
| 末端执行器速度 | `obs["safety"]["ee_vel"]` | TTC |
| 人类手部位置 | `HumanMotionController.compute_pose()` 或 `obs["safety"]["human_hand_pos"]` | 静态距离 |
| 人类手部速度 | 轨迹控制器或 `obs["safety"]["human_hand_vel"]` | TTC |
| 机器人关节状态 | `obs["safety"]["joint_pos/vel"]` | 日志 / Layer 2 |

**输出**：

| 输出 | 类型 | 含义 |
|:----|:----|:----|
| g_t | {ALLOW, STOP, SLOW_DOWN} | 安全门控决策 |
| reason | string | 触发原因（日志） |
| metadata | dict | dist、ttc、trigger_rule 等 |

**论文 g_t 映射（IV-F）**：`ALLOW` / `SLOW_DOWN` → 执行；`STOP` → 保持上一步动作（论文 $g_t=0$）。`SLOW_DOWN` 为 GM 扩展。

---

## 2. 决策规则

### 规则 1：静态空间冲突

```text
IF human_hand_to_ee_distance < safe_dist_static:
    g_t = STOP
    reason = "static_collision: hand inside safety zone"
```

### 规则 2：动态运动危险（TTC）

```text
d = ||p_human - p_ee||
r = p_human - p_ee
v_rel = v_human - v_ee
approach_rate = -dot(v_rel, r) / (||r|| + eps)    # >0 表示接近

IF approach_rate > 0:
    ttc = d / approach_rate
    IF ttc < ttc_threshold:        g_t = STOP
    ELIF ttc < ttc_warn_threshold: g_t = SLOW_DOWN
ELSE:
    ttc = inf    # 远离，不触发动态规则
```

### 规则 3：工作空间边界

```text
IF ee_position not in SAFE_WORKSPACE (world AABB):
    g_t = STOP
    reason = "workspace_boundary_violation"
```

默认 workspace 以工作台 `(0.6, 0, 0)` 为参考（相机文档 §4.3），见 [`configs/safety_layer1.yaml`](../../../../configs/safety_layer1.yaml)。

### 规则优先级

```text
STOP > SLOW_DOWN > ALLOW
```

### 门控执行语义

| g_t | 动作处理 | 状态机 `time_step` |
|-----|---------|-------------------|
| ALLOW | 执行 proposed 8D action | **+1**（任务时间推进） |
| STOP | 返回 `prev_action`（零速 hold） | **冻结**（保持当前路点） |
| SLOW_DOWN | `prev + slow_down_alpha * (proposed - prev)` | **冻结**（与 STOP 相同，避免轨迹超前） |

STOP / SLOW_DOWN 期间物理上 hold 或减速，**任务脚本索引不得前进**；恢复 ALLOW 后从**同一路点**继续，不得跳过正在搬运的零件（见 §13.1）。

---

## 3. 日志与数据采集

每步记录（Layer 2 训练源），写入 [`output/safety_logs/`](../../../../output/safety_logs/) `{timestamp}/episode_*.csv`（环境有 pandas 时同目录可生成 `.parquet`）。

**写入策略**：episode 首个 `record()` 时创建 CSV 并写 header；之后每步 append，默认 **每 50 步** `flush` 到磁盘（`SafetyLogger(flush_interval=50)`），长跑或 `kill` 后仍可分析已落盘片段；episode 结束时的 `flush()` 负责回填 `outcome`、最终 fsync 与 Parquet 转换。

| 字段 | 类型 | 说明 |
|:----|:----|:----|
| timestamp | float | `sim_time`（≈ `step_index * control_dt`） |
| step_index | int | 环境步计数 |
| env_index | int | 并行 env 索引 |
| ee_pos / ee_vel | (3,) JSON | 末端 |
| human_hand_pos / human_hand_vel | (3,) JSON | 人手 |
| joint_positions / joint_velocities | [6] JSON | UR10e 臂关节 |
| g_rule | {0,1,2} | ALLOW / STOP / SLOW_DOWN |
| trigger_rule | string | static / ttc / workspace |
| reason | string | 人类可读触发原因 |
| dist_ee_human / ttc | float | 规则元数据 |
| g_ground_truth / gt_collision | {0,1} | **仿真 GT v1.1**：EE 球（r=ee_radius）↔ hand 球侵入；0=ALLOW，1=STOP |
| dist_ee_human_gt | float | GT 用 EE↔hand 中心距 |
| min_dist_arm_links / g_gt_arm | float / {0,1} | **审计分支 B**（臂段距离；不门控） |
| gt_contact / gt_contact_pairs | string | **审计分支 A**（PhysX；kinematic hand 常为 `unknown`） |
| task_time_step / task_time_step_max | int | 状态机轨迹索引 / 预期上限（outcome 代理） |
| action_proposed / action_executed | [8] JSON | 门控前后 8D 动作 |
| outcome | string | episode 结束回填：`collision`（任一步 GT=STOP）/ `success` / `timeout` / `incomplete` |

### 3.1 Ground truth 定义（v1.1）

**方法**：Option A 距离法（[`ground_truth.py`](../GMRobot/safety/ground_truth.py)），未接 PhysX contact / `TerminationsCfg`。

| 量 | 值 | 说明 |
|:--|:--|:--|
| 人手 | 球体半径 **0.05 m** | 与 `human_hand` `SphereCfg` 一致 |
| EE | **球体 r=0.08 m**（`wrist_3_link` / policy `ee_pos`） | v1.1 包络；不含 gripper 网格 |
| 侵入判定 | `dist(ee, hand_center) < collision_threshold` | 默认 `collision_threshold = human_hand_radius + ee_radius = **0.13 m** |

配置项（[`safety_layer1.yaml`](../../../../configs/safety_layer1.yaml)）：`human_hand_radius`、`ee_radius`、`collision_threshold`（可选覆盖）。

**静态规则双阈值（Phase 1）**：

| 参数 | 默认 | 行为 |
|:--|:--|:--|
| `safe_dist_hard_stop` | 0.13 m | `dist <` 此值 → **STOP**（`trigger_rule=static`） |
| `safe_dist_warn` | 0.19 m | `hard_stop ≤ dist < warn` → **SLOW_DOWN**（非 STOP） |
| `safe_dist_static` | 0.25 m | 遗留字段；仅 yaml 含此项且无 dual 键时，映射为 hard/warn 同值（向后兼容） |

**待决问题（GT 范围）**：
- 是否将 gripper 手指 / 夹持零件纳入 EE 包络？（当前：**否**，仅 wrist_3 点 + r=ee_radius）
- 是否检测 human_hand 与 robot link（非 EE）碰撞？（**审计分支 B** 已 log-only，见 [`gt_branches.py`](../GMRobot/safety/gt_branches.py)）
- PhysX contact？（**审计分支 A**；kinematic `human_hand` 通常 `gt_contact=unknown`）

**审计分支（非主 GT）**：[`gt_branches.py`](../GMRobot/safety/gt_branches.py) 逐步写入 `min_dist_arm_links`、`g_gt_arm`、`gt_contact`；**不影响 `g_rule`**。离线对照：[`scripts/compare_gt_branches.py`](../../../../scripts/compare_gt_branches.py)。

**离线指标**：[`scripts/report_safety_metrics.py`](../../../../scripts/report_safety_metrics.py) 计算 intervention_rate、false_stop_rate、miss_rate、safety_recall；缺 `g_ground_truth` 列时从 `ee_pos`/`human_hand_pos` 重算。

**outcome 优先级**：`collision` > `success` > `timeout` > `incomplete`；非 success 时可附加 `@task_time_step/expected`（见 agent `finalize_safety_log`）。

---

## 4. 配套组件

### 4.1 仿真人类模型

场景实体 `human_hand`：[`gmrobot_env_cfg.py`](../GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py) 中 `RigidObjectCfg` + `SphereCfg`，半径 0.05 m，**kinematic**，初始位于人机共享通道（相机文档 §4.3）。

轨迹驱动：[`HumanMotionController`](../GMRobot/safety/human_motion.py) 在 agent 每步调用 `apply_to_env()`；参数见 `human_trajectory` in YAML。

| 已实现 | 未实现 |
|--------|--------|
| `linear_approach`（`start_step` / `duration_steps` / `start_pos` / `end_pos`） | 多轨迹类型、场景 preset 库、`human_torso` |

### 4.2 相机

Layer 1 **不读** RGB。运行 agent 时 env 已含相机，**须**传 `--enable_cameras`（相机文档 §3），否则 `reset()` 可能失败。

---

## 5. 评估指标

| 指标 | 计算 | 实现 |
|:----|:------|:----|
| 干预率 | STOP 步数 / 总步数 | `SafetyMetrics.intervention_rate`；T6 B 组实测 **0%**（0/7521） |
| 干预时长 | 连续 STOP 步数均值 | `SafetyMetrics.mean_stop_duration_steps`；T6 B 组实测 **0** |
| 成功率下降 | 无安全 vs 有安全完成率差 | A/B：`--enable_safety` on/off；T6 实测 **0%**（A **100%** − B **100%**；`is_success()` 语义见 §7） |
| slow_down_rate | SLOW_DOWN 步数 / 总步数 | `SafetyMetrics.slow_down_rate`；T6 B 组实测 **≈1.34%**（101/7521） |

Episode 结束时 agent 打印：`[INFO]: Safety metrics: {...}`（需 `--enable_safety` 且策略 `is_success()`）。

---

## 6. 配置参数

配置文件：[`configs/safety_layer1.yaml`](../../../../configs/safety_layer1.yaml)

| 参数 | 默认值 | 说明 |
|:----|:-----:|:----|
| safe_dist_static | 0.25 m | 静态安全距离 |
| ttc_threshold | 0.5 s | TTC → STOP |
| ttc_warn_threshold | 1.5 s | TTC → SLOW_DOWN |
| workspace x/y/z | `[0.45,1.05]×[-0.45,0.45]×[0.08,0.75]` | UR10e + 双容器 EE 包络（2026-06-17 重标定；`x_min=0.55` 会误报 transit） |
| control_frequency | **50 Hz** | 与 env 一致 |
| control_dt | **0.02 s** | TTC / 差分用 |
| slow_down_alpha | 0.3 | SLOW_DOWN 混合系数 |
| log_enabled | true | 逐步 CSV 日志 |
| log_dir | `/root/GMRobot/output/safety_logs` | 日志根目录 |
| human_enabled | true | 是否驱动 `human_hand` 轨迹 |
| human_hand_radius | 0.05 m | GT：人手球半径 |
| ee_radius | 0.08 m | GT：EE 球半径（wrist_3 包络） |
| collision_threshold | null | GT 侵入阈值；默认 `human_hand_radius + ee_radius` |
| eps | 1e-6 | TTC 分母稳定项 |

**`human_trajectory` 子项**（[`HumanTrajectoryConfig`](../GMRobot/safety/config.py)）：

| 参数 | 默认值 | 说明 |
|:----|:-----:|:----|
| type | `linear_approach` | 轨迹类型（当前唯一实现） |
| start_pos / end_pos | **挡空箱默认**（`safety_layer1.yaml`）：`[0.55,0.38,0.30]`→`[0.72,0.22,0.20]`；**远场低干预**（141625/143655/T6）：`[0.35,-0.40,0.45]`→`[0.85,0.40,0.45]` | 勿用 env 默认 `[0.45,-0.35,0.18]`（距 EE transit ≈0.25 m 触发 static） |
| start_step | 250（低干预）/ 150（stress） | 低干预：约 5 s 后自左后高处横穿台面至右前 |
| duration_steps | 120 / 100 | 线性插值步数（低干预 ≈2.4 s 可见穿越） |
| hold_far | true | 开始前保持 `start_pos` |

### 调参 preset（2026-06-17）

| Preset | 用途 | 实测 |
|------|------|-----------|
| [`safety_layer1.yaml`](../../../../configs/safety_layer1.yaml) | 挡空箱/高干预默认（夹持落箱场景） | 人手 `[0.55,0.38,0.30]`→`[0.72,0.22,0.20]` 挡 B 箱放置口（`start_step=248`、`duration=55` 对齐 carry transit→descend B 301–350）；预期 **static STOP**（及运动段 **TTC**） |
| [`safety_layer1_stress.yaml`](../../../../configs/safety_layer1_stress.yaml) | T3 static stress | 3000 steps：**38.8%** 干预率、STOP **100% static**（[`20260617_153055`](../../../../output/safety_logs/20260617_153055/episode_0000.csv)）；全序列历史 **77.6%** STOP（7420 steps，[`20260616_214132`](../../../../output/safety_logs/20260616_214132/episode_0000.csv)） |
| [`safety_layer1_ttc.yaml`](../../../../configs/safety_layer1_ttc.yaml) | T4 TTC stress | 3000 steps：**TTC STOP 11** + **SLOW_DOWN 70**、step 800 fast sweep → `trigger_rule=ttc`（[`20260617_153911`](../../../../output/safety_logs/20260617_153911/episode_0000.csv)）；总干预率 70.4%（含 static 副作用） |

**T7 手动验证（Isaac 跑完后）**：

1. 用低干预或 stress preset 跑有安全层，拿到 `episode_0000.csv`
2. `python tests/verify_t7_trajectory_clock.py --csv <path>` → 应 PASS（STOP 块内 `action_proposed` 不变；STOP→ALLOW 无跳变）
3. 对比修复前日志：旧 CSV 上同一命令应 FAIL（5858 次 proposed 漂移）

---

## 7. 成功标准

| # | 标准 | 状态 |
|---|------|:----:|
| 1 | 场景中有人类球体 `human_hand` | ✅ |
| 2 | 轨迹接近时规则触发 STOP / SLOW_DOWN | ✅（集成已观测） |
| 3 | `SafetyMetrics` 输出三项 baseline | ✅ T6 B 组：干预率 0%、`mean_stop_duration=0`、`slow_down_rate≈1.34%` |
| 4 | CSV 可供 Layer 2 直接读取 | ✅ |
| 5 | `--enable_safety` 开启后任务仍可完成（成功率下降可度量） | ✅ T6：B 组 100% 完成，成功率下降 **0%** |

---

## 8. 风险与边界

| 风险 | 缓解 |
|:----|:----|
| 阈值过保守 | 先宽松后收紧；用 TTC 替代纯距离；见待办 P1 调参 |
| 阈值过激进 | 场景库覆盖快进、侧向接近（待办 P1） |
| 球体简化 | Layer 1 可接受；距离保守估计 |
| 无视觉 | 功能性风险交 Layer 3 |
| 策略 success ≠ 物理完成 | 待 `outcome` ground truth（待办 P1） |

---

## 9. 论文对齐

| 论文要求 | Layer 1 |
|---------|---------|
| 静态 / 动态风险 | 规则 1 / 2 ✅ |
| 功能性风险 | Layer 3（不在 L1 范围） |
| 安全门控 $g_t$ | STOP ↔ 否决执行 ✅ |
| 20 Hz（报告） | 项目 **50 Hz**（§0） |
| 人类运动 IV-J | 部分：`HumanMotionController` + YAML；场景库 ⬜ |
| VLM 五阶段 | 不在 Layer 1 范围 |

---

## 10. 模块与文件结构

```
source/GMRobot/GMRobot/
├── safety/
│   ├── __init__.py
│   ├── types.py
│   ├── config.py
│   ├── rule_engine.py
│   ├── gate.py
│   ├── logger.py
│   ├── metrics.py
│   └── human_motion.py
├── tasks/manager_based/gmrobot/
│   ├── gmrobot_env_cfg.py      # human_hand + ObservationsGMCfg.SafetyCfg
│   └── mdp/safety_obs.py
configs/safety_layer1.yaml
configs/safety_layer1_stress.yaml
scripts/pick_and_place_policy.py    # SingleEnvPickAndPlacePolicy（轨迹时钟）
scripts/gm_state_machine_agent.py   # --enable_safety, --safety_config
tests/test_rule_engine.py
tests/test_policy_trajectory_clock.py
tests/verify_t7_trajectory_clock.py
```

---

## 11. 观测接口（`obs["safety"]`）

| 键 | shape | 说明 |
|----|-------|------|
| `ee_vel` | (3,) | 腕部线速度 |
| `human_hand_pos` | (3,) | 人手球心 |
| `human_hand_vel` | (3,) | 人手线速度 |
| `joint_pos` | (6,) | 臂关节相对 default |
| `joint_vel` | (6,) | 臂关节角速度 |

`obs["policy"]["ee_pos"]` 仍由相机文档 / README 定义；**不修改** `policy` / `camera` 组键名。

---

## 12. 核心 API

```python
from GMRobot.safety import (
    RuleEngine, SafetyGate, SafetyState, SafetyLogger,
    HumanMotionController, load_safety_config, GateDecision,
)

cfg = load_safety_config("configs/safety_layer1.yaml")
engine = RuleEngine(cfg)
gate = SafetyGate(cfg)

state = SafetyState.from_runtime(
    policy_obs, safety_obs,
    human_hand_pos=..., human_hand_vel=...,
    sim_time=step * cfg.control_dt, step_index=step,
)
result = engine.evaluate(state)
safe_action = gate.apply(result, proposed, prev_action)
# 仅 result.g_t == GateDecision.ALLOW 时：policy.advance_time_step()
```

---

## 13. 控制循环集成

实现文件：[`scripts/gm_state_machine_agent.py`](../../../../scripts/gm_state_machine_agent.py)

### 13.1 状态机轨迹时钟（与门控联动）

```text
proposed = policy.get_action(obs, advance=False)
result   = rule_engine.evaluate(state)
safe     = gate.apply(result, proposed, prev_action)
policy.advance_time_steps([g_t == ALLOW per env])
env.step(safe)
```

- 策略类：[`scripts/pick_and_place_policy.py`](../../../../scripts/pick_and_place_policy.py)
- 多 env 包装：`MultiEnvPickAndPlacePolicy.advance_time_steps(mask)`

**2026-06-16 修复**：STOP/SLOW_DOWN 期间不再推进 `time_step`，避免跳过当前零件。

### 13.2 逐步时序

```text
human_motion.apply_to_env(env, step)
proposed = policy.get_action(obs, advance=False)
result = rule_engine.evaluate(state)      # 人手位姿用 HumanMotionController.compute_pose
safe = gate.apply(result, proposed, prev_action)
policy.advance_time_steps([g_t == ALLOW])
obs, ... = env.step(safe)
logger.record(...); metrics.record_step(result.g_t)
prev_action = safe
```

默认 `--enable_safety` **关闭**，保持 baseline 可复现。CLI 见文首「运行命令」。

---

## 14. 验收测试

完整状态见文首 **「验收状态」** 表。

```bash
python tests/test_rule_engine.py
python tests/test_policy_trajectory_clock.py
```

仿真项（T2–T7）建议在调参后的 `human_trajectory` preset 上逐项执行，结果回填文首验收表。

---

## 15. 日志样例（参考）

| 字段 | 说明 |
|------|------|
| 路径 | `output/safety_logs/20260616_214132/episode_0000.csv` |
| 步数 | 7420（@50 Hz ≈ 148 s 仿真时间） |
| STOP 占比 | 77.6%（`end_pos` 过近，**修复前**轨迹时钟问题亦存在） |
| 用途 | 验证日志格式与规则触发；**非**修复后 baseline |

调参方向：`start_step` 增大或 `end_pos` 远离工作区 → 低干预场景；[`safety_layer1_stress.yaml`](../../../../configs/safety_layer1_stress.yaml) 保留原 `end_pos [0.72,0,0.18]` 作高干预 stress test。
