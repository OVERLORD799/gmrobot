# V1-D8A：证据规则 v2 前瞻性验证（未见 seed，2026-07-24）

## 目的

D7B 的窗口聚合运动证据是在存档数据上离线标定的（seed 43/44 的 6 个窗口）。
本轮把它接入规则（`evidence_gated_dynamic_rule_v2_window`），并在**从未参与
标定的 seed 45** 上做前瞻性验证——预测先行、采集在后，杜绝事后拟合。

## 规则 v2 实现

`GMRobot/safety/evidence_gated_rule.py :: decide_dynamic_from_window_motion`

- 触发条件：窗口平移率 ≥ 25 px/s（D7B 标定，`window_motion.py`）
  且 track score ≥ 0.5、窗口度量有效。
- 替换掉 D7A 证伪的两个 v1 运动组件：末帧瞬时速度（F10）、D4A 尺寸带漂移门（F9）。
- 身份/质量门保留；深度运动（缩放主导）保持 fail-closed，拒绝理由显式区分
  `translation_below_threshold_scale_dominant`。
- VLM 仍为标注方：可升级动作、不可否决或制造触发。
- 单元测试：`test_evidence_gated_rule_unit.py` 14/14 通过（新增 v2 用例 6 个）。

## 前瞻协议

- 采集：seed 45、mirrored_outer_lateral_patrol、单次 Isaac 运行（exit=0，无重试），
  单相机正视（D6A 合同），一次采两窗口共 27 帧。
- 预注册预测（写入评估脚本 docstring，先于任何跟踪调用）：
  - dyn_sweep（170–249，负向扫掠）→ v2 触发；
  - static_idle（420–465，idle 微晃）→ v2 不触发。
- 链路无 GT 种子（GDINO 文本种子 P3），27 track POST，0 VLM。

## 结果：D8A_PROSPECTIVE_PASS（2/2 预测确认）

| 窗口 | GT | 平移率 px/s | 缩放率 | v2 判决 | v1 判决 |
|---|---|---|---|---|---|
| dyn_sweep | 动 | 61.9 | 10.3 | **触发 ✓** | 漏报（D4A 漂移误标） |
| static_idle | 静 | 11.5 | 6.7 | **不触发 ✓** | 误报（瞬时微晃超阈） |

- 阈值余量在未见 seed 上保持：动态 61.9 ≈ 2.5× 阈值，微晃 11.5 ≈ 0.46× 阈值。
- v1 在同一数据上再次复现 D7A 的两类失败（0/2），确认 F9/F10 非偶发。

## 结论与边界

- 规则 v2 成为动态检测的当前推荐路径：D7B 离线 5/6 + D8A 前瞻 2/2。
- 已知局限不变：相机轴深度运动 fail-closed（b2 类型）；遮挡相位未测（场景不可用）。
- 本验证覆盖 1 个新 seed、1 个场景族、2 个相位；跨场景族推广仍需后续采集。
- seed 45 两窗口帧未注册为数据集候选（本轮目的是规则验证，非扩产）；如需
  入库需另行人工审查。

## 预算与身份

Isaac 运行 1 次（无重试）；POST 27（全部 SAM2 track）；镜像与 B0–B4 未触碰。
