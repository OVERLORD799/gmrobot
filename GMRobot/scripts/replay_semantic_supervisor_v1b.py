#!/usr/bin/env python3
"""Offline V1-B semantic supervisor replay over V0-C3 negative shadow JSONL.

Read-only. No POST / Isaac / Docker / live control.
Synthetic markers must not enter paper result trees.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import types

ROOT = Path(__file__).resolve().parents[1]
_SAFETY = ROOT / "source" / "GMRobot" / "GMRobot" / "safety"
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))
_pkg = types.ModuleType("safety")
_pkg.__path__ = [str(_SAFETY)]
sys.modules["safety"] = _pkg

from safety.semantic_supervisor import (  # noqa: E402
    SemanticSafetySupervisor,
    SemanticSupervisorConfig,
    advisory_input_from_shadow_row,
    load_semantic_supervisor_config,
)


def resolve_v0c3_jsonl(repo_root: Path) -> Path:
    base = repo_root / "g1_ur10e_disturbance" / "results" / "paper_demo" / "v0c3_isaac_shadow_20260721"
    top = base / "five_stage_shadow_requests.jsonl"
    if top.is_file():
        return top
    matches = sorted(base.glob("five_stage_shadow_*/five_stage_shadow_requests.jsonl"))
    if not matches:
        raise FileNotFoundError(f"V0-C3 jsonl not found under {base}")
    return matches[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="V1-B semantic supervisor offline replay")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("/home/czz/GMrobot"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="semantic_safety_supervisor.yaml (default: package config with enabled forced true)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    jsonl_path = resolve_v0c3_jsonl(repo)
    out_dir = args.out_dir or (
        repo / "g1_ur10e_disturbance" / "results" / "paper_demo" / "v1b_semantic_supervisor_replay_20260721"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.config is not None:
        cfg = load_semantic_supervisor_config(args.config)
    else:
        cfg = load_semantic_supervisor_config(
            ROOT / "configs" / "semantic_safety_supervisor.yaml"
        )
    # Replay must evaluate rules; keep shadow + defaults, only flip enabled.
    cfg = SemanticSupervisorConfig.from_dict(
        {
            **cfg.__dict__,
            "enabled": True,
            "enforcement_mode": "shadow",
            "allowed_actions": list(cfg.allowed_actions),
            "allowed_risk_types": list(cfg.allowed_risk_types),
        }
    )

    supervisor = SemanticSafetySupervisor(cfg)
    rows_out = []
    reasons: dict[str, int] = {}
    accepted = 0
    intentional = 0

    raw_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    for line in raw_lines:
        if not line.strip():
            continue
        row = json.loads(line)
        # Do not mutate original file; work on in-memory copy only.
        inp = advisory_input_from_shadow_row(
            row,
            current_geometry_gate="ALLOW",
            result_age_s=0.1,
            synthetic=False,
        )
        decision = supervisor.evaluate(inp)
        rec = decision.to_log_dict()
        rec["source_jsonl"] = str(jsonl_path.relative_to(repo)) if jsonl_path.is_relative_to(repo) else str(jsonl_path)
        rec["offline_replay"] = True
        rec["paper_result"] = False
        rows_out.append(rec)
        if decision.accepted:
            accepted += 1
        if decision.intentional_control_effect:
            intentional += 1
        r = decision.rejection_reason or ("accepted" if decision.accepted else "")
        if r:
            reasons[r] = reasons.get(r, 0) + 1

    summary = {
        "phase": "V1-B",
        "offline_replay": True,
        "source_jsonl": str(jsonl_path),
        "rows": len(rows_out),
        "accepted_count": accepted,
        "intentional_control_effect_count": intentional,
        "rejection_reasons": reasons,
        "contains_risk_type_not_allowed": "risk_type_not_allowed" in reasons,
        "would_stop_any": any(r.get("would_stop") for r in rows_out),
        "would_replan_any": any(r.get("would_replan") for r in rows_out),
        "note": "V0-C3 negative replay; not a new model experiment; not paper stats",
        "real_post_count": 0,
        "isaac_run": False,
    }

    out_jsonl = out_dir / "replay_rows.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for rec in rows_out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (out_dir / "replay_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    if accepted != 0:
        print("FAIL: accepted_count must be 0 for V0-C3 negative replay", file=sys.stderr)
        return 1
    if intentional != 0:
        print("FAIL: intentional_control_effect must be 0", file=sys.stderr)
        return 1
    if "risk_type_not_allowed" not in reasons:
        print("FAIL: expected risk_type_not_allowed in rejection reasons", file=sys.stderr)
        return 1
    print("V1B_NEGATIVE_REPLAY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
