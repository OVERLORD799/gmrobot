#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISTURB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DISTURB_ROOT}/.." && pwd)"
GM_ROOT="${REPO_ROOT}/GMRobot"

REQUIRED_HEAD="86b07d0"
TAG="gmdisturb:e01-func-c-empty-source-m1f7-20260723"
DOCKERFILE="${GM_ROOT}/docker/Dockerfile.e01-func-c-empty-source-m1f7"
RESULT_DIR="${DISTURB_ROOT}/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723"
DOC_BASENAME="vlm-v1m1f7-func-c-empty-source-visual-smoke-2026-07-23"
DOC_MD="${DISTURB_ROOT}/docs/cross-project/${DOC_BASENAME}.md"
DOC_JSON="${DISTURB_ROOT}/docs/cross-project/${DOC_BASENAME}.json"

REF_FRAME="${DISTURB_ROOT}/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png"
M1F5_REJECTED_FRAME="${DISTURB_ROOT}/results/paper_demo/v1e01_func_c_visual_smoke_m1f3r_20260723/scene/frame_000000_env0.png"

mkdir -p "${RESULT_DIR}/meta"

HEAD_SHORT="$(git -C "${REPO_ROOT}" rev-parse --short=7 HEAD)"
if [[ "${HEAD_SHORT}" != "${REQUIRED_HEAD}" ]]; then
  echo "STOP_NO_RETRY: HEAD mismatch (${HEAD_SHORT} != ${REQUIRED_HEAD})"
  exit 21
fi
git -C "${REPO_ROOT}" fetch origin
HEAD_FULL="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
ORIGIN_FULL="$(git -C "${REPO_ROOT}" rev-parse origin/main)"
if [[ "${HEAD_FULL}" != "${ORIGIN_FULL}" ]]; then
  echo "STOP_NO_RETRY: origin/main mismatch"
  exit 22
fi
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]]; then
  echo "STOP_NO_RETRY: worktree not clean"
  exit 23
fi

python3 "${GM_ROOT}/scripts/test_e01_func_c_capture_unit.py"
python3 "${DISTURB_ROOT}/scripts/test_v1e02_dataset_candidate_manifest_unit.py"
python3 "${DISTURB_ROOT}/scripts/validate_v1e02_dataset_candidate_manifest.py" \
  --manifest "${DISTURB_ROOT}/docs/cross-project/vlm-v1e02-visual-dataset-candidate-manifest-2026-07-23.json"

nvidia-smi -L > "${RESULT_DIR}/meta/gpu_info.txt" 2>&1 || true
nvidia-smi -q -d XID > "${RESULT_DIR}/meta/gpu_xid_pre.txt" 2>&1 || true
dmesg 2>/dev/null | grep -i "NVRM: Xid" > "${RESULT_DIR}/meta/dmesg_xid_pre.txt" || true

docker build -f "${DOCKERFILE}" -t "${TAG}" "${GM_ROOT}"
IMAGE_SHA="$(docker image inspect "${TAG}" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
if [[ -z "${IMAGE_SHA}" ]]; then
  IMAGE_SHA="sha256:$(docker image inspect "${TAG}" --format '{{.Id}}' | sed 's/^sha256://')"
fi
printf '%s\n' "${IMAGE_SHA}" > "${RESULT_DIR}/meta/image_sha.txt"

set +e
docker run --gpus all --rm \
  -e ACCEPT_EULA=Y \
  -e PRIVACY_CONSENT=Y \
  -e OMNI_KIT_ACCEPT_EULA=YES \
  -e GMROBOT_V1E01_TARGET_FULL=1 \
  -e GMROBOT_V1E01_VISUAL_ONLY=1 \
  -v "${DISTURB_ROOT}/results:/opt/projects/g1_ur10e_disturbance/results" \
  -v "${GM_ROOT}/configs/ivj_v1e01_target_container_full.yaml:/opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/shadow/target_full_override.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/target_full_override.py:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py:/opt/projects/GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/assets/container.usd:/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container.usd:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/assets/container_full.usd:/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_full.usd:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/assets/container_full_visual.usd:/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_full_visual.usd:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/assets/container_fixed.usd:/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/container_fixed.usd:ro" \
  -v "${GM_ROOT}/source/GMRobot/GMRobot/assets/part/part_fixed.usd:/opt/projects/GMRobot/source/GMRobot/GMRobot/assets/part/part_fixed.usd:ro" \
  -v "${HOME}/.cache/gmdisturb-docker/kit:/isaac-sim/kit/cache" \
  -v "${HOME}/.cache/gmdisturb-docker/ov:/root/.cache/ov" \
  -v "${HOME}/.cache/gmdisturb-docker/pip:/root/.cache/pip" \
  -v "${HOME}/.cache/gmdisturb-docker/gl:/root/.cache/nvidia" \
  -v "${HOME}/.cache/gmdisturb-docker/logs:/root/.nvidia-omniverse/logs" \
  -v "${HOME}/.cache/gmdisturb-docker/data:/root/.local/share/ov/data" \
  -v "${HOME}/.cache/gmdisturb-docker/documents:/root/Documents" \
  "${TAG}" \
  bash -lc "set -euo pipefail
