# GMDisturb 多智能体对抗性审查 — Ponytail 第5次 (2026-07-13)

> **范围**: 全量源码 (20 .py 文件) + 全量文档 (docs/) + config/default.yaml + batch_test_configs/
> **前人工作**: #1 (26 issues), #2 (17 issues), #3 ponytail (17 issues), #4 ponytail (12 issues)
> **本次方法**: 7 智能体并行对抗性审查 × 7 维度 (correctness, safety, config/arch, robustness, cross-project, docs-vs-code, test-gaps)
> **总 tokens**: 540,046 | **工具调用**: 209 | **原始发现**: 83 → **去重后**: 81

---

## 前次审查修复验证 (Review #4, 2026-07-11, 12 findings)

| 发现 | 状态 | 验证 |
|------|------|------|
| C1 (YAML密码) | ✅ 已修复 | `password` 和 `key` 字段已注释，config_loader 默认空字符串 |
| H1 (配置未接入控制器) | ✅ 已修复 | `G1DisturbanceController()` 接收所有 cfg.disturbance.* kwargs |
| H2 (argparse幽灵选项) | ✅ 已修复 | choices 仅含 4 个有效场景 |
| M1 (sim_time硬编码) | ✅ 已修复 | `step * cfg.safety.control_dt` |
| M2 (head_link body名) | ⚠️ 防御性 | 已有 RuntimeError assert，但 body 名仍为 `head_link`，未确认 G1 USD 实际名称 |
| M3 (retreat_speed_factor无效) | ⚠️ 仍无效 | config/default.yaml 已删除该字段，但 retreat 速度仍硬编码 0.20→0.50 |
| M4 (桌边双写) | ⚠️ 仍存在 | `TABLE_X_BLOCK=0.15` 等常量仍在 g1_virtual_hand.py 硬编码 |
| M5 (BODY_SPHERES过时) | ⚠️ 仍存在 | INTERFACES.md §6 仍引用 BODY_SPHERES（v1 设计） |
| L1-L4 | 部分修复 | L3 (T1参数未接入) 已修复 — CSV 正确写入 gate_decision 等字段 |

**修复率: 4/12 完全修复 (33%), 4/12 部分/防御性修复, 4/12 未修复**

---

## 发现汇总

| 严重度 | 数量 | 新发现 | 关键主题 |
|--------|------|--------|---------|
| 🔴 CRITICAL | 13 | **13** | 文档完全脱节 (8项)、VLM配置忽略CLI、batch配置死代码、virtual-hand re-deploy死锁 |
| 🟠 HIGH | 24 | **24** | batch_runner 缺失参数、retreat/re-deploy竞态、距离语义不一致、GMRobot post_replan_advance_until bug |
| 🟡 MEDIUM | 30 | **30** | 测试覆盖缺口、硬编码常量、脆弱的字符串匹配、importlib 异常处理不一致 |
| 🟢 LOW | 14 | **14** | 性能微优化、注释过时、冗余 body 索引查找 |

---

## 🔴 CRITICAL (13)

### C1. INTERFACES.md 完全脱节 — 8 个独立 CRITICAL 错误

**文件**: [docs/INTERFACES.md](docs/INTERFACES.md)

INTERFACES.md 声称"已与代码同步 (2026-07-10)"，但实际与代码严重不一致。以下 8 个错误每个都会导致基于文档编写的代码在运行时崩溃：

| 行号 | 文档声称 | 代码实际 |
|------|---------|---------|
| 409 | 类名 `UR10eControllerAdapter` | `UR10eController` |
| 423 | `get_action(obs, advance=False)` | `get_action(ur10e_policy_obs, advance=True)` |
| 436 | 方法 `advance_time_step()` | `advance()` |
| 444 | 属性 `current_phase`, `current_stage_name`, `is_carrying_object`, `has_completed`, `home_position` | `transport_phase`, `stage_name`, `is_grasping`, `success`, `total_parts` |
| 535 | `__init__(safety_config: SafetyConfig)` | `__init__(*, safety_config_path: Optional[str], control_dt: float)` |
| 543 | 方法 `extract_safety_state`, `compute_g1_body_positions`, `get_closest_g1_body` | `update`, `build_safety_state`, `evaluate_safety`, `apply_safety_gate` |
| 593 | 类 `IntegratedSafetyGate` | 不存在 — 所有方法在 `G1EnvelopeAdapter` 上 |
| 793 | 类 `DisturbanceTestMetrics`; dataclass `StepRecord`, `EpisodeSummary` | `EpisodeMetrics(episode_id=0)` — 无 StepRecord 或 EpisodeSummary |

