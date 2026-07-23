# V1-M1F2.1 Func-C provenance 前门禁修复（离线，2026-07-23）

## 结论
- 门禁失败原因为前门禁测试正则误写（把 `\s` 写成了 `\\s`），导致无法识别生成器中已存在且正确的 `FROZEN_SOURCE_SHA256`。
- 已修复为真实 provenance 校验（非绕过）：从实际源文件重算 SHA，验证生成器声明一致，验证 canonical visual 资产身份与结构门禁。
- 保持离线限制：未执行 Docker / Isaac / build / capture / network / POST。

## 前置核验
- `HEAD`: `7bc00bd5fd5ff589ff09e49c23777b90056680ef`（匹配要求）
- 工作区：`git status --porcelain` 为空（clean）

## provenance 证据链（实际文件重算）
- 源资产：`GMRobot/source/GMRobot/GMRobot/assets/container_full.usd`
  - 实测 SHA256：`ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0`
- 生成器：`GMRobot/scripts/generate_container_full_visual_usd.py`
  - 声明 `FROZEN_SOURCE_SHA256`：`ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0`
  - 与源资产实测 SHA 一致（无需写死新值）
- canonical visual 资产：`GMRobot/source/GMRobot/GMRobot/assets/container_full_visual.usd`
  - 实测 SHA256：`f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e`
  - 结构指纹门禁仍为：`bb90e8cbf865dd9bdeb0c2fc0eea25f0ac1cc74a48f68f5d09709c079820920d`

## 代码与测试变更
- `GMRobot/scripts/test_e01_func_c_capture_unit.py`
  - 修复 `test_container_full_visual_provenance_chain()` 中正则，使其正确匹配 `FROZEN_SOURCE_SHA256` 声明。
- `GMRobot/scripts/test_generate_container_full_visual_usd_unit.py`
  - 新增 `test_freeze_hash_fail_closed_on_source_change()`：
    - 篡改临时源文件字节后使用 `--freeze-hash` 运行生成器；
    - 断言必须失败并报 `Source hash mismatch`（fail closed）。

## 执行记录（离线）
- `python -m pytest GMRobot/scripts/test_e01_func_c_capture_unit.py::test_container_full_visual_provenance_chain -q`：PASS
- `python -m pytest GMRobot/scripts/test_e01_func_c_capture_unit.py -q`：PASS（`16 passed`）
- `GMROBOT_TEST_M1E_GENERATOR=1 python -m pytest GMRobot/scripts/test_generate_container_full_visual_usd_unit.py::TestGeneratorFull::test_source_hash_matches_frozen GMRobot/scripts/test_generate_container_full_visual_usd_unit.py::TestGeneratorFull::test_freeze_hash_fail_closed_on_source_change -q`：PASS（`2 passed`）
- `python GMRobot/scripts/audit_func_c_visual_usd.py --json-out g1_ur10e_disturbance/docs/cross-project/vlm-v1m1f21-func-c-provenance-gate-fix-2026-07-23.audit.json`：PASS（`gate_passed=true`）

## M1F3 NOT_RUN 证据
- 在 `g1_ur10e_disturbance/docs/cross-project/` 范围内未检索到 `m1f3` 对应文档（包含 `NOT_RUN` 证据的独立 M1F3 文档缺失）。
- 本文档作为本轮 M1F2.1 的补充证据记录该缺口，不覆盖历史 M1F2 结论。

## 状态约束
- 保持 Func-C：`visual_corruption_confirmed_fix_pending`
- 保持 `reviewer_approved=false`

## 下一步（可重新申请）
- 可申请一次严格受限的 `build + visual smoke`，仅用于验证门禁在构建后路径持续生效；
- 仍应保持禁止 network/POST 与正式重采集，直到该一次性验证完成并归档。
