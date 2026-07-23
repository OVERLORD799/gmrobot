# V1-M1S E01-Dyn-B Runtime Preflight (2026-07-23)

## 结论
- Verdict: **FAIL**
- Formal run count: **1**（严格单次、无重试、无并发 Docker）
- Runner status: `capture_one_shot_runner` `exit_code=86`（postcheck fail-closed）

## 运行约束执行情况
- Anchor commit: `095d192`（M1R）
- Image: `gmdisturb:e01-func-c-m1j-20260723`
- Image ID: `sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`
- New image build: `false`
- POST target: `0`（未启用 VLM/perception/five-stage/SAM2/red proxy）

## 预保存元数据
- 目录：`g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1s_20260723/meta`
- 已保存：git HEAD、镜像 ID/Tag、seed=43、scenario、motion_source、frame targets、GPU 快照 pre/post、Xid pre/post/diff、formal command、runtime profile copy。

## 单次正式运行
- Command file: `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1s_20260723/meta/formal_command.txt`
- Runner status file: `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1s_20260723/meta/run_status.json`
- Start UTC: `2026-07-23T04:42:53.742+00:00`
- End UTC: `2026-07-23T04:43:09.606+00:00`
- Elapsed: `15.863174814` s
- Exit: `86`（raw returncode=0，但命中 forbid/missing-required-path，按 hardened 规则提升为失败）

## Fail-closed 审计
- Real runner status: `phase=finished`, `postcheck_failed=true`
- 错误扫描：
  - `Traceback`: **true**
  - NumPy/ABI (`broadcast_to` / `numpy.dtype size changed`): **true**
  - `device lost`: **false**
  - `POST` keyword count: **0**
- Required artifacts:
  - Frames `219/220/221/329/330/331`: **全部缺失**
  - `safety_logs/phase3.csv`: **缺失**
  - `meta/camera_pose.json`, `meta/body_poses.jsonl`: **缺失**
- G1 visible: **N/A**（关键帧缺失）
- Centroid displacement `220->330 >=20 px`: **N/A**（关键帧缺失）
- Phase checks:
  - expected step 220 phase: `lateral_positive_sweep`
  - expected step 330 phase: `lateral_negative_sweep`
  - runtime confirmation: **false**（CSV 缺失）
- Geometry gate window `190..340`:
  - ALL ALLOW with zero STOP/SLOW/replan: **N/A/FAIL**（CSV 缺失）
- G1 not fallen: **N/A**（无运行轨迹/CSV）

## 标签声明
- `dynamic=true`
- `provisional=true`
- `reviewer_approved=false`
- `scripted_provenance=true`
- `vlm_claimed=false`

## 最终判定
- FAIL reasons:
  - `traceback_present`
  - `numpy_abi_incompatibility_present`
  - `required_frames_missing_219_220_221_329_330_331`
  - `required_csv_missing_phase3`
  - `required_pose_artifacts_missing`
  - `runtime_gate_window_not_verifiable`

## 下一里程碑
- Next milestone: **V1-M1T**
- 建议目标：在不改 B0-B4 阈值和不改原始证据前提下，仅修复运行时 ABI/导入链后再申请新的单次 preflight。
