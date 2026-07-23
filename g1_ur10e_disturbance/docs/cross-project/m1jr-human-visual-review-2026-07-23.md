# M1JR Human Visual Review Archive (2026-07-23)

Verdict: **M1JR_HUMAN_VISUAL_GATE_PASS**

Scope: 基于人工审查者对 `frame_000000_env0.png` 的逐项视觉复核归档；该帧属于 1-step 验证证据，不等同于正式 Func-C 正样本。

## Repository / Baseline
- Repo: `/home/czz/GMrobot`
- HEAD: `02b2662`
- Branch: `main` (worktree clean)

## Evidence Binding
- Frame path: `g1_ur10e_disturbance/results/paper_demo/m1j_visual_validation_20260723/scene/frame_000000_env0.png`
- Frame SHA256: `1c68b10b21aa8c19bea375cb647dbd7548a040e2fd4e0df9896825bde1832a77`
- PNG integrity: valid, shape `480x640x3`, type `uint8`
- Build exit code: `0`
- Run exit code: `0`
- Xid delta: `0` (no new Xid)

## Human Visual Conclusions (Reviewer Confirmed)
- 白色扇形完全消失。
- 右侧 ContainerA 及 20 个黑色 source parts 规整正常。
- 左侧 ContainerB 尺度正常、浅绿色槽体完整。
- 米色 filled contents 清晰可见且位于目标箱区域。
- 两箱无爆炸、散落、巨大尺度或乱码伪影。

## Gate Decision and Boundary
- Human visual gate: **PASS** (`M1JR_HUMAN_VISUAL_GATE_PASS`)
- Allowed next step: 可进入“固定镜像上的一次正式 Func-C 重采集”。
- Not granted by this review:
  - 不等于批准进入 VLM 评估。
  - 不等于批准进入数据集。
  - 正式 capture 仍需独立门禁审批。

## Compliance Notes
- 未运行 Docker、未运行仿真。
- 未修改代码、镜像或资产。
- 未改动既有 M1J 历史文档。
