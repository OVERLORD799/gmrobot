# V1-E2K Arm-Only Settled Threshold Decision (2026-07-24)

## Decision

- **user_approved: true**（2026-07-24，会话内明确批准："允许放宽到 5e-4 rad"）
- arm-only settled 门槛：`1e-6 rad` → **`5e-4 rad`**
- **EE near-zero 门禁保留为强制项**：`ur10_ee_displacement_settled_max_m <= 1e-6 m` 不变
- 适用范围：Dyn-C 分析器 arm-freeze 判定（`v1e2g1_postrun_analyzer.py`）；不改动任何冻结 B0–B4 阈值，不改写历史 verdict（E2I/E2J/E2J.1 保持 FAIL 记录）。

## Rationale

1. E2J.1 观测漂移为 `shoulder_lift_joint` `-0.00015 rad`（重力负载最大的关节），同时 **EE settled 位移精确为 0.0 m**——说明这是 GPU PhysX 在 PD hold 下的关节空间数值残差，而非真实机械运动。
2. `1e-6 rad` 低于 PhysX 关节求解器数值分辨率，对物理仿真中的持位关节不可达，属于门槛设计过严。
3. `5e-4 rad` 的物理上界：按 UR10e ~1.3 m 臂展，最坏情况 EE 位移 ≈ 0.65 mm，远低于该相机视角像素尺度（1 px ≈ 数毫米），对 `>=40 px` 质心位移门禁无可测影响。
4. EE near-zero（任务空间）门禁保留为真实的"UR10e 静止"守卫；arm-only（关节空间）门槛仅为冗余检查。
5. gripper 保持 report-only（E2I.1 政策不变）。

## Effect on gate set (Dyn-C formal capture)

| Gate | Threshold | Status |
| --- | --- | --- |
| arm-only settled max abs | `<= 5e-4 rad`（本决策放宽） | mandatory |
| EE displacement settled | `<= 1e-6 m`（不变） | mandatory |
| projected centroid displacement | `>= 40 px`，`>= 2` frame-pairs（不变） | mandatory |
| ROI / direction / no-fall / camera contract | 不变 | mandatory |

## Boundary

- E2J.1 verdict 不改写，仍为 `FAIL_STOP_NO_RETRY_NO_FORMAL_CAPTURE`（其判定基于当时生效的 1e-6）。
- 本决策生效后允许一次 E2K 正式采集（单次、无重试、失败即停）。
- preflight ≠ 正式样本的边界不变；正式样本标签保持 `provisional` / `reviewer_approved=false`。
