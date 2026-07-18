#!/usr/bin/env python3
"""Report shadow Layer 2 metrics (g_rule vs g_ml / tier fusion vs OR vs GT)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

from _layer2_import import load_layer2_module
from _safety_import import bootstrap_safety, load_safety_module

bootstrap_safety()
_config = load_safety_module("config")
_gt = load_safety_module("gt_branches")
_types = load_safety_module("types")
_fusion = load_safety_module("fusion")

load_safety_config = _config.load_safety_config
recompute_gt_from_row = _gt.recompute_gt_from_row
GateDecision = _types.GateDecision
compute_fusion = _fusion.compute_fusion
load_fusion_config = _fusion.load_fusion_config
row_for_predictor = _fusion.row_for_predictor

_predictor = load_layer2_module("predictor")
SafetyPredictor = _predictor.SafetyPredictor


def _gt_label(row: dict, config) -> int:
    for col in ("g_ground_truth", "gt_collision"):
        val = row.get(col, "")
        if val not in (None, ""):
            return int(val)
    g_gt, _ = recompute_gt_from_row(row, config)
    return g_gt


def _gate_metrics(rows: list[dict], gate_col: str, config) -> dict:
    n = len(rows)
    if n == 0:
        return {}

    false_stops = 0
    misses = 0
    gt_stops = 0
    caught = 0
    stop_steps = 0

    for row in rows:
        g_gate = int(row.get(gate_col, 0))
        g_gt = _gt_label(row, config)

        if g_gate == int(GateDecision.STOP):
            stop_steps += 1
            if g_gt == int(GateDecision.ALLOW):
                false_stops += 1
        if g_gt == int(GateDecision.STOP):
            gt_stops += 1
            if g_gate == int(GateDecision.STOP):
                caught += 1
            elif g_gate == int(GateDecision.ALLOW):
                misses += 1

    return {
        "gate": gate_col,
        "steps": n,
        "stop_rate": stop_steps / n,
        "false_stop_rate": false_stops / n,
        "miss_rate": misses / n,
        "safety_recall": caught / gt_stops if gt_stops else None,
        "gt_stop_steps": gt_stops,
        "false_stops": false_stops,
        "misses": misses,
    }


def _optional_float(row: dict, col: str) -> float | None:
    val = row.get(col, "")
    if val in (None, ""):
        return None
    return float(val)


def enrich_rows_with_shadow(
    rows: list[dict],
    predictor: SafetyPredictor,
    config,
    fusion_config,
) -> list[dict]:
    envelope_gating = bool(getattr(getattr(config, "envelope", None), "gating_enabled", False))
    enriched = []
    for row in rows:
        out = dict(row)
        g_rule = int(row.get("g_rule", 0))
        g_ml = predictor.predict_row(row)
        g_ml_confidence = predictor.predict_proba_for_label(row, g_ml)
        fusion = compute_fusion(
            g_rule=g_rule,
            g_ml=g_ml,
            g_ml_confidence=g_ml_confidence,
            dist_ee_human=_optional_float(row, "dist_ee_human"),
            dist_min_envelope=_optional_float(row, "dist_min_envelope"),
            envelope_gating=envelope_gating,
            safe_dist_hard_stop=fusion_config.safe_dist_hard_stop,
            safe_dist_warn=fusion_config.safe_dist_warn,
            ml_override_theta=fusion_config.ml_override_theta,
            trigger_rule=str(row.get("trigger_rule", "")),
        )
        log = fusion.to_log_dict()
        out.update({k: str(v) if v != "" else "" for k, v in log.items()})
        enriched.append(out)
    return enriched


def collect_csv_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("episode_*.csv")))
        else:
            files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Shadow Layer 2 metrics vs GT")
    parser.add_argument("paths", nargs="+", type=Path, help="CSV files or log directories")
    parser.add_argument(
        "--config",
        type=Path,
        default=_REPO / "configs" / "safety_layer1.yaml",
        help="Safety config for GT recompute",
    )
    parser.add_argument(
        "--fusion-config",
        type=Path,
        default=_REPO / "configs" / "safety_fusion.yaml",
        help="Tier fusion config",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Layer 2 model dir; if set, compute g_ml/would_fuse when columns missing",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Write per-run metrics JSON",
    )
    args = parser.parse_args()

    config = load_safety_config(args.config)
    fusion_config = load_fusion_config(args.fusion_config)
    predictor = SafetyPredictor.from_artifacts(args.model_dir) if args.model_dir else None
    csv_files = collect_csv_files(args.paths)
    if not csv_files:
        print("No CSV files found.", file=sys.stderr)
        return 1

    all_reports = []
    print(f"Config: {args.config}")
    print(f"Fusion: {args.fusion_config} (theta={fusion_config.ml_override_theta})")
    print("=" * 72)
    for csv_path in csv_files:
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        has_shadow = "g_ml" in (rows[0].keys() if rows else [])
        if not has_shadow and predictor is not None:
            rows = enrich_rows_with_shadow(rows, predictor, config, fusion_config)

        report = {
            "csv": str(csv_path),
            "run_id": csv_path.parent.name,
            "g_rule": _gate_metrics(rows, "g_rule", config),
        }
        for col in ("would_fuse", "would_fuse_or", "g_ml"):
            if rows and col in rows[0]:
                report[col] = _gate_metrics(rows, col, config)

        all_reports.append(report)
        preset = (csv_path.parent / "preset.txt").read_text(encoding="utf-8").strip() if (
            csv_path.parent / "preset.txt"
        ).is_file() else csv_path.parent.name
        print(f"Run: {report['run_id']}  preset={preset}")
        print(f"  CSV: {csv_path}  steps={report['g_rule']['steps']}")
        for key in ("g_rule", "would_fuse", "would_fuse_or", "g_ml"):
            if key not in report:
                continue
            m = report[key]
            recall = m["safety_recall"]
            recall_s = f"{recall:.4f}" if recall is not None else "N/A"
            print(
                f"  [{key}] false_stop={m['false_stop_rate']:.4f} "
                f"miss={m['miss_rate']:.4f} recall={recall_s}"
            )
        print()

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(all_reports, f, indent=2)
        print(f"Wrote {args.output_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
