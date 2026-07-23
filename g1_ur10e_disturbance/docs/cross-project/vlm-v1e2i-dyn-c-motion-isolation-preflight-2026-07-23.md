# V1-E2I Dyn-C Motion-Isolation Short Preflight (2026-07-23)

- verdict: `FAIL_STOP_NO_RETRY_NO_FORMAL_CAPTURE`
- decision: `STOP_NO_FORMAL_CAPTURE` (single-run only, no retry)
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2i_dyn_c_motion_isolation_preflight_20260723`
- HEAD: `992cabb` (expected `992cabb`)
- image: `gmdisturb:e01-dyn-c-motion-isolation-preflight-m1e2i-20260723` / `sha256:c52c4a56746a175fd20a4f9ad004147cc0cadc62a17a4c2267a163a181dc8dd5`

## Host Prechecks
- motion-isolation related unit tests: pass
- py_compile checks: pass
- prebuild import-closure check: pass

## Single Docker/Isaac Run Contract
- run attempts: `1/1` (no retry)
- scenario/seed: `mirrored_outer_lateral_patrol` / `44`
- camera: `pos=[0.45,0.0,2.7] rot=[0.7071,0.0,0.7071,0.0]`
- capture steps: `149,150,219,220`
- freeze: `--freeze-ur10e`
- POST=0 and VLM/perception off evidence: `POST,/analyze,/ground,enable_vlm,enable_perception = 0`

## Gate Results
- exit0: `True`
- no Traceback/Xid: `True` / `True`
- G1 no fall: `True`
- G1 commanded XY m: `[1.1164, -0.29279999999999995]`
- G1 actual XY m: `[1.0598589999999999, -0.28755200000000003]`
- G1 direction dot (>0 expected): `1.2674218132`
- projected G1 ROI exists: `True`
- projected centroid displacement >=40px on >=2 audit frames: `False` (count=`0`, max=`36.88848765316308`)
- UR10 settled joint delta near-zero (<=1e-6): `False` (observed `0.314159`)
- UR10 settled EE displacement near-zero (<=1e-6 m): `True` (observed `3.129243850708008e-07`)

## Motion Attribution
- synchronous G1 link projection + actual root telemetry both produced and audited.
- UR10 EE displacement after settling is near numerical noise; UR10 is not evidenced as the main visible-change source.
- however projected centroid displacement gate is not met, so attribution gate remains FAIL.

## Artifacts
- runtime telemetry csv: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2i_dyn_c_motion_isolation_preflight_20260723/safety_logs/phase3_runtime_telemetry.csv` (rows=264, sha256=`9fcec5da3bd6093eb30353e3a95267522373321615c7c2a3635fa4153f706483`)
- postrun analyzer json: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2i_dyn_c_motion_isolation_preflight_20260723/meta/v1e2i_postrun_analyzer.json`
- docker log: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2i_dyn_c_motion_isolation_preflight_20260723/meta/docker_run.log`

## Final Policy
- FAIL: keep evidence only, do not rerun, do not retune thresholds, do not perform formal capture.
- If needed next: only apply for a future formal-capture request after explicit approval and fresh gate plan.
