#!/usr/bin/env bash
# V1-M1W1: corrected one-shot Dyn-B 0-POST preflight capture.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS_ROOT="$(cd "${DIST_ROOT}/.." && pwd)"
REPO_ROOT="${WS_ROOT}"
RUNNER="${WS_ROOT}/GMRobot/scripts/capture_one_shot_runner.py"
TAG="gmdisturb:e01-dyn-b-clean-m1v1-20260723"
IMAGE_SHA_EXPECTED="sha256:19112b9c1e8f63c04e8ef777840da823f0323b55f950f432f27ea8ba9d4cf14f"
RESULTS_HOST_ROOT="${DIST_ROOT}/results"
OUT_DIR="${DIST_ROOT}/results/paper_demo/v1e01_dyn_b_preflight_m1w1_20260723"
META_DIR="${OUT_DIR}/meta"
DOC_BASE="${DIST_ROOT}/docs/cross-project/vlm-v1m1w1-dyn-b-corrected-preflight-2026-07-23"

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
from e01_dyn_b_runtime_guard import build_m1v1_dyn_b_preflight_outer_argv  # noqa: E402

result_root_in_container = "/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1w1_20260723"
argv = build_m1v1_dyn_b_preflight_outer_argv(
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

git rev-parse HEAD > "${META_DIR}/git_head.txt"
git rev-parse 25c7518 > "${META_DIR}/anchor_commit.txt"
cp "${DIST_ROOT}/configs/e01_dyn_b_capture.yaml" "${META_DIR}/e01_dyn_b_capture.yaml"
docker image inspect "${TAG}" > "${META_DIR}/image_inspect.json"
python3 - <<'PY' "${META_DIR}/image_inspect.json" "${IMAGE_SHA_EXPECTED}"
import json
import sys
ins = json.loads(open(sys.argv[1], "r", encoding="utf-8").read())
actual = ins[0]["Id"]
expect = sys.argv[2]
if actual != expect:
    raise SystemExit(f"image sha mismatch: expected={expect} actual={actual}")
print(actual)
PY
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
  --require-path "${OUT_DIR}/scene/frame_000219_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000220_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000221_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000329_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000330_env0.png" \
  --require-path "${OUT_DIR}/scene/frame_000331_env0.png" \
  --require-path "${OUT_DIR}/safety_logs/phase3.csv" \
  --require-path "${OUT_DIR}/meta/camera_pose.json" \
  --require-path "${OUT_DIR}/meta/body_poses.jsonl" \
  --require-path "${OUT_DIR}/meta/numpy_origin_pre.json" \
  --require-path "${OUT_DIR}/meta/numpy_origin_post.json" \
  --require-path "${OUT_DIR}/meta/typing_extensions_pre.json" \
  --require-path "${OUT_DIR}/meta/typing_extensions_post.json" \
  -- \
  "${CMD[@]}"
RUN_EXIT=$?
set -e
echo "${RUN_EXIT}" > "${META_DIR}/runner_exit_code.txt"

nvidia-smi > "${META_DIR}/gpu_post.txt" || true
nvidia-smi -q -d XID > "${META_DIR}/gpu_xid_post.txt" || true
docker ps -a > "${META_DIR}/docker_ps_after.txt" || true
ps -eo pid,cmd > "${META_DIR}/process_ps_after.txt" || true

python3 - <<'PY' "${REPO_ROOT}" "${OUT_DIR}" "${META_DIR}" "${DOC_BASE}.json" "${DOC_BASE}.md" "${TAG}" "${IMAGE_SHA_EXPECTED}" "${RUN_EXIT}"
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
image_sha_expected = sys.argv[7]
run_exit = int(sys.argv[8])
sys.path.insert(0, str(repo_root / "g1_ur10e_disturbance"))
from scene_camera_override import g1_roi_from_body_points  # noqa: E402

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def png_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    sig = path.read_bytes()[:8]
    return sig == b"\x89PNG\r\n\x1a\n"

def xid_count(path: Path) -> int:
    if not path.is_file():
        return 0
    txt = path.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"\\bXid\\b", txt, flags=re.I))

status = json.loads((meta / "run_status.json").read_text(encoding="utf-8"))
stdout = (meta / "capture_stdout.txt").read_text(encoding="utf-8", errors="replace")
stderr = (meta / "capture_stderr.txt").read_text(encoding="utf-8", errors="replace")
text = stdout + "\n" + stderr
post_count = len(re.findall(r"\\bPOST\\b", text))

