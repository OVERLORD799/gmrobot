# V1-M1O Func-C 人工语义标签批准记录（2026-07-23）

## 结论
- 本次记录的是**独立人工语义裁决**，不是 VLM 输出。
- 监督审阅明确批准：目标 `B` 为右上绿色箱体，场景满足功能正例  
  `target container full/unavailable for continued placement`。
- 标签提升为：`label_status=reviewer_approved`，`reviewer_approved=true`。

## 审阅边界
- 仅离线证据记录；不执行 Docker/Isaac/网络/VLM/SAM2/POST。
- 保持原始证据不变：未重写 PNG、安全日志、历史 FAIL 文档。

## 证据来源与哈希
- 结果目录：`g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_final_m1m_20260723`
- 审阅帧：
  - `frame_000100_env0.png` -> `8da7319646faf76734624fd8b2453e3b0a0eea13b903ff5eeaf26d3531e96d80`
  - `frame_000200_env0.png` -> `37baa81ff93ece84dd2a7cc13a11b65837e56876bd7eff83101a1cff84698051`

## 批准对象与 ROI
- 目标容器 ROI：`[341,80,415,211]`
- 填充内容 ROI：`[350,97,407,192]`
- 语义理由：两帧中目标 B 内部均为规则排列且高密度占用，视觉上无明显同类零件可继续放置空位。

## 分组与数据集约束
- M1M 两帧按**一个 functional 正例场景组**计数，不拆成两个独立样本。
- 分组完整性：D1B/M1M 相关帧不得跨 train/held-out 泄漏。
- 保守复核后：新增 `1` 组、`2` 帧；dynamic 仍为 `0`，因此**不批准** live/active semantic control。

## 关联更新
- 已同步更新：
  - `vlm-v1e01-func-c-final-m1m-capture-2026-07-23.json`
  - `vlm-v1m1n-func-c-label-roi-audit-2026-07-23.json`
  - `vlm-v1e0-semantic-evaluation-design-2026-07-22.json`
  - `vlm-v1e01-positive-dataset-acquisition-plan-2026-07-22.json`
  - `paper-evidence-index-2026-07-22.json`
