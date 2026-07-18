# GMDisturb 多角度对抗性审查 — Ponytail 第4次 (2026-07-11)

> **范围**: 全量源码 (12 .py 文件) + 全量文档 (docs/) + config/default.yaml
> **前人工作**: #1 (26 issues), #2 (17 issues), #3 ponytail (17 issues + 修复验证)
> **本次重点**: 前次修复回归验证 + 新盲区 (配置管线、body name 校验、argparse sync)
> **方法**: 文档声称行为 vs 代码实际行为 vs 配置文件 — 三维交叉

---

## 发现汇总

| 严重度 | 数量 | 新发现 | 关键主题 |
|--------|------|--------|---------|
| 🔴 CRITICAL | 1 | **1** | C1 修复不彻底 — 密码仍在 git 追踪的 YAML 中 |
| 🟠 HIGH | 2 | **2** | YAML 配置未接入控制器、argparse 幽灵选项 |
| 🟡 MEDIUM | 5 | **4** | sim_time 硬编码、head_link body 名存疑、配置一致性 |
| 🟢 LOW | 4 | **2** | 终止条件不完整、VLM 模块级初始化脆弱 |

---

## 前次修复回归验证 (2026-07-10 ponytail, 17 issues)

| 发现 | 状态 | 验证 |
|------|------|------|
| C1 (SSH密码) | ❌ **修复不彻底** | 密码从源码移至 `config/default.yaml`，但该文件被 git 追踪 → **密码仍在仓库中** |
| C2 (VLM prompt) | ✅ 已修复 | `VLM_NAV_PROMPT` 改为对抗性测试 prompt，含 STRATEGY guidelines |
| H1 (隧道生命周期) | ✅ 已修复 | `_ensure_tunnel()` 有 health check + Popen handle + atexit cleanup |
| H2 (VLM避障) | ✅ 已修复 | 见 C2 — prompt 已改为对抗性测试意图 |
| H3 (14≠17关节) | ✅ 已修复 | DATA_FLOW.md §6 已标注实际 14 DOF，文档注明了 waist 3 由行走策略控制 |
| M1 (fragile字符串) | ✅ 已修复 | 400步 sanity check warning |
| M2 (shadow geometry) | ⚠️ 运行时绕过 | `run_phase3.py:449` 每次 step 覆盖 `_attractor = ur10e_ee[:2]`，硬编码默认值不生效 |
| M3 (rate limit) | ✅ 已修复 | `G1VLMClient.query()` 有 `min_interval` 强制 |
| M4 (dt硬编码) | ✅ 已修复 | `control_dt` 可配置，`_detect_and_handle_stuck` 使用 `self.control_dt` |
| M5 (dead code) | ✅ 已修复 | 4 个 phase 定义已删除，SCENARIOS 仅保留 4 个有效条目 |
| M6 (阻塞sleep) | ✅ 已修复 | 改为轮询 20×100ms + health check |
| M7 (文档过时) | ✅ 已修复 | INTERFACES.md VLM 状态 → IMPLEMENTED |
| L1 (全局状态) | ⚠️ 未改 | `_disturbance_cmd_buffer` 仍是模块级，ponytail 注释接受单 env |
| L2 (双RNG) | ✅ 已修复 | `_generate_schedule` 使用 `self._rng` |
| L3 (reset不彻底) | ✅ 已修复 | `reset()` 现在清 `_contact_forces = None` |
| L4 (stage解析) | ⚠️ 未改 | pick_and_place_policy.py 的字符串解析是 vendored 代码 |
| L5 (attractor) | ✅ 运行时绕过 | 见 M2 |

**修复率: 11/17 完全修复 (65%), 2 运行时绕过, 1 不彻底 (C1), 3 接受现状**

---

## 🔴 CRITICAL

### C1 (回归). SSH 凭据仍在 git 追踪的配置文件中

**位置**: [config/default.yaml:70](config/default.yaml) ← `git ls-files` 确认已追踪

**发现**: 前次 C1 修复将密码从 `g1_vlm_client.py` 源码中移除，但 `config/default.yaml` 仍包含：

```yaml
ssh:
    host: "120.209.70.195"
    port: 30481
    user: "root"
    password: "0k7fv9pr"
```

