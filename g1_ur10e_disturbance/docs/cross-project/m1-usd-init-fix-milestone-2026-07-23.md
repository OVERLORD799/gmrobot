# M1-USD-Init Fix Milestone (2026-07-23)

## Verdict: **M1_GATES_PASS**

All structural gates and smoke test passed. Func-C capture path is opt-in, frozen defaults unchanged.

---

## 1. Fix Summary

### Container (box_A)
- **Root cause**: `container.usd` has nested RigidBodyAPI at `/Root/Container` and `/Root/Container/Ref` — two active rigid bodies in parent-child hierarchy.
- **Isaac warning**: "nested RigidBodyAPI produces unpredictable results"
- **Fix**: Generated `container_fixed.usd` — single RigidBodyAPI at `/Root/Container`, kinematic enabled (static box = fixed, not dynamic).
- **Script**: `GMRobot/scripts/normalize_container_usd.py`
- **SHA256**: `acb2151a26baee9ff27dcdfe9c8c5bf2919182747389160f3f621347dc2a057d`

### Parts (Part_1..20)
- **Root cause**: `part_5000.usd` has RigidBodyAPI at child prim `/Root/container_part_fixed_5000`, not at root. When Isaac spawns and applies `rigid_props` + `mass_props`, it may create a second RigidBodyAPI at the spawn prim, producing nested rigid bodies and causing `modify_mass_properties` to fail.
- **Fix**: Generated `part_fixed.usd` — RigidBodyAPI + MassAPI at `/Root`, no rigid body on any child.
- **Script**: `GMRobot/scripts/normalize_part_usd.py`
- **SHA256**: `ccf516872c8501169efa5274cebe4f9740b091914cdd6ff9e52082ddbfe10441`

### Opt-in gating
- Default: All scenarios (B0–B4, D1A/D1B) use original `container.usd` + `part_5000.usd`. Frozen semantics unchanged.
- Func-C enabled (`GMROBOT_V1E01_TARGET_FULL=1`):
  - `box_A` → `container_fixed.usd` (single kinematic rigid body)
  - `box_B` → `container_full_visual.usd` (visual-only, no physics) — unchanged
  - `Part_1..20` → `part_fixed.usd` (root-prim RigidBodyAPI + MassAPI)

---

## 2. Asset Structure Gates

| Gate | Asset | Result |
|---|---|---|
| Single active RigidBodyAPI | container_fixed.usd | ✅ 1 at `/Root/Container`, kinematic=True |
| Single active RigidBodyAPI | part_fixed.usd | ✅ 1 at `/Root` |
| MassAPI present | part_fixed.usd | ✅ 1 at `/Root`, mass=0.2 |
| No child rigid bodies | part_fixed.usd | ✅ |
| No nested rigid bodies | container_fixed.usd | ✅ |
| Frozen originals unchanged | container.usd, part_5000.usd | ✅ SHA256 matches |

---

## 3. Smoke Test

| Item | Value |
|---|---|
| Image tag | `gmdisturb:e01-func-c-m1-fix-20260723` |
| Image SHA256 | `d8bef5e28f319e93903f5185a313c68f10a817eb5a08f17aa2f3672dd51e6b58` |
| Base image | `gmdisturb:e01-dyn-a-20260722` (frozen) |
| Smoke exit code | **0** |
| Steps | 1 (diagnostic) |
| Nested RigidBodyAPI warnings | **0** ✅ |
| Box B modify_rigid warnings | 1 (expected: visual-only USD has no rigid body) |
| Box B modify_collision warnings | 1 (expected: visual-only USD has no collision) |
| Frame0 PNG | `smoke_scene/frame_000000_env0.png` |
| Frame0 SHA256 | `c28596ba5f1caa87deb6899bc08509bc8b413a976afd0b16b6d93a8b5f740649` |
| Frame0 size | 186,050 bytes |
| Original faulty frame0 | 187,432 bytes (white fan scatter) |

---

## 4. Offline Regression Tests

All tests pass (`PASS test_e01_func_c_capture_unit`):
- ✅ Default-off semantics unchanged
- ✅ Func-C enables box_A→container_fixed, box_B→container_full_visual, parts→part_fixed
- ✅ Frozen asset hashes unchanged (6 assets verified)
- ✅ PXR read-only structure assertions
- ✅ Normalized asset structure gate
- ✅ No secrets in new files

---

## 5. Changed Files (M1)

| Path | Change |
|---|---|
| `GMRobot/scripts/normalize_container_usd.py` | NEW: reproducible container USD normalization |
| `GMRobot/scripts/normalize_part_usd.py` | NEW: reproducible part USD normalization |
| `GMRobot/source/.../shadow/target_full_override.py` | +resolve_part_usd_name, +box_A fixed asset, +CONTAINER_FIXED_USD_NAME |
| `GMRobot/source/.../gmrobot_env_cfg.py` | Func-C: box_A→container_fixed, parts→part_fixed |
| `GMRobot/scripts/test_e01_func_c_capture_unit.py` | +frozen hashes, +asset structure gates, +switching tests |
| `GMRobot/docker/Dockerfile.e01-func-c` | +normalize scripts |
| `g1_ur10e_disturbance/scripts/run_e01_func_c_capture.sh` | +container_fixed/part_fixed mounts |
| `.gitignore` / `GMRobot/.gitignore` | +generated USD assets |

**Generated assets (gitignored)**:
- `GMRobot/source/.../assets/container_fixed.usd`
- `GMRobot/source/.../assets/part/part_fixed.usd`

---

## 6. Stop Boundary

- ✅ M1 complete: all structural gates + smoke passed
- ⛔ NOT a Func-C positive sample recovery — that requires a fresh formal capture (separate milestone)
- ⛔ No formal Func-C capture executed in M1
- ⛔ Docker image `gmdisturb:e01-func-c-m1-fix-20260723` built but NOT a frozen release

---

## 7. Remaining Blockers for Func-C Recovery

1. Fresh formal capture required with `GMROBOT_V1E01_TARGET_FULL=1` and the M1-fixed assets
2. Frame0 visual verification (human review)
3. Full episode gate audit
4. VLM readiness decision
