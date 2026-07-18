---
name: configuration-system
description: Overview of the YAML-driven configuration system with 18 tunable parameters
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

全部 18 个安全参数通过 YAML 配置文件驱动，不需要改 Python 代码。

**默认配置**：[configs/safety_layer1.yaml](configs/safety_layer1.yaml)
**融合配置**：[configs/safety_fusion.yaml](configs/safety_fusion.yaml)

**层级结构（SafetyConfig 已重构为子数据类）：**
- `StaticSafetySubConfig`：`safe_dist_hard_stop`(0.13m)、`safe_dist_warn`(0.16m)、`slow_down_alpha`(0.18)、`safe_dist_slow_far`(0.35m)
- `TTCSubConfig`：`ttc_threshold`(0.5s)、`ttc_warn_threshold`(1.5s)、`ttc_dist_source`(envelope)、`ttc_forecast_replan_threshold`
- `ReplanSubConfig`：`replan_lateral_offset_m`(0.10)、`replan_detour_stage_duration`(55)、`replan_trigger_threshold`(50)
- `HumanModelSubConfig`：`human_hand_radius`(0.05)、`ee_radius`(0.08)、`human_torso_radius`(0.0=禁用)
- `EnvelopeConfig`：`gating_enabled`(true)、`arm_link_radius`(0.05)、`held_box_dims_m`[0.05,0.05,0.17]
- `HumanTrajectoryConfig`：`start_pos`/`end_pos`、`start_step`(1680)、`duration_steps`(55)、`hold_steps`(1000)、`retreat_pos`

**IV-J 场景可通过 `base: _base.yaml` 继承默认值后覆盖**。自动调参需求已定义（离线 CSV 重放 + 评分函数 + 搜索空间），脚本待实现。

**Why:** 这是项目工程成熟度的重要体现——参数与代码解耦，场景可独立配置。

**How to apply:** 讨论阈值或行为调整时，直接引用 YAML 键名。改参数→改配置文件→跑离线重放验证效果（无需 Isaac GPU）。