该文件被 git 追踪 (`git ls-files config/default.yaml` 返回该文件)。`g1_vlm_client.py` 的 `_load_vlm_config()` 通过 `ssh_cfg.password` 读取此字段——如果环境变量 `VLM_SSH_PASSWORD` 未设置，密码从 YAML 流入 `sshpass` 命令。

**与 C1 原始修复的关系**: 原始修复 (2026-07-10) 在 `g1_vlm_client.py` 中添加了 env-var 覆盖和 `sshpass -f /dev/stdin` 管道方式。但默认 YAML 仍含明文密码，且文件在版本控制中。任何 clone 此仓库的人都能读取该密码。

**影响**: 与原始 C1 完全一致——凭据泄露。`git log -- config/default.yaml` 会保留历史中的所有密码版本。

**修复**:
1. 从 `default.yaml` 删除 `password` 字段（保留 `key` 字段，设为空字符串）
2. 在 README 中添加说明：VLM SSH 凭据通过环境变量 `VLM_SSH_PASSWORD` 或 `VLM_SSH_KEY` 提供
3. `git filter-branch` / `bfg` 清理 git 历史中的密码（或轮换密码后接受历史泄露）
4. 立即轮换 `120.209.70.195` 上的 root 密码

---

## 🟠 HIGH

### H1. YAML 配置参数被打印但从未传给 G1DisturbanceController

