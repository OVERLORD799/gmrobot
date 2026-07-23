#!/usr/bin/env python3
"""Offline unit tests for capture_one_shot_runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "capture_one_shot_runner.py"


def _run_runner(result_dir: Path, cmd: list[str], *, timeout_sec: float | None = None, refuse_nonempty: bool = False):
    status = result_dir / "meta" / "run_status.json"
    stdout = result_dir / "meta" / "stdout.txt"
    stderr = result_dir / "meta" / "stderr.txt"
    argv = [
        sys.executable,
        str(RUNNER),
        "--result-dir",
        str(result_dir),
        "--status-file",
        str(status),
        "--stdout-file",
        str(stdout),
        "--stderr-file",
        str(stderr),
    ]
    if timeout_sec is not None:
        argv += ["--timeout-sec", str(timeout_sec)]
    if refuse_nonempty:
        argv.append("--refuse-nonempty-dir")
    argv += ["--", *cmd]
    proc = subprocess.run(argv, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, status, stdout, stderr


def _run_runner_with_checks(
    result_dir: Path,
    cmd: list[str],
    *,
    forbid_patterns: list[str] | None = None,
    require_paths: list[str] | None = None,
):
    status = result_dir / "meta" / "run_status.json"
    stdout = result_dir / "meta" / "stdout.txt"
    stderr = result_dir / "meta" / "stderr.txt"
    argv = [
        sys.executable,
        str(RUNNER),
        "--result-dir",
        str(result_dir),
        "--status-file",
        str(status),
        "--stdout-file",
        str(stdout),
        "--stderr-file",
        str(stderr),
    ]
    for pat in forbid_patterns or []:
        argv += ["--forbid-pattern", pat]
    for path in require_paths or []:
        argv += ["--require-path", path]
    argv += ["--", *cmd]
    proc = subprocess.run(argv, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, status, stdout, stderr


def test_success_and_argv_and_outputs():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "ok"
        rc, status_path, stdout_path, stderr_path = _run_runner(
            result_dir,
            [sys.executable, "-c", "import sys; print('HELLO'); print('ERR', file=sys.stderr)"],
        )
        assert rc == 0
        assert status_path.is_file()
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["phase"] == "finished"
        assert data["exit_code"] == 0
        assert data["timed_out"] is False
        assert data["signal"] is None
        assert data["command_argv"][-1] == "import sys; print('HELLO'); print('ERR', file=sys.stderr)"
        assert data["start_time_utc"] and data["end_time_utc"]
        assert float(data["elapsed_monotonic_sec"]) >= 0.0
        assert "HELLO" in stdout_path.read_text(encoding="utf-8")
        assert "ERR" in stderr_path.read_text(encoding="utf-8")
        tmp_left = list((result_dir / "meta").glob("*.tmp"))
        assert not tmp_left, tmp_left


def test_argv_quoting_preserved():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "argv"
        script = "import json, sys; print(json.dumps(sys.argv[1:]))"
        args = ["arg with spaces", "quote'char", 'double"char', "semi;colon", "utf8-safe-ascii"]
        rc, status_path, stdout_path, _ = _run_runner(
            result_dir,
            [sys.executable, "-c", script, *args],
        )
        assert rc == 0
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["command_argv"][-len(args) :] == args
        echoed = json.loads(stdout_path.read_text(encoding="utf-8").strip())
        assert echoed == args


def test_nonzero_exit_code_propagates():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "nonzero"
        rc, status_path, _, _ = _run_runner(
            result_dir,
            [sys.executable, "-c", "import sys; sys.exit(7)"],
        )
        assert rc == 7
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["exit_code"] == 7
        assert data["timed_out"] is False


def test_signal_exit_recorded():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "signal"
        rc, status_path, _, _ = _run_runner(
            result_dir,
            [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
        )
        assert rc == 128 + 15
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["exit_code"] == 143
        assert data["returncode_raw"] == -15
        assert data["signal"] == "SIGTERM"
        assert data["timed_out"] is False


def test_timeout_exit_and_status():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "timeout"
        t0 = time.monotonic()
        rc, status_path, _, _ = _run_runner(
            result_dir,
            [sys.executable, "-c", "import time; time.sleep(2.0)"],
            timeout_sec=0.2,
        )
        elapsed = time.monotonic() - t0
        assert rc == 124
        assert elapsed < 2.0
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["exit_code"] == 124
        assert data["timed_out"] is True
        assert data["signal"] is None


def test_refuse_nonempty_result_dir():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "existing"
        result_dir.mkdir(parents=True, exist_ok=False)
        (result_dir / "keep.txt").write_text("keep", encoding="utf-8")
        rc, _, _, _ = _run_runner(
            result_dir,
            [sys.executable, "-c", "print('never')"],
            refuse_nonempty=True,
        )
        assert rc != 0


def test_exit_zero_with_traceback_is_rejected():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "traceback"
        rc, status_path, _, _ = _run_runner_with_checks(
            result_dir,
            [sys.executable, "-c", "print('Traceback (most recent call last):'); print('fake')"],
            forbid_patterns=[r"Traceback \(most recent call last\):"],
        )
        assert rc == 86
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["postcheck_failed"] is True
        assert data["forbid_pattern_hits"]


def test_exit_zero_with_missing_artifact_is_rejected():
    with tempfile.TemporaryDirectory() as td:
        result_dir = Path(td) / "artifact"
        required = result_dir / "must_exist.txt"
        rc, status_path, _, _ = _run_runner_with_checks(
            result_dir,
            [sys.executable, "-c", "print('ok')"],
            require_paths=[str(required)],
        )
        assert rc == 86
        data = json.loads(status_path.read_text(encoding="utf-8"))
        assert data["postcheck_failed"] is True
        assert str(required) in data["missing_required_paths"]


def main():
    test_success_and_argv_and_outputs()
    test_argv_quoting_preserved()
    test_nonzero_exit_code_propagates()
    test_signal_exit_recorded()
    test_timeout_exit_and_status()
    test_refuse_nonempty_result_dir()
    test_exit_zero_with_traceback_is_rejected()
    test_exit_zero_with_missing_artifact_is_rejected()
    print("PASS test_capture_one_shot_runner_unit")


if __name__ == "__main__":
    main()
