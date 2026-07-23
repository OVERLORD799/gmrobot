# V1-M1Z11 Dyn-B acceptance semantics fix (2026-07-23)

- scope: offline replay only (M1Z5/M1Z9 historical docs)
- TTC non-ALLOW fail-closed: `preserved`
- step completion rule: `total sim steps/max_steps primary; policy_steps diagnostic-only`
- red proxy rule: `proxy_telemetry_present replaces red_proxy_any; visual_red_proxy_detected not_evaluated/null without explicit segmentation evidence`
- replay overall: `FAIL_NONALLOW_GEOMETRY` (unchanged)
- Dyn-B capture status: `frozen`
- next step constraint: `independent approval required for safety observability/closest-link study before further progression`

## Historical replay
- V1-M1Z5: raw=`DYN_B_REVIEWABLE_PREFLIGHT_FAIL_FINAL`; steps_completed_by_total=`True`; proxy_telemetry_present=`False`; visual_red_proxy_detected=`None`; overall=`FAIL_NONALLOW_GEOMETRY`
- V1-M1Z9: raw=`DYN_B_FORMAL_M1Z9_FAIL_FINAL`; steps_completed_by_total=`True`; proxy_telemetry_present=`True`; visual_red_proxy_detected=`None`; overall=`FAIL_NONALLOW_GEOMETRY`
