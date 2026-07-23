# V1-M1Z9 Dyn-B formal reviewable capture + TTC attribution audit (2026-07-23)

- verdict: **DYN_B_FORMAL_M1Z9_FAIL_FINAL**
- next_gate: `STOP_NO_RETRY`
- image sha: `sha256:1707dec1b229b97eb493c433d7ad60f886a0f304a4bc6558e5792c52155dfc1d`
- image digest: `gmdisturb@sha256:1707dec1b229b97eb493c433d7ad60f886a0f304a4bc6558e5792c52155dfc1d`
- run budget usage: `Isaac/AppLauncher formal run = 1/1`, `analyzer = 1/1`
- raw exit/runner exit/analyzer exit: `0/0/0`
- steps completed(341): `False` (policy_steps_last=`335`)
- review window 159..338 rows: `180`; step180 exactly-once: `True`
- effective ALLOW/STOP/SLOW/replan: `177/1/2/0`
- margin min m: `0.738` (gate >=0.10)
- phases(220/330): `` / ``
- centroid displacement 220->330 px: `24.297366596071075` (gate >=20)
- workcell/double-container visible: `True`
- G1 fallen/red proxy/POST/Traceback/DEVICE_LOST/new Xid/residual: `False/True/0/False/False/False/False`

## non-ALLOW ranges (window 159..338)
[{"start": 167, "end": 167, "length": 1, "continuity": "contiguous"}, {"start": 212, "end": 212, "length": 1, "continuity": "contiguous"}, {"start": 228, "end": 228, "length": 1, "continuity": "contiguous"}]

## non-ALLOW points attribution detail
[
  {
    "sim_step": 167,
    "attribution_status": "EXPLAINED",
    "trigger_rule": "ttc",
    "trigger_reason": "dynamic_ttc: 0.069s to potential contact",
    "gate_effective": "STOP",
    "ttc_observed_s": "0.068866",
    "ttc_forecast_s": "0.059465",
    "approach_rate_mps": "14.959372",
    "relative_velocity_mps": "null",
    "velocity_provenance": {
      "approach_rate_source": "gate_result.metadata.approach_rate",
      "relative_velocity_source": "not_exposed_in_runtime_gate_metadata"
    },
    "distance_source_phase_reason": {
      "dist_min_for_gating_m": "1.0302",
      "dist_min_g1_body_m": "1.043795",
      "dist_min_proxy_m": "1.043795",
      "distance_source": null,
      "protocol_phase": "",
      "trigger_reason": "dynamic_ttc: 0.069s to potential contact"
    }
  },
  {
    "sim_step": 212,
    "attribution_status": "EXPLAINED",
    "trigger_rule": "ttc",
    "trigger_reason": "dynamic_ttc_warning: 0.987s",
    "gate_effective": "SLOW_DOWN",
    "ttc_observed_s": "0.987445",
    "ttc_forecast_s": "1.010462",
    "approach_rate_mps": "1.123983",
    "relative_velocity_mps": "null",
    "velocity_provenance": {
      "approach_rate_source": "gate_result.metadata.approach_rate",
      "relative_velocity_source": "not_exposed_in_runtime_gate_metadata"
    },
    "distance_source_phase_reason": {
      "dist_min_for_gating_m": "1.1099",
      "dist_min_g1_body_m": "1.118868",
      "dist_min_proxy_m": "1.118868",
      "distance_source": null,
      "protocol_phase": "",
      "trigger_reason": "dynamic_ttc_warning: 0.987s"
    }
  },
  {
    "sim_step": 228,
    "attribution_status": "EXPLAINED",
    "trigger_rule": "ttc",
    "trigger_reason": "dynamic_ttc_warning: 0.564s",
    "gate_effective": "SLOW_DOWN",
    "ttc_observed_s": "0.564015",
    "ttc_forecast_s": "0.486311",
    "approach_rate_mps": "1.903555",
    "relative_velocity_mps": "null",
    "velocity_provenance": {
      "approach_rate_source": "gate_result.metadata.approach_rate",
      "relative_velocity_source": "not_exposed_in_runtime_gate_metadata"
    },
    "distance_source_phase_reason": {
      "dist_min_for_gating_m": "1.0736",
      "dist_min_g1_body_m": "1.083372",
      "dist_min_proxy_m": "1.083372",
      "distance_source": null,
      "protocol_phase": "",
      "trigger_reason": "dynamic_ttc_warning: 0.564s"
    }
  }
]