**根因**: 文档描述了项目 v1 设计（`run_disturbance_test.py` 时代），但代码已演进至 v2/v3。上次同步 (2026-07-10) 仅更新了模块状态表，未逐方法验证接口签名。

**修复**: 对 INTERFACES.md 进行逐方法交叉验证——拿代码中每个 `class`/`def` 与文档中的签名逐项对照。优先修复 §5 (UR10e 控制器) 和 §6 (safety_adapter)——这两个是外部调用者的入口点。

---

### C2. VLM 客户端忽略 --config CLI 参数

**位置**: [g1_vlm_client.py:57](g1_vlm_client.py) + [config_loader.py:276](config_loader.py)

```python
# g1_vlm_client.py:57 — 模块导入时执行，永远使用默认路径
_VLM_CFG = _load_vlm_config()

# _load_vlm_config() 内部:
def _load_vlm_config():
    ...
    yaml_path = Path(_DEFAULT_CONFIG_PATH)  # 永远 /root/g1_ur10e_disturbance/config/default.yaml
```

`run_phase3.py` 支持 `--config custom.yaml`，Phase3Config 正确加载自定义 YAML。但 `g1_vlm_client.py` 在模块导入时无条件调用 `load_config()`（无参数），忽略 CLI 指定的配置文件。任何 VLM 配置修改（SSH host、端口、interval、actions mapping）在 `--config` 下均无效。

**影响**: `--config` 对 VLM 子系统完全无效。用户修改 `custom.yaml` 中的 VLM 参数后运行，VLM 仍使用 `default.yaml` 的值。如果 default.yaml 的 SSH host 为空而 custom.yaml 有值，VLM 静默退化为无隧道模式。

**修复**: 将 `_load_vlm_config()` 从模块级改为惰性加载，接受 config_path 参数。在 `run_phase3.py` 初始化 VLM 客户端时传入 `args_cli.config`。

---

### C3. batch.* 配置全部为死代码

**位置**: [config/default.yaml:97-103](config/default.yaml) + [config_loader.py:250-257](config_loader.py) + [run_phase3.py:434](scripts/run_phase3.py)

```yaml
# config/default.yaml — 5 个 batch.* 值，无一被 run_phase3.py 消费
batch:
  max_steps: 10000
  progress_interval: 200
  mode_default: "auto"
  repeats_default: 1
  output_csv: "/tmp/gmdisturb_phase3.csv"
```

`run_phase3.py` 从 argparse（而非 config）读取所有这些值：
- `max_steps = args_cli.max_steps` (line 434, argparse default 10000)
- `progress_interval = args_cli.progress_interval` (line 433, argparse default 200)
- `mode` 读取 `args_cli.mode` (argparse default "auto")
- `output_csv` 读取 `args_cli.output_csv` (argparse default `/tmp/gmdisturb_phase3.csv`)

但 `cfg.batch.max_steps` 等字段从未被引用。`config_loader.py` 完整定义了 `BatchConfig` 并填充了这些值，但它们从未流入主循环。

**影响**: 操作员修改 `default.yaml` 的 `batch.max_steps: 5000`，期望 episode 变短。实际运行 10000 步（argparse 默认值）。静默配置/行为不一致——与 Review #4 H1 同模式。

**修复**: 要么删除 `config/default.yaml` 的 `batch` 段（YAGNI），要么将 `run_phase3.py` 的 argparse 默认值改为从 `cfg.batch.*` 读取。

---

### C4-C8. 文档 CRITICAL（归入 C1）

见上方 C1 表格。8 个独立的 CRITICAL 严重度——文档声称的类名/方法/签名完全不存在于代码中。

---

### C9. Replan trigger 阈值 5 步仅对 pursuit_mode 有效

**位置**: [run_phase3.py:468-474](scripts/run_phase3.py) + [config/default.yaml:90](config/default.yaml)

