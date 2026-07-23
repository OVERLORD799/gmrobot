# V1-M1Z7 Dyn-B TTC 根因可观测性补齐（源码/离线）

- 结论: **完成 source-only 改造**；未执行 build / Docker / Isaac / 网络 / POST。
- 目标达成: 扩展 Dyn-B per-step audit，补齐 TTC SLOW/STOP 的逐步归因字段与缺失来源；不改 gate/replan/action 判定路径。
- 兼容性: 旧版 M1Z5 CSV 仍可读；离线 analyzer 对旧 schema 的非 ALLOW 点返回 `INSUFFICIENT`，不抛异常、不猜测。

## 源码字段映射（仅复用运行时已有值）

- `sim_step` / `policy_step`: 来自循环 `step` 与 `ur10e.time_step`。
- `protocol_phase`: 来自 `per_part.phase.value`（若无 `per_part` 则空字符串）。
- `ur10e_stage`: 来自 `ur10e.stage_name`。
- `motion_source_label`: 原参数 `--motion_source_label`。
- `gate_evaluated` / `gate_effective`: 来自 `gate_decision.name` 与 `resolve_effective_gate_name(...)`。
- `trigger_rule`: 来自 `gate_result.metadata["trigger_rule"]`。
- `trigger_reason`: 来自 `gate_result.reason`。
- `dist_min_for_gating_m`: 来自 `_gate_distance_audit()["dist_min_for_gating"]`（RuleEngine 实际使用口径）。
- `dist_min_g1_body_m` / `closest_g1_body`: 来自 `_g1_closest_body_dist` / `_g1_closest_body_name`。
- `dist_min_proxy_m`: 来自 `adapter_surface_dist`（现有运行时变量）。
- `safe_dist_warn_active_m` / `safe_dist_hard_stop_active_m`: 来自 `_gate_distance_audit()`。
- `ttc_observed_s` / `ttc_forecast_s` / `approach_rate_mps`: 分别来自 `gate_result.metadata.ttc` / `ttc_forecast_s` / `approach_rate`。
- `proxy_surface_velocity_*`: 来自 `adapter.human_hand_vel` 与其模长。
- `robot_ee_velocity_*`: 来自 `obs["safety"]["ee_vel"]`（已在 safety 路径采集）。
- `disturbance_active` / `disturbance_source` / `disturbance_attempt_id`: 来自现有扰动状态变量。
- `relative_velocity_mps`: 运行时 gate metadata 未直接暴露该量，统一写 `null`，并提供 `relative_velocity_availability=missing` 与 `relative_velocity_source=not_exposed_in_runtime_gate_metadata`。

## null/missing provenance 约定

- 对可能缺失字段，写入值列 + `*_availability` + `*_source`：
  - `ttc_observed_*`
  - `ttc_forecast_*`
  - `approach_rate_*`
  - `relative_velocity_*`
  - `proxy_surface_velocity_*`
  - `robot_ee_velocity_*`
- 缺失值统一写 `null`（字符串），禁止伪造。

## 离线 analyzer（M1Z7）

- 文件: `scripts/dyn_b_per_step_audit_analyzer.py`
- 新行为:
  - 统计 `non_allow_steps` 与连续区间 `non_allow_ranges`。
  - 对每个非 ALLOW 点输出 `attribution_status`:
    - `EXPLAINED`: 归因信息充分。
    - `INSUFFICIENT`: 字段缺失或旧 schema 无法解释。
  - 旧 schema（如 M1Z5）自动识别为 `legacy_pre_m1z7`，非 ALLOW 默认 `INSUFFICIENT`。
- 安全判定约束:
  - analyzer 不再用 `margin` 大小推断“安全”。
  - `pass` 依赖：step 完整性（缺失/重复）+ 非 ALLOW 归因是否充分。

## 离线测试覆盖

- `scripts/test_dyn_b_per_step_audit_writer_unit.py`
  - 校验 header 与数据列数一致（防止 schema 漂移）。
- `scripts/test_dyn_b_per_step_audit_analyzer_unit.py`
  - 完整窗口通过；
  - 缺行/重复行失败；
  - 旧 schema 非 ALLOW -> `INSUFFICIENT`；
  - TTC 非 ALLOW 在字段完整时 -> `EXPLAINED`；
  - TTC 字段缺失 -> `INSUFFICIENT`；
  - 非 ALLOW 连续区间输出正确。

## 允许的下一步（仍限 source-only）

- 仅允许：source-only image build + 1-step audit smoke。
- 仍不允许：正式 capture、Docker/Isaac 实跑、网络/POST。
