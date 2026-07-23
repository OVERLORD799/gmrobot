#!/usr/bin/env bash
# V1-M1Z: one-shot reviewable Dyn-B 0-POST preflight (no retry).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS_ROOT="$(cd "${DIST_ROOT}/.." && pwd)"
REPO_ROOT="${WS_ROOT}"
RUNNER="${WS_ROOT}/GMRobot/scripts/capture_one_shot_runner.py"
TAG="gmdisturb:e01-dyn-b-clean-m1z-20260723"
RESULTS_HOST_ROOT="${DIST_ROOT}/results"
OUT_DIR="${DIST_ROOT}/results/paper_demo/v1e01_dyn_b_preflight_m1z_20260723"
META_DIR="${OUT_DIR}/meta"
DOC_BASE="${DIST_ROOT}/docs/cross-project/vlm-v1m1z-dyn-b-reviewable-preflight-2026-07-23"
CAM_POS="0.45,0.0,2.7"
CAM_ROT="0.7071,0,0.7071,0"

if [[ -e "${OUT_DIR}" ]]; then
  echo "REFUSE: result dir already exists: ${OUT_DIR}"
  exit 2
fi
mkdir -p "${META_DIR}" "${OUT_DIR}/scene" "${OUT_DIR}/safety_logs"

python3 - <<'PY' "${DIST_ROOT}" "${TAG}" "${RESULTS_HOST_ROOT}" "${OUT_DIR}" "${META_DIR}"
import json
import shlex
import sys
from pathlib import Path

dist_root = Path(sys.argv[1])
tag = sys.argv[2]
results_host_root = sys.argv[3]
out_dir = Path(sys.argv[4])
meta = Path(sys.argv[5])
sys.path.insert(0, str(dist_root))
from e01_dyn_b_runtime_guard import build_m1z_dyn_b_preflight_outer_argv  # noqa: E402

result_root_in_container = "/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z_20260723"
argv = build_m1z_dyn_b_preflight_outer_argv(
    run_sh_path=str(dist_root / "docker" / "run.sh"),
    image_tag=tag,
    host_results_dir=results_host_root,
    result_root_in_container=result_root_in_container,
)
inner = argv[-1]
(meta / "outer_command_argv.json").write_text(json.dumps(argv, indent=2) + "\n", encoding="utf-8")
(meta / "container_inner_command.txt").write_text(inner + "\n", encoding="utf-8")
(meta / "formal_command.txt").write_text(shlex.join(argv) + "\n", encoding="utf-8")
PY

printf '%s\n' "${CAM_POS}" > "${META_DIR}/camera_pos_expected.txt"
printf '%s\n' "${CAM_ROT}" > "${META_DIR}/camera_rot_expected.txt"
python3 - <<'PY' "${META_DIR}" "${CAM_POS}" "${CAM_ROT}"
import json
import sys
from pathlib import Path

meta = Path(sys.argv[1])
payload = {
    "GMDISTURB_SCENE_CAMERA_OVERRIDE": "1",
    "GMDISTURB_SCENE_CAMERA_POS": sys.argv[2],
    "GMDISTURB_SCENE_CAMERA_ROT": sys.argv[3],
}
(meta / "host_forwarded_camera_env.json").write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
PY

git rev-parse HEAD > "${META_DIR}/git_head.txt"
cp "${DIST_ROOT}/configs/e01_dyn_b_capture_m1y_design.yaml" "${META_DIR}/e01_dyn_b_capture_m1y_design.yaml"
docker image inspect "${TAG}" > "${META_DIR}/image_inspect.json"
nvidia-smi > "${META_DIR}/gpu_pre.txt" || true
nvidia-smi -q -d XID > "${META_DIR}/gpu_xid_pre.txt" || true

mapfile -t CMD < <(python3 - <<'PY' "${META_DIR}/outer_command_argv.json"
import json
import sys
for x in json.loads(open(sys.argv[1], "r", encoding="utf-8").read()):
    print(x)
PY
)