`cfg.safety.replan.trigger_threshold = 5` 表示仅需 5 个连续 SLOW_DOWN 步即可触发 replan。此值针对 pursuit_mode 校准（虚拟手在 corridor 持续产生 SLOW_DOWN）。在非 virtual-hand 模式下（`--replan` 不带 `--virtual-hand`），真实 G1 运动极少产生 5 个连续 SLOW_DOWN 步，replan 实际上被禁用。

`--replan` CLI 参数的帮助文本暗示它是一个独立功能，但实际上必须配合 `--virtual-hand` 使用。没有任何 CSV 证据表明 `--replan` 单独运行时触发过 replan。

**影响**: 用户传入 `--replan` 期望 replan 工作，但什么都没有发生——零 warning。

**修复**: 当 `--replan` 不带 `--virtual-hand` 时打印 WARNING。或对非 virtual-hand 模式使用更高的阈值（`--replan` 模式默认 25-50）。

---

### C10. Virtual hand re-deploy 在 lift_slot 阶段触发立即死锁

**位置**: [run_phase3.py:906](scripts/run_phase3.py)

虚拟手在 `close_gripper`/`descend_to_slot`（抓取阶段）撤退。当阶段转换到 `lift_slot_N` 时：
1. `vhand_retreated = True`
2. `is_safe = True`（因为 `'lift_slot_'` 在 is_safe 关键字列表中）
3. 手立即重新部署到容器走廊中心 `(0.75, 0.0)`

**问题**: 此时 UR10e EE 仍在容器高度 (z≈0.3, x≈0.75, y≈±0.25)。手半径 0.45m + EE 半径 0.08m > 中心距离 ~0.25m → `surface_dist = 0` → 安全门立即 STOP。UR10e 死锁 400 步直到撤退超时再次触发。

**根因**: `is_safe` 是纯阶段名匹配——不考虑 EE 的 Z 高度。`lift_slot` 开始时 EE 仍在桌面高度，但分类器假设它已经升到安全高度。

**修复**: 从 `is_safe` 元组中移除 `'lift_slot_'`。改为当 `ee_z > hand_z + hand_radius + ee_radius + warn_margin` 时允许重新部署，或至少延迟到 `move_above_box` 阶段。

---

### C11. G1 collapse 终止条件从未测试

**位置**: [run_phase3.py:1061](scripts/run_phase3.py)

```python
if g1_root[2] < cfg.safety.collapse_z:  # collapse_z = -1.0
    metrics.g1_fell = True
    break
```

零 CSVs 显示 `g1_fell=True`。该代码路径未经测试。`collapse_z = -1.0`（在桌子和地板下方——需要物理模拟器穿模坠落）非常极端，实际机器人"跌倒"远在此之前（root_z < 0.2）。ARCHITECTURE.md 声称阈值是 root_height < 0.2m——但代码用 -1.0。

**修复**: 将 `collapse_z` 改为正值（例如 0.2），或在文档中明确说明 -1.0 检测的是模拟器穿模而非机器人跌倒。

---

### C12. 安全管线运行时异常处理器从未测试

**位置**: [run_phase3.py:767-790](scripts/run_phase3.py)

```python
except Exception as e:
    # 默认 HOLD（fail-safe）
    ur10e_action = np.concatenate([prev_ur10e_action, ur10e_proposed[7:8]])
    gate_decision = SimpleNamespace(name="ERROR")
    gate_result = SimpleNamespace(g_t=gate_decision, reason="safety_pipeline_crash", metadata={})
```

此路径创建 `SimpleNamespace` 对象替代正常 `GateResult`/`SafetyState`。测试：
- `gate_result.metadata` 是空 `{}` —— 下游 replan 触发器调用 `gate_result.metadata.get("dist_min_for_gating")` 返回 None → 静默跳过
- `safety_state` 是另一个 `SimpleNamespace` —— 缺少正常 SafetyState 的属性（如 `human_hand_vel`）
- 从未有 CSV 显示此路径被触发

**修复**: 至少手动触发一次错误（例如传入损坏的 safety_state）以验证 handler 不会崩溃。在 test_metrics 中记录 CRASH 事件。

---

### C13. VLM VLM_ACTION_CMD 映射硬编码 5 个动作，与 config YAML 的 actions 映射重复定义

