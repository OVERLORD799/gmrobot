# V1-M1F2 Func-C 左侧起始箱/零件阵列视觉损坏：根因定位与离线修复（2026-07-23）

## 结论
- 已撤回“无 USD 乱码”技术结论。
- 根因可由源码+资产证据确定：**旧 Func-C lineage 的 `container_full_visual.usd` 视觉资产链存在尺度链问题并触发白色阶梯/扇形伪影**；不是 instance/prototype 组合、不是 `Part_*` 重复 spawn、不是父子变换写错导致的重复阵列。
- 本次仅做离线最小修复：**新增资产静态门禁 + 单测 + 审计输出 + 候选 manifest 降级**，不重跑仿真。

## 证据链（只读）
- 前置核验：`HEAD=edfb5a2`，启动时工作区 clean。
- 固定证据图：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/scene/frame_000200_env0.png`（SHA256=`72b5c116...`）。
- 历史捕获文档已记录 legacy 视觉 spawn 资产哈希 `60ef...`，并关联白色扇形/阶梯伪影。
- M1D 隔离证据：隐藏 `ContainerB` 后伪影消失，`ContainerA` 与 parts 正常，指向容器视觉资产链，而非 part 阵列重复。
- 当前 canonical 视觉资产静态审计（`f392...`）显示：
  - 无 instance/instanceable；
  - 无 references/payloads/inherits；
  - `FilledContent_*` 命名 30 个；
  - `/FullContainer/Container` 仅 `translate + rotateXYZ`，无额外 scale op。

## 离线最小修复（已实施）
- `GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py`
  - 在 `precheck_container_full_asset()` 增加 `container_full_visual.usd` 静态门禁：
    - defaultPrim / metersPerUnit；
    - instance/prototype 与 composition 引用门禁；
    - `Part_*` 命名冲突门禁；
    - 容器根变换门禁（op 顺序与值）。
- `GMRobot/scripts/test_e01_func_c_capture_unit.py`
  - 新增 `test_container_full_visual_scenegraph_transform_gate()`，离线验证 scene graph / transform / 引用约束。
- `GMRobot/scripts/audit_func_c_visual_usd.py`
  - 新增离线审计脚本，可导出 JSON + ASCII USDA：
    - `g1_ur10e_disturbance/docs/cross-project/v1m1f2-func-c-visual-usd-audit-2026-07-23.json`
    - `g1_ur10e_disturbance/docs/cross-project/v1m1f2-func-c-visual-usd-audit-2026-07-23.usda`

## E0.2/E0.3 候选 manifest 调整
- 已下调 Func-C 状态为 `visual_corruption_confirmed_fix_pending`，`reviewer_approved=false`。
- Dyn-B 条目保持不变。
- 旧版本引用（`previous_version_refs`）保持不变。
- 相关更新文件：
  - `g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json`
  - `g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-review-packet-2026-07-23.md`
  - `g1_ur10e_disturbance/docs/cross-project/vlm-v1e02-visual-dataset-review-packet-2026-07-23.json`
  - `g1_ur10e_disturbance/scripts/v1e02_visual_dataset_review_packet.py`

## 为什么这不是“隐藏问题”
- 未隐藏起始箱，未裁剪相机，未改历史 PNG。
- 修复点在**资产封装门禁与审计约束**，目的是阻止同类视觉腐坏再次进入 capture/评审链路。
- 目标“满箱语义”与 `Part_*` 任务逻辑保持隔离；保留 `FilledContent_*` 命名策略，避免历史正则冲突。

## 待验证门禁与下一步（严格限制）
- 允许：`source-only build` + `1 次 visual smoke`（仅验证门禁生效）。
- 禁止：Docker/Isaac 正式重采集、网络/POST、覆盖历史结果。
