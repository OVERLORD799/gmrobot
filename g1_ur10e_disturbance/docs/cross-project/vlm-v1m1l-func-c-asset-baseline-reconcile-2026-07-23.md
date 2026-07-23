# V1-M1L Func-C Asset Baseline Reconcile (2026-07-23)

## 结论
- 判定：**期望陈旧（stale expectation）**，非意外资产突变。
- 处理：将 `test_e01_func_c_capture_unit.py` 中 `container_full_visual.usd` 的冻结哈希从旧值更新为已批准 repaired lineage 的 canonical 值，并新增 provenance 约束测试。

## 取证范围与约束
- 提交区间审查：`2741c7a..7764e30`
- 禁止项：未运行 Docker / Isaac / network / POST。
- 未改：USD 几何本体、安全阈值、B0-B4 资产/配置/结果、历史 verdict 文档。

## Canonical 身份证明
- 在 `2741c7a..7764e30` 区间内，最终审批提交 `7764e30` 对应的人审通过链路指向同日 repaired capture 证据。
- repaired capture 证据文档记录 `container_full_visual.usd` SHA 为：
  - `f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e`
- 当前工作区该资产实测 SHA：
  - `f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e`
- 旧冻结期望（测试内）为：
  - `60efbaa11fc845492dcb5e734fe509e20a67e1b9fd7e51c03a65f4b404c83885`
  - 语义：修复前历史 visual USD 基线（已被 repaired lineage 替代，不再 canonical）。

## 生成器/构建路径与更强 provenance
- 生成器：`GMRobot/scripts/generate_container_full_visual_usd.py`
- 冻结输入源：`container_full.usd`
  - 生成器内 `FROZEN_SOURCE_SHA256` = `ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0`
  - 当前源资产实测 SHA 同值，证明输入身份一致。
- 结构身份（强校验）：`structural_fingerprint`
  - canonical 指纹：`bb90e8cbf865dd9bdeb0c2fc0eea25f0ac1cc74a48f68f5d09709c079820920d`
  - 新增单测会对当前 `container_full_visual.usd` 做该指纹校验。
- 说明：本机直接重生一次 USD 得到不同二进制 SHA（`00383bf...`），但结构指纹一致，说明 USDC 二进制可受写出环境影响；因此采用“canonical SHA + 冻结输入 + 结构指纹”三重约束，不降低腐坏检测能力。

## 代码变更
- `GMRobot/scripts/test_e01_func_c_capture_unit.py`
  - 更新 `container_full_visual.usd` 冻结 SHA：`60ef... -> f392...`
  - 新增 `test_container_full_visual_provenance_chain()`：
    - 校验 `container_full.usd` 冻结源 SHA
    - 校验生成器 `FROZEN_SOURCE_SHA256` 一致
    - 校验 `container_full_visual.usd` 结构指纹为 canonical 值

## 测试执行结果
- `python3 GMRobot/scripts/test_e01_func_c_capture_unit.py` ✅
- `python3 GMRobot/scripts/test_capture_one_shot_runner_unit.py` ✅
- `pytest -q GMRobot/scripts/test_generate_container_full_visual_usd_unit.py` ✅（`10 passed, 6 skipped`）
- `python3 GMRobot/scripts/analyze_e01_func_c_capture.py --results-dir g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_recovery_20260723 --assets-dir GMRobot/source/GMRobot/GMRobot/assets` ✅

## old/new SHA 精确定义
- old SHA `60ef...`：2026-07-22 旧 visual asset 基线（修复前/历史阶段）。
- new SHA `f392...`：2026-07-23 repaired Func-C lineage（经后续人审链路批准）对应的 canonical visual asset 二进制身份。
- 若后续 canonical 再次变更，必须同步更新：审批证据文档 + provenance 测试常量，不可只改单一哈希字符串。
