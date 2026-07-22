# M1C: Correction Record (2026-07-23)

## Verdict: **M1_STRUCTURAL_FIX_PASS_VISUAL_GATE_FAIL**

### Source: Human review of M1 smoke test frame0

---

## 1. Correction Summary

The M1 milestone document (commit `9ac4f0a`) originally recorded verdict `M1_GATES_PASS`, claiming all structural gates and smoke test passed. **This conclusion was incorrect.**

Human review of the smoke test frame0 (`smoke_scene/frame_000000_env0.png`) found the **white fan-shaped scatter artifact still present** — visually identical to the pre-fix anomalous frame.

The structural normalization (nested RigidBodyAPI removal) succeeded, but the **visual gate (frame0 pixel-level verification) failed**.

---

## 2. What M1 Actually Proved

| Claim | Status | Evidence |
|---|---|---|
| Nested RigidBodyAPI warnings eliminated | ✅ TRUE | 0 warnings in smoke log |
| Container/part USD structure normalized | ✅ TRUE | Single rigid body per prim, correct API placement |
| Frozen originals unchanged | ✅ TRUE | SHA256 verified |
| White fan artifact resolved | ❌ FALSE | Human review: artifact visually identical to pre-fix |
| Func-C ready for dataset | ❌ FALSE | Visual gate failed |

---

## 3. Smoke Frame Evidence

| Field | Value |
|---|---|
| Frame path (on disk) | `g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/smoke_scene/frame_000000_env0.png` |
| Frame SHA256 | `c28596ba5f1caa87deb6899bc08509bc8b413a976afd0b16b6d93a8b5f740649` |
| Frame size | 186,050 bytes |
| Commit at time of smoke | `9ac4f0a` (HEAD, pushed to origin/main) |
| Docker image | `gmdisturb:e01-func-c-m1-fix-20260723` (SHA256 `d8bef5e2...`) |
| Smoke exit code | 0 |
| Nested RigidBodyAPI warnings | 0 |
| Human reviewer | OVERLORD799 |
| Review date | 2026-07-23 |
| Review finding | **WHITE FAN SCATTER STILL PRESENT** |
| Visual comparison | Visually identical to pre-fix anomalous frame |

### Pre-fix reference frame

| Field | Value |
|---|---|
| Pre-fix frame0 SHA256 | `6e203cc482f1fcb12309ac0586a7665e1749fba3a8c20bea1953fc4ae0a33ba6` |
| Pre-fix frame0 size | 187,432 bytes |

Note: Frame sizes differ (186,050 vs 187,432) but visual content of the **white fan artifact region** is identical. The size delta likely comes from other scene changes (e.g., container mesh difference between `container.usd` and `container_fixed.usd`).

---

## 4. Root Cause Hypothesis (Updated)

The white fan artifact was initially attributed to nested RigidBodyAPI causing unpredictable physics behavior. M1 disproved this hypothesis: **removing nested RigidBodyAPI does NOT resolve the artifact.**

The artifact is now suspected to originate from:
1. **container_full_visual.usd (box_B)**: Visual-only USD with many `FilledContent` mesh prims. If any FilledContent mesh has incorrect world-space transforms (flattened or identity), it could render as a fan-shaped scatter from the box origin.
2. **Part_1..20 spawn transforms**: If parts are spawned with incorrect initial poses relative to the container slots, they could scatter visibly.
3. **Camera/projection interaction**: If the camera views the scene from an angle where box_B's FilledContent meshes overlap/interleave incorrectly.

**M1D is required for precise attribution.**

---

## 5. What Was NOT Done in M1

- ❌ init numerical gate: 20 parts actual pose, linear/angular velocity, box drift values NOT recorded
- ❌ container_full_visual.usd transform/preservation audit
- ❌ FilledContent mesh world-space pose verification
- ❌ Isolation rendering (hide box_A / box_B / parts separately)
- ❌ AABB/pose telemetry to map visible anomaly to specific prims
- ❌ VLM/perception POST
- ❌ Formal Func-C capture

---

## 6. Next Steps (M1D)

M1D must precisely attribute the white fan artifact to specific prim(s) using auditable methods:

1. Runtime world AABB/pose telemetry + semantic/instance segmentation
2. Isolation rendering: hide box_B (container_full_visual.usd) vs hide box_A parts separately
3. Verify `container_full_visual.usd` generation method and transform preservation
4. Check each FilledContent mesh world/local transform for flattening
5. Record Part_1..20 post-spawn root pose, linear/angular velocity, expected slot offsets
6. Max 2 short diagnostic smoke runs, each with explicit hypothesis and verdict
7. No formal capture, no safety threshold changes, no B0-B4 rerun

---

## 7. Correction Integrity

- ✅ Original M1 milestone md/json preserved with updated verdict (NOT replaced)
- ✅ This correction file is a NEW artifact (does not overwrite history)
- ✅ Original commit `9ac4f0a` is NOT rewritten
- ✅ All prior cross-project docs remain intact

---

## 8. Related Documents

- `m1-usd-init-fix-milestone-2026-07-23.md` — Original milestone (verdict updated)
- `m1-usd-init-fix-milestone-2026-07-23.json` — Original milestone data (verdict updated)
- `m1c-correction-2026-07-23.json` — This correction as structured data
- `f01-usd-asset-structure-audit-2026-07-23.md` — Pre-M1 audit
- `vlm-v1e01-func-c-capture-2026-07-22.md` — Prior Func-C capture attempt