**位置**: [run_phase3.py:299](scripts/run_phase3.py#L299) vs [config_loader.py:36-54](config_loader.py#L36-L54)

**发现**: `run_phase3.py` 第 299 行创建控制器：
```python
disturb = G1DisturbanceController(scripted_phases=scripted_phases)
```

仅传了 `scripted_phases`，其他参数全部使用模块级默认值 (`WORKSPACE_X_RANGE`, `CAUTIOUS_THRESHOLD` 等)。

但第 321-328 行打印了 `cfg.disturbance.*` 的值：
```python
f"CAUTIOUS < {cfg.disturbance.cautious_threshold:.2f}m  "
f"MODERATE < {cfg.disturbance.moderate_threshold:.2f}m  "
```

**终端显示** `CAUTIOUS < 0.15m MODERATE < 0.30m` ← 来自 YAML；
**实际行为**使用模块常量 `CAUTIOUS_THRESHOLD = 0.15` ← 来自 `g1_disturbance_controller.py`。

当前碰巧一致（YAML 默认值 = 模块常量）。一旦用户修改 `config/default.yaml` 中的阈值/速度，终端会显示新值但控制器使用旧值——**静默配置/行为不一致**。

`config_loader.py` 定义了完整的 `DisturbanceConfig`（含 `speed_aggressive`, `workspace_x`, `stuck.*` 等）——这些从未被传入 `G1DisturbanceController`。

**影响**: 用户通过 YAML 调参完全无效。批量测试中不同配置的对比结果无意义。

**修复**: `run_phase3.py:299` 改为：
```python
disturb = G1DisturbanceController(
    scripted_phases=scripted_phases,
    workspace_x=cfg.disturbance.workspace_x,
    workspace_y=cfg.disturbance.workspace_y,
    cautious_threshold=cfg.disturbance.cautious_threshold,
    moderate_threshold=cfg.disturbance.moderate_threshold,
    speed_aggressive=cfg.disturbance.speed_aggressive,
    speed_moderate=cfg.disturbance.speed_moderate,
    speed_cautious=cfg.disturbance.speed_cautious,
    resample_interval=cfg.disturbance.resample_interval,
    seed=cfg.disturbance.stuck.consecutive_steps,  # or dedicated seed field
    control_dt=cfg.safety.control_dt,
)
```

---

### H2. argparse choices 包含已删除的场景 → 静默 fallback 为 wander

**位置**: [run_phase3.py:40-43](scripts/run_phase3.py#L40-L43) vs [g1_disturbance_controller.py:117-122](g1_disturbance_controller.py#L117-L122)

**发现**: argparse 的 `--scenario` choices 列表包含 `table_bump`, `object_push`, `circulate`, `combined`，但 `SCENARIOS` dict 只包含 `arm_collision`, `arm_wave`, `constrained_wander`, `vlm_explore`。

执行路径：
```python
# argparse 允许 --scenario table_bump (在 choices 中)
scripted_phases = SCENARIOS.get(args_cli.scenario)  # → None (不在 dict 中)
# scripted_phases=None → G1DisturbanceController 进入默认随机游走模式
```

**无 error，无 warning**。用户以为在运行 `table_bump` 场景，实际在跑默认随机游走。SCENARIOS.md 明确标记这些场景为"已移除"并说明可从 git history 恢复，但 CLI 没有同步更新。

**影响**: 用户误操作静默产生错误数据。批量测试中更难发现。

**修复**: 从 argparse choices 中移除 4 个已删除场景名：
```python
choices=[None, "arm_collision", "arm_wave", "constrained_wander", "vlm_explore"],
```

---

## 🟡 MEDIUM

### M1. sim_time 硬编码 0.02 而非使用 cfg.safety.control_dt

**位置**: [run_phase3.py:483](scripts/run_phase3.py#L483)

```python
sim_time = step * 0.02  # 50 Hz control
```

`safety_adapter.py` 的 adapter 用 `cfg.safety.control_dt=0.02`，`G1DisturbanceController` 用 `control_dt=0.02`，但传给 `adapter.build_safety_state(sim_time=...)` 的 `sim_time` 仍是硬编码乘法。

如果 decimation 改为 2（dt=0.01, 100Hz），adapter 内部用 0.02 计算速度、sim_time 也偏离——两个错误叠加。

**修复**: `sim_time = step * cfg.safety.control_dt`

---

### M2. SAFETY_BODIES 的 `head_link` body 名可能不存在于 G1 USD

**位置**: [safety_adapter.py:41-45](safety_adapter.py#L41-L45)

**发现**: `SAFETY_BODIES` 包含 `"head_link"`（半径 0.12）。但 `run_phase3.py:463` 用 `g1.find_bodies("d435_link")` 获取头部位置——说明 USD 中的头部 body 名为 `d435_link`，非 `head_link`。

`_init_body_indices()` 调用 `robot.find_bodies("head_link")`——如果此 body 不存在于 37 个 body names 中，`find_bodies` 返回空列表，该条目被静默跳过。结果是 **SAFETY_BODIES 实际只有 2 个手腕被追踪**，头部永远不会被用作安全门候选。

ARCHITECTURE.md 说 SAFETY_BODIES 是 "头 + 双手腕"，但如果 `head_link` 不存在，实际只有双手腕。

**验证**: 需要在 Phase 1 smoke test 中确认 G1 body_names 是否包含 `"head_link"`。ARCHITECTURE.md 第 440 行的 body_names 验证清单至今未有人工确认记录。

**修复**: 
1. 确认 G1 body_names 中头部 body 的正确名称
2. 将 `SAFETY_BODIES` 中的 `"head_link"` 改为实际 body 名（可能是 `"d435_link"` 或 `"Bhead"` 等）
3. 在 `_init_body_indices` 中对 SAFETY_BODIES 的每个条目加 `assert len(idx_list) > 0, f"body '{name}' not found"`（当前只 assert 了 TRACKED_BODIES）

---

### M3. config/default.yaml retreat_speed_factor=0.4 对 CAUTIOUS 模式无效

**位置**: [config/default.yaml:25](config/default.yaml) vs [g1_disturbance_controller.py:451-482](g1_disturbance_controller.py#L451-L482)

**发现**: YAML 定义了 `retreat_speed_factor: 0.4`（"multiplier on speed_moderate for CAUTIOUS retreat"），但 `_retreat_command()` 方法硬编码了速度斜坡 0.20→0.50 m/s，完全不读取此参数。`DisturbanceConfig` 类包含 `retreat_speed_factor` 字段但从未被任何代码消费。

**影响**: 配置参数存在但在所有代码路径中被忽略。类似 H1，但影响面更窄（仅 retreat 速度）。

---

### M4. VirtualHand 桌边检测使用硬编码常量，与 dual_env_cfg 不同步

**位置**: [g1_virtual_hand.py:33-36](g1_virtual_hand.py#L33-L36)

前次审查 M2（"shadow geometry"）指出这些常量和 `dual_env_cfg.py` 桌子/容器位置独立维护。运行时通过 `virtual_hand._attractor = ur10e_ee[:2]` 绕过了 attractor 硬编码，但 `TABLE_X_BLOCK=0.15`, `TABLE_Y_MIN=-0.50` 等障碍物常量仍在 `g1_virtual_hand.py` 中硬编码，与 `config/default.yaml` 的 `virtual_hand.table_x_block` / `table_y` 重复定义。

`config_loader.py` 的 `VirtualHandConfig` 包含 `table_x_block`, `table_y` 等字段——但 `VirtualHand.__init__` 不接受这些参数，只用模块级常量。

**修复**: VirtualHand 接受 `table_x_block`, `table_y` 参数或从 config 对象构建。

---

### M5. INTERFACES.md G1EnvelopeAdapter 仍定义 BODY_SPHERES（v1 设计）

**位置**: [INTERFACES.md:494-503](docs/INTERFACES.md#L494-L503)

```python
BODY_SPHERES: list[tuple[str, float]] = [
    ("head", 0.12),
    ("torso", 0.20),
    ("left_upper_arm", 0.07),
    ...
]
```

实际代码已分离为 `TRACKED_BODIES`（8 体，日志用）和 `SAFETY_BODIES`（3 体：head + 双手腕，安全门用）。W3 fix 的成果未同步到接口文档——新开发者看 INTERFACES.md 会以为所有 8 个体都用于安全门距离计算。

---

## 🟢 LOW

### L1. 终止条件不完整：ARCHITECTURE.md 列 5 种，代码仅 3 种

**位置**: [ARCHITECTURE.md:421-426](docs/ARCHITECTURE.md) vs [run_phase3.py:625-635](scripts/run_phase3.py#L625-L635)

ARCHITECTURE.md §5 列出 5 种终止条件：
1. all parts placed ✅
2. G1 fell (root_height < 0.2) ⚠️ — 代码用 `cfg.safety.collapse_z = -1.0`（不同阈值）
3. Step limit ✅
4. All parts on floor ❌ — 未实现
5. G1 walked off mat ❌ — 未实现

代码注释说 `g1_root[2] < cfg.safety.collapse_z` 是 "G1 collapsed"，但 ARCH 文档说 root_height < 0.2m。两者的语义不同（collapse_z=-1.0 检测穿模坠落 vs 0.2 检测摔倒）。

---

### L2. VLM 配置在模块导入时加载 → 无配置文件时不报错

**位置**: [g1_vlm_client.py:58](g1_vlm_client.py#L58)

```python
_VLM_CFG = _load_vlm_config()
```

在 `import g1_vlm_client` 时执行。如果 `config/default.yaml` 不存在，`_load_vlm_config()` 的 `except Exception` 分支返回空字符串凭据——不报错，不 warning。后续 `_ensure_tunnel()` 看到 `VLM_SSH_HOST=""` 静默跳过隧道。用户启动 `--vlm` 看到 `[phase3] VLM: status=error` 但不知道为什么。

**修复**: `_load_vlm_config()` 的 except 分支打印 warning 说明配置文件缺失。

---

### L3. EpisodeMetrics.record_step 的 gate_decision 参数传入但从未在 run_phase3.py 中调用

**位置**: [test_metrics.py:68-73](test_metrics.py#L68-L73) vs [run_phase3.py:595-600](scripts/run_phase3.py#L595-L600)

`record_step()` 支持 `gate_decision`, `gate_trigger`, `gate_distance`, `closest_body` 参数（T1 fix 添加），但 `run_phase3.py:595` 调用时只传了 `g1_root_z`, `g1_ur10e_distance`, `surface_distance`, `mat_events`——**4 个 T1 参数从未被传入**。

CSV 中 `last_gate_decision` 列永远是 "N/A"。`min_surface_distance_m` 列 (L2 fix from #2) 已正确传入 `surface_distance` 参数。

---

### L4. _ensure_tunnel 健康检查成功条件缺少 `_tunnel_health_ok()` 中的 `/health` endpoint 约定

**位置**: [g1_vlm_client.py:176-182](g1_vlm_client.py#L176-L182)

如果 VLM 服务器的 `/health` endpoint 返回 200 但 body 为空或格式不对，`_tunnel_health_ok()` 返回 True。但这只是形式健康检查——实际 `/analyze` endpoint 可能返回 500。`query()` 的 except 捕获后返回 `{"action": "wait"}`，静默降级。

---

## 角度交叉矩阵

| 发现 | 正确性 | 鲁棒性 | 安全性 | 架构 | 测试 | 文档 | 配置 |
|------|--------|--------|--------|------|------|------|------|
| C1 YAML密码 | | | ✓ | | | | ✓ |
| H1 配置未接入 | ✓ | | | ✓ | | | ✓ |
| H2 argparse幽灵选项 | | ✓ | | | | ✓ | |
| M1 sim_time硬编码 | ✓ | | | | | | |
| M2 head_link存疑 | ✓ | | | | ✓ | | |
| M3 retreat_speed_factor无效 | | | | | | | ✓ |
| M4 桌边双写 | | ✓ | | ✓ | | | ✓ |
| M5 BODY_SPHERES过时 | | | | | | ✓ | |
| L1 终止条件不完整 | ✓ | | | | ✓ | ✓ | |
| L2 VLM导入时静默 | | ✓ | | | | | |
| L3 T1参数未接入 | | | | | ✓ | | |
| L4 健康检查浅 | | ✓ | | | | | |

---

## Ponytail 裁决

### 必须立即修 (blocking)

1. **C1 — 从 default.yaml 删除密码**: 删除 `password` 字段 → 轮换服务器密码 → 添加 `.env.example` 说明凭据设置方式。不修 = 每次 clone 泄露凭据。

2. **H1 — YAML 配置接入控制器**: `run_phase3.py` 将 `cfg.disturbance.*` 传入 `G1DisturbanceController()`。当前任何 YAML 参数调优都无效。一行 import 已导入 `cfg`，只需补上 kwargs。

### Phase 5 前应该修

3. **H2 — argparse choices 删除幽灵选项**: 一行删 4 个字符串。
4. **M1 — sim_time 用 cfg.safety.control_dt**: 一行改。
5. **M2 — 确认 head_link body 名**: smoke test 验证 + 可能改一行 body 名。

### 可推迟

6. M3 (retreat_speed_factor 死参数) — 要么接线要么删字段
7. M4 (桌边双写) — VirtualHand 从 config 对象构建
8. M5 (文档 BODY_SPHERES 过时) — 文档更新
9. L1-L4 — 低优先级

---

## 与前三次审查的关系

| | #1 (07-01) | #2 (07-10) | #3 ponytail (07-10) | **#4 ponytail (07-11)** |
|---|---|---|---|---|
| 范围 | 初版全量 | 全量回扫 | 增量盲区 + 修复验证 | **修复回归 + 配置管线** |
| CRITICAL | 3 | 0 | 2 | **1 (C1回归)** |
| HIGH | 3 | 3 | 3 | **2 (全新)** |
| 方法 | 逐文件 | 逐文件 + 修复验证 | 七角度×四维 | **代码-配置-文档 三维交叉** |
| 独特贡献 | 路径迁移+架构 | W3修复+doc-audit | 凭据泄露+VLM退化 | **配置脱节 + body名校验 + 修复不彻底发现** |

**累计 OPEN: 前次 7 项 + 本次 12 项 = 19 项待处理。**

### 前次仍 OPEN 项 (本次未覆盖)

| 发现 | 说明 |
|------|------|
| M2 (drop缺零件匹配) | `MatEvent` 仍无 `part_id` 字段 |
| M8 (ARM_JOINT_INDICES无校验) | 无运行时 assert |
| L1 (全局buffer) | 仍是模块级 |
| L2 (距离口径) | CSV 已有 `min_surface_distance_m` 列 (✅ L2已修) |
| L3 (attractor) | 运行时覆盖 (✅ 已绕过) |
| L4 (命名 _PHASE_PERIOD) | 未改 |

---

## 总体评价

前次 ponytail 审查的修复质量**可接受**（65% 完全修复 + 2 项运行时绕过）。但 **C1 修复不彻底是本次最大发现**——密码从源码搬到 YAML 但 YAML 仍在 git 中，本质上是同一个漏洞换了位置。

**新盲区在配置管线**：`config_loader.py` → `default.yaml` → `G1DisturbanceController` 这条链路上，YAML 值被加载、打印，但从未传到目标对象。这是"配置外部化"重构的常见遗漏——提取了参数定义但忘记了接线。H1 + M3 + M4 三个发现都指向同一模式。

**建议 Phase 5 之前做一次"配置接线 audit"**：拿 `config/default.yaml` 的每个 leaf 值，grep 确认至少有一个非 config_loader 的 `.py` 文件消费它。