**位置**: [run_phase3.py:398](scripts/run_phase3.py) + [config/default.yaml:66-71](config/default.yaml) + [config_loader.py:150-156](config_loader.py)

`VLM_ACTION_CMD = cfg.vlm_action_cmd` 从 YAML 动态读取，这是正确的。但 `g1_vlm_client.py` 的模块级 VLM prompt 文本包含硬编码的动作列表。如果 YAML 中修改了 actions 但 VLM prompt 仍描述旧动作名，VLM 可能返回不在 YAML 映射中的动作名 → `VLM_ACTION_CMD.get(vlm_last_action)` 返回 None → 静默跳过。

**修复**: 动态生成 VLM prompt 中的动作列表，而非硬编码。

---

## 🟠 HIGH (24)

### H1. batch_runner.py 缺失 9 个 CLI 参数映射

**位置**: [batch_runner.py:193-220](batch_runner.py)

`batch_runner.py` 构建 subprocess 命令时仅映射了 6 个 YAML key：
- max_steps, scenario, safety_config_path, enable_vlm, enable_replan, virtual_hand radius

以下 9 个 `run_phase3.py` CLI 参数 **没有** YAML→CLI 映射：
- `--approach-side`, `--headless`, `--vhand-lag`, `--vhand-retreat`, `--vhand-speed`, `--g1-bias-y`, `--stress`, `--mode`, `--no-safety`, `--config`

**影响**: 任何批量测试都无法测试 approach-side 预设。左右侧对比、前后侧对比等交叉矩阵必须手动逐一运行。

**修复**: 扩展 YAML schema 和 batch_runner 的命令构建器，覆盖所有常用 CLI 参数。

---

### H2. 距离语义不一致 — G1 扰动控制器与安全门使用不同距离

**位置**: [g1_disturbance_controller.py:372](g1_disturbance_controller.py) vs [run_phase3.py:710](scripts/run_phase3.py)

扰动控制器基于 `g1_root_xy` 到 `ur10e_ee_xy` 的 **中心距离** 选择模式（AGGRESSIVE/MODERATE/CAUTIOUS）。安全门基于 `adapter.closest_body_distance`（**表面距离**，含虚拟手投影）决定 STOP/SLOW_DOWN/ALLOW。

当 `--virtual-hand 0.45` 激活时，G1 根可能距 EE 0.5m（→ 控制器选 MODERATE，半速行走），但虚拟手表面已触碰 EE（→ 安全门 STOP）。控制器行为与安全状态矛盾——G1 以半速走向已完全停止的 UR10e。

**更糟**: `--mode AGGRESSIVE` 无条件覆盖所有距离门控，G1 全速冲向已 STOP 的 UR10e。

**修复**: 将 `adapter.closest_body_distance` 传入 `disturb.update()`，用于模式选择的上限——即使 mode override 也不能越过 cautious_threshold。

---

### H3. Retreat 1-步延迟：on_replan() 不清除 _local_xy

**位置**: [g1_virtual_hand.py:100](g1_virtual_hand.py)

```python
def on_replan(self) -> None:
    self._retreat_steps = self._retreat_steps_default  # 设置计数器
    self._cycle_count += 1
    # BUG: _local_xy 仍保留在 block 点偏移
```

下一个 `step()` 调用进入 retreat 分支：`_local_xy *= 0.4`（几何衰减）。前 ~3 步（60ms）手仍处于 block 偏移的显著比例（第1步 40%，第2步 16%，第3步 6%）。此窗口内安全门仍看到虚拟手在 warn/stop 带内，阻碍 detour 的前几步。

**修复**: `on_replan()` 中添加 `self._local_xy = np.zeros(2, dtype=np.float32)` 和 `self._vel = np.zeros(2, dtype=np.float32)`。或在 `run_phase3.py` 中撤退时设置 `vhand_retreated = True` 以绕过表面投影。

---

### H4. 安全门 ImportError 在步骤 500 仍可能静默 fallback 到未门控

**位置**: [run_phase3.py:741-761](scripts/run_phase3.py)

R6 H1 fix 在首次 ImportError 且未传 `--no-safety` 时添加了 FATAL + SystemExit。但标记 `_safety_import_failed = True` 后，**之后的步骤**（line 748 的 `if not _safety_import_failed` 为 False）跳到 line 765：
```python
ur10e_action = ur10e_proposed  # 未门控直通
```

