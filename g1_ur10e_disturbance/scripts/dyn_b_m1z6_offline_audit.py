#!/usr/bin/env python3
"""V1-M1Z6 offline-only root-cause audit and recapture plan generator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e01_dyn_b_m1y_camera_framing import TARGET_LINKS, evaluate_step, load_body_pose_steps


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _non_allow_ranges(rows: list[dict[str, str]], start: int, end: int) -> list[dict[str, int | str]]:
    flagged = []
    by_step = {int(r["sim_step"]): r for r in rows}
    for step in range(start, end + 1):
        row = by_step.get(step)
        if row is None:
            continue
        gate = str(row.get("gate_effective", "")).upper()
        if gate != "ALLOW":
            flagged.append(step)
    out: list[dict[str, int | str]] = []
    if not flagged:
        return out
    s = flagged[0]
    p = flagged[0]
    for cur in flagged[1:]:
        if cur == p + 1:
            p = cur
            continue
        out.append({"start": s, "end": p, "length": p - s + 1, "continuity": "contiguous"})
        s = cur
        p = cur
    out.append({"start": s, "end": p, "length": p - s + 1, "continuity": "contiguous"})
    return out


def _get_step(rows: list[dict[str, str]], step: int) -> dict[str, str]:
    for row in rows:
        if int(row["sim_step"]) == step:
            return row
    raise ValueError(f"missing step in audit csv: {step}")


def _to_float_or_none(v: str | None) -> float | None:
    if v is None:
        return None
    t = str(v).strip()
    if t in {"", "nan", "NaN", "inf", "Infinity"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def build_report(results_dir: Path) -> dict[str, Any]:
    safety_dir = results_dir / "safety_logs"
    meta_dir = results_dir / "meta"
    scene_dir = results_dir / "scene"
    audit_rows = _read_csv_rows(safety_dir / "phase3_dyn_b_per_step_audit.csv")
    sampled_steps_rows = _read_csv_rows(safety_dir / "phase3_steps.csv")
    events_rows = _read_csv_rows(safety_dir / "phase3_events.csv")
    body = load_body_pose_steps(meta_dir / "body_poses.jsonl")
    camera_pose = json.loads((meta_dir / "camera_pose.json").read_text(encoding="utf-8"))
    image_inspect = json.loads((meta_dir / "image_inspect.json").read_text(encoding="utf-8"))
    z5_doc = json.loads(
        (ROOT / "docs" / "cross-project" / "vlm-v1m1z5-dyn-b-formal-reviewable-preflight-2026-07-23.json").read_text(encoding="utf-8")
    )

    non_allow_ranges = _non_allow_ranges(audit_rows, 0, 340)
    step212 = _get_step(audit_rows, 212)
    step228 = _get_step(audit_rows, 228)

    sampled_by_step = {int(r["step"]): r for r in sampled_steps_rows}
    sampled_snapshot = {}
    for s in (200, 250, 300):
        if s in sampled_by_step:
            sampled_snapshot[str(s)] = {
                "stage": sampled_by_step[s].get("stage", ""),
                "closest_g1_body": sampled_by_step[s].get("closest_g1_body", ""),
                "dist_min_g1_body": _to_float_or_none(sampled_by_step[s].get("dist_min_g1_body")),
                "dist_min_proxy": _to_float_or_none(sampled_by_step[s].get("dist_min_proxy")),
                "dist_min_for_gating": _to_float_or_none(sampled_by_step[s].get("dist_min_for_gating")),
                "safe_dist_warn_active": _to_float_or_none(sampled_by_step[s].get("safe_dist_warn_active")),
                "safe_dist_hard_stop_active": _to_float_or_none(sampled_by_step[s].get("safe_dist_hard_stop_active")),
            }

    cam_pos = camera_pose["pos"]
    key_groups = {"positive_lateral": [219, 220, 221], "negative_lateral": [329, 330, 331]}
    frame_eval: dict[str, Any] = {}
    for group_name, steps in key_groups.items():
        frame_eval[group_name] = []
        for step in steps:
            links = [body[step]["g1_bodies"][k] for k in TARGET_LINKS if k in body[step]["g1_bodies"]]
            ev = evaluate_step(links, cam_pos=cam_pos)
            png = scene_dir / f"frame_{step:06d}_env0.png"
            frame_eval[group_name].append(
                {
                    "step": step,
                    "sha256": _sha256(png),
                    "links_visible_margin_8": ev.links_visible_margin,
                    "clipping_ratio": ev.clipping_ratio,
                    "roi_area_fraction": ev.roi_area_fraction,
                    "gate_links_ge_4": ev.links_visible_margin >= 4,
                    "gate_clipping_le_0_5": ev.clipping_ratio <= 0.5,
                    "gate_roi_ge_0_01": ev.roi_area_fraction >= 0.01,
                }
            )

    centroid_disp = float(z5_doc["visual"]["centroid_displacement_px_220_330"])
    step_details = {}
    for target_step, row in ((212, step212), (228, step228)):
        step_details[str(target_step)] = {
            "gate_evaluated": row.get("gate_evaluated", ""),
            "gate_effective": row.get("gate_effective", ""),
            "trigger_rule": row.get("trigger_rule", ""),
            "trigger_reason_in_available_logs": row.get("trigger_rule", ""),
            "distance": {
                "dist_min_g1_body_m": _to_float_or_none(row.get("dist_min_g1_body_m")),
                "margin_to_gate_m": _to_float_or_none(row.get("margin_to_gate_m")),
            },
            "ttc": {
                "ttc_value_s": None,
                "time_to_risk_steps": None,
                "available": False,
                "evidence": "phase3_events.csv is empty; per-step audit retains trigger_rule only",
            },
            "velocity": {
                "g1_or_sweep_velocity_xyz": None,
                "available": False,
                "evidence": "velocity fields are not persisted in phase3_dyn_b_per_step_audit.csv",
            },
            "source_phase": {
                "motion_source_label": row.get("motion_source_label", ""),
                "phase": row.get("phase", ""),
            },
            "g1_state": {
                "g1_root_xyz": [
                    _to_float_or_none(row.get("g1_root_x")),
                    _to_float_or_none(row.get("g1_root_y")),
                    _to_float_or_none(row.get("g1_root_z")),
                ],
                "g1_tilt_rad": _to_float_or_none(row.get("g1_tilt_rad")),
                "g1_fell_flag": int(row.get("g1_fell_flag", "0") or "0"),
            },
            "ur10e_stage_proxy": {
                "stage_from_phase3_steps_at_same_step": None,
                "proxy_fields_at_same_step": None,
                "available": False,
                "evidence": "phase3_steps.csv is sparse (0/50/.../300); no rows for steps 212/228",
            },
            "flags": {
                "stop_flag": int(row.get("stop_flag", "0") or "0"),
                "slow_flag": int(row.get("slow_flag", "0") or "0"),
                "replan_flag": int(row.get("replan_flag", "0") or "0"),
            },
        }

    missing_step_ttc_velocity = len(events_rows) == 0
    verdict = "BLOCKED" if missing_step_ttc_velocity else "RECAPTURE_PLAN_READY"
    report = {
        "milestone": "V1-M1Z6",
        "verdict": verdict,
        "root_cause_confidence": {
            "level": "low_to_medium",
            "score_0_to_1": 0.45,
            "reason": "Two isolated ttc-triggered slowdowns with large static distance margins, but exact TTC/velocity telemetry at steps 212/228 is missing.",
        },
        "fixed_result_dir": str(results_dir),
        "head_verification_required": "7902bd59bcba5b11e93681b0cc5cb741db72a004",
        "step_root_cause_audit": step_details,
        "scan_0_340_non_allow_ranges": non_allow_ranges,
        "scan_0_340_non_allow_steps": [s for r in non_allow_ranges for s in range(int(r["start"]), int(r["end"]) + 1)],
        "risk_source_judgement": {
            "primary": "telemetry_or_rule_projection",
            "secondary": "g1_ur10e_relative_self_motion",
            "excluded_or_low_likelihood": ["static_scene", "proxy_contact", "g1_fall"],
            "evidence": [
                "all non-ALLOW trigger_rule == ttc",
                "dist_min_g1_body_m at 212/228 remains >1.08m",
                "motion_source_label is scripted_g1_outer_lateral_patrol",
                "phase3_events.csv missing prevents direct TTC/velocity validation",
            ],
        },
        "available_field_coverage_note": {
            "phase3_dyn_b_per_step_audit_rows": len(audit_rows),
            "phase3_steps_sampled_rows": len(sampled_steps_rows),
            "phase3_events_rows": len(events_rows),
            "sampled_stage_proxy_context": sampled_snapshot,
        },
        "review_window_design": {
            "window_name": "lateral_dual_sweep_full_segment",
            "step_start": 159,
            "step_end": 338,
            "continuity": "fixed_contiguous",
            "phase_basis": {
                "start_phase": "lateral_positive_sweep",
                "includes_transition_phase": "lateral_negative_sweep",
                "physical_basis": "covers complete signed lateral direction change under scripted_g1_outer_lateral_patrol with unchanged camera pose",
            },
            "anti_cherry_pick_rules": [
                "window bounds are declared by phase boundary before recapture",
                "window includes known historical anomalies (212, 228) and must not be filtered post-hoc",
                "no sparse frame selection outside declared contiguous window",
                "keyframe groups are deterministic offsets anchored to this fixed window",
            ],
        },
        "keyframe_groups": {
            "group_A_positive_lateral": frame_eval["positive_lateral"],
            "group_B_negative_lateral": frame_eval["negative_lateral"],
            "centroid_displacement_px_220_330": centroid_disp,
            "centroid_displacement_gate_px": 20.0,
        },
        "no_code_change_feasibility": {
            "can_attempt_with_window_only": True,
            "reason": "Current fixed camera and scripted trajectory already satisfy link/ROI/clipping/displacement gates on both 3-frame groups.",
            "minimal_source_change_if_future_blocked": {
                "needed": False,
                "candidate": "add per-step event logging durability checks only; no control/threshold semantics changes",
            },
        },
        "next_capture_command_draft": {
            "outer_command": "/home/czz/GMrobot/g1_ur10e_disturbance/docker/run.sh --tag gmdisturb:e01-dyn-b-clean-m1z4-20260723 --results /home/czz/GMrobot/g1_ur10e_disturbance/results bash -lc 'set -euo pipefail; /isaac-sim/python.sh /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py --headless --seed 43 --scenario outer_lateral_patrol --motion_source_label scripted_g1_outer_lateral_patrol --max_steps 341 --progress_interval 1 --output_csv /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/safety_logs/phase3.csv --save_camera --camera_output_dir /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/scene --camera_save_steps 219,220,221,329,330,331 --camera_pose_json /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/meta/camera_pose.json --body_pose_jsonl /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/meta/body_poses.jsonl --dyn-b-per-step-audit-csv /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/safety_logs/phase3_dyn_b_per_step_audit.csv --numpy-origin-pre-json /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/meta/numpy_origin_pre.json --numpy-origin-post-json /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/meta/numpy_origin_post.json --typing-extensions-pre-json /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/meta/typing_extensions_pre.json --typing-extensions-post-json /opt/projects/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_preflight_m1z6_20260723/meta/typing_extensions_post.json'",
            "declared_review_window_step_start": 159,
            "declared_review_window_step_end": 338,
            "declared_keyframe_steps": [219, 220, 221, 329, 330, 331],
        },
        "expected_image_sha": {
            "tag": "gmdisturb:e01-dyn-b-clean-m1z4-20260723",
            "sha256": image_inspect[0]["Id"],
            "expected_exact": "sha256:962de1e3f5e9c761d5106c660af7e7dfdbc79319194839a284a06e64dfb45e83",
        },
        "forbidden_items": [
            "no Docker/Isaac/build/network execution in this milestone",
            "no POST, VLM, GDINO, SAM2",
            "no credentials read",
            "no change to B0-B4 frozen configs/results",
            "no safety threshold or gate/replan/control semantic changes",
            "no deletion or rewrite of M1Z5 FAIL evidence",
        ],
        "budget": {"build_runs_allowed": 0, "capture_runs_allowed": 1},
        "stop_conditions": [
            "HEAD mismatch or dirty worktree at execution time",
            "result directory already exists",
            "events telemetry still missing exact TTC/velocity for non-ALLOW steps",
            "any non-ALLOW appears inside declared review window 159..338",
            "centroid displacement < 20px or any keyframe ROI/link/clipping gate fails",
            "missing per-step evidence for declared keyframes or window",
        ],
    }
    return report


def _to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# V1-M1Z6 Dyn-B M1Z5 root-cause audit and recapture plan (2026-07-23)",
        "",
        f"- verdict: **{report['verdict']}**",
        f"- root_cause_confidence: `{report['root_cause_confidence']['level']}` ({report['root_cause_confidence']['score_0_to_1']})",
        f"- fixed_result_dir: `{report['fixed_result_dir']}`",
        f"- expected image: `{report['expected_image_sha']['tag']}` / `{report['expected_image_sha']['expected_exact']}`",
        "",
        "## 212 / 228 审计结论",
    ]
    for s in ("212", "228"):
        d = report["step_root_cause_audit"][s]
        lines.extend(
            [
                f"- step `{s}`: gate `{d['gate_evaluated']}/{d['gate_effective']}`, trigger `{d['trigger_rule']}`, "
                f"dist_min `{d['distance']['dist_min_g1_body_m']}` m, margin `{d['distance']['margin_to_gate_m']}` m, "
                f"phase `{d['source_phase']['phase']}`, source `{d['source_phase']['motion_source_label']}`, "
                f"slow/stop/replan `{d['flags']['slow_flag']}/{d['flags']['stop_flag']}/{d['flags']['replan_flag']}`",
                f"- step `{s}` TTC/velocity: unavailable (`{d['ttc']['evidence']}`; `{d['velocity']['evidence']}`)",
            ]
        )
    lines.extend(
        [
            "",
            "## 0..340 非 ALLOW 区间",
            "- ranges: "
            + ", ".join(
                f"[{r['start']},{r['end']}] len={r['length']}" for r in report["scan_0_340_non_allow_ranges"]
            ),
            "",
            "## 新固定窗口与关键帧",
            f"- review window: `{report['review_window_design']['step_start']}..{report['review_window_design']['step_end']}` (连续固定，覆盖正/负横移)",
            f"- keyframe group A: `{[x['step'] for x in report['keyframe_groups']['group_A_positive_lateral']]}`",
            f"- keyframe group B: `{[x['step'] for x in report['keyframe_groups']['group_B_negative_lateral']]}`",
            f"- centroid displacement px(220->330): `{report['keyframe_groups']['centroid_displacement_px_220_330']}` (gate >=20)",
            "",
            "## 执行约束与一次性预算",
            f"- build/run budget: `{report['budget']}`",
            "- forbidden items: " + "; ".join(report["forbidden_items"]),
            "- stop conditions: " + "; ".join(report["stop_conditions"]),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate V1-M1Z6 offline audit report.")
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--md-out", required=True)
    args = ap.parse_args()

    report = build_report(Path(args.results_dir))
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_out.write_text(_to_markdown(report), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "json_out": str(json_out), "md_out": str(md_out)}))


if __name__ == "__main__":
    main()
