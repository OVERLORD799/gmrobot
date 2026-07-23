# M1H Image Assets + Visual Validation (2026-07-23)

Verdict: **M1H_BUILD_FAIL**

Scope: 非正式 Func-C 样本流程；按约束先做镜像构建门禁，构建失败即停止，不执行视觉 `docker run`。

## Repository / Baseline
- Repo: `/home/czz/GMrobot`
- HEAD at start: `a5ee529`
- Branch: `main` (worktree clean, origin/main sync at start)

## Stage A (Build Once) Execution
- New Dockerfile: `GMRobot/docker/Dockerfile.e01-func-c-m1h`
- Base image: `gmdisturb:e01-func-c-m1e-20260723`
- Single build command (executed exactly once):
  - `docker build -f GMRobot/docker/Dockerfile.e01-func-c-m1h -t gmdisturb:e01-func-c-m1h-20260723 .`
- Logging mode:
  - stdout: `g1_ur10e_disturbance/results/paper_demo/m1h_visual_validation_20260723/meta/build.stdout.log`
  - stderr: `g1_ur10e_disturbance/results/paper_demo/m1h_visual_validation_20260723/meta/build.stderr.log`
  - exit/elapsed: `g1_ur10e_disturbance/results/paper_demo/m1h_visual_validation_20260723/meta/build.exit`
  - No `tee`, no pipe used.

## Build Result (Real Exit)
- Real docker exit code: `1`
- Elapsed: `1s`
- Built image SHA/Created: **N/A (build did not complete)**
- Base resolved digest during build:
  - `gmdisturb:e01-func-c-m1e-20260723@sha256:3364f5165f35136ccbd93d3a7b46ca67f5e106b862c852f7167322572850feee`

## Structural Gate Evidence
- `normalize_container_usd.py` executed and produced:
  - `/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_fixed.usd`
  - SHA256: `acb2151a26baee9ff27dcdfe9c8c5bf2919182747389160f3f621347dc2a057d`
- `normalize_part_usd.py` executed and produced:
  - `/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/part/part_fixed.usd`
  - SHA256: `ccf516872c8501169efa5274cebe4f9740b091914cdd6ff9e52082ddbfe10441`
- Failure happened in same `RUN` hard gate step:
  - Python traceback: `AttributeError: 'Prim' object has no attribute 'GetDescendants'`
  - Consequence: build failed by gate design (as required).

## Stage B (Visual Run) Status
- Not executed.
- Reason: Stage A failed; per rule, stop immediately and forbid `docker run`.
- Therefore no frame/image SHA, no Xid snapshot for run, no scene visual checklist.

## Compliance Notes
- Did not overwrite source USD.
- Did not copy host-generated USD into image.
- Did not run build more than once.
- Did not run container after build failure.

