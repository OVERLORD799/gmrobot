# V1-E1R Func-C 正式替代采集（2026-07-23）

- verdict: `FAIL_FINAL`
- 单次正式运行：`1/1`，未重试
- 历史 E1 失败真实根因（审计）：`host bind /home/czz/GMrobot:/opt/projects/GMRobot 覆盖 baked source`，并非镜像内脚本缺失
- 本次失败根因：`--network none` 下无法访问远程 `default_environment.usd`，场景创建失败

## 前置门禁
- HEAD: `5b688458dbba29329fe13bf40555377afc5563fc`（要求 `5b688458dbba29329fe13bf40555377afc5563fc`）
- origin/main 一致：`true`
- worktree clean：`true`
- 固定镜像：`gmdisturb:e01-func-c-dual-reference-m1f13-20260723`
- 镜像 SHA：`sha256:afc9120b374adfc83b6fde7d49e77c80b60047c3fe6b7ac0b36bfca316dedb68`
- 镜像内 `/opt/projects/GMRobot/scripts/gm_state_machine_agent.py` 存在校验：`PASS`

## 单次正式运行证据
- command: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1r_func_c_formal_capture_20260723/meta/command.txt`
- stdout: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1r_func_c_formal_capture_20260723/meta/capture_stdout.txt`
- stderr: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e1r_func_c_formal_capture_20260723/meta/capture_stderr.txt`
- raw exit: `0`
- elapsed(s): `88`

## 结果与门禁
- `frame_000100_env0.png`: `missing`
- `frame_000200_env0.png`: `missing`
- `runtime_scene_assertions.json`: `missing`
- 结论：`FAIL_FINAL`（按规则不重跑）

## Artifact Manifest（单组）
- JSONL: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1r-func-c-formal-capture-2026-07-23.artifact-manifest.jsonl`
- Summary: `/home/czz/GMrobot/g1_ur10e_disturbance/docs/cross-project/vlm-v1e1r-func-c-formal-capture-2026-07-23.artifact-summary.json`
- group_count: `1`（两帧同组）
