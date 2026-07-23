# V1-M1T Dyn-B AppLauncher Runtime Repair (2026-07-23)

## 结论

- Verdict: `STOP_DYN_B_RUNTIME_LOOP`
- 原因：在“最多两次顺序 Docker smoke”硬预算下，未取得满足要求的 **AppLauncher + outer_lateral_patrol + 1 step** 成功运行。
- 严禁继续 Dyn-B capture，直至外部环境/镜像重建并重新过本里程碑。

## 静态根因对比（先证据后修复）

- M1M 成功链路使用镜像默认 `ENTRYPOINT` 与容器内既有启动环境，命令为 `bash -lc "/isaac-sim/python.sh ... gm_state_machine_agent.py ..."`。
- M1Q/M1S 失败链路使用直接 `--entrypoint /isaac-sim/python.sh` 跑 `run_phase3.py`，并在 M1R/M1S 引入自定义 `PYTHONPATH` 注入尝试（`omni.kit.pip_archive`），触发 NumPy 命名空间混装风险。
- M1S 的注入还存在 shell 展开缺陷（`$USD_LIBS`/`$PIP_ARCHIVE` 在宿主被提前展开为空），日志中先出现 `ls: cannot access ...`，随后仍落入 ABI 错误。
- 镜像元数据确认：
  - `gmdisturb:e01-func-c-m1j-20260723` `Entrypoint=["/opt/projects/g1_ur10e_disturbance/docker/entrypoint.sh"]`
  - `Cmd=["phase3","--help"]`
  - 说明 canonical 路径应优先复用 `docker/run.sh` + entrypoint，而非覆盖为裸 `python.sh`。

## 本里程碑两次 smoke（严格顺序，逐条记录）

- Smoke #1（失败，修正点明确：误用容器裸 `python3`）
  - 结果目录：`g1_ur10e_disturbance/results/paper_demo/v1m1t_smoke_20260723`
  - 退出：`exit_code=1`
  - 关键错误：`ModuleNotFoundError: No module named 'numpy'`
  - 精确命令（runner 内 argv）：
    - `bash -lc "cd /home/czz/GMrobot/g1_ur10e_disturbance/docker && TAG=gmdisturb:e01-func-c-m1j-20260723 RESULTS_DIR=/home/czz/GMrobot/g1_ur10e_disturbance/results ./run.sh bash -lc \"set -euo pipefail; python3 - <<'PY' ... ; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py ...\""`

- Smoke #2（失败，唯一允许修正后再次验证）
  - 结果目录：`g1_ur10e_disturbance/results/paper_demo/v1m1t_smoke2_20260723`
  - 退出：`exit_code=1`
  - NumPy 溯源文件已产出：`meta/numpy_origin.json`
  - `run_phase3.py` 参数门禁失败：`invalid choice: 'outer_lateral_patrol'`
  - 精确命令（runner 内 argv）：
    - `bash -lc "cd /home/czz/GMrobot/g1_ur10e_disturbance/docker && TAG=gmdisturb:e01-func-c-m1j-20260723 RESULTS_DIR=/home/czz/GMrobot/g1_ur10e_disturbance/results ./run.sh bash -lc \"set -euo pipefail; /isaac-sim/python.sh -c \\\"import json,numpy as np; ...\\\"; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py --headless --seed 43 --scenario outer_lateral_patrol --max_steps 1 --progress_interval 1 --motion_source_label scripted_g1_outer_lateral_patrol --output_csv /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1m1t_smoke2_20260723/safety_logs/phase3.csv\""`

## NumPy 来源核对

- 取自 `v1m1t_smoke2_20260723/meta/numpy_origin.json`：
  - `numpy_file=/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/__init__.py`
  - `numpy_random_file=/isaac-sim/kit/python/lib/python3.11/site-packages/numpy/random/__init__.py`
  - `numpy_version=2.4.6`
- 结论：`numpy` 与 `numpy.random` 同源于 kit site-packages，本次未出现 pip_prebundle 混装。

## 代码修复（不改历史证据）

- 移除误导性 M1R 守卫注入路径，不再拼接 `omni.kit.pip_archive` 到 `PYTHONPATH`：
  - `g1_ur10e_disturbance/e01_dyn_b_runtime_guard.py`
  - `g1_ur10e_disturbance/scripts/run_e01_dyn_b_abi_preflight.sh`
- 新增 canonical 命令构造（先记录 NumPy 来源，再跑真实 AppLauncher 一步）：
  - `canonical_dyn_b_smoke_shell()` in `e01_dyn_b_runtime_guard.py`
- 强化导入预检：若 `numpy` 与 `numpy.random` 非同源树则 fail-fast：
  - `g1_ur10e_disturbance/scripts/isaac_abi_import_preflight.py`
- 新增/更新测试（命令构造 + 禁止混装注入）：
  - `g1_ur10e_disturbance/scripts/test_e01_dyn_b_runtime_guard_unit.py`

## Canonical Future Dyn-B 启动路径（后续仅供重建后使用）

- 目标：复用仓库已验证 Isaac 启动环境（`docker/run.sh` + image entrypoint），禁止自定义 `pip_prebundle` 注入。
- 规范命令：
  - `cd /home/czz/GMrobot/g1_ur10e_disturbance/docker`
  - `TAG=gmdisturb:e01-func-c-m1j-20260723 RESULTS_DIR=/home/czz/GMrobot/g1_ur10e_disturbance/results ./run.sh bash -lc "<canonical_dyn_b_smoke_shell 生成的命令>"`
- 说明：当前镜像内 `run_phase3.py` 不含 `outer_lateral_patrol` 选项，需外部环境重建后再验证，不得直接恢复 capture。
