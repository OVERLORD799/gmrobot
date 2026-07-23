#!/usr/bin/env python3
"""Deterministic host-side one-shot command runner for capture tasks."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _ensure_result_dir(path: Path, refuse_nonempty: bool) -> None:
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"result_dir is not a directory: {path}")
        if refuse_nonempty and any(path.iterdir()):
            raise RuntimeError(f"refuse nonempty result_dir: {path}")
        return
    path.mkdir(parents=True, exist_ok=False)


def _signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except Exception:
        return f"SIG{signum}"


def _shell_observable_exit(raw_returncode: int) -> int:
    if raw_returncode < 0:
        return 128 + (-raw_returncode)
    return raw_returncode


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result-dir", type=Path, required=True)
    ap.add_argument("--status-file", type=Path, required=True)
    ap.add_argument("--stdout-file", type=Path, required=True)
    ap.add_argument("--stderr-file", type=Path, required=True)
    ap.add_argument("--timeout-sec", type=float, default=None)
    ap.add_argument("--refuse-nonempty-dir", action="store_true")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    return ap


def _main() -> int:
    args = _build_parser().parse_args()
    if not args.command or args.command[0] != "--" or len(args.command) == 1:
        raise SystemExit("expected command after --")
    command_argv = args.command[1:]

    _ensure_result_dir(args.result_dir, refuse_nonempty=args.refuse_nonempty_dir)
    args.stdout_file.parent.mkdir(parents=True, exist_ok=True)
    args.stderr_file.parent.mkdir(parents=True, exist_ok=True)

    start_wall = _utc_now_iso()
    start_mono_ns = time.monotonic_ns()
    pre_status = {
        "schema_version": 1,
        "phase": "started",
        "command_argv": command_argv,
        "start_time_utc": start_wall,
        "end_time_utc": None,
        "elapsed_monotonic_sec": None,
        "exit_code": None,
        "timed_out": False,
        "signal": None,
        "stdout_file": str(args.stdout_file),
        "stderr_file": str(args.stderr_file),
    }
    _atomic_write_json(args.status_file, pre_status)

    timed_out = False
    rc: int | None = None
    signal_name: str | None = None
    with args.stdout_file.open("wb") as out_fh, args.stderr_file.open("wb") as err_fh:
        try:
            proc = subprocess.run(
                command_argv,
                check=False,
                timeout=args.timeout_sec,
                stdout=out_fh,
                stderr=err_fh,
            )
            rc = int(proc.returncode)
        except subprocess.TimeoutExpired:
            timed_out = True
            rc = 124

    end_wall = _utc_now_iso()
    elapsed_sec = (time.monotonic_ns() - start_mono_ns) / 1_000_000_000.0
    if rc is not None and rc < 0:
        signal_name = _signal_name(-rc)

    exit_code = _shell_observable_exit(rc if rc is not None else 125)
    final_status = {
        **pre_status,
        "phase": "finished",
        "end_time_utc": end_wall,
        "elapsed_monotonic_sec": elapsed_sec,
        "exit_code": exit_code,
        "returncode_raw": rc,
        "timed_out": timed_out,
        "signal": signal_name,
    }
    try:
        _atomic_write_json(args.status_file, final_status)
    except Exception as exc:
        raise SystemExit(f"fatal: failed to persist final status atomically: {exc}") from exc
    return exit_code


if __name__ == "__main__":
    raise SystemExit(_main())