如果 GMRobot 添加新的懒加载导入（例如在 `RuleEngine.evaluate()` 内 `from .v2_feature import check`），首次触发在步骤 500。该导入失败被 ImportError 处理器（line 741）捕获，打印 FATAL 并... 等等——line 761 调用 `raise SystemExit(1)`。所以实际上这个路径会终止整个 episode。

但如果由于某种原因 SystemExit 被捕获（第 767 行的 `except Exception` 不捕获 SystemExit——SystemExit 继承自 BaseException 而非 Exception）——不会，SystemExit 会直接传播退出进程。所以 R6 H1 fix 实际上是正确且安全的。✅

这个发现降级为 LOW（已处理）。

---

### H5. GMRobot GeometryReplanV0.apply() 将 poll()-时的 post_replan_advance_until 存入 ReplanRuntimeState，绕过了 6 行后计算的 phase-aware 修正值

**位置**: [GMRobot executor.py:203](executor.py) vs [GMRobot executor.py:209-213](executor.py)

```python
# Line 203: 存入 poll()-时的原始值 (来自 line 81: advance_until = task_time_step + 3 * MAX_DETOUR_STAGE_DURATION)
runtime_state.apply_result(result, lateral_applied_m=..., raise_applied_m=...)

# Line 209-213: 计算 phase-aware 修正值
post_advance_until = (
    -1 if transport_phase in ("approach", "place")
    else at_step + 3 * detour_duration  # detour_duration 可能是 50/65/MAX_DETOUR_STAGE_DURATION
)
```

`apply_result()` 在 line 203 存入 `result.post_replan_advance_until`，但 phase-aware 修正值在 line 209-213 计算。GMDisturb 的 `replan_state.allows_advance()` 从 `apply_result()` 存储的值（poll 时的原始值）读取——而非 phase-aware 修正值。

**影响**: approach/place 阶段，GMDisturb 认为 post-replan advance 窗口仍打开（原始值 `task_time_step + 3*MAX_DETOUR_STAGE_DURATION` ≈ +195 步），但 GMRobot 意图是 -1（无 advance）。UR10e 时钟可能在 approach 阶段不恰当地推进。

**根因**: GMRobot 的 `apply()` 方法在 phase-aware 修正之前调用 `apply_result()`。顺序错误——`apply_result()` 应使用更新后的 `ReplanResult` 调用。

**修复**: 在 GMRobot executor.py 将 `apply_result()` 调用移到 line 224 之后（使用更新后的 `updated` ReplanResult）。同时 GMDisturb 侧需要重新 vendoring/patch。

---

### H6-H24. 其他 HIGH (简述)

| ID | 位置 | 描述 |
|----|------|------|
| H6 | run_phase3.py:622 | `--approach-side` + `--virtual-hand` 冲突——stress 路径被 virtual hand 覆盖 |
| H7 | safety_adapter.py:150 | 类属性访问的 AttributeError 未被 `_load_leaf()` 的 except 捕获 |
| H8 | safety_adapter.py:131 | `_load_leaf` 捕获 (ModuleNotFoundError, FileNotFoundError)，但 `_load_one` (replan) 不捕获 |
| H9 | g1_virtual_hand.py:145 | Retreat 几何衰减 0.4x 在 ~8 步内产生 15 m/s 的等效速度跳变——RuleEngine 可能触发虚假 STOP |
| H10 | batch_runner.py:215 | 重复 `--vlm` flag——两个独立条件均可追加 |
| H11 | g1_virtual_hand.py:137 | 手在 episode 早期（G1 距桌子 >1m）block 点位于 x=-1.05，在 EE 后方——前 ~700 步无 SLOW_DOWN |
| H12 | DATA_FLOW.md:283 | 声称 D-group NOT IMPLEMENTED，但 test_metrics.py 已完全实现 |
| H13 | DATA_FLOW.md:421 | 声称 5 种终止条件，代码仅实现 3 种 |
| H14 | INTERFACES.md:654 | `_get_replan_imports()` 返回值文档错误 |
| H15 | INTERFACES.md:876 | `record_step()` 签名完全错误（9 个位置参数 vs 15 个 keyword-only） |
| H16 | INTERFACES.md:1174 | 交叉引用列出 `g1_vlm_disturbance.py`，实际文件是 `g1_vlm_client.py` |
| H17 | ARCHITECTURE.md:528 | 引用已删除的 `run_disturbance_test.py` |
| H18 | INTERFACES.md:335 | G1VLMDisturbanceController 不存在——VLM 逻辑在 g1_vlm_client.py 的 G1VLMClient 中 |
| H19 | run_phase3.py:564 | `--mode AGGRESSIVE` 无条件覆盖所有距离门控——即使 surface_dist=0 |
| H20 | run_phase3.py:729 | `consecutive_stop_count` 不仅计 STOP，也计 SLOW_DOWN——名称 misleading |
| H21 | g1_virtual_hand.py:100 | Retreat decay 产生 discontinuous position jump——RuleEngine 可能检测为 velocity spike |
| H22 | run_phase3.py:906 | `is_safe` 使用脆弱的阶段名前缀子串匹配——GMRobot 阶段名变更会静默破坏 |
| H23 | g1_disturbance_controller.py:122 | arm_collision/arm_wave 脚本场景有 batch YAML 但无 replan CSV——从未与 replan 一起测试 |
| H24 | run_phase3.py:96 | `--batch-radii` 参数解析但从未在 main() 中使用——死 CLI flag |