set +e
python3 "${RUNNER}" \
  --result-dir "${OUT_DIR}" \
  --status-file "${META_DIR}/run_status.json" \
  --stdout-file "${META_DIR}/capture_stdout.txt" \
  --stderr-file "${META_DIR}/capture_stderr.txt" \
  --forbid-pattern "Traceback \\(most recent call last\\):" \
  --forbid-pattern "ModuleNotFoundError" \
  --forbid-pattern "No module named" \
  --forbid-pattern "numpy dtype mismatch" \
  --forbid-pattern "cannot import ParamSpec" \
  --forbid-pattern "cannot import name 'broadcast_to'" \
  --forbid-pattern "NUMPY_ABI_GUARD_FAIL" \
  --forbid-pattern "Failed to startup python extension" \
  --forbid-pattern "ERROR_DEVICE_LOST" \
  --forbid-pattern "DEVICE_LOST" \
  --forbid-pattern "POST /" \
  --require-path "${OUT_DIR}/scene/frame_000219_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000220_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000221_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000329_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000330_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000331_env0.png" \
  --require-path "${OUT_DIR}/safety_logs/phase3.csv" \
  --require-path "${OUT_DIR}/safety_logs/phase3_dyn_b_per_step_audit_m1z.csv" \
  --require-path "${OUT_DIR}/meta/camera_pose.json" \
  --require-path "${OUT_DIR}/meta/body_poses.jsonl" \
  --require-path "${OUT_DIR}/meta/numpy_origin_pre.json" \
  --require-path "${OUT_DIR}/meta/numpy_origin_post.json" \
  --require-path "${OUT_DIR}/meta/typing_extensions_pre.json" \
  --require-path "${OUT_DIR}/meta/typing_extensions_post.json" \
  -- \
  env \
  GMDISTURB_SCENE_CAMERA_OVERRIDE=1 \
  GMDISTURB_SCENE_CAMERA_POS="${CAM_POS}" \
  GMDISTURB_SCENE_CAMERA_ROT="${CAM_ROT}" \
  "${CMD[@]}"
RUN_EXIT=$?
set -e
echo "${RUN_EXIT}" > "${META_DIR}/runner_exit_code.txt"

python3 "${DIST_ROOT}/scripts/dyn_b_per_step_audit_analyzer.py" \
  --csv "${OUT_DIR}/safety_logs/phase3_dyn_b_per_step_audit_m1z.csv" \
  --step-start 190 \
  --step-end 340 \
  --min-margin-m 0.10 \
  --json-out "${META_DIR}/per_step_window_report.json"
ANALYZER_EXIT=$?
echo "${ANALYZER_EXIT}" > "${META_DIR}/per_step_analyzer_exit_code.txt"

nvidia-smi > "${META_DIR}/gpu_post.txt" || true
nvidia-smi -q -d XID > "${META_DIR}/gpu_xid_post.txt" || true
docker ps -a > "${META_DIR}/docker_ps_after.txt" || true
ps -eo pid,cmd > "${META_DIR}/process_ps_after.txt" || true

python3 - <<'PY' "${REPO_ROOT}" "${OUT_DIR}" "${META_DIR}" "${DOC_BASE}.json" "${DOC_BASE}.md" "${TAG}" "${RUN_EXIT}" "${ANALYZER_EXIT}"
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
meta = Path(sys.argv[3])
doc_json = Path(sys.argv[4])
doc_md = Path(sys.argv[5])
tag = sys.argv[6]
run_exit = int(sys.argv[7])
analyzer_exit = int(sys.argv[8])
sys.path.insert(0, str(repo_root / "g1_ur10e_disturbance"))
from e01_dyn_b_m1y_camera_framing import TARGET_LINKS, WORKCELL_ANCHORS, evaluate_step  # noqa: E402
from scene_camera_override import project_world_to_pixel  # noqa: E402

expected_steps = [219, 220, 221, 329, 330, 331]
status = json.loads((meta / "run_status.json").read_text(encoding="utf-8"))
stdout = (meta / "capture_stdout.txt").read_text(encoding="utf-8", errors="replace")
stderr = (meta / "capture_stderr.txt").read_text(encoding="utf-8", errors="replace")
text = stdout + "\n" + stderr
post_count = len(re.findall(r"\bPOST\b", text))

camera_pose = json.loads((out_dir / "meta" / "camera_pose.json").read_text(encoding="utf-8"))
cam_pos = camera_pose.get("pos", [None, None, None])
cam_rot = camera_pose.get("rot", [None, None, None, None])
expected_cam_pos = [0.45, 0.0, 2.7]
expected_cam_rot = [0.7071, 0.0, 0.7071, 0.0]
camera_pos_match = [round(float(x), 4) for x in cam_pos] == expected_cam_pos
camera_rot_match = [round(float(x), 4) for x in cam_rot] == expected_cam_rot