/isaac-sim/python.sh - <<'PY'
import json
import os
import sys
sys.path.insert(0, '/opt/projects/GMRobot/source/GMRobot/GMRobot')
sys.path.insert(0, '/opt/projects/GMRobot/source/GMRobot')
from shadow.target_full_override import resolve_v1e01_mode_flags
from GMRobot.tasks.manager_based.gmrobot import gmrobot_env_cfg as cfg

assert os.environ.get('GMROBOT_V1E01_TARGET_FULL') == '1'
assert os.environ.get('GMROBOT_V1E01_VISUAL_ONLY') == '1'
flags = resolve_v1e01_mode_flags(dict(os.environ))
assert flags.get('task_execution') is False
assert flags.get('visual_dataset_only') is True
assert flags.get('spawn_task_parts') is False
part_count = len([k for k in cfg.PART_ASSETS.keys() if k.startswith('part_')])
containerA = 'box_A' in cfg.CONTAINER_ASSETS
gridA = 'grid_A' in cfg.CONTAINER_ASSETS
containerB = 'box_B' in cfg.CONTAINER_ASSETS
assert part_count == 0, part_count
assert containerA and gridA and containerB
out = {
    'flags': flags,
    'part_count': part_count,
    'containerA_exists': containerA,
    'gridA_exists': gridA,
    'containerB_exists': containerB,
    'container_assets_keys': sorted(cfg.CONTAINER_ASSETS.keys()),
}
with open('/opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723/meta/runtime_prim_counts.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print('runtime_assert_ok', json.dumps(out, ensure_ascii=False))
PY
/isaac-sim/python.sh /opt/projects/GMRobot/scripts/gm_state_machine_agent.py --task gm --headless --enable_cameras --enable_safety --safety_config /opt/projects/GMRobot/configs/ivj_v1e01_target_container_full.yaml --save_camera --camera_output_dir /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723/scene --camera_save_interval 1 --max_steps 1
" \
  > "${RESULT_DIR}/meta/smoke_stdout.txt" \
  2> "${RESULT_DIR}/meta/smoke_stderr.txt"
SMOKE_EC=$?
set -e
printf '%s\n' "${SMOKE_EC}" > "${RESULT_DIR}/meta/smoke_exit_code.txt"

nvidia-smi -q -d XID > "${RESULT_DIR}/meta/gpu_xid_post.txt" 2>&1 || true
dmesg 2>/dev/null | grep -i "NVRM: Xid" > "${RESULT_DIR}/meta/dmesg_xid_post.txt" || true

python3 - <<'PY'
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image
import numpy as np

REPO_ROOT = Path("/home/czz/GMrobot")
DISTURB_ROOT = REPO_ROOT / "g1_ur10e_disturbance"
GM_ROOT = REPO_ROOT / "GMRobot"
RESULT_DIR = DISTURB_ROOT / "results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723"
DOC_JSON = DISTURB_ROOT / "docs/cross-project/vlm-v1m1f7-func-c-empty-source-visual-smoke-2026-07-23.json"
DOC_MD = DISTURB_ROOT / "docs/cross-project/vlm-v1m1f7-func-c-empty-source-visual-smoke-2026-07-23.md"
REF_FRAME = DISTURB_ROOT / "results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png"
REJECTED_FRAME = DISTURB_ROOT / "results/paper_demo/v1e01_func_c_visual_smoke_m1f3r_20260723/scene/frame_000000_env0.png"

sys.path.insert(0, str(GM_ROOT / "source/GMRobot/GMRobot"))
sys.path.insert(0, str(GM_ROOT / "source/GMRobot"))
from shadow.v1e01_func_c_capture import filled_content_roi, source_box_a_roi, target_box_b_roi  # noqa: E402
from shadow.target_full_override import CAMERA_POS, CAMERA_ROT  # noqa: E402

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""

def count_xid(path: Path) -> int:
    if not path.is_file():
        return 0
    txt = path.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(r"Xid", txt, flags=re.IGNORECASE))

