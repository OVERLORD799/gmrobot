#!/usr/bin/env python3
"""Unified IV-J offline Layer1 + Layer2 shadow summary."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

from report_safety_metrics import analyze_path, collect_csv_files  # noqa: E402
from report_shadow_metrics import main as shadow_main  # noqa: E402

_REGISTRY = _REPO / "configs" / "ivj" / "registry.yaml"
_LOG_DIR = _REPO / "output" / "safety_logs"
_MIN_RUN_ID = "20260617_141625"
_DEFAULT_MODEL = _REPO / "output" / "safety_models" / "20260617_211615"

# Phase-1 runs without preset.txt (documented in collect_ivj_logs.py)
_PHASE1_RUN_BY_PRESET = {
    "ivj_static_block_place": "20260617_192734",
    "ivj_static_far_observer": "20260617_193244",
}

# Best-effort TTC fast-sweep proxy (safety_layer1_ttc timing fingerprint, >= min_run_id)
_FAST_SWEEP_PROXY_RUN = "20260617_153911"


def load_scenarios(registry: Path) -> dict:
    with open(registry, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("scenarios", data)


def preset_from_run(run_dir: Path) -> str | None:
    pf = run_dir / "preset.txt"
    if pf.is_file():
        return pf.read_text(encoding="utf-8").strip()
    mf = run_dir / "run_manifest.json"
    if mf.is_file():
        try:
            meta = json.loads(mf.read_text(encoding="utf-8"))
            return meta.get("preset_id")
        except json.JSONDecodeError:
            return None
    return None


def best_run_for_preset(preset_id: str, log_dir: Path, min_run_id: str) -> str | None:
    best: str | None = None
    for d in sorted(log_dir.iterdir()):
        if not d.is_dir() or d.name < min_run_id:
            continue
        if not list(d.glob("episode_*.csv")):
            continue
        if preset_from_run(d) == preset_id:
            best = d.name
    if best:
        return best
    if preset_id in _PHASE1_RUN_BY_PRESET:
        rid = _PHASE1_RUN_BY_PRESET[preset_id]
        if (log_dir / rid).is_dir() and rid >= min_run_id:
            return rid
    if preset_id == "ivj_dynamic_fast_sweep":
        proxy = log_dir / _FAST_SWEEP_PROXY_RUN
        if proxy.is_dir() and list(proxy.glob("episode_*.csv")):
            return _FAST_SWEEP_PROXY_RUN
    return None


def fmt_rate(x) -> str:
    if x is None:
        return "N/A"
    return f"{100 * float(x):.1f}%"


def fmt_recall(x) -> str:
    if x is None:
        return "N/A"
    return f"{float(x):.4f}"


def _legacy_shadow_json(preset_id: str) -> Path | None:
    legacy = _REPO / "output" / f"ivj_shadow_{preset_id}.json"
    return legacy if legacy.is_file() else None


def run_shadow(
    run_dir: Path,
    config: Path,
    model_dir: Path,
    out_json: Path,
    preset_id: str,
) -> list[dict]:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    for candidate in (out_json, _legacy_shadow_json(preset_id)):
        if candidate and candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if data and data[0].get("run_id") == run_dir.name:
                return data
    argv = [
        sys.executable,
        str(_REPO / "scripts" / "report_shadow_metrics.py"),
        str(run_dir),
        "--config",
        str(config),
        "--model-dir",
        str(model_dir),
        "--output-json",
        str(out_json),
    ]
    subprocess.run(argv, check=True, cwd=_REPO)
    return json.loads(out_json.read_text(encoding="utf-8"))


def build_rows(
    scenarios: dict,
    *,
    log_dir: Path,
    min_run_id: str,
    model_dir: Path,
    shadow_dir: Path,
) -> list[dict]:
    rows: list[dict] = []
    for preset_id in scenarios:
        run_id = best_run_for_preset(preset_id, log_dir, min_run_id)
        config = _REPO / "configs" / "ivj" / scenarios[preset_id]["config"]
        row: dict = {"preset": preset_id, "run_id": run_id, "config": str(config)}
        if not run_id:
            row["status"] = "missing_run"
            rows.append(row)
            continue
        run_dir = log_dir / run_id
        csv_files = collect_csv_files([run_dir])
        if not csv_files:
            row["status"] = "missing_csv"
            rows.append(row)
            continue
        l1 = analyze_path(csv_files[0], config)
        shadow_json = shadow_dir / f"{preset_id}.json"
        shadow = run_shadow(run_dir, config, model_dir, shadow_json, preset_id)[0]
        gr = shadow["g_rule"]
        gml = shadow.get("g_ml", {})
        wf = shadow.get("would_fuse", {})
        row.update(
            {
                "status": "ok",
                "steps": l1.get("steps"),
                "intervention_rate": l1.get("intervention_rate"),
                "false_stop_rate": l1.get("false_stop_rate"),
                "miss_rate": l1.get("miss_rate"),
                "safety_recall": gr.get("safety_recall"),
                "g_ml_false_stop_rate": gml.get("false_stop_rate"),
                "would_fuse_false_stop_rate": wf.get("false_stop_rate"),
                "outcome": l1.get("outcome", ""),
                "shadow_json": str(shadow_json),
            }
        )
        rows.append(row)
    return rows


def to_markdown(rows: list[dict], *, model_dir: Path, min_run_id: str) -> str:
    lines = [
        "# IV-J offline shadow report",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Model: `{model_dir}`",
        f"Min run id: `{min_run_id}`",
        "",
        "| preset | run_id | intervention | false_stop | miss | recall | g_ml false_stop | would_fuse false_stop | outcome |",
        "|:-------|:-------|-------------:|-----------:|-----:|-------:|----------------:|----------------------:|:--------|",
    ]
    for r in rows:
        if r.get("status") != "ok":
            lines.append(
                f"| {r['preset']} | — | — | — | — | — | — | — | **{r.get('status')}** |"
            )
            continue
        lines.append(
            "| {preset} | `{run_id}` | {intervention} | {false_stop} | {miss} | {recall} | {gml} | {wf} | {outcome} |".format(
                preset=r["preset"],
                run_id=r["run_id"],
                intervention=fmt_rate(r["intervention_rate"]),
                false_stop=fmt_rate(r["false_stop_rate"]),
                miss=fmt_rate(r["miss_rate"]),
                recall=fmt_recall(r["safety_recall"]),
                gml=fmt_rate(r["g_ml_false_stop_rate"]),
                wf=fmt_rate(r["would_fuse_false_stop_rate"]),
                outcome=r.get("outcome", "") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="IV-J offline summary (Layer1 + shadow)")
    parser.add_argument("--registry", type=Path, default=_REGISTRY)
    parser.add_argument("--log-dir", type=Path, default=_LOG_DIR)
    parser.add_argument("--min-run-id", default=_MIN_RUN_ID)
    parser.add_argument("--model-dir", type=Path, default=_DEFAULT_MODEL)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=_REPO / "output" / "ivj_offline_shadow_report.md",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=_REPO / "output" / "ivj_offline_shadow_summary.json",
    )
    parser.add_argument(
        "--shadow-dir",
        type=Path,
        default=_REPO / "output" / "ivj_shadow",
    )
    parser.add_argument(
        "--presets",
        nargs="*",
        default=None,
        help="Subset of preset ids (default: all in registry)",
    )
    args = parser.parse_args()

    scenarios = load_scenarios(args.registry)
    if args.presets:
        scenarios = {k: scenarios[k] for k in args.presets if k in scenarios}

    if not args.model_dir.is_dir():
        candidates = sorted((_REPO / "output" / "safety_models").iterdir())
        if candidates:
            args.model_dir = candidates[-1]

    rows = build_rows(
        scenarios,
        log_dir=args.log_dir,
        min_run_id=args.min_run_id,
        model_dir=args.model_dir,
        shadow_dir=args.shadow_dir,
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model_dir": str(args.model_dir),
        "min_run_id": args.min_run_id,
        "rows": rows,
    }
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    md = to_markdown(rows, model_dir=args.model_dir, min_run_id=args.min_run_id)
    args.output_md.write_text(md, encoding="utf-8")
    print(md)
    print(f"Wrote {args.output_md}")
    print(f"Wrote {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
