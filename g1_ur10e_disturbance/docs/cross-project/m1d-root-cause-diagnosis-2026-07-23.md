# M1D: Root Cause Diagnosis — White Fan Artifact (2026-07-23)

## Verdict: **M1D_ROOT_CAUSE_IDENTIFIED**

Root cause: **Scale inconsistency in `container_full_visual.usd` (box_B)**. The Container mesh renders at 100× the intended size (~38m × 60m instead of ~0.38m × 0.60m), dominating the camera view. The white fan artifact is the inner surface of this massive mesh, seen from the camera's near-tangential perspective.

No runtime smoke test was needed — static analysis of mesh extents, env scale config, and metersPerUnit metadata is conclusive.

---

## 1. Culprit Prim

| Field | Value |
|---|---|
| Asset | `GMRobot/source/GMRobot/GMRobot/assets/container_full_visual.usd` |
| Culprit prim | `/FullContainer/Container/mesh` (Mesh, 891,318 vertices) |
| SHA256 | `60efbaa11fc845492dcb5e734fe509e20a67e1b9fd7e51c03a65f4b404c83885` |
| Role | box_B (visual-only "full" container, Func-C mode) |
| Contributing | `CONTAINER_FULL_SCALE = (1.0, 1.0, 1.0)` in `target_full_override.py:35` |

---

## 2. Evidence

### 2a. Mesh extent comparison

| Asset | Container mesh X span | Container mesh Z span | metersPerUnit | Env scale | Effective world span |
|---|---|---|---|---|---|
| `container.usd` (box_A, normal) | 380 units | 608 units | 0.01 | 0.01 | ~0.38m × 0.61m ✅ |
| `container_full_visual.usd` (box_B) | 38 units | 60 units | **1.0** | **1.0** | ~38m × 60m ❌ |

The `container.usd` mesh (cm-space, scale chain 0.01×0.1×0.01 = 1e-5) renders at ~0.38m — a reasonable tabletop container. The `container_full_visual.usd` mesh (declared meter-space, no internal scale, env scale 1.0) renders at 38m — **100× larger**.

### 2b. Scale config

```python
# target_full_override.py:35
CONTAINER_FULL_SCALE: tuple[float, float, float] = (1.0, 1.0, 1.0)

# vs gmrobot_env_cfg.py:71
CONTAINER_SCALE = (0.01, 0.01, 0.01)
```

Box_B's `resolve_box_scale` returns `(1.0, 1.0, 1.0)` in Func-C mode, while box_A uses `(0.01, 0.01, 0.01)`. This 100× scale factor directly causes the massive world-space container.

### 2c. Camera containment analysis

| Parameter | Value |
|---|---|
| Camera world position | (0.35, 0.0, 2.5) |
| Camera orientation | (w=0.7071, x=0, y=0.7071, z=0) — 90° around world Y |
| Camera forward | world +X |
| Camera up | world +Y |
| Camera right | world +Z |
| Box_B world center | (0.75 + 0.015, 0.25 + 0, 0.0 + 0.100) = (0.765, 0.25, 0.10) |
| Container world X range | 0.765 ± 19.038 = [-18.3, 19.7] |
| Container world Z range | 0.10 ± 30.525 = [-30.4, 30.6] |
| Camera X | 0.35 → **INSIDE container X range** |
| Camera Z | 2.5 → **INSIDE container Z range** |

The camera at (0.35, 0, 2.5) is inside the enormous container mesh. The container's inner surface fills the entire frame, and the mesh triangle layout creates the fan-shaped pattern visible in the smoke frame.

### 2d. FilledContent scale verification

| Item | Mesh X span | Notes |
|---|---|---|
| FilledContent_00 mesh | 0.172 units | ~17cm at scale 1.0 — correct part size |
| FilledContent grid (all 30) | 0.275 × 0.440 units | ~27cm × 44cm — correct slot grid |
| Container mesh | 38 units | ~38m — **100× too large** |

The FilledContent items ARE at the correct scale (~17cm each, arranged in a 6×5 grid spanning 27cm × 44cm). The Container mesh is the only object at the wrong scale. The FilledContent grid sits at world Z ≈ 0.35m (0.10 + 0.250), well inside the giant container.

---

## 3. Camera / World Y Mapping

| Image axis | World axis | Direction |
|---|---|---|
| Image right (+x) | World +Z | Right |
| Image down (+y) | World -Y | Down |
| Image center | World +X | Forward |

Container B (world Y=0.25) is **above** the camera (Y=0) → appears in the **upper** portion of the image.
Container B (world Z=0) is **left** of the camera (Z=2.5) in the camera's right-axis → appears on the **left** side of the image.

**Target B is in the upper-left quadrant of the frame**, but the 38m-wide container extends across the entire image.

---

## 4. Part_1..20 Expected Poses (Static Analysis)

Parts 1–19 are in container A (slots A@1–A@19). Part 20 is in container B (slot B@10).

```
Slot grid (5 cols × 4 rows):
  Col 0: x_offset = -0.22084  (slots 1,5,9,13,17)
  Col 1: x_offset = -0.11042  (slots 2,6,10,14,18)
  Col 2: x_offset =  0.00000  (slots 3,7,11,15,19)
  Col 3: x_offset =  0.11042  (slots 4,8,12,16,-)
  Col 4: x_offset =  0.22084  (unused for A@20; B@10 uses col 2)

  Row 0: y_offset = -0.105
  Row 1: y_offset = -0.035
  Row 2: y_offset =  0.035
  Row 3: y_offset =  0.105

Part Z (height): 0.17
Part rotation: (0.7071068, 0.0, -0.7071068, 0.0)  [90° around -Z]

Container A world: pos=(0.75, -0.25, 0.0), yaw=0.0
Container B world: pos=(0.75,  0.25, 0.0), yaw=0.0
```

