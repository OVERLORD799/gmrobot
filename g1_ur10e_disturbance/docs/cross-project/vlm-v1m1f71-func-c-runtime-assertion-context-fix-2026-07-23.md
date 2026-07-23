# V1-M1F7.1 Func-C runtime assertion context fix（2026-07-23）

## 目标
- 修复 M1F7 smoke 预断言错误：禁止在宿主机/非 Kit runtime 上下文导入 `pxr`。
- 保留并强化场景断言，不允许删除或降级为 warning。

## 根因
- 原流程在 shell 预断言阶段触发 `pxr` 导入，运行环境不是 Isaac/Kit stage，出现 `ModuleNotFoundError` 并导致启动提前失败。

## 修复策略（两层）
- 宿主机 prebuild：仅执行无需 `pxr` 的检查（文件 SHA、env/config、源码合同）。
- Container/AppLauncher 运行时：在 stage 建立后执行 prim/asset identity 断言，产出机器可读 `runtime_scene_assertions.json`。

## 运行时强制断言
- `Part_*` 计数必须为 `0`。
- 三对象必须存在：`ContainerA`、`GridA`、`ContainerB`。
- 模式标志必须正确：`task_execution=false`、`visual_dataset_only=true`、`spawn_task_parts=false`。
- 断言产物缺失时最终 smoke 必须 FAIL。

## 状态修正（保持事实）
- raw 启动状态：失败。
- frame：缺失（absent）。
- verdict：`SMOKE_STARTUP_FAIL_FINAL`。
- next_gate：`FIX_VALIDATION_CONTEXT_ONLY`。
- 不伪称 visual review。

## 记录保留
- 保留原记录引用：`vlm-v1m1f7-func-c-empty-source-visual-smoke-2026-07-23.md/.json`。
- 保留提交引用：`f361363`。
