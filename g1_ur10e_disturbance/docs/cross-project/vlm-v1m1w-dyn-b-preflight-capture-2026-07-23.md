# V1-M1W Dyn-B 0-POST Runtime Preflight Capture (2026-07-23)

## Verdict

- **DYN_B_PREFLIGHT_CAPTURE_FAIL**
- `next_gate=STOP_NO_RETRY`
- formal run count: **1** (exactly one; no retry; no concurrent container)

## Fixed Inputs and Constraints

- anchor commit: `a62119c`
- image tag: `gmdisturb:e01-dyn-b-clean-m1v1-20260723`
- image SHA (expected=actual): `sha256:19112b9c1e8f63c04e8ef777840da823f0323b55f950f432f27ea8ba9d4cf14f`
- rebuilds: `0`
- host source mount: **forbidden and not used**
- scenario: `outer_lateral_patrol`
- motion source label: `scripted_g1_outer_lateral_patrol`
- seed: `43`
- max steps: `341` (configured to cover step `331`)
- POST target: `0`

## Pre-save Provenance

Saved under:

- `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w_20260723/meta`

Captured before formal run:

- git head / anchor commit snapshot
- image inspect JSON and SHA verification
- config copy (`e01_dyn_b_capture.yaml`)
- source provenance SHA list (source-closure set)
- GPU pre snapshot and Xid pre snapshot
- exact formal command file

## One-shot Execution Record

- runner: `GMRobot/scripts/capture_one_shot_runner.py`
- status file: `meta/run_status.json`
- start UTC: `2026-07-23T06:42:21.641+00:00`
- end UTC: `2026-07-23T06:42:21.953+00:00`
- elapsed: `0.312463794` s
- runner exit: `1` (`returncode_raw=1`, `postcheck_failed=true`)

Primary runtime stderr:

```text
File "/isaac-sim/python.sh", line 21
  echo "There was an error running python"
SyntaxError: invalid syntax. Perhaps you forgot a comma?
```

Interpretation:

- the container command failed before simulation/capture, because `/isaac-sim/python.sh` was interpreted as Python source.
- by policy, this milestone remains **single-shot** and is **not rerun**.

## Fail-closed Audit

- no `Traceback` hit in stdout/stderr
- no module/ABI/ParamSpec/extension/device-lost hit in stdout/stderr
- `POST` count in stdout/stderr: `0`
- Xid pre/post: `0 -> 0` (no new Xid)

Required artifacts:

- frames `219,220,221,329,330,331`: **all missing** (therefore PNG validity = fail)
- `safety_logs/phase3.csv`: **missing**
- `meta/camera_pose.json`: **missing**
- `meta/body_poses.jsonl`: **missing**
- NumPy pre/post json: **missing**
- typing_extensions pre/post json: **missing**

Derived gates (must fail-closed due missing evidence):

- G1 ROI visible in frame 220 and 330: **not observable (FAIL)**
- centroid displacement `220 -> 330 >= 20 px`: **not observable (FAIL)**
- phases must be exactly `lateral_positive_sweep` and `lateral_negative_sweep`: **not observable (FAIL)**
- safety window `190..340` 151 steps all `ALLOW`, zero STOP/SLOW/replan: **not observable (FAIL)**
- conservative separation margin `>=0.10m`: **not observable (FAIL)**
- G1 not fallen: **not observable (FAIL)**
- no red ball/proxy: **not observable (FAIL)**

## Residual Audit

- residual container for image `gmdisturb:e01-dyn-b-clean-m1v1-20260723`: **none**
- residual capture process: **none**

## Provenance Labels

- `dynamic=true`
- `provisional=true`
- `reviewer_approved=false`
- scripted locomotion evidence (not human hand/gesture/PPE)
- not VLM output

## Evidence Root

- `g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w_20260723/`
