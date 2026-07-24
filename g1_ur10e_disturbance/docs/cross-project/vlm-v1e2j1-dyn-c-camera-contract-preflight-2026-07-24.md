# V1-E2J.1 Dyn-C Camera Contract Preflight (2026-07-24)

- verdict: `FAIL_STOP_NO_RETRY_NO_FORMAL_CAPTURE`
- decision: `STOP_NO_RETRY_NO_FORMAL_CAPTURE`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2j1_dyn_c_camera_contract_preflight_20260724`

## Camera Contract (Fail-Closed)
- requested pos/rot: `[0.45, 0.0, 2.7]` / `[0.7071, 0.0, 0.7071, 0.0]`
- effective pos/rot: `[0.45, 0.0, 2.7]` / `[0.7071, 0.0, 0.7071, 0.0]`
- abs error: `{'pos_max_abs': 0.0, 'rot_max_abs': 0.0}`; contract_match=`True`

## Gate Results
- exit0/noTraceback/noXid: `True` / `True` / `True`
- G1 not fell: `True`
- commanded vs actual same direction (dot): `True` (`1.2602046313762612`)
- ROI exists all frames: `True`
- centroid>=40 count>=2: `True` (count=`4`)
- UR10 arm-only settled <=1e-6: `False` (observed=`0.00015` joint=`shoulder_lift_joint` value=`-0.00015`)
- UR10 EE settled <=1e-6m: `True` (observed=`0.0`)

## Historical E2J Lineage (Not Overwritten)
- prior E2J verdict remains FAIL and is preserved in existing report files.
- E2J.1 adds camera-contract enforcement evidence and per-joint arm-settled telemetry.

## Stop Policy
- Preflight gate failed on UR10 arm-only settled threshold; stop immediately.
- No retry, no threshold change, no formal E2K capture in this run.
