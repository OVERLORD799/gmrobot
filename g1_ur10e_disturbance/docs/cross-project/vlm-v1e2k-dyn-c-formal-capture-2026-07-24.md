# V1-E2K Dyn-C Formal Capture (2026-07-24)

## Verdict

- **verdict: `DYN_C_FORMAL_CAPTURE_PASS`**
- **next_gate: `HUMAN_DYNAMIC_LABEL_REVIEW`**
- run_count=`1` / retry_count=`0` / image_rebuild=`false`
- 阈值依据：`vlm-v1e2k-arm-only-threshold-decision-2026-07-24`（用户批准 arm-only 5e-4 rad，EE 门禁保留 1e-6 m）

## Identity

| Field | Value |
| --- | --- |
| HEAD (run 时) | `940f9b94f5f04f8732ab3b63f9f13fa928236a2c` |
| image | `gmdisturb:e01-dyn-c-motion-preflight-m1e2j1-20260724`（复用 E2J.1 镜像，未重建） |
| result_dir | `results/paper_demo/v1e2k_dyn_c_formal_capture_20260724/` |
| scenario | `mirrored_outer_lateral_patrol`, seed=44, `--freeze-ur10e`, max_steps=260 |
| camera | pos=`[0.45,0,2.7]` rot=`[0.7071,0,0.7071,0]`，合同 fail-closed 强制，误差 0.0/0.0 |
| capture steps | `169,170,249,259` |

## Gate results (12/12 PASS)

| Gate | Observed | Threshold |
| --- | --- | --- |
| run exit / no Traceback / POST | `0` / none / `0` | 强制 |
| camera contract | pos_err=0.0 rot_err=0.0 | 精确匹配 |
| arm-only settled | `0.00015 rad`（`shoulder_lift_joint`） | `<= 5e-4`（本轮放宽） |
| EE settled displacement | `0.0 m` | `<= 1e-6`（不变） |
| 质心位移 ≥40px 帧对 | `4` 对（47.6/43.7/47.6/43.6 px） | `>= 2` 对 |
| ROI area fraction（全帧最小） | `0.0186` | `>= 0.012` |
| 指令-实际方向一致 | dot=`1.049 > 0`；cmd `[0.93,-0.23]` vs act `[1.06,-0.28]` | 同向 |
| G1 未倒地 | `g1_fell=False` | 强制 |
| 新增 Xid / 残留 | 无 | 强制 |

位移证据来自 **G1 body pose 投影质心**（非整图差分、非 UR10e 位移）；相邻稳定对 169↔170 PNG sha256 完全一致（静稳性符合设计）。

## Harness note（如实记录）

runner 报 exit=86 仅因 host 侧误将 `frame_inventory.json` 列为运行时必需产物；该文件与 E2J.1 一致为 **host 离线后处理生成**（本轮含 PNG sha256）。底层 Isaac 运行 `returncode_raw=0`，无 forbid 命中，全部真实产物齐备。未重跑。

## Labels (provisional, 待人工审查)

- risk_type=`dynamic`
- label_status=`provisional`
- reviewer_approved=`false`
- motion provenance=`scripted_g1_mirrored_outer_lateral_patrol`
- synthetic/scripted=`true`；human_hand=`false`；PPE=`false`；VLM_output=`false`

## Policy

- results 不提交；本文档与阈值决策文档提交。
- 本 PASS **不**触发 VLM/SAM2，**不**自动批准标签；下一步为人工动态标签审查。
- E2I/E2J/E2J.1 历史 FAIL verdict 未改写。
