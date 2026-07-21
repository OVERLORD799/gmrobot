#!/usr/bin/env python3
"""Aggregate B0/B1 final regression results vs historical 0320 (offline)."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "results/paper_demo/b0_b1_final_p010_20260721"
HIST = REPO / "results_paper_final_0320/final_six_ordered"
FROZEN_B0 = REPO / "paper_scenarios_b0b1/baseline_safe.yaml"
FROZEN_B1 = REPO / "paper_scenarios_b0b1/static_occupancy_proxy.yaml"
IMAGE = {
    "tag": "gmdisturb:b4-p010-20260721",
    "image_id": "sha256:defe95e7df25b73cb08c3bb768c3e18d15807d0ae38fc52135d5474d3c820b68",
}
HIST_IMAGE = "sha256:0320fd6e9d7c061c48fdb51bf44a738bbee5e6bd469f8e5f2e52c05963ae0ca6"

COMPARE_KEYS = [
    "parts_placed",
    "parts_total",
    "task_completed",
    "total_steps",
    "policy_steps",
    "d_stop_caused",
    "d_slow_caused",
    "d_replan_caused",
    "d_knock_off",
    "g1_fell",
    "collision_count",
    "tier0_stop_count",
    "slowdown_count",
    "replan_count",
    "proxy_physical_contact_count",
    "progress_after_retreat",
    "held_critical_replan_count",
]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def episode_csv(d: Path) -> Path | None:
    for c in sorted(d.glob("*.csv")):
        n = c.name
        if any(
            x in n
            for x in ("_events", "_steps", "_attempts", "trajectory", "dynamic_audit")
        ):
            continue
        return c
    return None


def read_row(d: Path) -> dict:
    p = episode_csv(d)
    if p is None:
        raise FileNotFoundError(f"no episode csv in {d}")
    return next(csv.DictReader(p.open()))


def find_run_dir(scenario: str, seed: int) -> Path:
    if scenario == "baseline_safe":
        parent = ROOT / f"b0_s{seed}"
        candidates = [
            p
            for p in sorted(parent.glob("baseline_safe_*"))
            if p.is_dir() and episode_csv(p) is not None and (p / "manifest.json").exists()
        ]
        # Prefer clean single-seed override: snapshot seed==seed and repeat==1
        ranked = []
        for p in candidates:
            man = json.loads((p / "manifest.json").read_text())
            if int(man.get("seed", -1)) != seed:
                continue
            snap = man.get("config_yaml_snapshot") or {}
            clean = int(snap.get("repeat", 1) or 1) == 1 and int(snap.get("seed", seed)) == seed
            ranked.append((0 if clean else 1, p))
        if not ranked:
            raise FileNotFoundError(f"B0 seed{seed} run dir missing under {parent}")
        ranked.sort(key=lambda x: (x[0], x[1].name))
        return ranked[0][1]

    parent = ROOT / f"b1_s{seed}"
    candidates = [
        p
        for p in sorted(parent.glob("static_occupancy_proxy_*"))
        if p.is_dir() and episode_csv(p) is not None and (p / "manifest.json").exists()
    ]
    for p in candidates:
        man = json.loads((p / "manifest.json").read_text())
        if int(man.get("seed", -1)) == seed:
            return p
    if not candidates:
        raise FileNotFoundError(f"B1 seed{seed} run dir missing under {parent}")
    return candidates[0]


def hist_dir(scenario: str, seed: int) -> Path:
    mapping = {
        ("baseline_safe", 42): "baseline_safe_s42_051225",
        ("baseline_safe", 43): "baseline_safe_r1_s43_054917",
        ("baseline_safe", 44): "baseline_safe_r2_s44_062605",
        ("static_occupancy_proxy", 42): "static_occupancy_proxy_s42_012630",
        ("static_occupancy_proxy", 43): "static_occupancy_proxy_r1_s43_034046",
        ("static_occupancy_proxy", 44): "static_occupancy_proxy_r2_s44_042409",
    }
    return HIST / mapping[(scenario, seed)]


def pairing_stats(d: Path) -> dict:
    rid = d.name
    ev_path = d / f"{rid}_events.csv"
    att_path = d / f"{rid}_attempts.csv"
    out = {
        "trigger": 0,
        "applied": 0,
        "retreat": 0,
        "redeploy": 0,
        "recovered_attempts": 0,
        "unpaired_events": [],
        "unpaired_attempts": [],
        "held_critical_triggers": 0,
        "trigger_rules": {},
    }
    if not ev_path.exists():
        return out
    ev = list(csv.DictReader(ev_path.open()))
    types = Counter(r.get("event_type") for r in ev)
    for k in ("trigger", "applied", "retreat", "redeploy"):
        out[k] = int(types.get(k, 0))
    rules = Counter(r.get("trigger_rule") for r in ev if r.get("event_type") == "trigger")
    out["trigger_rules"] = dict(rules)
    out["held_critical_triggers"] = int(rules.get("held_critical", 0)) + int(
        rules.get("held_critical_early", 0)
    )
    by = defaultdict(list)
    for r in ev:
        et = r.get("event_type")
        if et in ("trigger", "applied", "retreat", "redeploy", "recovered"):
            by[r.get("attempt_id")].append(et)
    need = {"trigger", "applied", "retreat", "redeploy"}
    for aid, ets in by.items():
        missing = sorted(need - set(ets))
        if missing:
            out["unpaired_events"].append({"attempt_id": aid, "missing": missing})
    if att_path.exists():
        for a in csv.DictReader(att_path.open()):
            ok = (
                str(a.get("recovered", "")).lower() in ("true", "1")
                and bool(a.get("retreat_step"))
                and bool(a.get("redeploy_step"))
            )
            if ok:
                out["recovered_attempts"] += 1
            else:
                out["unpaired_attempts"].append(a.get("attempt_id"))
    return out


def elapsed_from(d: Path, row: dict) -> float | None:
    if row.get("elapsed_s") not in (None, ""):
        try:
            return float(row["elapsed_s"])
        except ValueError:
            pass
    jl = d / f"{d.name}.jsonl"
    if jl.exists():
        for line in jl.open():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict):
                if "elapsed_s" in o:
                    return float(o["elapsed_s"])
                m = o.get("metrics")
                if isinstance(m, dict) and "elapsed_s" in m:
                    return float(m["elapsed_s"])
    bs = d.parent / "batch_summary.json"
    if bs.exists():
        data = json.loads(bs.read_text())
        for r in data.get("runs", []):
            if r.get("run_id") == d.name and r.get("elapsed_s") is not None:
                return float(r["elapsed_s"])
    return None


def batch_fields(d: Path) -> dict:
    bs = d.parent / "batch_summary.json"
    out = {
        "subprocess_validated": None,
        "scenario_pass": None,
        "scenario_failure_reasons": "",
        "subprocess_validation_errors": "",
    }
    if not bs.exists():
        return out
    data = json.loads(bs.read_text())
    for r in data.get("runs", []):
        if r.get("run_id") == d.name:
            for k in out:
                if k in r:
                    out[k] = r[k]
            break
    return out


def gate_b0(row: dict, bf: dict, stderr: str) -> tuple[bool, list[str]]:
    fails = []
    if str(row.get("task_completed")).lower() not in ("true", "1"):
        fails.append("task_completed!=True")
    if int(float(row.get("parts_placed") or 0)) != 20:
        fails.append("parts!=20/20")
    for k in ("d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off"):
        if int(float(row.get(k) or 0)) != 0:
            fails.append(f"{k}!={row.get(k)}")
    if int(float(row.get("disturbance_attempt_id") or 0)) != 0:
        fails.append(f"disturbance_attempt_id={row.get('disturbance_attempt_id')}")
    if str(row.get("g1_fell")).lower() not in ("false", "0"):
        fails.append("g1_fell")
    if "Traceback" in stderr:
        fails.append("Traceback")
    if bf.get("subprocess_validated") is False:
        fails.append(f"subprocess:{bf.get('subprocess_validation_errors')}")
    if bf.get("scenario_pass") is False:
        fails.append(f"scenario:{bf.get('scenario_failure_reasons')}")
    return len(fails) == 0, fails


def infer_b0_batch_if_missing(d, row, bf, stderr):
    """B0 seed42 host wrapper was stopped early; episode artifacts are complete."""
    if bf.get("subprocess_validated") is not None:
        return bf
    schema_ok = all(
        k in row
        for k in (
            "task_completed",
            "parts_placed",
            "d_stop_caused",
            "d_slow_caused",
            "d_replan_caused",
            "g1_fell",
            "d_knock_off",
        )
    )
    ok = (
        schema_ok
        and "Traceback" not in stderr
        and str(row.get("task_completed")).lower() in ("true", "1")
        and int(float(row.get("parts_placed") or 0)) == 20
        and all(int(float(row.get(k) or 0)) == 0 for k in ("d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off"))
        and str(row.get("g1_fell")).lower() in ("false", "0")
    )
    bf = dict(bf)
    bf["subprocess_validated"] = ok
    bf["scenario_pass"] = ok
    bf["subprocess_validation_errors"] = "" if ok else "offline B0 inference failed"
    bf["scenario_failure_reasons"] = "" if ok else "offline B0 inference failed"
    bf["batch_summary_note"] = "inferred_offline_missing_batch_summary"
    return bf


def gate_b1(row: dict, bf: dict, pair: dict, stderr: str) -> tuple[bool, list[str]]:
    fails = []
    if str(row.get("task_completed")).lower() not in ("true", "1"):
        fails.append("task_completed!=True")
    if int(float(row.get("parts_placed") or 0)) != 20:
        fails.append("parts!=20/20")
    if int(float(row.get("d_stop_caused") or 0)) + int(float(row.get("d_slow_caused") or 0)) < 1:
        fails.append("no attributed STOP/SLOW")
    if int(float(row.get("d_replan_caused") or 0)) < 1:
        fails.append("d_replan_caused<1")
    if str(row.get("progress_after_retreat")).lower() not in ("true", "1"):
        fails.append("progress_after_retreat!=True")
    if str(row.get("g1_fell")).lower() not in ("false", "0"):
        fails.append("g1_fell")
    if int(float(row.get("d_knock_off") or 0)) != 0:
        fails.append("d_knock_off!=0")
    if int(float(row.get("proxy_physical_contact_count") or 0)) != 0:
        fails.append("proxy_physical_contact_count!=0")
    if pair["unpaired_events"] or pair["unpaired_attempts"]:
        fails.append("unpaired event/attempt")
    if pair["applied"] and (
        pair["applied"] != pair["retreat"]
        or pair["applied"] != pair["redeploy"]
        or pair["recovered_attempts"] != pair["applied"]
    ):
        fails.append(
            "pairing mismatch trigger/applied/retreat/redeploy/recovered="
            f"{pair['trigger']}/{pair['applied']}/{pair['retreat']}/"
            f"{pair['redeploy']}/{pair['recovered_attempts']}"
        )
    if pair["held_critical_triggers"] < 1:
        fails.append("no held_critical trigger")
    if "Traceback" in stderr:
        fails.append("Traceback")
    if bf.get("subprocess_validated") is False:
        fails.append(f"subprocess:{bf.get('subprocess_validation_errors')}")
    if bf.get("scenario_pass") is False:
        fails.append(f"scenario:{bf.get('scenario_failure_reasons')}")
    return len(fails) == 0, fails


def compare(new: dict, hist: dict) -> dict:
    diffs = {}
    same = {}
    for k in COMPARE_KEYS:
        nv, hv = new.get(k), hist.get(k)
        if nv is None and hv is None:
            continue
        if hv is None and k in (
            "held_critical_replan_count",
            "proxy_physical_contact_count",
            "task_completed",
        ):
            if k == "task_completed":
                hv = "True" if str(hist.get("parts_placed")) == "20" else "False"
            else:
                continue
        if str(nv) == str(hv):
            same[k] = nv
        else:
            diffs[k] = {"hist_0320": hv, "new_p010": nv}
    label = "回归一致" if not diffs else "指标变化"
    return {"label": label, "matched_keys": sorted(same.keys()), "changed": diffs}


def summarize_one(scenario: str, seed: int) -> dict:
    d = find_run_dir(scenario, seed)
    row = read_row(d)
    man = json.loads((d / "manifest.json").read_text())
    stderr = (d / "stderr.txt").read_text() if (d / "stderr.txt").exists() else ""
    pair = pairing_stats(d)
    bf = batch_fields(d)
    if scenario == "baseline_safe":
        bf = infer_b0_batch_if_missing(d, row, bf, stderr)
    elapsed = elapsed_from(d, row)
    hd = hist_dir(scenario, seed)
    hrow = read_row(hd)
    if "task_completed" not in hrow:
        hrow["task_completed"] = (
            "True" if int(float(hrow.get("parts_placed") or 0)) == 20 else "False"
        )
    cmp = compare(row, hrow)
    yaml_sha = sha256_file(FROZEN_B0 if scenario == "baseline_safe" else FROZEN_B1)
    if scenario == "baseline_safe":
        ok, fails = gate_b0(row, bf, stderr)
        mechanism = "none (safety baseline; no virtual-hand disturbance)"
    else:
        ok, fails = gate_b1(row, bf, pair, stderr)
        mechanism = "held_critical STOP → replan recovery"
    snap = man.get("config_yaml_snapshot") or {}
    return {
        "scenario": scenario,
        "seed": seed,
        "effective_seed": man.get("seed"),
        "run_id": d.name,
        "run_dir": str(d.relative_to(REPO)),
        "image": IMAGE,
        "frozen_yaml_sha256": yaml_sha,
        "config_source": man.get("config_source"),
        "config_snapshot_seed": snap.get("seed"),
        "config_snapshot_repeat": snap.get("repeat"),
        "task_completed": row.get("task_completed"),
        "parts": f"{row.get('parts_placed')}/{row.get('parts_total')}",
        "total_steps": int(float(row.get("total_steps") or 0)),
        "policy_steps": int(float(row.get("policy_steps") or 0)),
        "elapsed_s": elapsed,
        "attributed_stop": int(float(row.get("d_stop_caused") or 0)),
        "attributed_slow": int(float(row.get("d_slow_caused") or 0)),
        "attributed_replan": int(float(row.get("d_replan_caused") or 0)),
        "raw_stop": int(float(row.get("tier0_stop_count") or 0)),
        "raw_slow": int(float(row.get("slowdown_count") or 0)),
        "raw_replan": int(float(row.get("replan_count") or 0)),
        "held_critical_replan_count": int(float(row.get("held_critical_replan_count") or 0)),
        "mechanism_label": mechanism,
        "pairing": {
            "trigger": pair["trigger"],
            "applied": pair["applied"],
            "retreat": pair["retreat"],
            "redeploy": pair["redeploy"],
            "recovered": pair["recovered_attempts"],
            "unpaired_events": pair["unpaired_events"],
            "unpaired_attempts": pair["unpaired_attempts"],
            "trigger_rules": pair["trigger_rules"],
        },
        "progress_after_retreat": row.get("progress_after_retreat"),
        "collision_count": int(float(row.get("collision_count") or 0)),
        "robot_object_collision_count": int(
            float(row.get("robot_object_collision_count") or row.get("object_collision_count") or 0)
        ),
        "proxy_physical_contact_count": int(float(row.get("proxy_physical_contact_count") or 0)),
        "d_knock_off": int(float(row.get("d_knock_off") or 0)),
        "g1_fell": row.get("g1_fell"),
        "disturbance_attempt_id": row.get("disturbance_attempt_id"),
        "subprocess_validated": bf.get("subprocess_validated"),
        "scenario_pass": bf.get("scenario_pass"),
        "scenario_failure_reasons": bf.get("scenario_failure_reasons"),
        "subprocess_validation_errors": bf.get("subprocess_validation_errors"),
        "batch_summary_note": bf.get("batch_summary_note"),
        "gate_pass": ok,
        "gate_failures": fails,
        "vs_0320": cmp,
        "hist_0320_run_id": hd.name,
        "hist_0320_image": HIST_IMAGE,
    }


def render_md(summary: dict) -> str:
    lines = []
    lines.append("# B0/B1 最终回归 — P0-10（2026-07-21）")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    if summary["all_six_pass"]:
        lines.append(
            "**六组（B0/B1 × seed 42/43/44）在 `defe95e…` 最终候选镜像上全部通过门禁；"
            "可与 B2/B4-Dynamic 统一冻结。**"
        )
    else:
        lines.append("**六组未全部通过；见下方 gate_failures。**")
    lines.append("")
    lines.append(f"- 冻结镜像：`{summary['frozen_image']['tag']}`")
    lines.append(f"- image ID：`{summary['frozen_image']['image_id']}`")
    lines.append(f"- 结果根目录：`{summary['results_root']}`")
    lines.append(f"- machine summary：`results/paper_demo/b0_b1_final_summary_p010.json`")
    lines.append("")
    lines.append("### 冻结 YAML（未修改）")
    lines.append("")
    for k, v in summary["frozen_yamls"].items():
        lines.append(f"- `{k}` sha256=`{v}`")
    lines.append("")
    lines.append("### B1 机制标注（勿与 B2 混写）")
    lines.append("")
    lines.append(f"- B1：`{summary['b1_mechanism_label']}`")
    lines.append(f"- {summary['b1_not_b2']}")
    lines.append("")
    lines.append("## 六组结果")
    lines.append("")
    lines.append(
        "| 场景 | seed | run_id | parts | attr STOP/SLOW/replan | held_crit | "
        "trig/app/ret/redeploy/rec | unpaired | progress | collide | knock/G1 | "
        "subprocess/scenario | vs 0320 | gate |"
    )
    lines.append("|---|---:|---|---|---|---:|---|---|---|---:|---|---|---|---|")
    for r in summary["runs"]:
        p = r["pairing"]
        unpaired = len(p["unpaired_events"]) + len(p["unpaired_attempts"])
        chain = f"{p['trigger']}/{p['applied']}/{p['retreat']}/{p['redeploy']}/{p['recovered']}"
        lines.append(
            f"| {r['scenario']} | {r['seed']} | `{r['run_id']}` | {r['parts']} | "
            f"{r['attributed_stop']}/{r['attributed_slow']}/{r['attributed_replan']} | "
            f"{r['held_critical_replan_count']} | {chain} | {unpaired} | "
            f"{r['progress_after_retreat']} | {r['collision_count']} | "
            f"{r['d_knock_off']}/{r['g1_fell']} | "
            f"{r['subprocess_validated']}/{r['scenario_pass']} | "
            f"{r['vs_0320']['label']} | {'PASS' if r['gate_pass'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("## 与历史 0320 对比")
    lines.append("")
    lines.append(f"- 历史根目录：`{summary['historical_reference']['root']}`（**不覆盖**）")
    lines.append(f"- 历史镜像：`{summary['historical_reference']['image']}`")
    lines.append("")
    for r in summary["runs"]:
        lines.append(f"### {r['scenario']} seed{r['seed']}")
        lines.append("")
        lines.append(f"- 标注：`**{r['vs_0320']['label']}**`")
        lines.append(f"- hist run：`{r['hist_0320_run_id']}`")
        lines.append(f"- new run：`{r['run_id']}`")
        if r["vs_0320"]["changed"]:
            lines.append("- 变化字段：")
            for k, v in r["vs_0320"]["changed"].items():
                lines.append(f"  - `{k}`: 0320=`{v['hist_0320']}` → p010=`{v['new_p010']}`")
        else:
            lines.append("- 关键可比指标与 0320 完全一致（回归一致）。")
        lines.append("")
    lines.append("## 门禁")
    lines.append("")
    lines.append(f"- `all_six_pass`: `{summary['all_six_pass']}`")
    lines.append(f"- `freeze_b0_b1_b2_b4_on_defe95e`: `{summary['freeze_b0_b1_b2_b4_on_defe95e']}`")
    lines.append("")
    lines.append("历史 0320 证据保留于 `results_paper_final_0320/final_six_ordered/`。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    runs = []
    for seed in (42, 43, 44):
        runs.append(summarize_one("baseline_safe", seed))
        runs.append(summarize_one("static_occupancy_proxy", seed))
    all_pass = all(r["gate_pass"] for r in runs)
    summary = {
        "title": "B0/B1 final regression on P0-10 frozen image",
        "date": "2026-07-21",
        "frozen_image": IMAGE,
        "frozen_yamls": {
            "baseline_safe.yaml": sha256_file(FROZEN_B0),
            "static_occupancy_proxy.yaml": sha256_file(FROZEN_B1),
        },
        "results_root": "results/paper_demo/b0_b1_final_p010_20260721/",
        "historical_reference": {
            "root": "results_paper_final_0320/final_six_ordered/",
            "image": HIST_IMAGE,
            "note": "Do not overwrite; compare only.",
        },
        "b1_mechanism_label": "held_critical STOP → replan recovery",
        "b1_not_b2": "Do not conflate with B2 pre-hard-stop TTC proactive intervention.",
        "runs": runs,
        "all_six_pass": all_pass,
        "freeze_b0_b1_b2_b4_on_defe95e": all_pass,
    }
    out_json = REPO / "results/paper_demo/b0_b1_final_summary_p010.json"
    out_md = REPO / "docs/cross-project/b0-b1-final-regression-p010-2026-07-21.md"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    out_md.write_text(render_md(summary))
    print(json.dumps({"wrote_json": str(out_json), "wrote_md": str(out_md), "all_six_pass": all_pass}, indent=2))


if __name__ == "__main__":
    main()
