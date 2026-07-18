#!/usr/bin/env python3
"""Batch IV-J scenario data collection via gm_state_machine_agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]
_REGISTRY = _REPO / "configs" / "ivj" / "registry.yaml"
_LOG_DIR = _REPO / "output" / "safety_logs"
_AGENT = _REPO / "scripts" / "gm_state_machine_agent.py"
_ACTIVATE = Path("/root/activate_isaaclab.sh")

# Phase 1 already collected (skip unless --force)
_PHASE1_PRESETS = frozenset(
    {
        "ivj_static_block_place",  # default safety_layer1.yaml ~192734
        "ivj_static_far_observer",  # 193244
    }
)
# stress run used safety_layer1_stress.yaml, not IV-J preset id


def load_registry(path: Path | None = None) -> dict:
    reg_path = path or _REGISTRY
    with open(reg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("scenarios", data)


def list_session_dirs(log_dir: Path) -> set[str]:
    if not log_dir.is_dir():
        return set()
    return {p.name for p in log_dir.iterdir() if p.is_dir()}


def annotate_run(log_dir: Path, run_id: str, preset_id: str, meta: dict) -> None:
    run_dir = log_dir / run_id
    if not run_dir.is_dir():
        return
    (run_dir / "preset.txt").write_text(preset_id + "\n", encoding="utf-8")
    with open(run_dir / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def run_preset(
    preset_id: str,
    scenario: dict,
    *,
    max_steps: int,
    headless: bool,
    dry_run: bool,
    log_dir: Path,
) -> dict:
    config_name = scenario["config"]
    safety_config = _REPO / "configs" / "ivj" / config_name
    if not safety_config.is_file():
        raise FileNotFoundError(f"Missing IV-J config: {safety_config}")

    cmd = [
        "python",
        str(_AGENT),
        "--task=gm",
        "--headless",
        "--enable_cameras",
        "--enable_safety",
        f"--safety_config={safety_config}",
        f"--max_steps={max_steps}",
        "--progress_interval=500",
    ]
    if not headless:
        cmd.remove("--headless")

    shell_cmd = f"source {_ACTIVATE} && {' '.join(cmd)}"
    meta = {
        "preset_id": preset_id,
        "safety_config": str(safety_config),
        "max_steps": max_steps,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "command": shell_cmd,
    }

    if dry_run:
        print(f"[dry-run] {preset_id}: {shell_cmd}")
        return {"preset_id": preset_id, "status": "dry_run", **meta}

    before = list_session_dirs(log_dir)
    t0 = time.time()
    print(f"[collect] Starting {preset_id} (max_steps={max_steps})...", flush=True)
    proc = subprocess.run(
        ["bash", "-lc", shell_cmd],
        cwd=str(_REPO),
        capture_output=False,
    )
    elapsed = time.time() - t0
    after = list_session_dirs(log_dir)
    new_runs = sorted(after - before)
    run_id = new_runs[-1] if new_runs else ""
    meta["elapsed_sec"] = round(elapsed, 1)
    meta["run_id"] = run_id
    meta["exit_code"] = proc.returncode

    if run_id:
        annotate_run(log_dir, run_id, preset_id, meta)

    status = "ok" if proc.returncode == 0 and run_id else "failed"
    print(
        f"[collect] {preset_id} -> {status} run_id={run_id or 'unknown'} "
        f"({elapsed / 60:.1f} min)",
        flush=True,
    )
    return {"preset_id": preset_id, "status": status, **meta}


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch IV-J safety log collection")
    parser.add_argument(
        "--registry",
        type=Path,
        default=_REGISTRY,
        help="IV-J registry YAML",
    )
    parser.add_argument(
        "--presets",
        nargs="*",
        default=None,
        help="Subset of preset IDs (default: all not in Phase 1 skip list)",
    )
    parser.add_argument(
        "--max_steps",
        type=int,
        default=3000,
        help="Steps per episode (default 3000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List presets and commands without running Isaac",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run presets even if listed in Phase 1 skip set",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run with GUI (default: headless)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=_LOG_DIR,
        help="Safety log output root",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Write batch summary JSON",
    )
    args = parser.parse_args()

    scenarios = load_registry(args.registry)
    if not scenarios:
        print(f"No scenarios in {args.registry}", file=sys.stderr)
        return 1

    if args.presets:
        selected = [(pid, scenarios[pid]) for pid in args.presets if pid in scenarios]
        missing = set(args.presets) - set(scenarios)
        if missing:
            print(f"Unknown presets: {sorted(missing)}", file=sys.stderr)
            return 1
    else:
        selected = list(scenarios.items())
        if not args.force:
            selected = [(pid, sc) for pid, sc in selected if pid not in _PHASE1_PRESETS]

    if not selected:
        print("No presets to run (all skipped or empty). Use --force or --presets.")
        return 0

    print(f"IV-J batch: {len(selected)} preset(s), max_steps={args.max_steps}")
    results = []
    for preset_id, scenario in selected:
        results.append(
            run_preset(
                preset_id,
                scenario,
                max_steps=args.max_steps,
                headless=not args.no_headless,
                dry_run=args.dry_run,
                log_dir=args.log_dir,
            )
        )

    summary = {
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "max_steps": args.max_steps,
        "results": results,
    }
    summary_path = args.summary_json or (
        args.log_dir / f"ivj_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    if not args.dry_run:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(f"Summary written to {summary_path}")

    failed = [r for r in results if r.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
