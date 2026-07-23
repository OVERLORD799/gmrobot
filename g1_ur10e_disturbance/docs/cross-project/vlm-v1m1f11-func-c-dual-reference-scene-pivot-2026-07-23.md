# V1-M1F11 Func-C 切换到 Dual reference scene（2026-07-23）

- preflight: `HEAD=00544a3`，worktree clean
- 前置结论承接: `M1F10 主agent人工拒绝`，旧路线 `ABANDONED_WASTEFUL_LOOP`
- 目标: 停止失败的 Func-C 资产拼装链，改为 `g1_ur10e_disturbance DualEnvCfg` 同源场景

## 约束与实现
- 禁用路线: `GMRobot gm_state_machine Func-C scene`
- 新增默认关闭 opt-in: `GMDISTURB_V1E01_FUNC_C_VISUAL=1`
- 默认行为保持不变: Dual 基线 `PART_LOCATIONS=A@1..A@20`
- opt-in 行为: 20 个现有 `part_5000` 初始位置确定性映射到 `B@1..B@20`，另一箱保持空
- 不新增 USD/材质/箱壳/overlay，不改 part geometry，仅改 capture-only 初始 location
- 参考锁定: `e01_dyn_b_formal_m1z9_20260723/frame_000330_env0.png`
- 相机锁定: `pos=(0.45,0.0,2.7), rot=(0.7071,0,0.7071,0)`

## 代码交付
- contract: `g1_ur10e_disturbance/func_c_dual_reference_contract.py`
- dual cfg接入: `g1_ur10e_disturbance/dual_env_cfg.py`
- runtime assertions: `g1_ur10e_disturbance/func_c_dual_reference_runtime_assertions.py`
- capture config: `g1_ur10e_disturbance/configs/e01_func_c_dual_reference_capture.yaml`
- capture runner: `g1_ur10e_disturbance/scripts/run_e01_func_c_dual_reference_capture.py`
- shell runner: `g1_ur10e_disturbance/scripts/run_e01_func_c_dual_reference_capture.sh`
- scene contract unit test: `g1_ur10e_disturbance/scripts/test_v1m1f11_func_c_dual_reference_scene_unit.py`

## 离线验证范围
- pycompile
- scene contract 单测（默认不变 + opt-in 20 unique target slots + other box empty）
- runtime assertions 结构检查（Dual scene identity / ContainerA/B / GridA/B / part count20 / task_execution false）
- no legacy content/full assets in runner
- no B0-B4 YAML diff

## 状态
- func_c_status: `dual_reference_scene_rework_pending`
- formal: `false`
- next_step_allowed: `copy-only build + one visual smoke`
