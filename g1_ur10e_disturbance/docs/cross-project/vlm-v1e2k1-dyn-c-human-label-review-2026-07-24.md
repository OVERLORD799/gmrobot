# V1-E2K.1 Dyn-C Human Dynamic Label Review (2026-07-24)

## Result

- **reviewer_approved: `true`**（用户明确批准，2026-07-24 会话内）
- 样本：`v1e2k_dyn_c_formal_capture_20260724`（E02-DYN-C-E2K-STEP170-249）
- **计入 dynamic positive 组**（count_as_dynamic_positive_group=true）

## Reviewer observation (recorded verbatim in substance)

- 审查者确认：仅在 **170 与 249 之间**可见 G1 移动；
- 169→170 与 249→259 未见移动——与设计一致（相邻稳定对，169↔170 PNG sha256 完全一致，249→259 质心仅 4 px）；
- 动态证据对为跨窗口 170→249（质心位移 47.6 px）。

## Review basis

- 4 帧 RGB（169/170/249/259），UR10e/工作台/Container A/B 全帧静止；
- 技术门禁 12/12 PASS（`vlm-v1e2k-dyn-c-formal-capture-2026-07-24.json`）；
- 门槛依据：`vlm-v1e2k-arm-only-threshold-decision-2026-07-24`（arm-only 5e-4 rad，EE 1e-6 m 强制）。

## Scope limits

- 批准范围仅限**数据集视觉真值**（dynamic positive 样本资格）；
- **不**构成 VLM 输出证据、**不**构成 live/active 语义控制证据；
- 数据集整体状态更新为 `MINIMUM_GROUP_COVERAGE_MET_PROVISIONAL`（1 functional + 1 dynamic approved，达到既定最低组数与类目覆盖），`eligible_for_live_or_active` 保持 `false`；
- Dyn-B 候选组（E02-DYN-B-M1Z9）仍为 pending user，不受本次批准影响。

## Manifest update

- `vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json` → **v3.3.0**（3.2.0 已列入 immutable 历史）。
