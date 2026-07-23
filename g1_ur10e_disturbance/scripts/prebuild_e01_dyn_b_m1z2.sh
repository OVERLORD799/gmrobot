#!/usr/bin/env bash
# Host-side prebuild gate for V1-M1Z2. Any failure must prevent docker build.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WS_ROOT="$(cd "${DIST_ROOT}/.." && pwd)"
OUT_DIR="${DIST_ROOT}/results/paper_demo/v1m1z2_prebuild_20260723"
META_DIR="${OUT_DIR}/meta"
SUMMARY_JSON="${OUT_DIR}/prebuild_summary.json"
DOCKERFILE="${DIST_ROOT}/docker/Dockerfile.e01-dyn-b-clean-m1z2"
BASE_TAG="gmdisturb:b4-p010-20260721"
BASE_SHA_EXPECTED="sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68"

mkdir -p "${META_DIR}" "${OUT_DIR}"

fail() {
  echo "PREBUILD_FAIL: $*" >&2
  exit 1
}

echo "=== M1Z2 prebuild: git / base image / Dockerfile policy ==="
cd "${WS_ROOT}"
HEAD="$(git rev-parse HEAD)"
ORIGIN="$(git rev-parse origin/main)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
PORCELAIN="$(git status --porcelain)"
[[ "${BRANCH}" == "main" ]] || fail "branch must be main (got ${BRANCH})"
git merge-base --is-ancestor 315c48eec1a7afb424cbf23803651ab86669c5f8 HEAD \
  || fail "HEAD must contain baseline 315c48e"
# Refuse secrets/results accidentally tracked; allow dirty milestone sources before final commit.
if echo "${PORCELAIN}" | grep -E '(^.. |^\?\?)' | grep -Eiq '(\.env|token|credentials|\.pyc$|results/paper_demo)'; then
  fail "forbidden dirty paths in worktree (secrets/results/pyc)"
fi
BASE_SHA="$(docker image inspect "${BASE_TAG}" --format '{{.Id}}')"
[[ "${BASE_SHA}" == "${BASE_SHA_EXPECTED}" ]] || fail "base SHA mismatch: ${BASE_SHA}"

DF_TEXT="$(cat "${DOCKERFILE}")"
echo "${DF_TEXT}" | grep -Eqi 'pip install|pip uninstall|conda |apt-get|apt install' && fail "Dockerfile package mutation"
echo "${DF_TEXT}" | grep -Eqi '^[[:space:]]*RUN' && fail "Dockerfile must not contain RUN"
echo "${DF_TEXT}" | grep -Eqi 'pytest|test_e01_|dyn_b_source_closure|grep -q|results/paper_demo' && fail "Dockerfile behavior/history gate"

# Ensure secrets/results are dockerignored
DI="${DIST_ROOT}/.dockerignore"
grep -q '^results/' "${DI}" || fail ".dockerignore missing results/"
grep -q 'token' "${DI}" || fail ".dockerignore missing token exclusion"
grep -q 'docs/cross-project' "${DI}" || fail ".dockerignore missing docs/cross-project"
grep -q '__pycache__' "${DI}" || fail ".dockerignore missing __pycache__"

echo "=== py_compile related sources ==="
mapfile -t PY_FILES < <(
  find "${DIST_ROOT}" -type f -name '*.py' \
    ! -path '*/results/*' \
    ! -path '*/docs/cross-project/*' \
    ! -path '*/__pycache__/*' \
    ! -path '*/.venv/*' \
    | sort
)
python3 -m py_compile "${PY_FILES[@]}"

echo "=== offline unit tests ==="
declare -a TESTS=(
  "${DIST_ROOT}/scripts/test_e01_dyn_b_m1v1_source_closure_unit.py"
  "${DIST_ROOT}/scripts/test_e01_dyn_b_m1v1_docker_copy_coverage_unit.py"
  "${DIST_ROOT}/scripts/test_e01_dyn_b_m1y_camera_framing_unit.py"
  "${DIST_ROOT}/scripts/test_dyn_b_per_step_audit_analyzer_unit.py"
  "${DIST_ROOT}/scripts/test_e01_dyn_b_m1w1_command_construction_unit.py"
  "${DIST_ROOT}/scripts/test_run_sh_camera_env_forwarding_unit.py"
  "${DIST_ROOT}/scripts/test_e01_dyn_b_runtime_guard_unit.py"
  "${DIST_ROOT}/scripts/test_e01_dyn_b_m1z2_dockerfile_policy_unit.py"
)
TEST_RESULTS=()
for t in "${TESTS[@]}"; do
  [[ -f "${t}" ]] || fail "missing test ${t}"
  echo "-- $(basename "${t}")"
  python3 "${t}"
  TEST_RESULTS+=("$(basename "${t}"):PASS")
