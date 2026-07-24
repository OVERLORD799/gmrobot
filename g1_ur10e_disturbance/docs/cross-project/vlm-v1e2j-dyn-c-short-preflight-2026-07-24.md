# V1-E2J Dyn-C 短预检 (2026-07-24)

- verdict: `FAIL_STOP_NO_RETRY_NO_FORMAL_CAPTURE`
- decision: `STOP_NO_RETRY_NO_FORMAL_CAPTURE`
- preflight runs: `1`
- formal runs: `0`
- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e2j_dyn_c_short_preflight_20260724`

## Build Provenance
- image tag: `gmdisturb:e01-dyn-c-motion-preflight-m1e2j-20260724`
- base image id: `sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68`
- image id: `sha256:1b560306690316117db34491fee73381993a276a23868fddb637b12f56352f76`
- HEAD: `f017402c45250747cd6e6479147fbd8a941f96a6`
- config sha256: `b0663690906f7f2e98b6fd7028f961ff82f7fcf9fbc49426e6412f1a685fb275`

## Contract vs Observed
- requested camera pos/rot: `[0.45,0.0,2.7]` / `[0.7071,0.0,0.7071,0.0]`
- observed camera pos: `[1.0, 0.0, 3.0]` (**mismatch**) 
- requested capture steps: `149,150,239,250` (single run)
- freeze: `--freeze-ur10e`; seed: `44`; VLM/perception/POST: off

## Gate Results
- exit0: `True`
- no Traceback / no new Xid: `True` / `True`
- G1 no fall: `True`
- G1 commanded XY: `[1.1164, -0.2928]`
- G1 actual XY: `[1.0598587393760681, -0.28755156695842743]`
- direction dot (>0): `1.26742139544487`
- projected ROI exists: `True`
- projected centroid >=40px (>=2 frames): `False` (count=`0`, max=`36.802840533688624`)
- UR10 arm-only settled delta <=1e-6: `False` (observed=`0.00015`)
- UR10 EE settled displacement <=1e-6m: `True` (observed=`3.129243850708008e-07`)
- gripper selected/open settle report-only: state=`open`, delta=`0.314159` (not counted as arm fail)

## Stop Policy
- 预检未同时满足门禁，按规则停止；不重跑、不调参、不执行正式 Dyn-C 采集。
- 正式阶段状态: `NOT_EXECUTED_DUE_TO_PRECHECK_FAIL`。
