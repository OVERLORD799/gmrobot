#!/usr/bin/env bash
# V1-D7A boundary-phase batch capture (4 single-shot front-camera runs).
set -uo pipefail
BASE=/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo
CBASE=/opt/projects/g1_ur10e_disturbance/results/paper_demo
IMG=gmdisturb:e01-dyn-c-motion-preflight-m1e2j1-20260724
CFG=/opt/projects/g1_ur10e_disturbance/configs/e01_dyn_c_motion_preflight_v1e2j1k_20260724.yaml
CAM="--scene-camera-override --scene-camera-pos=-2.0,-0.15,-0.05 --scene-camera-rot=1.0,0.0,0.0,0.0"

run_one() {
  local name=$1 scenario=$2 label=$3 seed=$4 max_steps=$5 steps=$6
  local R=$BASE/$name C=$CBASE/$name
  mkdir -p "$R/meta"
  local REQ=""
  for s in ${steps//,/ }; do
    REQ="$REQ --require-path $R/scene/frame_$(printf %06d "$s")_env0.png"
  done
  python3 /home/czz/GMrobot/GMRobot/scripts/capture_one_shot_runner.py \
    --result-dir "$R" --status-file "$R/meta/run_status.json" \
    --stdout-file "$R/meta/stdout.txt" --stderr-file "$R/meta/stderr.txt" \
    --timeout-sec 900 \
    --forbid-pattern 'Traceback \(most recent call last\):' \
    --forbid-pattern 'ModuleNotFoundError' --forbid-pattern 'DEVICE_LOST' \
    --forbid-pattern 'POST /' \
    $REQ --require-path "$R/meta/body_poses.jsonl" --require-path "$R/meta/camera_pose.json" \
    -- /home/czz/GMrobot/g1_ur10e_disturbance/docker/run.sh --tag "$IMG" \
    --results /home/czz/GMrobot/g1_ur10e_disturbance/results bash -lc \
    "set -euo pipefail; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py --config $CFG --headless --seed $seed --scenario $scenario --motion_source_label $label --freeze-ur10e --max_steps $max_steps --progress_interval 50 $CAM --output_csv $C/safety_logs/phase3.csv --save_camera --camera_output_dir $C/scene --camera_save_steps $steps --camera_pose_json $C/meta/camera_pose.json --body_pose_jsonl $C/meta/body_poses.jsonl"
  echo "RUN $name exit=$? frames=$(ls "$R/scene" 2>/dev/null | wc -l)"
}

run_one v1d7a_b1_reverse_sweep_20260724 mirrored_outer_lateral_patrol scripted_g1_mirrored_outer_lateral_patrol 44 320 250,255,260,265,270,275,280,285,290,295,300,305,310,315
run_one v1d7a_b2_retreat_depth_20260724 mirrored_outer_lateral_patrol scripted_g1_mirrored_outer_lateral_patrol 44 410 325,330,335,340,345,350,355,360,365,370,375,380,385,390,395,400
run_one v1d7a_b3_static_idle_20260724 mirrored_outer_lateral_patrol scripted_g1_mirrored_outer_lateral_patrol 44 470 420,425,430,435,440,445,450,455,460,465
run_one v1d7a_b4_outer_traj_20260724 outer_lateral_patrol scripted_g1_outer_lateral_patrol 43 260 165,170,175,180,185,190,195,200,205,210,215,220,225,230,235,240,245
