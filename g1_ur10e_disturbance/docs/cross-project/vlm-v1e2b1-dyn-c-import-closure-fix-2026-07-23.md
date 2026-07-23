# V1-E2B.1 Dyn-C Import Closure Fix (Offline Only)

- baseline HEAD: `2c5ee80` (exact match), worktree clean before edits
- scope: offline only, no image build, no container run
- target: fix Dyn-C mirror image local `python import` closure for `scripts/run_phase3.py`
- gate: `IMPORT_CLOSURE_FIX_ONLY`
- E2B raw failure status: `retained`

## Root Cause Reproduction (ModuleNotFoundError)

- old Dyn-C Dockerfile copied only a narrow subset of runtime files, while `run_phase3.py` imports a wider local dependency graph
- dependency closure includes `scripts/dyn_b_per_step_audit_writer.py` and transitive local modules (e.g. `mdp/*`, `vendored/*`, root runtime modules)
- under partial COPY, runtime would hit follow-on `ModuleNotFoundError` as soon as the next missing local module is imported

## Implemented Fix

- add prebuild checker: `scripts/v1e2b1_dyn_c_import_closure_prebuild.py`
- checker behavior:
  - parse Docker `COPY` plan from `docker/Dockerfile.e01-dyn-c-mirrored-m1e2b`
  - recursively compute local import closure from planned entrypoints (default `scripts/run_phase3.py`)
  - verify every required `.py` is copied
  - verify each copied file lands on canonical importable container path: `/opt/projects/g1_ur10e_disturbance/<relative_path>`
  - include `predicted_module_not_found` to avoid single-module hardcode blind spots
- Dockerfile remains copy-only; fix applied by copying:
  - full `scripts/`
  - required package dirs `mdp/` and `vendored/`
  - explicit required root runtime modules
  - no `results`/`token`/`cache` content copied

## Validation (Offline)

- `pycompile`: pass
- `unit`: pass (`test_v1e2b1_dyn_c_import_closure_unit.py`)
- `prebuild import closure`: pass, with:
  - `missing_required_files=[]`
  - `misplaced_required_files=[]`
  - `contains_dyn_b_per_step_audit_writer=true`
- `sensitive`: pass (`COPY` paths do not include `results|token|cache`)
- `diffcheck`: pass (`git diff --check`)

## Next Step Budget

- next action only: `1 rebuild + 1 replacement capture`