smoke_ec = int((RESULT_DIR / "meta/smoke_exit_code.txt").read_text().strip())
frame = RESULT_DIR / "scene/frame_000000_env0.png"
if smoke_ec != 0:
    raise SystemExit("STOP_NO_RETRY: smoke exit != 0")
if not frame.is_file():
    raise SystemExit("STOP_NO_RETRY: frame missing")

img = np.asarray(Image.open(frame).convert("RGB"))
non_black = bool(np.any(img > 0))
if not non_black:
    raise SystemExit("STOP_NO_RETRY: png black")

src_roi = source_box_a_roi()
tgt_roi = target_box_b_roi()
fill_roi = filled_content_roi()
if not (src_roi.get("visible") and tgt_roi.get("visible")):
    raise SystemExit("STOP_NO_RETRY: dual box roi not visible")
if int(fill_roi.get("pixel_area", 0)) <= 0:
    raise SystemExit("STOP_NO_RETRY: right full content roi empty")

runtime_json = RESULT_DIR / "meta/runtime_prim_counts.json"
runtime = json.loads(runtime_json.read_text(encoding="utf-8"))
if int(runtime.get("part_count", -1)) != 0:
    raise SystemExit("STOP_NO_RETRY: part_count != 0")
if not (runtime.get("containerA_exists") and runtime.get("gridA_exists") and runtime.get("containerB_exists")):
    raise SystemExit("STOP_NO_RETRY: container/grid existence assert failed")

stdout = (RESULT_DIR / "meta/smoke_stdout.txt").read_text(encoding="utf-8", errors="ignore")
stderr = (RESULT_DIR / "meta/smoke_stderr.txt").read_text(encoding="utf-8", errors="ignore")
combined = stdout + "\n" + stderr

for bad in ("Traceback", "DEVICE_LOST", "residual"):
    if bad in combined:
        raise SystemExit(f"STOP_NO_RETRY: bad token detected: {bad}")
if re.search(r"\bPOST\b[^0-9]*[1-9]", combined):
    raise SystemExit("STOP_NO_RETRY: POST non-zero detected")

pre_xid = count_xid(RESULT_DIR / "meta/gpu_xid_pre.txt") + count_xid(RESULT_DIR / "meta/dmesg_xid_pre.txt")
post_xid = count_xid(RESULT_DIR / "meta/gpu_xid_post.txt") + count_xid(RESULT_DIR / "meta/dmesg_xid_post.txt")
new_xid = post_xid > pre_xid
if new_xid:
    raise SystemExit("STOP_NO_RETRY: newXid detected")

source_asset = GM_ROOT / "source/GMRobot/GMRobot/assets/container.usd"
source_sha = sha(source_asset)
if not source_sha.startswith("ee307"):
    raise SystemExit("STOP_NO_RETRY: ContainerA source asset SHA drift")

head = subprocess.check_output(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True).strip()
image_sha = (RESULT_DIR / "meta/image_sha.txt").read_text(encoding="utf-8").strip()
gpu_line = subprocess.check_output(
    ["bash", "-lc", "nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"], text=True
).strip()

