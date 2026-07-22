# M1E — container_full_visual.usd Deterministic Generation Fix

**Date:** 2026-07-23
**Base:** `gmdisturb:e01-func-c-m1-fix-20260723` (M1 structural fix)
**Image:** `gmdisturb:e01-func-c-m1e-20260723` (sha256:3364f5165f35136ccbd93d3a7b46ca67f5e106b862c852f7167322572850feee)

## Verdict: **STRUCTURAL_PASS_VISUAL_UNVERIFIED** (= M1E FAIL)

All structural gates PASS. **However, `STRUCTURAL_PASS_VISUAL_UNVERIFIED` is a formal M1E FAIL:**
the visual gate could not be confirmed, therefore:

- **Func-C official capture is PROHIBITED.** No Func-C dataset may be collected from
  this image until visual verification passes.
- **No M1E-based dataset is authorized.** Any dataset claiming M1E provenance is invalid.

Visual inspection could not be completed because the 1-step smoke screenshot capture
failed (Isaac Sim 5.1 API mismatch — `capture_next_frame` and `omni.kit.viewport_legacy`
unavailable in headless kit 5.1).

## Changes

1. **Generator** (`scripts/generate_container_full_visual_usd.py`):
   - Added explicit `primvars:displayColor` — source has `None` displayColor and OmniPBR MDL materials that are not copied
   - Container: green `(0.2, 0.6, 0.28)`
   - FilledContent items: warm visible tone `(0.7, 0.45, 0.22)`
   - Verified `FROZEN_SOURCE_SHA256` = `ff4d02a2...` matches actual source

2. **Dockerfile** (`docker/Dockerfile.e01-func-c-m1e`):
   - Base image: `gmdisturb:e01-func-c-m1-fix-20260723` (not old e01)
   - Uses `/isaac-sim/kit/python/bin/python3` with `omni.usd.libs` PYTHONPATH/LD_LIBRARY_PATH
   - Installs numpy via pip for isaac-sim Python
   - Lightweight pxr import verification before generation
   - Generates `container_full_visual.usd` at build time

3. **Tests** (`scripts/test_generate_container_full_visual_usd_unit.py`):
   - Moved from gitignored `tests/` to tracked `scripts/`
   - 10/10 static tests pass

## Structural Gates (PASS)

| Gate | Value | Expected | Status |
|------|-------|----------|--------|
| mesh_count | 31 | 31 | PASS |
| rigid_body_api_count | 0 | 0 | PASS |
| collision_api_count | 0 | 0 | PASS |
| mass_api_count | 0 | 0 | PASS |
| physics_scene_count | 0 | 0 | PASS |
| container_x_span_m | 0.3800 | 0.38±0.04 | PASS |
| filled_item_span_m | 0.1662 | 0.17±0.02 | PASS |
| grid_x_span_m | 0.2750 | 0.275±0.035 | PASS |
| grid_y_span_m | 0.4400 | 0.44±0.05 | PASS |
| defaultPrim | /FullContainer | /FullContainer | PASS |
| has_world_prim | False | False | PASS |
| part_n_pattern | False | False | PASS |
| nested_rb_paths | [] | [] | PASS |

| Item | Value |
|------|-------|
| Source SHA256 | `ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0` |
| Structural fingerprint | `bb90e8cbf865dd9b...` |
| Image SHA | `sha256:3364f5165f35136ccbd93d3a7b46ca67f5e106b862c852f7167322572850feee` |
| Output size | 40.7 MB |
| Container displayColor | (0.2, 0.6, 0.28) green |
| FilledContent displayColor | (0.7, 0.45, 0.22) warm |

## Smoke

- **The single smoke attempt has been consumed.** No further smoke runs are planned without
  fixing the screenshot API.
- 1-step smoke: scene loaded (31 meshes, /FullContainer), but `frame0.png` **not produced**
  — `capture_next_frame` and `omni.kit.viewport_legacy` unavailable in Isaac Sim 5.1 headless kit.
- **No PNG evidence exists.** Do NOT claim white fan disappearance is confirmed, ContainerB
  filled contents visible, or any other visual property — all visual claims are unverified.
- Stdout saved to `results/paper_demo/m1e_visual_fix_20260723/stdout.log` (ignored, not committed).
- Visual inspection remains deferred until a working screenshot pipeline is available.

## Files Changed

- `GMRobot/scripts/generate_container_full_visual_usd.py` — add displayColor, verified SHA
- `GMRobot/docker/Dockerfile.e01-func-c-m1e` — base image fix, isaac-sim Python env
- `GMRobot/scripts/test_generate_container_full_visual_usd_unit.py` — moved from tests/
- (deleted) `GMRobot/scripts/m1e_smoke.py` — removed (API errors, not committed)
- (deleted) `GMRobot/tests/test_generate_container_full_visual_usd_unit.py` — moved

## Results Directory (ignored, not committed)

`results/paper_demo/m1e_visual_fix_20260723/`
  - `stdout.log` — full smoke log
  - `smoke_report.json` — smoke report
  - `m1e_report.json` — evidence report (copied to cross-project as JSON)
