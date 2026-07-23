# V1-E2C.1 Dyn-C Config Schema Fix (2026-07-23)

- scope: `V1-E2C.1` Dyn-C complete config schema repair, offline only
- baseline head: `b7487781bdbac956b5913781c28edc7bd34e7b83` (clean start)
- result: schema-mismatch root cause fixed; mapping-section bool now fail-fast

## Applied Fixes

- repaired `configs/e01_dyn_c_capture.yaml` by removing bool entries that were illegally occupying mapping sections:
  - `virtual_hand: false`
  - `vlm: false`
  - `perception: false`
  - `five_stage: false`
- added prebuild schema validation in `config_loader.py` for every section consumed as mapping by `_build_config`:
  - top-level: `disturbance`, `virtual_hand`, `vlm`, `safety`, `ee_track`, `dynamic_sweep`, `batch`, `arm`
  - nested: `vlm.actions`, `vlm.ssh`, `safety.replan`
- validation behavior: fail-fast with `ValueError` if any mapping section is `bool`/list/other non-object.

## Test Coverage

- updated: `scripts/test_v1e2a_dyn_c_config_unit.py`
  - checks `scenario/seed/camera/capture_steps/adjacent_groups` labels
  - runs real `load_config(...)` parse on `e01_dyn_c_capture.yaml`
  - asserts Dyn-C prebuild runtime command does **not** enable `--virtual-hand` or `--vlm` (disable boundary belongs to CLI/runtime command)
- added: `scripts/test_v1e2c1_dyn_c_config_schema_validator_unit.py`
  - mapping-section bool negative case (`virtual_hand: false`, `vlm: false`) must fail fast.

## Invariants Kept

- capture-frame contract unchanged: `239/240/241` and `309/310/311`
- primary capture steps unchanged: `240/310`
- trajectory hash identity unchanged:
  - Dyn-C: `7beb111400ccc2f8cd5d9ed1ab19192705714ff3d6cbc7dc3ccb16154c74683c`
  - Dyn-B seed43: `759e778529465b118250e90b84d9cfafade6dca9c7011603794f05724d9d164e`
- E2C raw failure record retained (for traceability):
  - `AttributeError: 'bool' object has no attribute 'get' (config virtual_hand schema)`
  - `e2b_raw_failure_status: retained`

## Verification Log

- pycompile: pass
- unit: pass
- full config load: pass
- prebuild: pass
- import closure prebuild: pass
- manifest validation: pass
- sensitive scan: pass (no newly introduced secret values; only known field names such as `password`)
- diffcheck (`git diff --check`): pass

## Next-Step Guardrail

- allow exactly **1 rebuild + 1 final capture**
- if any pre-AppLauncher config/import error recurs: `AUTOMATION_LOOP_STOP`
