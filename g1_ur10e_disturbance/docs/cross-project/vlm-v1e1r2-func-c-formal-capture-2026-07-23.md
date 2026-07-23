# V1-E1R2 Func-C 正式替代采集（2026-07-23）

- verdict: `FAIL_FINAL`
- 单次正式运行：`1/1`，未重试
- E1R 失败根因记录：`人为 --network none 阻断 Isaac 远程 default_environment.usd`（非场景/图片流程故障）

## 前置门禁
- HEAD: `8c36e10bb11cd3d46ea7c5b8e8bb4514773a4446`（要求 `8c36e10bb11cd3d46ea7c5b8e8bb4514773a4446`）
- origin/main 一致：`true`
- worktree clean：`true`
- 固定镜像：`gmdisturb:e01-func-c-dual-reference-m1f13-20260723`
- 镜像 SHA 证据：`gmdisturb@sha256:afc9120b374adfc83b6fde7d49e77c80b60047c3fe6b7ac0b36bfca316dedb68 sha256:afc9120b374adfc83b6fde7d49e77c80b60047c3fe6b7ac0b36bfca316dedb68`

## 运行策略（严格单次）
- 沿用 E1R 修正后的 `run.sh` 入口；无源码覆盖 mount
- `DOCKER_EXTRA_ARGS` 不含 `--network none`；允许 Isaac/Nucleus 读取基础场景资产
- 禁止：VLM/perception/GDINO/SAM2/five-stage/任何 inference POST/凭据
- 保留：`GMDISTURB_V1E01_FUNC_C_VISUAL=1`、runtime assertions path、camera flags/pose、seed51、interval100、max_steps201

## 单次正式运行证据
- command: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1r2_func_c_formal_capture_20260723/meta/command.txt`
- stdout: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1r2_func_c_formal_capture_20260723/meta/capture_stdout.txt`
- stderr: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1r2_func_c_formal_capture_20260723/meta/capture_stderr.txt`
- raw exit: `0`
- elapsed(s): `46`

## 门禁结果
- `frame_000100_env0.png`: `present`
- `frame_000200_env0.png`: `present`
- `runtime_scene_assertions.json`: `missing`
- inference POST hits: `0`
- traceback/device_lost/xid/residual: `False/False/False/False`
- frame SHA256: `{"frame_000100_env0.png": "97c1998fa08e6ead3ade1ed7bd49d3fe4640f724bb5f557ca7e7a808b3e8b934", "frame_000200_env0.png": "626e8c6be85324b64b7756cda58d52d5933df2c6b6d682fa14a7da7a4e480417"}`
- 结论：`FAIL_FINAL`；`next_gate=FORMAL_CAPTURE_ROUTE_STOP`

## Artifact Manifest（单组）
- JSONL: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1r2-func-c-formal-capture-2026-07-23.artifact-manifest.jsonl`
- Summary: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1r2-func-c-formal-capture-2026-07-23.artifact-summary.json`
- group_count: `1`


## 审计追加（V1-E1R2.1，离线事实更正与正式视觉冻结）
- raw verdict 保持不变：`FAIL_FINAL`（不覆盖）
- 新增 audited verdict：`FORMAL_VISUAL_CAPTURE_PASS_WITH_COMPOSITE_ASSERTION_EVIDENCE`
- 说明：composite_assertion_evidence 来自 M1F13 runtime assertions + E1R2 stdout 观测项，仅作跨 run 复合证据，不可声明为本 run 原生 runtime assertion。
- 审计报告：`/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1r21-func-c-formal-visual-audit-2026-07-23.md` / `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1r21-func-c-formal-visual-audit-2026-07-23.json`
