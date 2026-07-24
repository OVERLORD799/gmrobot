# Paper Demo Context Handoff (2026-07-24)

## 0) Preflight (this handoff generation)

- repo: `/home/czz/GMrobot`
- branch: `main`
- HEAD: `04992f462db25c662aeee393563cdf5fc9efd3e9`
- `origin/main` (local ref): `04992f462db25c662aeee393563cdf5fc9efd3e9`
- worktree clean: `true`
- note: this handoff is docs/metadata only; no Docker/Isaac/POST run in this update.

## 1) Global Goal (must stay unchanged)

Overall objective remains:

1. GMRobot paper roadmap five-stage progression (physical baseline + visual/semantic evidence chain).
2. G1 disturbance adversarial and visual dataset expansion (Dyn/Func branches), without mutating frozen physical benchmark evidence.

## 2) Physical Baseline Freeze (B0/B1/B2/B4)

- status: **frozen PASS**.
- canonical freeze image tag: `gmdisturb:b4-p010-20260721`
- canonical freeze image SHA: `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- source docs:
  - `docs/cross-project/paper-demo-physical-baseline-acceptance-2026-07-21.md`
  - `docs/cross-project/b0-b1-final-regression-p010-2026-07-21.md`
  - `docs/cross-project/b2-b4-final-validation-p010-2026-07-21.md`
- policy: **do not rerun, retune, rebuild, or overwrite** frozen B0/B1/B2/B4 assets/results.

## 3) Evidence Level: canonical/legacy gateway, five-stage shadow, semantic shadow

- `legacy gateway` and `canonical import` chain:
  - V1-C1R import bug root cause and canonical fix recorded in `vlm-v1c1r-canonical-import-fix-2026-07-22.md`.
  - `gmdisturb:semantic-shadow-v1c0p1-20260722` / `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c` is the post-fix image lineage.
- five-stage real shadow evidence:
  - V0-C3: PASS (`vlm-v0c3-isaac-shadow-result-2026-07-21.md`, status json).
  - scope boundary: negative scene + safety disabled + shadow independent of live safety.
- semantic supervisor shadow evidence:
  - V1-C1R-P1: PASS with `accepted=0` legal negative rejection (`risk_type_not_allowed x2`).
  - confirms isolation, drain, leakage-zero, and request/session accounting in shadow mode.
- cannot claim yet:
  - cannot claim paper-level completed five-stage visual validation.
  - cannot claim active semantic control success.
  - cannot claim real positive semantic acceptance in live control.

## 4) VLM remote/model + real POST/Isaac shadow PASS/FAIL timeline (key)

- V0-C3 (Isaac shadow, real remote VLM/GDINO/SAM2, POST=6): PASS.
- V1-C1R (historical): FAIL due to canonical packaging import issue (preserved).
- V1-C1R-P1 (post canonical fix, Isaac semantic shadow, POST=6): PASS (negative-scene legal reject).
- V1-D2B fixed-frame replay (POST=2): FAIL (`D2B_TASK_CONTEXT_FAIL`, static@0.8, no functional>=0.85).
- policy outcome: model/prompt quality for control-grade positive remains insufficient; no threshold-lowering allowed.

## 5) Positive Dataset Status (current)

- V1-E0 conclusion: `DATASET_INSUFFICIENT`.
- V1-E0.1: design ready, capture not auto-approved/executed.
- Func-C status (document-grounded only):
  - latest formal visual audit artifact: `vlm-v1e1r21-func-c-formal-visual-audit-2026-07-23.*`.
  - this artifact is visual-evidence oriented and explicitly **not** geometry/control clean evidence.
  - unless explicit reviewer approval evidence is accepted by user policy for current claim scope, keep dataset semantic label conservative (`provisional` / `reviewer_approved=false`) when forming control-grade claims.
- do not elevate preflight-only or audit-only artifacts into formal active semantic evidence.

## 6) Dyn-A/B/C and E2I/E2J/E2J.1 latest state

- Dyn-A (`vlm-v1e01-dyn-a-capture-2026-07-22.md`):
  - `GEOMETRY_WINDOW_FAIL`; displacement gate failed; POST=0; no rerun.
- Dyn-B (`vlm-v1e03-dyn-b-offline-temporal-evidence-2026-07-23.md`):
  - technical temporal evidence pass pending user; dataset still insufficient (dynamic groups insufficient).
- Dyn-C lineage:
  - E2I: FAIL stop; projected displacement and UR10 settle gates fail.
  - E2J: FAIL stop; camera contract mismatch and gates fail.
  - E2J.1: camera contract PASS; ROI PASS; centroid>=40px PASS; G1 actual-direction PASS; UR10 EE near-zero PASS.
  - **single remaining blocker**: arm-only settle threshold fail (`shoulder_lift_joint` delta `0.00015 rad` vs current `1e-6` criterion).
  - formal E2K runs: `0` (not executed).
- mandatory boundary:
  - preflight/precheck artifacts are **not** formal samples and cannot be claimed as formal capture.

## 7) Pending User Decision (hard gate)

User decision required before any formal Dyn-C capture:

- whether to documentarily relax **arm-only settled threshold** from `1e-6 rad` to `5e-4 rad`,
- while keeping EE near-zero gate as mandatory.

Until explicit approval: **no formal capture**.

## 8) Known latest tags/SHA, commit chain, and key paths

### image/tag SHA snapshot (from files/docs only)

- frozen physical baseline:
  - `gmdisturb:b4-p010-20260721` -> `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- V0-C3 five-stage shadow:
  - `gmdisturb:five-stage-shadow-v0c3-20260721` -> `sha256:cab6bf5cf637a1f16bd1ac4b14cd6611bb85c7c75ec71cacfddffc963b6ed452`
