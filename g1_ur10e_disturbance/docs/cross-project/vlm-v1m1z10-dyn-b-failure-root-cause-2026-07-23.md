# V1-M1Z10 Dyn-B M1Z9 FAIL_FINAL root-cause audit (offline)

- result_dir: `/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723`
- A global judgement: `PROXY_DOMINATED_SPIKES_NOT_PROVEN_REAL_G1_RELATIVE_MOTION` (confidence `0.88`)
- B classification: `ACCEPTER_PROXY_PRESENCE_FLAG_NOT_PIXEL_RED_DETECTOR` (confidence `0.95`)
- C classification: `MAX_STEPS_REACHED` (confidence `0.83`)
- window 159..338 complete: `True`

## A) step 167/212/228
- step `167`: `CLOSEST_LINK_SWITCH_WITH_PROXY_SPIKE`; closest `left_wrist_pitch_link -> right_wrist_pitch_link`; ttc `0.068866`; approach `14.959372`; proxy_v `17.693438`; ee_v `0.362789`
- step `212`: `CLOSEST_LINK_SWITCH_WITH_PROXY_SPIKE`; closest `right_wrist_pitch_link -> left_wrist_pitch_link`; ttc `0.987445`; approach `1.123983`; proxy_v `7.254128`; ee_v `0.561783`
- step `228`: `CLOSEST_LINK_SWITCH_WITH_PROXY_SPIKE`; closest `left_wrist_pitch_link -> right_wrist_pitch_link`; ttc `0.564015`; approach `1.903555`; proxy_v `4.83148`; ee_v `0.501081`

## B) red_proxy_any
- definition: `/home/czz/GMrobot/g1_ur10e_disturbance/scripts/run_e01_dyn_b_m1z_reviewable_preflight.sh: red_proxy_any set true when proxy_center_(x,y,z) any non-zero string in step window`
- detector_type: `telemetry-presence, not color segmentation`
- window_proxy_rows_nonzero: `180`

## C) 335 vs 341
- total_steps/policy_steps/max_steps: `341/335/341`
- lag explanation: `metrics.policy_steps tracks ur10e.time_step and can lag under safety gate holds`

## Recommendation
- direction: `FIX_ACCEPTANCE_AUDITER_SEMANTICS`
- Dyn-B decision: `WASTEFUL_LOOP_STOP`
