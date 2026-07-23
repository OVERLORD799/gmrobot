# M1J Float Tolerance + Visual Validation (2026-07-23)

Verdict: **M1J_HUMAN_REVIEW_REQUIRED**

Scope: 非正式 Func-C 样本流程；按要求执行 1 次 build + 1 次真实场景 run，并进行视觉门禁核查。

## Repository / Baseline
- Repo: `/home/czz/GMrobot`
- HEAD at start: `5706c47`
- Branch: `main`（worktree clean）

## Stage A (Build Once)
- New Dockerfile: `GMRobot/docker/Dockerfile.e01-func-c-m1j`
- Base image: `gmdisturb:e01-func-c-m1e-20260723`
- Target tag: `gmdisturb:e01-func-c-m1j-20260723`
- Executed times: `1`
- Build command (single execution):
  - `docker build -f GMRobot/docker/Dockerfile.e01-func-c-m1j -t gmdisturb:e01-func-c-m1j-20260723 .`
- Logging:
  - stdout: `g1_ur10e_disturbance/results/paper_demo/m1j_visual_validation_20260723/meta/build.stdout.log`
  - stderr: `g1_ur10e_disturbance/results/paper_demo/m1j_visual_validation_20260723/meta/build.stderr.log`
  - exit/elapsed: `g1_ur10e_disturbance/results/paper_demo/m1j_visual_validation_20260723/meta/build.exit`
  - no `tee`, no pipe

### Static Constraint Check
- `GetDescendants` count in new Dockerfile: `0`
- Tolerance edit location count: `1`
- Gate expression:
  - `assert abs(float(mass) - 0.2) <= 1e-6`
- Expected mass `0.2` unchanged; other gate logic unchanged.

### Build Result
- Real docker exit code: `0`
- Elapsed: `1s`
- Built image SHA: `sha256:c3fd8087df51d5c9811fe192c1e0be61c0224209bb01c7ad4941632bac0f8248`

## Stage B (Run Once, Real GM Scene)
- Run output root: `g1_ur10e_disturbance/results/paper_demo/m1j_visual_validation_20260723/`
- Executed times: `1`
- Image: `gmdisturb:e01-func-c-m1j-20260723`
- Entrypoint override: `--entrypoint /isaac-sim/python.sh`
- Required env:
  - `GMROBOT_V1E01_TARGET_FULL=1`
- Required flags enabled:
  - camera: `--enable_cameras`
  - safety: `--enable_safety --safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml`
  - save camera: `--save_camera --camera_output_dir ... --camera_save_interval 1`
  - max steps 1: `--max_steps 1`
- Mount policy:
  - mounted only `results` + caches
  - no code/YAML/USD host mount
- Logging:
  - stdout: `.../meta/stdout.txt`
  - stderr: `.../meta/stderr.txt`
  - exit/elapsed: `.../meta/run.exit`
  - direct redirection only, no `tee`, no pipe

### Run Result
- Real docker exit code: `0`
- Elapsed: `30s`
- Log grep for `Traceback|FileNotFound|DEVICE_LOST`: no matches
- `nested` rigid-body failure signal: no matches
- Xid pre/post:
  - `meta/xid_pre.txt` lines: `0`
  - `meta/xid_post.txt` lines: `0`
  - new Xid lines: `0`

## Frame Evidence
- Frame path: `g1_ur10e_disturbance/results/paper_demo/m1j_visual_validation_20260723/scene/frame_000000_env0.png`
- SHA256: `1c68b10b21aa8c19bea375cb647dbd7548a040e2fd4e0df9896825bde1832a77`
- PNG validity: `uint8`, shape `(480, 640, 3)` -> PASS

## Visual Gate Assessment
- Exit0: PASS
- No Traceback/FileNotFound/DEVICE_LOST: PASS
- No nestedRB/new Xid: PASS
- PNG uint8 480x640x3: PASS
- White sector disappears: **cannot be reliably auto-verified from single frame script**
- Two-box scale normal: visually plausible but **not machine-reliable**
- A + 20 source parts normal: visually plausible but **count/identity not machine-reliable**
- B complete and filled contents visible: visually plausible but **not machine-reliable**

Because multiple semantic visual checks cannot be reliably confirmed by deterministic script in this one-pass run, final gate is marked:

**M1J_HUMAN_REVIEW_REQUIRED**

## Policy Compliance
- Build retries: `0` (single build only)
- Run retries: `0` (single run only)
- Run failure rerun policy: N/A (run succeeded; no rerun performed)
- Results/generated assets not included in commit.
