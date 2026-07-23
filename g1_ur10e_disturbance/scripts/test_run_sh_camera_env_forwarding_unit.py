#!/usr/bin/env python3
"""Offline unit test: run.sh must forward camera override envs into docker run."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "docker" / "run.sh"


def _run_capture(env_overrides: dict[str, str]) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        fake_bin = tdp / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        out_json = tdp / "docker_argv.json"
        docker_stub = fake_bin / "docker"
        docker_stub.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "python3 - \"$@\" <<'PY'\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['GMDISTURB_DOCKER_ARGV_OUT']).write_text(json.dumps(sys.argv[1:], ensure_ascii=True), encoding='utf-8')\n"
            "PY\n",
            encoding="utf-8",
        )
        docker_stub.chmod(0o755)

        env = os.environ.copy()
        env.update(env_overrides)
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
        env["HOME"] = str(tdp / "home")
        env["GMDISTURB_DOCKER_ARGV_OUT"] = str(out_json)
        cmd = [
            str(RUN_SH),
            "--tag",
            "gmdisturb:test",
            "--results",
            str(tdp / "results"),
            "bash",
            "-lc",
            "echo ok",
        ]
        subprocess.run(cmd, check=True, cwd=str(ROOT), env=env)
        return json.loads(out_json.read_text(encoding="utf-8"))


def _env_map_from_docker_run(argv: list[str]) -> dict[str, str]:
    # argv is docker argv starting at "run ...", produced by stub.
    out: dict[str, str] = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "-e" and i + 1 < len(argv):
            kv = argv[i + 1]
            if "=" in kv:
                k, v = kv.split("=", 1)
                out[k] = v
            i += 2
            continue
        i += 1
    return out


def test_forwards_only_when_present() -> None:
    argv = _run_capture({})
    emap = _env_map_from_docker_run(argv)
    assert "GMDISTURB_SCENE_CAMERA_OVERRIDE" not in emap
    assert "GMDISTURB_SCENE_CAMERA_POS" not in emap
    assert "GMDISTURB_SCENE_CAMERA_ROT" not in emap


def test_forwards_values_exactly() -> None:
    argv = _run_capture(
        {
            "GMDISTURB_SCENE_CAMERA_OVERRIDE": "1",
            "GMDISTURB_SCENE_CAMERA_POS": "0.45,0.0,2.7",
            "GMDISTURB_SCENE_CAMERA_ROT": "0.7071,0,0.7071,0",
        }
    )
    emap = _env_map_from_docker_run(argv)
    assert emap["GMDISTURB_SCENE_CAMERA_OVERRIDE"] == "1"
    assert emap["GMDISTURB_SCENE_CAMERA_POS"] == "0.45,0.0,2.7"
    assert emap["GMDISTURB_SCENE_CAMERA_ROT"] == "0.7071,0,0.7071,0"


def main() -> None:
    test_forwards_only_when_present()
    test_forwards_values_exactly()
    print("PASS test_run_sh_camera_env_forwarding_unit")


if __name__ == "__main__":
    main()
