#!/usr/bin/env python3
"""Layer 2 online Isaac A/B: Layer 1 only (A) vs Tier fusion (B)."""

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
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

from report_safety_metrics import analyze_path  # noqa: E402
from report_shadow_metrics import enrich_rows_with_shadow, _gate_metrics  # noqa: E402
from _layer2_import import load_layer2_module
from _safety_import import bootstrap_safety, load_safety_module

bootstrap_safety()
_fusion = load_safety_module("fusion")
_predictor_mod = load_layer2_module("predictor")

load_fusion_config = _fusion.load_fusion_config
SafetyPredictor = _predictor_mod.SafetyPredictor

_REGISTRY = _REPO / "configs" / "ivj" / "registry.yaml"
_LOG_DIR = _REPO / "output" / "safety_logs"
_AGENT = _REPO / "scripts" / "gm_state_machine_agent.py"
_ACTIVATE = Path("/root/activate_isaaclab.sh")
_DEFAULT_MODEL = _REPO / "output" / "safety_models" / "20260618_142722"
_DEFAULT_PRESETS = [
    "ivj_static_shoulder_pass",
    "ivj_dynamic_fast_sweep",
    "ivj_intrusion_positive",
]
_REPORT_PATH = _REPO / "output" / "layer2_ab_report.md"
_CSV_WATCHDOG_SEC = 15 * 60


