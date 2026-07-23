# V1-M1Z3 Dyn-B formal reviewable preflight (2026-07-23)

## Verdict

- **verdict:** `DYN_B_REVIEWABLE_PREFLIGHT_FAIL_FINAL`
- **next_gate:** `STOP_NO_RETRY`
- run_count=`1` / retry_count=`0` / image_rebuild=`false` / runtime_code_modified=`false`
- VLM / perception / SAM2 / five-stage：**未运行**
- 标签：**未自动批准**（仍为 provisional）

## Fixed identity

| Field | Value |
| --- | --- |
| HEAD | `c0eeaf771efc2d56f4a89a2cba11e416c31af268` |
| image | `gmdisturb:e01-dyn-b-clean-m1z2-20260723` |
| image SHA | `sha256:84b0bdbfb50f3912abd3d55cc2cb9f17a43be82b9bae161df04fab2520777c28` |
| results | `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z3_20260723/` |

## Scenario (as executed)

- seed=`43`, scenario=`outer_lateral_patrol`
- motion_source_label=`scripted_g1_outer_lateral_patrol`
- max_steps=`341`
- camera pos=`0.45,0.0,2.7` / rot=`0.7071,0.0,0.7071,0.0`（env override，default-off）
- capture steps=`219,220,221,329,330,331`

## Launcher

Canonical shape only:

```text
docker/run.sh --tag IMAGE --results RESULTS bash -lc \
  'set -euo pipefail; /isaac-sim/python.sh .../run_phase3.py ...'
```

- first payload = `bash -lc`（**未**把 `/isaac-sim/python.sh` 作为 `run.sh` 第一参数）
- 未挂载宿主机源码（仅 results/cache）
- 通过 `GMRobot/scripts/capture_one_shot_runner.py` 记录 exit / elapsed / argv / stdout / stderr

## Failure (primary)

仿真在写 `--dyn-b-per-step-audit-csv` 时崩溃：

```text
NameError: name 'csv' is not defined
  File ".../run_phase3.py", line 977, in main
    _dyn_b_per_step_audit_writer = csv.DictWriter(
```

- 失败类：`RUNTIME_NAMEERROR_CSV_IMPORT_MISSING`
- runner exit=`86`，elapsed≈`30.86s`
- Traceback 命中 forbid pattern；6 张 PNG 与 `phase3.csv` 缺失
- audit CSV 文件存在但 size=`0`（header 未写出）；`body_poses.jsonl` size=`0`
- `camera_pose.json` 已写出且与设计位姿一致（崩溃前 sidecar）
- 说明：M1Z2 smoke 为 `max_steps=1` 且**未**启用 per-step audit，故未覆盖此路径；固定 HEAD 宿主机源码同样缺少 `import csv`。本轮按策略**不修码、不调参、不重跑、不重建镜像**。

## Gate summary

| Gate group | Result |
| --- | --- |
| Runtime exit=0 / no Traceback | **FAIL** |
| NumPy pre/post 单根 `1.26.0` | PASS |
| ParamSpec pre/post=`true` | PASS |
| POST=`0` | PASS |
| 无新增 Xid / 无残留容器或 compute | PASS |
| Geometry 190..340（151 行、ALLOW、margin、phase） | **FAIL**（0 行） |
| Visual 220/330 PNG + ROI + 质心位移 | **FAIL**（无帧） |

## Labels (unchanged)

- risk_type=`dynamic`
- label_status=`provisional`
- reviewer_approved=`false`
- motion provenance=`scripted_g1_outer_lateral_patrol`
- synthetic/scripted=`true` / human_hand=`false` / PPE=`false` / VLM_output=`false`

## Policy

- results **不提交**
- 仅提交本轮文档
- 即使失败也不得启动 VLM/SAM2，不得自动批准标签
- next_gate=`STOP_NO_RETRY`
