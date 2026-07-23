# V1-M1Z8 Dyn-B TTC Audit Image Smoke（2026-07-23）

- verdict: `M1Z8_AUDIT_SMOKE_PASS`
- next_gate: `PASS_ONLY_ONE_FORMAL_M1Z9_CAPTURE_REQUEST_ALLOWED`
- policy: `STOP_NO_RETRY`（build 仅 1 次，smoke 仅 1 次，未触发重试）

## 前置核验（build 前）
- HEAD: `7eac42a76c7518a0f3ed164b48a9a203a35e1cb4`（匹配要求）
- worktree: clean（`git status --porcelain` 为空）
- 宿主机 M1Z7 相关校验:
  - `python3 -m py_compile scripts/run_phase3.py scripts/dyn_b_per_step_audit_writer.py scripts/dyn_b_per_step_audit_analyzer.py`
  - `python3 scripts/test_dyn_b_per_step_audit_writer_unit.py`
  - `python3 scripts/test_dyn_b_per_step_audit_analyzer_unit.py`
  - 结果: 全 PASS

## Dockerfile 与镜像策略
- 复用已验证 clean B4 路径: `docker/Dockerfile.e01-dyn-b-clean-m1z4`
- Dockerfile SHA256: `3a728249ab63e052469f5cdc05ec5ee97f5ddcb4007df1a075dc4f000635ee51`
- Dockerfile 约束核验: 仅 `FROM/WORKDIR/COPY/LABEL`；无 `RUN`、无 `pip install`、无 quarantine、无 NumPy/typing_extensions/系统包变更
- 新镜像 tag: `gmdisturb:e01-dyn-b-ttc-audit-m1z8-20260723`
- 新镜像完整 SHA: `sha256:1707dec1b229b97eb493c433d7ad60f886a0f304a4bc6558e5792c52155dfc1d`
- 历史关键镜像未覆盖:
  - `defe95e7...` => `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
  - `f81e59ce...` => `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c`
  - `962de1e3...` => `sha256:962de1e3f5e9c761d5106c660af7e7dfdbc79319194839a284a06e64dfb45e83`

## 唯一一次 1-step AppLauncher smoke
- 执行次数: `1`
- 命令形态: `docker/run.sh --tag ... phase3 ...`（遵循 ENTRYPOINT；未重复 `/isaac-sim/python.sh`）
- 关键参数: `--headless --max_steps 1 --output_csv ... --dyn-b-per-step-audit-csv ...`
- raw exit: `0`
- PROGRESS/step=1 证据: `phase3.csv` 中 `policy_steps=1`
- 禁止项执行情况: 未执行正式 capture、VLM/perception/GDINO/SAM2/five-stage、网络 POST、凭据读取

## CSV 与 TTC 审计核验
- 常规 CSV: `results/paper_demo/v1e01_dyn_b_ttc_audit_smoke_m1z8_20260723/safety_logs/phase3.csv`（非空）
- 专用审计 CSV: `results/paper_demo/v1e01_dyn_b_ttc_audit_smoke_m1z8_20260723/safety_logs/phase3_dyn_b_per_step_audit.csv`（非空）
- 专用审计 CSV 行数: 恰好 `header + 1`（2 行）
- header 含 M1Z7 新字段:
  - TTC: `ttc_observed_s`, `ttc_forecast_s`
  - approach/velocity: `approach_rate_mps`, `relative_velocity_mps`
  - provenance: `ttc_observed_source`, `ttc_forecast_source`, `approach_rate_source`, `relative_velocity_source`
- 数据列数与 header 一致；离线 analyzer 可读取（`--step-start 0 --step-end 0` 下 pass）
- ALLOW 行 TTC 为 `inf`，且 provenance 明确，符合“可为 null/inf 但来源必须明确”

## 运行后安全复核
- NumPy 单根: pre/post 均为 true（单根路径）
- ParamSpec: pre/post 均为 true
- Traceback: `0`
- DEVICE_LOST: `0`
- POST: `0`
- 新 Xid: 无法直接读内核缓冲（权限限制，已记录为 unavailable，未发现 DEVICE_LOST）
- 残留容器: 无
- 残留进程（`kit/isaac-sim` 精确探测）: 无

## 元数据清单（build 前 + smoke 后）
- 目录: `results/paper_demo/v1e01_dyn_b_ttc_audit_smoke_m1z8_20260723/meta/`
- 关键文件:
  - `head.txt`
  - `dockerfile_sha256.txt`
  - `source_sha256.json`
  - `config_sha256.json`
  - `old_key_images_pre.json`
  - `gpu_pre.txt`, `gpu_post.txt`
  - `xid_pre.log`, `xid_post.log`
  - `numpy_paramspec_expected.json`
  - `smoke_command.txt`
  - `smoke_exit_code.txt`
  - `numpy_origin_pre.json`, `numpy_origin_post.json`
  - `typing_extensions_pre.json`, `typing_extensions_post.json`
  - `dyn_b_analyzer_0_0.json`
  - `post_validation.json`