def load_registry(path: Path | None = None) -> dict:
    reg_path = path or _REGISTRY
    with open(reg_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("scenarios", data)


def list_session_dirs(log_dir: Path) -> set[str]:
    if not log_dir.is_dir():
        return set()
    return {p.name for p in log_dir.iterdir() if p.is_dir()}


def find_completed_run(
    log_dir: Path,
    preset_id: str,
    ab_group: str,
    *,
    experiment: str = "layer2_online_ab",
) -> tuple[str, dict] | tuple[None, None]:
    """Reuse a prior successful A/B run (has CSV + manifest, not watchdog-killed)."""
    if not log_dir.is_dir():
        return None, None
    for run_dir in sorted(log_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.is_file():
            continue
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        if meta.get("ab_experiment") != experiment:
            continue
        if meta.get("preset_id") != preset_id or meta.get("ab_group") != ab_group:
            continue
        if meta.get("watchdog_killed"):
            continue
        if meta.get("exit_code", 0) != 0:
            continue
        if not list(run_dir.glob("episode_*.csv")):
            continue
        return run_dir.name, meta
    return None, None


def annotate_run(
    log_dir: Path,
    run_id: str,
    preset_id: str,
    meta: dict,
) -> None:
    run_dir = log_dir / run_id
    if not run_dir.is_dir():
        return
    (run_dir / "preset.txt").write_text(preset_id + "\n", encoding="utf-8")
    with open(run_dir / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def build_agent_cmd(
    safety_config: Path,
    *,
    max_steps: int,
    enable_layer2_fusion: bool,
    layer2_model_dir: Path | None,
    enable_replan: bool = False,
) -> list[str]:
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
    if enable_layer2_fusion:
        cmd.append("--enable_layer2_fusion")
        cmd.append(f"--layer2_model_dir={layer2_model_dir}")
    if enable_replan:
        cmd.append("--enable_replan")
    return cmd


def run_with_watchdog(
    shell_cmd: str,
    log_dir: Path,
    before: set[str],
    watchdog_sec: int,
) -> tuple[int, str, bool]:
    """Run Isaac agent; return (exit_code, run_id, watchdog_killed)."""
    proc = subprocess.Popen(
        ["bash", "-lc", shell_cmd],
        cwd=str(_REPO),
    )
    t0 = time.time()
    run_id = ""
    watchdog_killed = False

    while proc.poll() is None:
        after = list_session_dirs(log_dir)
        new_runs = sorted(after - before)
        if new_runs:
            candidate = new_runs[-1]
            csv_files = list((log_dir / candidate).glob("episode_*.csv"))
            if csv_files:
                run_id = candidate
        elapsed = time.time() - t0
        if not run_id and elapsed >= watchdog_sec:
            print(
                f"[watchdog] No CSV after {watchdog_sec // 60} min; killing pid={proc.pid}",
                flush=True,
            )
            proc.kill()
            proc.wait()
            watchdog_killed = True
            break
        time.sleep(10)

    exit_code = proc.returncode if proc.returncode is not None else proc.wait()
    if not run_id:
        after = list_session_dirs(log_dir)
        new_runs = sorted(after - before)
        run_id = new_runs[-1] if new_runs else ""
    return exit_code, run_id, watchdog_killed


def run_metrics_scripts(
    run_dir: Path,
    safety_config: Path,
    *,
    ab_group: str,
    model_dir: Path | None,
) -> dict:
    """Offline Layer1 metrics; shadow replay for B group."""
    csv_files = sorted(run_dir.glob("episode_*.csv"))
    if not csv_files:
        return {"status": "no_csv"}

    subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts" / "report_safety_metrics.py"),
            str(run_dir),
            "--config",
            str(safety_config),
        ],
        cwd=str(_REPO),
        check=False,
    )

    layer1 = analyze_path(csv_files[0], safety_config)
    result = {"layer1": layer1, "shadow": None}

    if ab_group == "B" and model_dir is not None:
        shadow_json = run_dir / "shadow_metrics.json"
        subprocess.run(
            [
                sys.executable,
                str(_REPO / "scripts" / "report_shadow_metrics.py"),
                str(run_dir),
                "--config",
                str(safety_config),
                "--model-dir",
                str(model_dir),
                "--output-json",
                str(shadow_json),
            ],
            cwd=str(_REPO),
            check=False,
        )
        if shadow_json.is_file():
            result["shadow"] = json.loads(shadow_json.read_text(encoding="utf-8"))
        else:
            import csv

            fusion_config = load_fusion_config(_REPO / "configs" / "safety_fusion.yaml")
            predictor = SafetyPredictor.from_artifacts(model_dir)
            with open(csv_files[0], newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            config = load_safety_module("config").load_safety_config(safety_config)
            rows = enrich_rows_with_shadow(rows, predictor, config, fusion_config)
            result["shadow"] = [
                {
                    "g_rule": _gate_metrics(rows, "g_rule", config),
                    "would_fuse": _gate_metrics(rows, "would_fuse", config),
                }
            ]
    return result


def fmt_pct(x) -> str:
    if x is None:
        return "N/A"
    return f"{100.0 * x:.1f}%"


def fmt_recall(x) -> str:
    if x is None:
        return "N/A"
    return f"{x:.4f}"


def check_acceptance(a: dict, b: dict, preset_id: str) -> dict:
    """Evaluate acceptance criteria vs A baseline."""
    a_fs = a.get("false_stop_rate")
    b_fs = b.get("false_stop_rate")
    a_ir = a.get("intervention_rate")
    b_ir = b.get("intervention_rate")
    a_recall = a.get("safety_recall")
    b_recall = b.get("safety_recall")

    notes: list[str] = []
    passed = True

    if preset_id in ("ivj_static_shoulder_pass", "ivj_dynamic_fast_sweep"):
        if a_fs is not None and b_fs is not None:
            if b_fs <= a_fs or (a_fs - b_fs) >= 0.05:
                notes.append(f"false_stop B({fmt_pct(b_fs)}) <= A({fmt_pct(a_fs)}) or ↓≥5pp")
            else:
                passed = False
                notes.append(f"false_stop B({fmt_pct(b_fs)}) > A({fmt_pct(a_fs)}) without 5pp drop")
        else:
            notes.append("false_stop: insufficient data")

    if preset_id == "ivj_intrusion_positive":
        if a_recall is not None and b_recall is not None:
            if b_recall >= a_recall - 0.01:
                notes.append(f"recall B({fmt_recall(b_recall)}) >= A({fmt_recall(a_recall)})")
            else:
                passed = False
                notes.append(f"recall degraded: A={fmt_recall(a_recall)} B={fmt_recall(b_recall)}")
        elif b_recall == 1.0 or a_recall == 1.0:
            notes.append(f"recall A={fmt_recall(a_recall)} B={fmt_recall(b_recall)}")
        else:
            notes.append("recall: check GT STOP steps")

    if a_ir is not None and b_ir is not None:
        delta = b_ir - a_ir
        notes.append(f"intervention_rate A={fmt_pct(a_ir)} B={fmt_pct(b_ir)} (Δ={delta:+.1%})")

    return {"passed": passed, "notes": notes}


def write_report(
    results: list[dict],
    *,
    model_dir: Path,
    report_path: Path,
) -> None:
    lines = [
        "# Layer 2 Online A/B Report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Model (B group): `{model_dir}`",
        "",
        "## Acceptance criteria",
        "",
        "- **shoulder / fast_sweep**: B `false_stop_rate` ≤ A or significantly lower (≥5pp)",
        "- **intrusion**: B `safety_recall` not degraded vs A",
        "- **all presets**: compare `intervention_rate`",
        "",
        "## Results",
        "",
        "| preset | group | run_id | intervention | false_stop | miss | recall | outcome | accept |",
        "|:-------|:-----:|:-------|-------------:|-----------:|-----:|-------:|:--------|:------:|",
    ]

    by_preset: dict[str, dict[str, dict]] = {}
    for r in results:
        preset = r["preset_id"]
        grp = r["ab_group"]
        m = r.get("metrics", {}).get("layer1", {})
        accept = ""
        if r.get("status") != "ok":
            accept = "❌"
        by_preset.setdefault(preset, {})[grp] = r

        lines.append(
            f"| `{preset}` | {grp} | `{r.get('run_id', '')}` | "
            f"{fmt_pct(m.get('intervention_rate'))} | {fmt_pct(m.get('false_stop_rate'))} | "
            f"{fmt_pct(m.get('miss_rate'))} | {fmt_recall(m.get('safety_recall'))} | "
            f"{m.get('outcome', r.get('status', ''))} | {accept} |"
        )

    lines.extend(["", "## Acceptance summary", ""])
    for preset in sorted(by_preset):
        groups = by_preset[preset]
        if "A" not in groups or "B" not in groups:
            lines.append(f"- `{preset}`: incomplete (missing A or B run)")
            continue
        a_m = groups["A"].get("metrics", {}).get("layer1", {})
        b_m = groups["B"].get("metrics", {}).get("layer1", {})
        verdict = check_acceptance(a_m, b_m, preset)
        mark = "✅" if verdict["passed"] else "❌"
        lines.append(f"- {mark} `{preset}`: " + "; ".join(verdict["notes"]))

    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```bash",
            "cd /root/GMRobot",
            "python scripts/run_layer2_ab.py",
            "python scripts/report_safety_metrics.py output/safety_logs/<run_id> --config configs/ivj/<preset>.yaml",
            "python scripts/report_shadow_metrics.py output/safety_logs/<run_id> \\",
            f"  --model-dir {model_dir} --output-json output/shadow_metrics.json",
            "```",
            "",
        ]
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] Wrote {report_path}")


