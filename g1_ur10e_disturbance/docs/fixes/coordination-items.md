# 双方协调事项

需要 GMDisturb 框架升级 + GMRobot 适配配合的工作。共 9 项。

## 协调 1：三档距离行为模式

- **GMDisturb 侧**：在 `G1DisturbanceController` 中实现 `ProximityBehavior` 枚举，支持 CAUTIOUS/MODERATE/AGGRESSIVE 三档
- **GMRobot 配合**：无需修改。三档测试 GMRobot 不同维度
- **状态**：已实现（Phase 3, `g1_disturbance_controller.py` DisturbanceMode 枚举 + `run_phase3.py` 注入）

## 协调 2：VLM 日志字段对齐

- **GMDisturb 侧**：新增 `DisturbanceCsvWriter`，写入专属 H 组字段（H09-H14），通过 `step_index` 与 GMRobot SafetyLogger CSV 关联
- **GMRobot 配合**：当 GMDisturb 验证需要时，在 Logger 中实现 `vlm_latency_ms`、`vlm_effective` 等字段
- **状态**：待实现（Phase 4+）

## 协调 3：相机启用

- **GMDisturb 侧**：Phase 2 取消 `scene_camera: TiledCameraCfg` 注释。验证相机 FOV 覆盖 G1 扰动活动区域
- **GMRobot 配合**：确认 `--enable_cameras` 在双机器人场景下无冲突
- **状态**：已实现（Phase 2, `run_phase3.py` line 81 `args_cli.enable_cameras = True` 强制启用）

## 协调 4：workspace 边界继承

- **GMDisturb 侧**：从 GMRobot `safety_layer1.yaml` 读取 workspace 边界，传入安全观测组。TestMetrics 增加 workspace STOP 分类
- **GMRobot 配合**：无需修改（参数已在 YAML 中定义）
- **状态**：部分实现（Phase 3 使用硬编码阈值 CAUTIOUS=0.15m, MODERATE=0.30m，未从 YAML 读取）

## 协调 5：A/B 对比设施

- **GMDisturb 侧**：`batch_runner.py` 支持"同一场景 × 不同 GMRobot 配置"对比运行。产出标准化对比表
- **GMRobot 配合**：新功能（如 velocity-aware warn）提供可配置开关
- **状态**：待实现（Phase 4）

## 协调 6：Replan 阶段化验证

- **GMDisturb 侧**：`object_push` 场景验证 place 阶段 wait-hold 是否正确触发
- **GMRobot 配合**：Phase 4a v1 已实现三阶段运输模型
- **状态**：GMRobot 侧已完成，GMDisturb 侧待验证

## 协调 7：IK 配置验证

- **GMDisturb 侧**：记录 UR10e 关节角度分布。发现异常 → 反馈 GMRobot
- **GMRobot 配合**：如发现关节极限/自碰撞，调整 IK 参数
- **状态**：GMDisturb 侧已修复（自修 8），持续监控

## 协调 8：Smoke Test 统一

- **GMDisturb 侧**：smoke test 的 core 验证步骤与 GMRobot Isaac 回归短跑对齐
- **GMRobot 配合**：共享基础验证清单
- **状态**：待协调

## 协调 9：文档镜像维护

- **GMDisturb 侧**：`/root/g1_ur10e_disturbance/gmdisturb_docs/` 维护所有三项目文档的副本。当 GMRobot 文档更新时，同步副本
- **GMRobot 配合**：重大文档变更时通知
- **状态**：已建立（`/root/g1_ur10e_disturbance/gmdisturb_docs/`）