done

echo "=== import closure ==="
python3 - <<'PY' "${DIST_ROOT}" "${META_DIR}/source_closure.json"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "scripts"))
from dyn_b_source_closure import compute_local_import_closure
report = compute_local_import_closure(
    entry_file=root / "scripts" / "run_phase3.py",
    project_root=root,
)
out = Path(sys.argv[2])
out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
assert report["unresolved_local_imports"] == [], report["unresolved_local_imports"]
members = set(report["closure_members"])
assert "scene_camera_override.py" in members
print("closure_ok", len(members))
PY

echo "=== camera design fixture gate ==="
python3 - <<'PY' "${DIST_ROOT}" "${META_DIR}/camera_design_gate.json"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from e01_dyn_b_m1y_camera_framing import evaluate_anchors, evaluate_candidate, load_body_pose_steps
rows = load_body_pose_steps(root / "fixtures" / "m1y" / "body_poses_minimal.jsonl")
pos = (0.45, 0.0, 2.7)
rot = (0.7071, 0.0, 0.7071, 0.0)
cand = evaluate_candidate(cam_pos=pos, cam_rot=rot, body_rows=rows, prior_cam_pos=(0.35, 0.0, 2.5))
anchors = evaluate_anchors(pos)
assert cand["cam_pos"] == list(pos)
assert cand["cam_rot"] == list(rot)
assert cand["step_220"]["links_visible_margin"] >= 4
assert cand["step_330"]["links_visible_margin"] >= 4
assert cand["step_220"]["clipping_ratio"] <= 0.50
assert cand["step_330"]["clipping_ratio"] <= 0.50
assert cand["step_220"]["roi_area_fraction"] >= 0.01
assert cand["step_330"]["roi_area_fraction"] >= 0.01
assert (cand.get("centroid_separation_px_220_330") or 0) >= 20.0
assert anchors["pass"] is True
assert cand["gate_all"] is True
payload = {"camera_pos": list(pos), "camera_rot": list(rot), "candidate": cand, "anchors": anchors}
Path(sys.argv[2]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("camera_design_ok")
PY

echo "=== command construction shape ==="
python3 - <<'PY' "${DIST_ROOT}"
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from e01_dyn_b_runtime_guard import (
    M1Z2_IMAGE_TAG,
    assert_canonical_run_sh_payload,
    build_m1z2_smoke_outer_argv,
    smoke_enables_network_models,
)
argv = build_m1z2_smoke_outer_argv(
    run_sh_path=str(root / "docker" / "run.sh"),
    host_results_dir=str(root / "results"),
)
assert argv[1:5] == ["--tag", M1Z2_IMAGE_TAG, "--results", str(root / "results")]
assert_canonical_run_sh_payload(argv[5:])
assert argv[5:7] == ["bash", "-lc"]
assert not argv[7].startswith("/isaac-sim/python.sh")
assert smoke_enables_network_models(argv[7]) is False
assert "pip_prebundle" not in argv[7]
assert "PYTHONPATH" not in argv[7]
print("command_shape_ok")
PY

# Write summary JSON
python3 - <<'PY' "${SUMMARY_JSON}" "${HEAD}" "${BASE_SHA}" "${DOCKERFILE}" "${TEST_RESULTS[*]}"
import hashlib, json, sys
from pathlib import Path
summary_path = Path(sys.argv[1])
head = sys.argv[2]
base_sha = sys.argv[3]
dockerfile = Path(sys.argv[4])
tests = sys.argv[5].split() if len(sys.argv) > 5 else []
df_sha = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
payload = {
    "prebuild_verdict": "PASS",
    "head": head,
    "base_image": "gmdisturb:b4-p010-20260721",
    "base_image_sha": base_sha,
    "dockerfile": str(dockerfile),
    "dockerfile_sha256": df_sha,
    "tests": tests,
    "source_closure_json": "meta/source_closure.json",
    "camera_design_json": "meta/camera_design_gate.json",
}
summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("wrote", summary_path)
print("prebuild_summary_sha256", hashlib.sha256(summary_path.read_bytes()).hexdigest())
PY

echo "prebuild_verdict=PASS"