record = {
    "task": "V1-M1F7 Func-C visual-only empty-source occlusion fix smoke",
    "date": "2026-07-23",
    "preflight": {
        "head_expected_short": "86b07d0",
        "head_actual_full": head,
        "origin_match": True,
        "worktree_clean": True,
        "m1f6_tests_manifest_pass": True,
    },
    "budget": {"build": 1, "isaac_applauncher_smoke": 1, "retry": 0},
    "build": {
        "dockerfile": str(GM_ROOT / "docker/Dockerfile.e01-func-c-empty-source-m1f7"),
        "copy_only": True,
        "tag": "gmdisturb:e01-func-c-empty-source-m1f7-20260723",
        "image_sha": image_sha,
        "exit_code": 0,
    },
    "smoke": {
        "result_dir": str(RESULT_DIR),
        "exit_code": smoke_ec,
        "frame_abs_path": str(frame),
        "frame_sha256": sha(frame),
        "env_explicit": {
            "GMROBOT_V1E01_TARGET_FULL": "1",
            "GMROBOT_V1E01_VISUAL_ONLY": "1",
        },
    },
    "mode_flags": {
        "task_execution": False,
        "visual_dataset_only": True,
        "spawn_task_parts": False,
    },
    "runtime_assertions": runtime,
    "camera": {"pos": list(CAMERA_POS), "rot": list(CAMERA_ROT)},
    "roi": {
        "source_box_a": src_roi,
        "target_box_b": tgt_roi,
        "right_full_content": fill_roi,
    },
    "assets": {
        "containerA_asset_path": str(source_asset),
        "containerA_asset_sha256": source_sha,
        "containerA_asset_expected_prefix": "ee307...",
    },
    "references": {
        "reference_frame_path": str(REF_FRAME),
        "reference_frame_sha256": sha(REF_FRAME),
        "m1f5_rejected_frame_path": str(REJECTED_FRAME),
        "m1f5_rejected_frame_sha256": sha(REJECTED_FRAME),
    },
    "gpu_xid": {
        "gpu_info": gpu_line,
        "xid_pre_count": pre_xid,
        "xid_post_count": post_xid,
        "new_xid": new_xid,
    },
    "gates": {
        "exit_0": smoke_ec == 0,
        "png_valid_nonblack": non_black,
        "dual_box_roi_present": bool(src_roi.get("visible") and tgt_roi.get("visible")),
        "right_full_content_present": int(fill_roi.get("pixel_area", 0)) > 0,
        "part_count_zero": int(runtime.get("part_count", -1)) == 0,
        "post_zero": True,
        "no_traceback": "Traceback" not in combined,
        "no_device_lost": "DEVICE_LOST" not in combined,
        "no_new_xid": not new_xid,
        "no_residual": "residual" not in combined.lower(),
    },
    "forbidden_ops": {
        "formal_task_recapture": False,
        "network_post": False,
        "model_call": False,
    },
    "visual_verdict": "VISUAL_REVIEW_REQUIRED",
    "note": "Do not auto-pass. Main agent must compare against reference frame_000330_env0 (left green box, white grid, proportion/orientation, no bracket/stair/fan occlusion).",
}

DOC_JSON.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

md = f"""# V1-M1F7 Func-C visual-only 去遮挡修复：source-only build + 单次 visual smoke（2026-07-23）

结论：`VISUAL_REVIEW_REQUIRED`（按要求不自动PASS，需与 reference `frame_000330_env0` 人工并排复核）

## 前置核验
- HEAD（short）：`86b07d0`（完整匹配）
- origin/main 一致：`true`
- worktree clean：`true`
- M1F6 tests + manifest：`PASS`

## 一次性预算执行（无重试）
- Build（1/1）：`{record['build']['tag']}`，Dockerfile 仅 COPY，exit=`0`
- Isaac/AppLauncher smoke（1/1）：exit=`{smoke_ec}`

## 关键结果
- 结果目录：`{RESULT_DIR}`
- 顶视 RGB：`{frame}`
- frame SHA256：`{record['smoke']['frame_sha256']}`
- image SHA：`{image_sha}`
- source asset SHA256：`{source_sha}`
- reference frame SHA256：`{record['references']['reference_frame_sha256']}`
- M1F5 rejected frame SHA256：`{record['references']['m1f5_rejected_frame_sha256']}`

## 运行断言与门禁
- 显式环境变量：`GMROBOT_V1E01_TARGET_FULL=1` + `GMROBOT_V1E01_VISUAL_ONLY=1`
- mode flags：`task_execution=false`、`visual_dataset_only=true`、`spawn_task_parts=false`
- runtime prim asserts：`Part_* count=0`，`ContainerA/GridA/ContainerB` 均存在
- 自动门禁：exit0/PNG非黑/双箱ROI/右满箱内容/Part count0/POST0/无Traceback/无DEVICE_LOST/无newXid/无residual 均通过

## 人工复核要求（保持未自动通过）
- 与 `reference frame_000330_env0` 对照左箱绿色框、白色规则栅格、比例朝向
- 确认无白托架/阶梯/扇形/遮挡
- 当前 verdict 固定为：`VISUAL_REVIEW_REQUIRED`
"""
DOC_MD.write_text(md, encoding="utf-8")
print("record_written", DOC_JSON)
print("markdown_written", DOC_MD)
PY

echo "DONE: ${TAG}"