required_steps = [219, 220, 221, 329, 330, 331]
frame_report = {}
all_png_ok = True
for s in required_steps:
    p = out_dir / "scene" / f"frame_{s:06d}_env0.png"
    ok = png_ok(p)
    all_png_ok = all_png_ok and ok
    frame_report[str(s)] = {"path": str(p.relative_to(repo_root)), "exists": p.exists(), "valid_png": ok, "sha256": sha256_file(p) if p.exists() else None}

body_by_step = {}
bp = out_dir / "meta" / "body_poses.jsonl"
if bp.is_file():
    for line in bp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            body_by_step[int(rec["step"])] = rec

def step_phase(step: int) -> str | None:
    rec = body_by_step.get(step)
    if not rec:
        return None
    return rec.get("phase")

phase_220 = step_phase(220)
phase_330 = step_phase(330)
phase_ok = phase_220 == "lateral_positive_sweep" and phase_330 == "lateral_negative_sweep"

cam_pos = [0.2, 0.0, 3.2]
cp = out_dir / "meta" / "camera_pose.json"
if cp.is_file():
    cam_pos = json.loads(cp.read_text(encoding="utf-8")).get("pos", cam_pos)

def centroid_at(step: int):
    rec = body_by_step.get(step) or {}
    bodies = rec.get("g1_bodies") or {}
    pts = list(bodies.values())
    if not pts and rec.get("g1_root"):
        pts = [rec["g1_root"]]
    roi = g1_roi_from_body_points(pts, cam_pos=cam_pos, image_w=640, image_h=480)
    return roi

roi220 = centroid_at(220)
roi330 = centroid_at(330)
disp = None
if roi220.get("centroid_uv") and roi330.get("centroid_uv"):
    dx = roi330["centroid_uv"][0] - roi220["centroid_uv"][0]
    dy = roi330["centroid_uv"][1] - roi220["centroid_uv"][1]
    disp = float(math.hypot(dx, dy))
disp_ok = (disp is not None) and (disp >= 20.0)

steps_path = out_dir / "safety_logs" / "phase3_steps.csv"
window_rows = []
if steps_path.is_file():
    with steps_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            st = int(row["step"])
            if 190 <= st <= 340:
                window_rows.append(row)

allow_count = sum(1 for r in window_rows if str(r.get("gate", "")).upper() == "ALLOW")
stop_count = sum(1 for r in window_rows if str(r.get("gate", "")).upper() == "STOP")
slow_count = sum(1 for r in window_rows if str(r.get("gate", "")).upper() == "SLOW_DOWN")
replan_count = sum(1 for r in window_rows if str(r.get("replan_count", "0")).strip() not in {"", "0"})
margins = []
fallen_any = False
red_proxy_any = False
for r in window_rows:
    try:
        margins.append(float(r.get("dist_min_g1_body", "nan")))
    except ValueError:
        pass
    grz = r.get("g1_root_z", "")
    if grz not in {"", "nan", "NaN"}:
        try:
            if float(grz) < -0.5:
                fallen_any = True
        except ValueError:
            pass
    px = str(r.get("proxy_center_x", "")).strip()
    py = str(r.get("proxy_center_y", "")).strip()
    pz = str(r.get("proxy_center_z", "")).strip()
    if any(v not in {"", "0", "0.0", "nan", "NaN", "inf"} for v in (px, py, pz)):
        red_proxy_any = True

margin_min = min(margins) if margins else None
margin_ok = (margin_min is not None) and (margin_min >= 0.10)
safety_ok = len(window_rows) == 151 and allow_count == 151 and stop_count == 0 and slow_count == 0 and replan_count == 0

xid_pre = xid_count(meta / "gpu_xid_pre.txt")
xid_post = xid_count(meta / "gpu_xid_post.txt")
new_xid = xid_post > xid_pre
docker_ps = (meta / "docker_ps_after.txt").read_text(encoding="utf-8", errors="replace") if (meta / "docker_ps_after.txt").is_file() else ""
residual_container = tag in docker_ps
procs = (meta / "process_ps_after.txt").read_text(encoding="utf-8", errors="replace") if (meta / "process_ps_after.txt").is_file() else ""
residual_process = "run_phase3.py" in procs and "v1e01_dyn_b_preflight_m1w1_20260723" in procs

runner_exit = int(status.get("exit_code", 1))
elapsed = float(status.get("elapsed_monotonic_sec") or 0.0)

all_required_artifacts = all(
    (out_dir / rel).exists()
    for rel in [
        "safety_logs/phase3.csv",
        "meta/camera_pose.json",
        "meta/body_poses.jsonl",
        "meta/numpy_origin_pre.json",
        "meta/numpy_origin_post.json",
        "meta/typing_extensions_pre.json",
        "meta/typing_extensions_post.json",
    ]
)

