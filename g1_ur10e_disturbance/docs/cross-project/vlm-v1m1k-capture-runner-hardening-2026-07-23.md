# VLM V1-M1K Capture Runner Hardening - 2026-07-23

## Outcome
- Implemented a reusable host-side one-shot runner to harden future Docker capture execution evidence persistence.
- Integrated the runner into `run_e01_func_c_capture.sh` (smoke and formal capture paths) with minimal scope.
- No formal capture rerun was performed in this milestone.

## Why This Milestone
- Prior recovery commit `5fdc79a` remains correctly labeled `CAPTURE_FAIL`.
- Root cause: `meta/run_status.json` remained placeholder (`exit=999`, null timestamps) after a single formal Docker run.
- Per milestone constraint, that run cannot be replayed or promoted retroactively.

## What Was Changed
- Added `GMRobot/scripts/capture_one_shot_runner.py`:
  - Creates result directory and pre-run status metadata first.
  - Refuses nonempty result directory when requested (fail-closed guard for formal one-shot runs).
  - Executes exactly one command argv via `subprocess.run` (no shell pipeline, no tee).
  - Atomically persists `run_status.json` before and after run (`os.replace` temp-file swap).
  - Records:
    - command argv
    - UTC start/end timestamps
    - monotonic elapsed seconds
    - shell-observable exit code
    - raw returncode and signal name when applicable
    - timeout flag
  - Preserves command stdout/stderr into dedicated files.
  - Fails closed if final status persistence fails.
- Updated `g1_ur10e_disturbance/scripts/run_e01_func_c_capture.sh`:
  - Replaced `tee` pipeline execution with runner-based one-shot command invocation.
  - Captures stdout/stderr separately in `meta/capture_stdout.txt` and `meta/capture_stderr.txt`.
  - Uses `--refuse-nonempty-dir` on formal capture path.
  - Keeps no-rerun gate semantics (`formal_capture_done.flag` check).
- Updated `GMRobot/scripts/analyze_e01_func_c_capture.py`:
  - Post-proof now scans both stdout and stderr files for smoke/capture.
- Added focused offline unit tests:
  - `GMRobot/scripts/test_capture_one_shot_runner_unit.py`
  - Covers success, nonzero exit, signal exit, timeout, argv/quoting, nonempty-dir refusal, and atomic write hygiene (no temp residue).

## Verification
- Passed: `python3 GMRobot/scripts/test_capture_one_shot_runner_unit.py`
- Existing unrelated baseline failure observed in current workspace:
  - `python3 GMRobot/scripts/test_e01_func_c_capture_unit.py`
  - Fails on frozen hash expectation mismatch for `container_full_visual.usd` (expected `60ef...`, actual `f392...`), not introduced by this milestone's runner changes.

## Constraints Respected
- No Docker/Isaac/network/POST run initiated by this milestone work.
- No edits to B0-B4 frozen configs/results, safety thresholds, USD assets, or historical result files.
- No remote services accessed.

## Explicit Status of Prior Recovery Artifact
- Commit `5fdc79a` **remains `CAPTURE_FAIL`**.
- It **cannot be retroactively promoted** under one-shot evidence policy because required real exit/timing fields were not reliably persisted at run time.

## Recommended Next Milestone
- Run the next formal one-shot capture using the hardened runner path and produce fresh immutable evidence bundle for label review gating.
