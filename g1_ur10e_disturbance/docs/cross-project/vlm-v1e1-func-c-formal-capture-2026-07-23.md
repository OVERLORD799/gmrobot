# V1-E1 Func-C 正式视觉采集（2026-07-23）

- verdict: `FAIL_FINAL`
- 单次正式运行：`1/1`，未重试
- 失败原因：容器命令目标脚本路径错误，未进入 AppLauncher（`raw_exit_code=1`）

## 前置门禁
- HEAD: `896b59d6c9e6b643a593c1212bca7796866a24ca`（要求 `896b59d6c9e6b643a593c1212bca7796866a24ca`）
- origin/main 一致：`true`
- worktree clean：`true`
- 固定镜像：`gmdisturb:e01-func-c-dual-reference-m1f13-20260723`
- 镜像 SHA：`sha256:afc9120b374adfc83b6fde7d49e77c80b60047c3fe6b7ac0b36bfca316dedb68`
- M1F13 报告 SHA：`sha256:afc9120b374adfc83b6fde7d49e77c80b60047c3fe6b7ac0b36bfca316dedb68`
- SHA 一致：`true`

## 用户审批 provenance
- `reviewer_approved=true`
- `approval_source=user_explicit_2026-07-23`
- `approval_scope=reference_bin_visual_contract_and_formal_capture_go`
- 不扩展为 VLM 识别成功或 live-control 证据

## 单次正式运行证据
- command: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1_func_c_formal_capture_20260723/meta/command.txt`
- stdout: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1_func_c_formal_capture_20260723/meta/capture_stdout.txt`
- stderr: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1_func_c_formal_capture_20260723/meta/capture_stderr.txt`
- raw exit: `1`
- elapsed(s): `0`

## 结果与门禁
- 由于运行未进入 AppLauncher，`step100/200` 主帧与 Kit runtime assertions 均未产出。
- 按规则本次直接 `FAIL_FINAL`，并且不重跑。

## Artifact Manifest（单组）
- JSONL: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1-func-c-formal-capture-2026-07-23.artifact-manifest.jsonl`
- Summary: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1-func-c-formal-capture-2026-07-23.artifact-summary.json`
- group_count: `1`（未将两帧拆组）

## Candidate/E0 状态
- Func-C candidate: `func_c_formal_capture_fail_final`，`formal_recapture_allowed=false`，`consumed=true`
- E0 数据充分性：仅更新为本次正式采集失败，不宣称整体充分