def run_ab(
    presets: list[str],
    *,
    max_steps: int,
    model_dir: Path,
    log_dir: Path,
    dry_run: bool,
    watchdog_sec: int,
    resume: bool = True,
    enable_replan: bool = False,
) -> list[dict]:
    scenarios = load_registry()
    results: list[dict] = []

    for preset_id in presets:
        if preset_id not in scenarios:
            raise KeyError(f"Unknown preset: {preset_id}")
        scenario = scenarios[preset_id]
        safety_config = _REPO / "configs" / "ivj" / scenario["config"]

        for ab_group, enable_fusion in (("A", False), ("B", True)):
            cmd = build_agent_cmd(
                safety_config,
                max_steps=max_steps,
                enable_layer2_fusion=enable_fusion,
                layer2_model_dir=model_dir if enable_fusion else None,
                enable_replan=enable_replan,
            )
            shell_cmd = f"source {_ACTIVATE} && {' '.join(cmd)}"
            meta_base = {
                "preset_id": preset_id,
                "ab_group": ab_group,
                "ab_experiment": "layer2_online_ab",
                "layer2_model_dir": str(model_dir) if enable_fusion else "",
                "enable_layer2_fusion": enable_fusion,
                "enable_replan": enable_replan,
                "safety_config": str(safety_config),
                "max_steps": max_steps,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "command": shell_cmd,
            }

            print(
                f"\n[ab] preset={preset_id} group={ab_group} fusion={enable_fusion}",
                flush=True,
            )

            if resume and not dry_run:
                existing_id, existing_meta = find_completed_run(
                    log_dir, preset_id, ab_group
                )
                if existing_id:
                    print(
                        f"[ab] resume: reusing {existing_id} for {preset_id} group={ab_group}",
                        flush=True,
                    )
                    metrics = run_metrics_scripts(
                        log_dir / existing_id,
                        safety_config,
                        ab_group=ab_group,
                        model_dir=model_dir if enable_fusion else None,
                    )
                    entry = {
                        "preset_id": preset_id,
                        "ab_group": ab_group,
                        "run_id": existing_id,
                        "status": "ok",
                        "metrics": metrics,
                        "resumed": True,
                        **existing_meta,
                    }
                    results.append(entry)
                    continue

            if dry_run:
                print(f"  {shell_cmd}")
                results.append(
                    {
                        "preset_id": preset_id,
                        "ab_group": ab_group,
                        "status": "dry_run",
                        **meta_base,
                    }
                )
                continue

            before = list_session_dirs(log_dir)
            t0 = time.time()
            exit_code, run_id, watchdog_killed = run_with_watchdog(
                shell_cmd, log_dir, before, watchdog_sec
            )
            elapsed = time.time() - t0
            meta = {
                **meta_base,
                "elapsed_sec": round(elapsed, 1),
                "run_id": run_id,
                "exit_code": exit_code,
                "watchdog_killed": watchdog_killed,
            }
            if run_id:
                annotate_run(log_dir, run_id, preset_id, meta)

            has_csv = bool(run_id) and list((log_dir / run_id).glob("episode_*.csv"))
            status = "ok" if exit_code == 0 and has_csv and not watchdog_killed else "failed"
            meta["status"] = status

            metrics = {}
            if has_csv:
                metrics = run_metrics_scripts(
                    log_dir / run_id,
                    safety_config,
                    ab_group=ab_group,
                    model_dir=model_dir if enable_fusion else None,
                )

            entry = {
                "preset_id": preset_id,
                "ab_group": ab_group,
                "run_id": run_id,
                "status": status,
                "metrics": metrics,
                **meta,
            }
            results.append(entry)
            print(
                f"[ab] {preset_id} group={ab_group} -> {status} run_id={run_id or 'none'} "
                f"({elapsed / 60:.1f} min)",
                flush=True,
            )

    summary_path = log_dir / f"layer2_ab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"[ab] Summary JSON: {summary_path}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Layer 2 online Isaac A/B (A=L1, B=L1+Tier fusion)")
    parser.add_argument(
        "--presets",
        nargs="*",
        default=_DEFAULT_PRESETS,
        help="IV-J preset IDs (default: shoulder, fast_sweep, intrusion)",
    )
    parser.add_argument("--max-steps", type=int, default=3000)
    parser.add_argument("--model-dir", type=Path, default=_DEFAULT_MODEL)
    parser.add_argument("--log-dir", type=Path, default=_LOG_DIR)
    parser.add_argument("--report", type=Path, default=_REPORT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--watchdog-sec",
        type=int,
        default=_CSV_WATCHDOG_SEC,
        help="Kill run if no CSV appears within this many seconds (default 900)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Re-run all preset/group pairs even if a prior successful run exists",
    )
    parser.add_argument(
        "--enable-replan",
        action="store_true",
        help="Pass --enable_replan to gm_state_machine_agent (A and B for fair comparison)",
    )
    args = parser.parse_args()

    if not args.model_dir.is_dir() and not args.dry_run:
        print(f"Model dir not found: {args.model_dir}", file=sys.stderr)
        return 1

    results = run_ab(
        args.presets,
        max_steps=args.max_steps,
        model_dir=args.model_dir,
        log_dir=args.log_dir,
        dry_run=args.dry_run,
        watchdog_sec=args.watchdog_sec,
        resume=not args.no_resume,
        enable_replan=args.enable_replan,
    )
    if not args.dry_run:
        write_report(results, model_dir=args.model_dir, report_path=args.report)

    failed = [r for r in results if r.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