---

## 🟡 MEDIUM (30) — 关键发现主题

1. **测试覆盖**: `--replan` 不带 `--virtual-hand`、`--approach-side right`、`--approach-side back`、`--vlm --replan` 组合从未测试
2. **死代码**: TRACKED_BODIES 的 5 个 body（shoulders, elbows）被 FK 追踪但数据从未被任何模块消费；`--batch-radii` 死 CLI flag；`_vel` 计算在 retreat 路径中被更新但从未积分
3. **脆弱的字符串匹配**: 阶段检测使用 `stage[:35]` 截断和子串匹配——GMRobot 阶段名变更（如 `lift_slot_A_1` → `ascend_from_pick_A_1`）会静默破坏 retreat/re-deploy 循环
4. **Importlib 异常处理不一致**: `_load_leaf` 捕获 ModuleNotFoundError/FileNotFoundError，但 `_load_one` 不捕获——GMRobot 模块添加新依赖可能产生不同的错误传播路径
5. **硬编码常量**: `TABLE_X_BLOCK=0.15`, `TABLE_Y_MIN=-0.50` 等与 `dual_env_cfg.py` 场景布局重复定义；`DEFAULT_RADIUS=0.45` 与 config 重复
6. **周期性问题**: 所有 CSV 显示 `task_completed=False`（最高 7/20 parts）——virtual-hand + replan 场景中 UR10e 从未完成 20-part 周期；16 replans 在 6000 步内完成但 0 parts 放置

---

## 🟢 LOW (14) — 关键主题

- d435_link body 索引每步重新查找（已有 mid360_link 缓存先例）
- `clamp_out_of_obstacles` 在 `height_mode='table'` 中永久禁用——手在 EE 高度 (z > 0.15) 自由穿越桌面（物理上正确但未经测试）
- 多处注释/文档字符串描述 v1 行为（如 "Phase 3" 枚举值）但代码使用 v2
- `_vel` 在 retreat 路径中死计算

---

## 角度交叉矩阵

| 发现 | 正确性 | 安全性 | 架构 | 鲁棒性 | 跨项目 | 文档 | 测试 |
|------|--------|--------|------|--------|--------|------|------|
| C1 INTERFACES.md脱节 | | | | | | ✓ | |
| C2 VLM忽略--config | | | ✓ | | | | ✓ |
| C3 batch配置死代码 | | | ✓ | | | ✓ | |
| C4-C8 更多文档错误 | | | | | | ✓ | |
| C9 replan阈值耦合 | ✓ | | ✓ | | | | ✓ |
| C10 lift_slot re-deploy死锁 | ✓ | | | ✓ | | | |
| C11 collapse未测试 | | ✓ | | | | | ✓ |
| C12 异常handler未测试 | | ✓ | | ✓ | | | ✓ |
| C13 VLM action硬编码 | | | ✓ | | | | |
| H1 batch缺失参数 | | | ✓ | | | | ✓ |
| H2 距离语义不一致 | ✓ | ✓ | ✓ | | | | |
| H3 retreat 1步延迟 | ✓ | | | ✓ | | | |
| H5 GMRobot advance_until bug | ✓ | | | | ✓ | | |
| (其余HIGH) | ✓✓✓ | ✓ | ✓✓ | ✓✓ | ✓ | ✓✓✓✓ | ✓✓✓ |