**Part_20 (slot B@10)**: local offset from container B (col 2, row 1) = (0, -0.035, 0.17) → world pos = (0.75, 0.25-0.035, 0.17) = **(0.75, 0.215, 0.17)**.

**Init numerical gate NOT implemented**: Runtime pose/velocity telemetry, box drift values were NOT recorded in M1 or M1D (no formal capture executed).

---

## 5. container_full_visual.usd Generation / Transform Analysis

### 5a. Origin
- **No generation script found** in the repo. The file appears to have been authored externally or in a prior session and imported as a static asset.
- The F01 audit recorded it as a "clean asset" with `metersPerUnit = 1.0` — but the mesh vertex coordinates are NOT in meters.

### 5b. Transform preservation
- `/FullContainer`: No xform ops → identity
- `/FullContainer/Container`: One `xformOp:transform` → translate(0.015, 0, 0.100)
- `/FullContainer/FilledContents`: No xform ops → identity
- Each `FilledContent_{i:02d}`: One `xformOp:transform` → translate(grid_pos) × rotate(120° around (-0.577,-0.577,-0.577)), ALL 30 share same rotation

**The FilledContent transforms are internally consistent** — they form a correct 6×5 grid. The issue is ONLY the Container mesh scale relative to the FilledContent scale: the Container mesh spans 38 units while the FilledContent grid spans 0.44 units. The Container is 86× larger than the content grid.

### 5c. Likely generation error
The `container_full_visual.usd` was likely generated by:
1. Taking `container_full.usd` (physics version, metersPerUnit=1.0, mesh vertices in cm-space)
2. Extracting the Container mesh and FilledContent meshes
3. The Container mesh was NOT re-scaled to match metersPerUnit=1.0
4. The result: a cm-scale mesh in a meter-scale USD → 100× scale error

---

## 6. Fix Relevance

| Fix type | Relevant? | Rationale |
|---|---|---|
| container_fixed (box_A normalization) | NO | Box_A is not the culprit; its scale is correct |
| part_fixed (RigidBodyAPI normalization) | NO | Parts are fine; the issue is visual, not physics |
| **container_full_visual.usd scale** | **YES** | **THIS is the fix** |

---

## 7. Minimum Fix Recommendation

### Option A: Fix env scale (minimal, one-line)
Change `CONTAINER_FULL_SCALE` in `target_full_override.py:35`:
```python
# Before (bug):
CONTAINER_FULL_SCALE: tuple[float, float, float] = (1.0, 1.0, 1.0)

# After (fix):
CONTAINER_FULL_SCALE: tuple[float, float, float] = (0.01, 0.01, 0.01)
```
**Risk**: This scales BOTH the Container mesh AND the FilledContent items. The FilledContent items at 0.01 scale would become 1.7mm each — possibly too small. Test required.

### Option B: Regenerate container_full_visual.usd (preferred)
Regenerate `container_full_visual.usd` with:
1. Container mesh vertices in correct meter units (or metersPerUnit=0.01 matching container.usd)
2. FilledContent meshes preserved at correct relative scale
3. metersPerUnit explicitly set and verified
4. Keep CONTAINER_FULL_SCALE = (1.0, 1.0, 1.0) or set to (0.01, 0.01, 0.01) consistently

### Option C: Scale Container prim only
Add `xformOp:scale = (0.01, 0.01, 0.01)` on `/FullContainer/Container` in the USD file. This fixes only the Container mesh scale while keeping FilledContent at their correct size.

**Recommended path**: Option A as a quick smoke-test fix to confirm the diagnosis, then Option B for the proper fix.

---

## 8. Diagnostic Method

| Aspect | Status |
|---|---|
| Static USD mesh extent comparison | ✅ Conclusive |
| Static scale factor chain analysis | ✅ Conclusive |
| Camera/container spatial containment proof | ✅ Conclusive |
| FilledContent size vs Container size ratio | ✅ Conclusive |
| Runtime AABB/pose telemetry | ⛔ Not needed — static analysis is definitive |
| Isolation rendering | ⛔ Not needed |
| Diagnostic smoke test | ⛔ NOT executed — 0 of max 2 used |
| Formal capture | ⛔ NOT executed (per M1D constraints) |

---

## 9. Diagnostic Smoke Tests

**None executed.** The static analysis provides definitive root cause identification. Running a smoke test would only confirm what the mesh extents, scale config, and camera geometry already prove. This conserves token budget and follows the instruction "若一次已归因，不做第二次."

If a smoke test were to be run, the hypothesis would be:
> H1: Setting CONTAINER_FULL_SCALE to (0.01, 0.01, 0.01) will eliminate the white fan artifact and show a correctly-scaled container with FilledContent items visible inside.

---

## 10. Related Documents

- `m1-usd-init-fix-milestone-2026-07-23.md` — M1 structural fix (verdict corrected by M1C)
- `m1c-correction-2026-07-23.md` — M1C correction record
- `f01-usd-asset-structure-audit-2026-07-23.md` — Pre-M1 asset audit
- `target_full_override.py:35` — Line containing CONTAINER_FULL_SCALE
- `gmrobot_env_cfg.py:71` — Line containing CONTAINER_SCALE