pass_ok = (
    run_exit == 0
    and runner_exit == 0
    and not status.get("forbid_pattern_hits")
    and not status.get("missing_required_paths")
    and all_png_ok
    and all_required_artifacts
    and roi220.get("visible") is True
    and roi330.get("visible") is True
    and disp_ok
    and phase_ok
    and safety_ok
    and margin_ok
    and (not fallen_any)
    and (not red_proxy_any)
    and post_count == 0
    and (not new_xid)
    and (not residual_container)
    and (not residual_process)
)

verdict = "DYN_B_PREFLIGHT_CAPTURE_PASS" if pass_ok else "DYN_B_PREFLIGHT_CAPTURE_FAIL_FINAL"
next_gate = "HUMAN_DYNAMIC_LABEL_REVIEW" if pass_ok else "STOP_NO_RETRY"
report = {
    "doc": "vlm-v1m1w1-dyn-b-corrected-preflight-2026-07-23",
    "milestone": "V1-M1W1",
    "anchor_commit": "25c7518",
    "run_count": 1,
    "exact_command_shape": "docker/run.sh --tag IMAGE --results RESULTS bash -lc INNER",
    "image": {"tag": tag, "sha_expected": image_sha_expected, "sha_actual": json.loads((meta / "image_inspect.json").read_text(encoding="utf-8"))[0]["Id"]},
    "runner": {"exit_code": runner_exit, "run_exit_code": run_exit, "elapsed_sec": elapsed},
    "forbid_signatures_only": [
        "Traceback",
        "ModuleNotFoundError",
        "No module named",
        "numpy dtype mismatch",
        "cannot import name 'broadcast_to'",
        "cannot import ParamSpec",
        "NUMPY_ABI_GUARD_FAIL",
        "Failed to startup python extension",
        "ERROR_DEVICE_LOST",
        "DEVICE_LOST",
    ],
    "frames": frame_report,
    "roi": {
        "step220": roi220,
        "step330": roi330,
        "centroid_displacement_px_220_330": disp,
        "centroid_displacement_gate_px": 20.0,
    },
    "phases": {"step_220": phase_220, "step_330": phase_330, "exact_required": ["lateral_positive_sweep", "lateral_negative_sweep"], "pass": phase_ok},
    "safety_window_190_340": {
        "expected_steps": 151,
        "observed_steps": len(window_rows),
        "allow_count": allow_count,
        "stop_count": stop_count,
        "slow_count": slow_count,
        "replan_count_nonzero_steps": replan_count,
        "margin_min_m": margin_min,
        "margin_gate_m": 0.10,
        "all_allow_and_zero_stop_slow_replan": safety_ok,
        "margin_pass": margin_ok,
        "fallen": fallen_any,
        "red_proxy_present": red_proxy_any,
    },
    "post_and_residue": {"post_count_stdout_stderr": post_count, "xid_pre_count": xid_pre, "xid_post_count": xid_post, "new_xid": new_xid, "residual_container": residual_container, "residual_process": residual_process},
    "provenance": {"dynamic": True, "provisional": True, "reviewer_approved": False, "scripted": True, "human_hand_or_ppe": False, "vlm_output": False},
    "verdict": verdict,
    "next_gate": next_gate,
}
doc_json.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
md = [
    "# V1-M1W1 Dyn-B corrected preflight (2026-07-23)",
    "",
    f"- verdict: **{verdict}**",
    f"- next_gate: `{next_gate}`",
    f"- run_count: `{report['run_count']}`",
    f"- command_shape: `{report['exact_command_shape']}`",
    f"- image: `{tag}` / `{report['image']['sha_actual']}`",
    f"- runner exit: `{runner_exit}` (raw `{run_exit}`), elapsed `{elapsed:.3f}s`",
    f"- ROI displacement px (220->330): `{disp}`",
    f"- phases(220/330): `{phase_220}` / `{phase_330}`",
    f"- safety window ALLOW/STOP/SLOW/replan: `{allow_count}/{stop_count}/{slow_count}/{replan_count}`",
    f"- margin_min_m: `{margin_min}`",
    f"- POST count: `{post_count}`",
    f"- new Xid: `{new_xid}`",
  ]
doc_md.write_text("\n".join(md) + "\n", encoding="utf-8")
print(json.dumps({"verdict": verdict, "next_gate": next_gate, "runner_exit": runner_exit, "elapsed_sec": elapsed}, ensure_ascii=True))
PY