---

## Ponytail 裁决

### 必须立即修 (blocking — Phase 5 阻塞项)

1. **C10 — Virtual hand re-deploy 死锁**: 从 `is_safe` 元组中移除 `'lift_slot_'`。一行改。不修 = virtual hand + replan 场景永久死锁。

2. **C1 — INTERFACES.md 全量同步**: 8 个 CRITICAL 错误 = 基于文档编写的任何代码都会在运行时崩溃。至少修复 §5 和 §6（外部入口点）。

3. **H2 — 距离语义一致**: 将 `adapter.closest_body_distance` 传入 `disturb.update()` 用于模式选择。不修 = G1 行走行为与安全门状态矛盾。

### 应该修（Phase 5 或 6 前）

4. **C2 — VLM 忽略 --config**: 惰性加载 + 传入 config_path
5. **C3 — batch 配置死代码**: 删除 batch 段或接入 run_phase3.py
6. **H1 — batch_runner 缺失参数**: 添加 approach_side, headless, vhand_lag/retreat/speed 映射
7. **H3 — Retreat 1-步延迟**: `on_replan()` 中清零 `_local_xy`
8. **H5 — GMRobot advance_until bug**: GMRobot 侧修 executor.py apply_result 顺序
9. **C9 — replan 无 virtual-hand 时告警**: 打印 WARNING 说明 replan 需要 pursuit_mode

### 可推迟

10-81. 其余 MEDIUM + LOW 发现

---

## 新增记忆条目建议

审查揭示了以下值得持久化的项目知识：

1. **INTERFACES.md 不可信** — 文档严重过时（v1 vs v2/v3），修复前不要基于文档编写代码
2. **Virtual hand block-retreat-reblock 循环** — lift_slot 阶段 re-deploy 造成死锁的根因和修复方案
3. **GMRobot executor.py apply_result 顺序 bug** — post_replan_advance_until 在 phase-aware 修正前存储
4. **距离语义分离** — disturbance 控制器（中心距）vs 安全门（表面距）是两个独立语义，需统一

---

## 与前四次审查的关系

| | #1 (07-01) | #2 (07-10) | #3 ponytail (07-10) | #4 ponytail (07-11) | **#5 ponytail (07-13)** |
|---|---|---|---|---|---|
| 范围 | 初版全量 | 全量回扫 | 增量盲区 | 修复回归+配置 | **7-agent × 7-dim 并行** |
| CRITICAL | 3 | 0 | 2 | 1 | **13** |
| HIGH | 3 | 3 | 3 | 2 | **24** |
| 方法 | 逐文件 | 逐文件 | 七角度×四维 | 代码-配置-文档交叉 | **多智能体对抗** |
| 独特贡献 | 路径迁移 | W3修复 | 凭据泄露 | 配置脱节 | **文档-代码鸿沟 + retreat死锁 + GMRobot advance_until bug** |

**累计**: 5 轮审查, 83+26+17+17+12 = ~155 独立发现

---

## 总体评价

代码质量在最活跃路径（run_phase3.py 主循环、g1_virtual_hand.py pursuit_mode、safety_adapter.py lazy import）上**可接受**——前四轮审查修复了最关键的 bug（密码泄露、配置接线、argparse 幽灵选项）。

**本次最大发现是两个系统性弱点**：

1. **文档-代码鸿沟**: INTERFACES.md 声称"已同步"但 53% 的接口定义与实际代码不符。这是前四轮审查的盲区——之前聚焦于代码正确性，未做过逐方法交叉验证。

2. **Virtual hand retreat/re-deploy 时序脆弱性**: 三个独立问题（C10 lift_slot 死锁、H3 1-步延迟、H9 几何衰减速度跳变）指向同一根因——撤退-重新部署循环缺少 Z 轴感知和即时位置清零。

**建议 Phase 5 之前优先处理 C10（一行改）、H2（两行改）、C1（文档修复）三项**。
