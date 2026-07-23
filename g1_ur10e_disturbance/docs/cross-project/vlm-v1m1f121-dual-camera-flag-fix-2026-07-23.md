# V1-M1F12.1 Dual-reference camera flag 最小离线修复（2026-07-23）

- preflight: `HEAD=f78ac38`（完整匹配），worktree clean
- scope: 仅离线修复 runner/AppLauncher 参数链，不执行 Docker/build/Isaac/network
- root cause: Dual-reference smoke canonical command 缺少 `--enable_cameras`，导致 camera asset 创建前启动失败

## 修复内容
- 新增命令守卫：`g1_ur10e_disturbance/func_c_dual_reference_smoke_guard.py`
  - canonical inner command 强制包含且仅包含一次 `--enable_cameras`
  - preflight 缺失时 fail-closed：`SMOKE_STARTUP_FAIL_FINAL: camera_flag_missing`
  - 禁止重复 python launcher 与 ENTRYPOINT（防止错误命令拼接）
  - 保留开关：`--headless`、`--save_camera`、固定 camera pose、`GMDISTURB_V1E01_FUNC_C_VISUAL`
- 接入 runner shell：`g1_ur10e_disturbance/scripts/run_e01_func_c_dual_reference_capture.sh`
  - 在离线断言前生成并校验 canonical inner command，再写入 `meta/canonical_app_launcher_inner_command.txt`
- 新增单测：`g1_ur10e_disturbance/scripts/test_v1m1f121_dual_camera_flag_unit.py`
  - canonical 命令恰好 1 个 `--enable_cameras`
  - 缺失 camera flag 时 preflight fail
  - 重复 launcher/entrypoint 时拒绝
- 补充静态门禁：`test_v1m1f11_func_c_dual_reference_scene_unit.py` 增加 shell preflight 钩子存在性检查

## M1F12 文档纠偏
- `vlm-v1m1f12-func-c-dual-reference-visual-smoke-2026-07-23.*` 修正为：
  - `overall_status=SMOKE_STARTUP_FAIL_FINAL`
  - `visual_verdict=NO_FRAME`
  - `failure_reason=camera_flag_missing`
  - 不再伪称本次已进入人工视觉 review

## 预算元数据
- max run budget 元数据保持不变：`build=1/1`，`smoke=1/1`，`retry=0`
- next step（唯一允许）：`copy-only build + one smoke`
