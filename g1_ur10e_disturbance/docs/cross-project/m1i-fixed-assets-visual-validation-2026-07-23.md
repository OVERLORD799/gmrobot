# M1I Fixed Assets + Visual Validation (2026-07-23)

Verdict: **M1I_BUILD_FAIL**

Scope: 非正式 Func-C 样本流程；严格执行先构建门禁，构建失败即停止，不执行视觉 `docker run`。

## Repository / Baseline
- Repo: `/home/czz/GMrobot`
- HEAD at start: `a7d6ba8`
- Branch: `main`（worktree clean，origin 同步）

## Stage A (Build Once) Execution
- New Dockerfile: `GMRobot/docker/Dockerfile.e01-func-c-m1i`
- Base image: `gmdisturb:e01-func-c-m1e-20260723`
- Static scan in Dockerfile embedded Python:
  - `GetDescendants_count=0`
- Single build command (executed exactly once):
  - `docker build -f GMRobot/docker/Dockerfile.e01-func-c-m1i -t gmdisturb:e01-func-c-m1i-20260723 .`
- Logging mode:
  - stdout: `g1_ur10e_disturbance/results/paper_demo/m1i_visual_validation_20260723/meta/build.stdout.log`
  - stderr: `g1_ur10e_disturbance/results/paper_demo/m1i_visual_validation_20260723/meta/build.stderr.log`
  - exit/elapsed: `g1_ur10e_disturbance/results/paper_demo/m1i_visual_validation_20260723/meta/build.exit`
  - No `tee`, no pipe used.

## Build Result (Real Exit)
- Real docker exit code: `1`
- Elapsed: `1s`
- Base resolved digest during build:
  - `gmdisturb:e01-func-c-m1e-20260723@sha256:3364f5165f35136ccbd93d3a7b46ca67f5e106b862c852f7167322572850feee`
- Built image SHA/Created: **N/A (build did not complete)**

## Structural Gate Evidence
- `normalize_container_usd.py` executed and produced:
  - `/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_fixed.usd`
  - SHA256: `acb2151a26baee9ff27dcdfe9c8c5bf2919182747389160f3f621347dc2a057d`
- `normalize_part_usd.py` executed and produced:
  - `/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/part/part_fixed.usd`
  - SHA256: `ccf516872c8501169efa5274cebe4f9740b091914cdd6ff9e52082ddbfe10441`
- Gate failure (same `RUN` hard gate step):
  - `AssertionError: FATAL: /Root mass must be 0.2, got 0.20000000298023224`

## Stage B (Visual Run) Status
- Not executed.
- Reason: Stage A failed; per rule, stop immediately and forbid `docker run`.
- Therefore no image inspect SHA for new tag, no frame path/SHA, no Xid/nvidia-smi runtime snapshot, and no visual checklist execution.

## Gate Checklist
- Build gate:
  - Docker build real exit is 0: **FAIL**
  - Embedded Python static `GetDescendants=0`: **PASS**
  - Container/part fixed assets generated in build: **PASS**
  - Structural rigid-body nesting gate reached: **PARTIAL (container check passed; part mass check failed)**
- Visual gate:
  - Single run only: **NOT EXECUTED (blocked by build fail)**
  - Exit0 / no Traceback / no FileNotFound / no DEVICE_LOST / no nested RB / no new Xid: **NOT EXECUTED**
  - PNG uint8 480x640x3 and manual visual checks: **NOT EXECUTED**

## Compliance Notes
- Kept M1I policy of exactly one real build attempt.
- Did not run container after build failure.
- Results/generated assets are not part of git commit.
- This document is for non-formal sample validation record.
