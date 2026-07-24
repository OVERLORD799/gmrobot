#!/usr/bin/env bash
# V1-D10 S3 capture: outer_lateral_patrol family, seeds 49/50/51, four windows.
# Outer phase table: approach 0-140, settle 140-160, positive sweep 160-250,
# negative sweep 250-340, retreat 340-420, idle 420+.
# Windows: approach 55-135/5 (17), sweep 165-245/5 (17), retreat 345-415/5 (15),
#          idle 430-475/5 (10) = 59 frames, max_steps 480.
set -uo pipefail
BASE=/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo
CBASE=/opt/projects/g1_ur10e_disturbance/results/paper_demo
IMG=gmdisturb:e01-dyn-c-motion-preflight-m1e2j1-20260724
CFG=/opt/projects/g1_ur10e_disturbance/configs/e01_dyn_c_motion_preflight_v1e2j1k_20260724.yaml
CAM="--scene-camera-override --scene-camera-pos=-2.0,-0.15,-0.05 --scene-camera-rot=1.0,0.0,0.0,0.0"

STEPS=$(python3 -c "print(','.join(str(s) for s in list(range(55,136,5))+list(range(165,246,5))+list(range(345,416,5))+list(range(430,476,5))))")

for SEED in 49 50 51; do
  NAME=v1d10_s3_seed${SEED}_20260724
  R=$BASE/$NAME C=$CBASE/$NAME
  mkdir -p "$R/meta"
  python3 /home/czz/GMrobot/GMRobot/scripts/capture_one_shot_runner.py \
    --result-dir "$R" --status-file "$R/meta/run_status.json" \
    --stdout-file "$R/meta/stdout.txt" --stderr-file "$R/meta/stderr.txt" \
    --timeout-sec 900 \
    --forbid-pattern 'Traceback \(most recent call last\):' \
    --forbid-pattern 'ModuleNotFoundError' --forbid-pattern 'DEVICE_LOST' \
    --forbid-pattern 'POST /' \
    --require-path "$R/scene/frame_000055_env0.png" \
    --require-path "$R/scene/frame_000165_env0.png" \
    --require-path "$R/scene/frame_000345_env0.png" \
    --require-path "$R/scene/frame_000475_env0.png" \
    --require-path "$R/meta/body_poses.jsonl" --require-path "$R/meta/camera_pose.json" \
    -- /home/czz/GMrobot/g1_ur10e_disturbance/docker/run.sh --tag "$IMG" \
    --results /home/czz/GMrobot/g1_ur10e_disturbance/results bash -lc \
    "set -euo pipefail; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py --config $CFG --headless --seed $SEED --scenario outer_lateral_patrol --motion_source_label scripted_g1_outer_lateral_patrol --freeze-ur10e --max_steps 480 --progress_interval 50 $CAM --output_csv $C/safety_logs/phase3.csv --save_camera --camera_output_dir $C/scene --camera_save_steps $STEPS --camera_pose_json $C/meta/camera_pose.json --body_pose_jsonl $C/meta/body_poses.jsonl"
  echo "RUN $NAME exit=$? frames=$(ls "$R/scene" 2>/dev/null | wc -l)"
done
