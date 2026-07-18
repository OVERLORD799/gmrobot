# GMDisturb 自修清单

框架自身缺陷，直接修复，不涉及 GMRobot。共 13 项。

## 自修 1：移除 `reset_scene_to_default`

- **位置**：[dual_env_cfg.py:663-667](../../../g1_ur10e_disturbance/dual_env_cfg.py)
- **修复**：删除 `reset_ur10e_scene` 事件定义
- **状态**：✅ 已修复

## 自修 2：Episode 时长可配置

- **位置**：[dual_env_cfg.py:733](../../../g1_ur10e_disturbance/dual_env_cfg.py)
- **修复**：`episode_length_s` 从环境变量 `EPISODE_LENGTH_S` 读取，默认 200.0
- **状态**：✅ 已修复

## 自修 3：Taxel 排列验证

- **位置**：[mdp/tactile_obs.py](../../../g1_ur10e_disturbance/mdp/tactile_obs.py) + [smoke_test_dual.py](../../../g1_ur10e_disturbance/scripts/smoke_test_dual.py)
- **修复**：smoke test 中增加空间校准验证（比较触觉热点和 FK 脚部位置）；若偏差超阈值则恢复排列表
- **状态**：✅ 已修复（验证已添加）

## 自修 4：硬编码路径改为环境变量

- **位置**：[vendored/robot_cfg.py](../../../g1_ur10e_disturbance/vendored/robot_cfg.py) + [dual_env_cfg.py](../../../g1_ur10e_disturbance/dual_env_cfg.py)
- **修复**：所有路径基于 `PRESSURE_MAT_ROOT` 和 `GMROBOT_ROOT` 环境变量，提供 `/root/...` 默认值
- **状态**：✅ 已修复

## 自修 5：Body link 文档修正

- **位置**：[gmdisturb/VARIABLES.md](../gmdisturb/VARIABLES.md)
- **修复**：用 smoke test 实际 body_names 更新 A14、C01 等字段
- **状态**：✅ 已修复

## 自修 6：碰撞过滤

- **位置**：[dual_env_cfg.py](../../../g1_ur10e_disturbance/dual_env_cfg.py) `__post_init__`
- **修复**：在 PhysX 场景中禁止 G1↔UR10e 物理碰撞响应。安全门继续通过 FK 距离检测
- **状态**：✅ 已修复

## 自修 7：`last_processed_actions` clone bug

- **位置**：[mdp/walk_action.py:41](../../../g1_ur10e_disturbance/mdp/walk_action.py)
- **修复**：`self.last_processed_actions = self.processed_actions.clone()`
- **状态**：✅ 已修复

## 自修 8：IK null-space 约束

- **位置**：[dual_env_cfg.py](../../../g1_ur10e_disturbance/dual_env_cfg.py) `DifferentialIKControllerCfg`
- **修复**：增加 null-space 关节偏好角度配置
- **状态**：✅ 已修复

## 自修 9：`_PHASE_PERIOD` 公开导出

- **位置**：[mdp/__init__.py](../../../g1_ur10e_disturbance/mdp/__init__.py) + [dual_env_cfg.py](../../../g1_ur10e_disturbance/dual_env_cfg.py)
- **修复**：重导出为 `PHASE_PERIOD`，外部从公开路径导入
- **状态**：✅ 已修复

## 自修 10：Smoke test 空间校准

- **位置**：[scripts/smoke_test_dual.py](../../../g1_ur10e_disturbance/scripts/smoke_test_dual.py)
- **修复**：增加 Step 10：原地踏步 50 步，验证触觉热点与 FK 脚位置偏差 < 0.125m
- **状态**：✅ 已修复

## 自修 11：`git_push.sh` 纳入版本控制

- **位置**：`/root/pressure_mat_repro/scripts/git_push.sh`
- **修复**：`git add scripts/git_push.sh && git commit`
- **状态**：✅ 已修复

## 自修 12：Docstring typo 修复

- **位置**：[mdp/terminations.py:22](../../../g1_ur10e_disturbance/mdp/terminations.py)
- **修复**：`bounds_x: (min_x, max_y)` → `(min_x, max_x)`
- **状态**：✅ 已修复

## 自修 13：冗余条件简化

- **位置**：[dual_env_cfg.py:163](../../../g1_ur10e_disturbance/dual_env_cfg.py)
- **修复**：`slot_idx = local_idx`，加注释说明 A/B 容器使用相同槽位映射
- **状态**：✅ 已修复