body_by_step = {}
for line in (out_dir / "meta" / "body_poses.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        rec = json.loads(line)
        body_by_step[int(rec["step"])] = rec

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

frame_report = {}
all_png_ok = True
all_visual_pass = True
for st in expected_steps:
    png = out_dir / "scene" / f"frame_{st:06d}_env0.png"
    sig_ok = png.is_file() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    all_png_ok = all_png_ok and sig_ok
    rec = body_by_step.get(st, {})
    g1_bodies = rec.get("g1_bodies", {})
    links = [g1_bodies[k] for k in TARGET_LINKS if k in g1_bodies]
    ev = evaluate_step(links, cam_pos=cam_pos)
    link_ok = ev.links_visible_margin >= 4
    clip_ok = ev.clipping_ratio <= 0.50
    roi_ok = ev.roi_area_fraction >= 0.01
    visual_ok = sig_ok and link_ok and clip_ok and roi_ok
    all_visual_pass = all_visual_pass and visual_ok
    frame_report[str(st)] = {
        "path": str(png.relative_to(repo_root)),
        "sha256": sha256_file(png) if png.is_file() else None,
        "valid_png": sig_ok,
        "links_visible_margin_8": ev.links_visible_margin,
        "clipping_ratio": ev.clipping_ratio,
        "roi_area_fraction": ev.roi_area_fraction,
        "gate_links_ge_4": link_ok,
        "gate_clipping_le_0_5": clip_ok,
        "gate_roi_ge_0_01": roi_ok,
    }

ev220 = frame_report["220"]
ev330 = frame_report["330"]
centroid220 = body_by_step.get(220, {}).get("g1_bodies", {})
centroid330 = body_by_step.get(330, {}).get("g1_bodies", {})

def _centroid_uv(step: int):
    rec = body_by_step.get(step, {})
    links = [rec.get("g1_bodies", {}).get(k) for k in TARGET_LINKS]
    links = [x for x in links if x is not None]
    ev = evaluate_step(links, cam_pos=cam_pos)
    return ev.centroid_uv

c220 = _centroid_uv(220)
c330 = _centroid_uv(330)
disp = None
if c220 is not None and c330 is not None:
    disp = float(math.hypot(c330[0] - c220[0], c330[1] - c220[1]))
disp_ok = disp is not None and disp >= 20.0

anchor_visibility = {}
anchor_all_ok = True
for name, xyz in sorted(WORKCELL_ANCHORS.items()):
    uv = project_world_to_pixel(xyz, cam_pos=cam_pos, image_w=640, image_h=480)
    ok = bool(uv is not None and 24.0 <= uv[0] <= (640 - 1 - 24.0) and 24.0 <= uv[1] <= (480 - 1 - 24.0))
    anchor_visibility[name] = {"uv": [float(uv[0]), float(uv[1])] if uv is not None else None, "visible_with_margin": ok}
    anchor_all_ok = anchor_all_ok and ok

steps_rows = []
with (out_dir / "safety_logs" / "phase3_steps.csv").open("r", encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        st = int(row["step"])
        if 190 <= st <= 340:
            steps_rows.append(row)

allow_count = sum(1 for r in steps_rows if str(r.get("gate", "")).upper() == "ALLOW")
stop_count = sum(1 for r in steps_rows if str(r.get("gate", "")).upper() == "STOP")
slow_count = sum(1 for r in steps_rows if str(r.get("gate", "")).upper() == "SLOW_DOWN")
replan_count = sum(1 for r in steps_rows if str(r.get("replan_count", "0")).strip() not in {"", "0"})
margins = []
fallen_any = False
red_proxy_any = False
for r in steps_rows:
    try:
        margins.append(float(r.get("dist_min_g1_body", "nan")))
    except ValueError:
        pass
    try:
        if float(str(r.get("g1_root_z", "1.0"))) < -0.5:
            fallen_any = True
    except ValueError:
        pass
    px = str(r.get("proxy_center_x", "")).strip()
    py = str(r.get("proxy_center_y", "")).strip()
    pz = str(r.get("proxy_center_z", "")).strip()
    if any(v not in {"", "0", "0.0", "nan", "NaN", "inf"} for v in (px, py, pz)):
        red_proxy_any = True

margin_min = min(margins) if margins else None
margin_ok = margin_min is not None and margin_min >= 0.10
safety_ok = len(steps_rows) == 151 and allow_count == 151 and stop_count == 0 and slow_count == 0 and replan_count == 0
phase220 = body_by_step.get(220, {}).get("phase")
phase330 = body_by_step.get(330, {}).get("phase")
phase_ok = phase220 == "lateral_positive_sweep" and phase330 == "lateral_negative_sweep"

analyzer = json.loads((meta / "per_step_window_report.json").read_text(encoding="utf-8"))
analyzer_ok = analyzer_exit == 0 and analyzer.get("pass") is True

def xid_count(path: Path) -> int:
    txt = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    return len(re.findall(r"\bXid\b", txt, flags=re.I))

xid_pre = xid_count(meta / "gpu_xid_pre.txt")
xid_post = xid_count(meta / "gpu_xid_post.txt")
new_xid = xid_post > xid_pre
docker_ps = (meta / "docker_ps_after.txt").read_text(encoding="utf-8", errors="replace")
residual_container = tag in docker_ps
procs = (meta / "process_ps_after.txt").read_text(encoding="utf-8", errors="replace")
residual_process = "run_phase3.py" in procs and "v1e01_dyn_b_preflight_m1z_20260723" in procs

runner_exit = int(status.get("exit_code", 1))
elapsed = float(status.get("elapsed_monotonic_sec") or 0.0)

pass_ok = (
    run_exit == 0
    and runner_exit == 0
    and analyzer_ok
    and not status.get("forbid_pattern_hits")
    and not status.get("missing_required_paths")
    and all_png_ok
    and all_visual_pass
    and camera_pos_match
    and camera_rot_match
    and disp_ok
    and anchor_all_ok
    and safety_ok
    and margin_ok
    and phase_ok
    and (not fallen_any)
    and (not red_proxy_any)
    and post_count == 0
    and (not new_xid)
    and (not residual_container)
    and (not residual_process)
)

verdict = "DYN_B_REVIEWABLE_PREFLIGHT_PASS" if pass_ok else "DYN_B_REVIEWABLE_PREFLIGHT_FAIL_FINAL"
next_gate = "HUMAN_DYNAMIC_LABEL_REVIEW" if pass_ok else "STOP_NO_RETRY"
report = {
    "doc": "vlm-v1m1z-dyn-b-reviewable-preflight-2026-07-23",
    "milestone": "V1-M1Z",
    "build_count": 1,
    "run_count": 1,
    "image": {
        "tag": tag,
        "sha": json.loads((meta / "image_inspect.json").read_text(encoding="utf-8"))[0]["Id"],
    },
    "camera": {
        "expected_pos": expected_cam_pos,
        "expected_rot": expected_cam_rot,
        "actual_pos": cam_pos,
        "actual_rot": cam_rot,
        "pos_match": camera_pos_match,
        "rot_match": camera_rot_match,
        "forwarded_env": json.loads((meta / "host_forwarded_camera_env.json").read_text(encoding="utf-8")),
    },
    "frames": frame_report,
    "visual": {
        "all_key_frames_pass": all_visual_pass,
        "workcell_anchor_visibility_pass": anchor_all_ok,
        "workcell_anchor_visibility": anchor_visibility,
        "centroid_displacement_px_220_330": disp,
        "centroid_displacement_gate_px": 20.0,
    },
    "per_step_window_190_340": {
        "observed_steps": len(steps_rows),
        "allow_count": allow_count,
        "stop_count": stop_count,
        "slow_count": slow_count,
        "replan_count_nonzero_steps": replan_count,
        "margin_min_m": margin_min,
        "margin_gate_m": 0.10,
        "phase_220": phase220,
        "phase_330": phase330,
        "phase_pass": phase_ok,
        "analyzer_exit": analyzer_exit,
        "analyzer_pass": analyzer.get("pass"),
        "analyzer_errors": analyzer.get("errors"),
    },
    "safety_flags": {
        "fallen_any": fallen_any,
        "red_proxy_any": red_proxy_any,
    },
    "runner": {
        "exit_code": runner_exit,
        "run_exit_code": run_exit,
        "elapsed_sec": elapsed,
    },
    "post_and_xid": {
        "post_count_stdout_stderr": post_count,
        "xid_pre_count": xid_pre,
        "xid_post_count": xid_post,
        "new_xid": new_xid,
        "residual_container": residual_container,
        "residual_process": residual_process,
    },
    "provenance": {
        "dynamic": True,
        "provisional": True,
        "reviewer_approved": False,
        "scripted_locomotion": True,
        "human_hand_or_ppe": False,
        "vlm_output": False,
    },
    "verdict": verdict,
    "next_gate": next_gate,
}

doc_json.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
md_lines = [
    "# V1-M1Z Dyn-B reviewable preflight (2026-07-23)",
    "",
    f"- verdict: **{verdict}**",
    f"- next_gate: `{next_gate}`",
    f"- build_count/run_count: `{report['build_count']}/{report['run_count']}`",
    f"- image: `{report['image']['tag']}` / `{report['image']['sha']}`",
    f"- camera actual pos/rot: `{cam_pos}` / `{cam_rot}`",
    f"- runner exit/raw/elapsed: `{runner_exit}` / `{run_exit}` / `{elapsed:.3f}s`",
    f"- per-step ALLOW/STOP/SLOW/replan: `{allow_count}/{stop_count}/{slow_count}/{replan_count}`",
    f"- margin_min_m: `{margin_min}` (gate `>=0.10`)",
    f"- centroid displacement px(220->330): `{disp}` (gate `>=20`)",
    f"- visual all key frames pass: `{all_visual_pass}`",
    f"- workcell anchors visible: `{anchor_all_ok}`",
    f"- POST count: `{post_count}`",
    f"- new Xid: `{new_xid}`",
    f"- residual container/process: `{residual_container}` / `{residual_process}`",
]
doc_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
print(json.dumps({"verdict": verdict, "next_gate": next_gate, "runner_exit": runner_exit, "elapsed_sec": elapsed}, ensure_ascii=True))
PY