- semantic shadow fixed lineage:
  - `gmdisturb:semantic-shadow-v1c0p1-20260722` -> `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c`
- Dyn-C E2J:
  - `gmdisturb:e01-dyn-c-motion-preflight-m1e2j-20260724` -> `sha256:1b560306690316117db34491fee73381993a276a23868fddb637b12f56352f76`
- Dyn-C E2J.1:
  - `gmdisturb:e01-dyn-c-motion-preflight-m1e2j1-20260724` -> image SHA `unknown` (not explicitly recorded in E2J.1 json).

### commit chain

- current HEAD: `04992f462db25c662aeee393563cdf5fc9efd3e9`
- recent chain (newest first):
  - `04992f4` Enforce Dyn-C camera contract pre-make and fail closed on mismatch.
  - `acaab2e` V1-E2J record single-run Dyn-C short preflight failure.
  - `f017402` V1-E2I.1 split UR10 arm/gripper freeze metrics.
  - `7cebe69` docs: record V1-E2I dyn-c motion isolation preflight.
  - `992cabb` fix(capture): hold UR10 pose in IK root frame.

### results/docs anchors

- docs root: `g1_ur10e_disturbance/docs/cross-project/`
- results root: `g1_ur10e_disturbance/results/paper_demo/`
- frozen summaries:
  - `results/paper_demo/b0_b1_final_summary_p010.json`
  - `results/paper_demo/b2_b4_final_summary_p010.json`

## 9) Do Not Touch / Safe Next Steps / Recovery & acceptance checklist

### Do Not Touch

- frozen B0/B1/B2/B4 code thresholds, YAML, results, and freeze image lineage.
- historical FAIL directories and evidence documents.
- no rewriting verdicts (D1A/D1B/D1B-S/D2B/E2I/E2J/E2J.1).
- no active semantic control enabling.
- no formal capture before explicit gate decision.

### Safe next steps

1. docs-only decision record for arm-only threshold (`1e-6` vs `5e-4`) with rationale.
2. if approved, issue a strictly bounded formal Dyn-C runbook (single-run, no retry, EE gate preserved).
3. maintain dataset claim boundary (`DATASET_INSUFFICIENT`) unless group-level evidence requirements are met.

### Recovery commands (read-only)

```bash
git status --porcelain=v1 --branch
git rev-parse HEAD
git rev-parse origin/main
git log --oneline -12
```

### acceptance checklist for next agent

- [ ] reconfirm `main`/`origin/main`/clean worktree before any action.
- [ ] verify no Docker/Isaac/POST execution if task is docs-only.
- [ ] preserve freeze and historical verdict boundaries.
- [ ] keep preflight != formal sample.
- [ ] do not claim active semantic control progress without approved formal evidence.

## 10) PPE/Glove asset status and active semantic control pause

- no approved glove/PPE asset evidence chain exists for control-grade claim in current scope.
- current focus remains:
  - VLM feedback capability at lower control boundary,
  - dataset evidence quality/completeness expansion.
- active semantic control remains **paused**.

## 11) Paper claim boundary (can vs cannot claim)

### can claim

- physical safety baseline B0/B1/B2/B4 frozen PASS on `defe95e...`.
- real five-stage shadow pipeline PASS evidence exists (negative-scene boundary).
- semantic supervisor shadow isolation PASS evidence exists (negative-scene legal reject).
- Dyn-C preflight lineage currently blocked before formal capture.

### cannot claim

- cannot claim paper-complete five-stage visual semantic validation.
- cannot claim real positive semantic control intervention accepted in active control.
- cannot claim Dyn-C formal sample PASS.
- cannot convert preflight checks into formal dataset samples.

## 12) Copy-paste short context for next agent

Use this exact context:

> Repo `/home/czz/GMrobot` on `main` HEAD `04992f462db25c662aeee393563cdf5fc9efd3e9` (origin/main same, clean). Physical baselines B0/B1/B2/B4 are frozen at `gmdisturb:b4-p010-20260721` / `sha256:defe95e7...` and must not be rerun. V0-C3 and V1-C1R-P1 shadow evidence are PASS but negative-scene/shadow-boundary only; do not claim active semantic control success. Dataset remains insufficient for paper-level control-grade positive claims. Dyn-C latest E2J.1 fixed camera contract and passed ROI/centroid/G1-direction/UR10-EE gates, but still fails arm-only settle gate (`0.00015 rad` vs `1e-6`), so formal E2K count is 0. Pending explicit user approval: whether to documentarily relax arm-only threshold to `5e-4 rad` while keeping EE near-zero gate mandatory. Until approved, no formal capture.
