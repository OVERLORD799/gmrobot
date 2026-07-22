"""E01-Dyn-A offline capture helpers (no Isaac / no POST)."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from scene_camera_override import (
    DEFAULT_SCENE_CAMERA_POS,
    DEFAULT_SCENE_CAMERA_ROT,
    E01_DYN_A_CAPTURE_STEPS,
    E01_DYN_A_SCENE_CAMERA_POS,
    E01_DYN_A_SCENE_CAMERA_ROT,
    E01_DYN_A_SCENARIO,
    E01_DYN_A_SEED,
    MOTION_SOURCE_ARM_WAVE,
    arm_wave_phase_at_step,
    g1_roi_from_body_points,
    resolve_scene_camera_pose,
    scene_camera_override_enabled,
)

__all__ = [
    "E01_DYN_A_CAPTURE_STEPS",
    "E01_DYN_A_SCENARIO",
    "E01_DYN_A_SEED",
    "GEOMETRY_WINDOW",
    "MIN_G1_ROI_PX2",
    "MIN_CENTROID_DISPLACEMENT_PX",
    "MOTION_SOURCE_ARM_WAVE",
    "B0_B4_PAPER_SCENARIO_FILES",
    "sha256_file",
    "sha256_bytes",
    "validate_dyn_a_capture_flags",
    "audit_geometry_window",
    "audit_episode_gates",
    "build_frame_record",
    "build_capture_manifest",
    "assert_b0_b4_files_unchanged",
    "paper_scenario_sha_map",
]

GEOMETRY_WINDOW: tuple[int, int] = (210, 280)
MIN_G1_ROI_PX2: float = 400.0
MIN_CENTROID_DISPLACEMENT_PX: float = 40.0

B0_B4_PAPER_SCENARIO_FILES: tuple[str, ...] = (
    "paper_scenarios/baseline_safe.yaml",
    "paper_scenarios/static_occupancy_proxy.yaml",
    "paper_scenarios/static_occupancy_proxy_1part.yaml",
    "paper_scenarios/static_occupancy_proxy_8part.yaml",
    "paper_scenarios/static_occupancy_proxy_mini.yaml",
    "paper_scenarios/dynamic_lateral_sweep_proxy_1part.yaml",
    "paper_scenarios/dynamic_lateral_sweep_proxy_8part.yaml",
    "paper_scenarios/dynamic_lateral_sweep_proxy_shadow_mini.yaml",
)


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_dyn_a_capture_flags(
    *,
    scenario: str = E01_DYN_A_SCENARIO,
    seed: int = E01_DYN_A_SEED,
    motion_source: str = MOTION_SOURCE_ARM_WAVE,
    virtual_hand: bool = False,
    enable_vlm: bool = False,
    enable_perception: bool = False,
    enable_five_stage: bool = False,
    enable_replan: bool = False,
    post_count: int = 0,
    capture_steps: Sequence[int] = E01_DYN_A_CAPTURE_STEPS,
    camera_pos: Sequence[float] = E01_DYN_A_SCENE_CAMERA_POS,
    camera_rot: Sequence[float] = E01_DYN_A_SCENE_CAMERA_ROT,
) -> dict[str, Any]:
    reasons: list[str] = []
    if scenario != E01_DYN_A_SCENARIO:
        reasons.append(f"scenario={scenario!r}")
    if int(seed) != E01_DYN_A_SEED:
        reasons.append(f"seed={seed}")
    if motion_source != MOTION_SOURCE_ARM_WAVE:
        reasons.append(f"motion_source={motion_source!r}")
    if virtual_hand:
        reasons.append("virtual_hand_enabled")
    if enable_vlm or enable_perception or enable_five_stage:
        reasons.append("network_workers_enabled")
    if enable_replan:
        reasons.append("replan_enabled")
    if int(post_count) != 0:
        reasons.append(f"post_count={post_count}")
    if tuple(int(s) for s in capture_steps) != E01_DYN_A_CAPTURE_STEPS:
        reasons.append(f"capture_steps={list(capture_steps)}")
    if tuple(float(x) for x in camera_pos) != E01_DYN_A_SCENE_CAMERA_POS:
        reasons.append(f"camera_pos={list(camera_pos)}")
    if tuple(float(x) for x in camera_rot) != E01_DYN_A_SCENE_CAMERA_ROT:
        reasons.append(f"camera_rot={list(camera_rot)}")
    forbidden = (
        "G1关节挥手",
        "上肢控制策略",
        "全身控制策略",
        "PPO全身策略",
    )
    for tok in forbidden:
        if tok in motion_source:
            reasons.append(f"forbidden_motion_claim:{tok}")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "post_count_expected": 0,
        "clients_initialized_expected": False,
        "motion_source": MOTION_SOURCE_ARM_WAVE,
        "phases": {
            str(s): arm_wave_phase_at_step(s) for s in E01_DYN_A_CAPTURE_STEPS
        },
    }


def _read_steps_csv(path: Path | str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def audit_geometry_window(
    steps_csv: Path | str,
    *,
    window: tuple[int, int] = GEOMETRY_WINDOW,
) -> dict[str, Any]:
    """Audit Dual `*_steps.csv` gate column over inclusive window."""
    rows = _read_steps_csv(steps_csv)
    lo, hi = int(window[0]), int(window[1])
    win = [r for r in rows if lo <= int(r["step"]) <= hi]
    if not win:
        return {
            "ok": False,
            "verdict": "GEOMETRY_WINDOW_FAIL",
            "reason": "empty_window",
            "window": [lo, hi],
            "n_steps": 0,
        }
    gates = [r.get("gate", "NONE") for r in win]
    stops = sum(1 for g in gates if g == "STOP")
    slows = sum(1 for g in gates if g in ("SLOW_DOWN", "SLOW"))
    allows = sum(1 for g in gates if g == "ALLOW")
    replans = sum(int(float(r.get("replan_count") or 0)) for r in win)
    # replan_count is cumulative; use delta + event columns if present
    replan_events = 0
    for r in win:
        if str(r.get("replan_event_id") or "").strip() not in ("", "0"):
            replan_events += 1
        if str(r.get("replan_applied_step") or "").strip() not in ("", "0", "-1"):
            # applied step column may equal current step
            try:
                if int(float(r["replan_applied_step"])) == int(r["step"]):
                    replan_events += 1
            except (TypeError, ValueError):
                pass
    dists = []
    for r in win:
        for key in ("dist_min_for_gating", "g1_body_dist", "dist_min_g1_body"):
            raw = r.get(key, "")
            if raw in ("", None):
                continue
            try:
                dists.append(float(raw))
                break
            except ValueError:
                continue
    non_allow = [int(r["step"]) for r in win if r.get("gate") != "ALLOW"]
    ok = stops == 0 and slows == 0 and allows == len(win) and not non_allow
    # Capture-step TTC: Dual steps CSV may not have ttc; use gate_trigger text.
    ttc_hits = []
    for r in win:
        if int(r["step"]) in E01_DYN_A_CAPTURE_STEPS:
            trig = (r.get("gate_trigger") or "").lower()
            if "ttc" in trig and r.get("gate") != "ALLOW":
                ttc_hits.append(int(r["step"]))
    return {
        "ok": bool(ok and not ttc_hits),
        "verdict": "PASS" if (ok and not ttc_hits) else "GEOMETRY_WINDOW_FAIL",
        "window": [lo, hi],
        "n_steps": len(win),
        "allow": allows,
        "stop": stops,
        "slow": slows,
        "replan_events": replan_events,
        "replan_count_max": max(int(float(r.get("replan_count") or 0)) for r in win),
        "non_allow_steps": non_allow[:20],
        "ttc_trigger_at_capture_steps": ttc_hits,
        "dist_min": min(dists) if dists else None,
        "dist_max": max(dists) if dists else None,
        "dist_mean": (sum(dists) / len(dists)) if dists else None,
        "phases": {
            str(s): arm_wave_phase_at_step(s) for s in E01_DYN_A_CAPTURE_STEPS
        },
    }


def audit_episode_gates(steps_csv: Path | str) -> dict[str, Any]:
    rows = _read_steps_csv(steps_csv)
    counts: dict[str, int] = {}
    for r in rows:
        g = r.get("gate", "NONE")
        counts[g] = counts.get(g, 0) + 1
    non_allow = [int(r["step"]) for r in rows if r.get("gate") != "ALLOW"]
    return {
        "n_steps": len(rows),
        "gate_counts": counts,
        "non_allow_count": len(non_allow),
        "non_allow_steps_sample": non_allow[:30],
        "note": "Full-episode gates reported separately; Dyn-A formal gate uses 210-280.",
    }


def build_frame_record(
    *,
    step: int,
    rgb_path: Path | str,
    body_points: Sequence[Sequence[float]],
    cam_pos: Sequence[float],
    gate: str,
    phase: str | None = None,
    dist_min_g1_body: float | None = None,
) -> dict[str, Any]:
    path = Path(rgb_path)
    roi = g1_roi_from_body_points(body_points, cam_pos=cam_pos)
    data = path.read_bytes() if path.is_file() else b""
    return {
        "sim_step": int(step),
        "path": str(path),
        "sha256": sha256_bytes(data) if data else "",
        "phase": phase or arm_wave_phase_at_step(step),
        "gate": gate,
        "dist_min_g1_body": dist_min_g1_body,
        "roi": roi,
        "roi_source": roi.get("roi_source"),
        "roi_area_px2": roi.get("roi_area_px2"),
        "centroid_uv": roi.get("centroid_uv"),
        "motion_source": MOTION_SOURCE_ARM_WAVE,
    }


def build_capture_manifest(
    *,
    frames: Sequence[Mapping[str, Any]],
    camera_pose: Mapping[str, Any],
    geometry_window: Mapping[str, Any],
    episode_gates: Mapping[str, Any],
    seed: int = E01_DYN_A_SEED,
    scenario: str = E01_DYN_A_SCENARIO,
    motion_source: str = MOTION_SOURCE_ARM_WAVE,
    post_count: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cents = []
    for fr in frames:
        c = fr.get("centroid_uv")
        if c is not None:
            cents.append(c)
    disp = None
    if len(cents) >= 2:
        disp = math.hypot(
            float(cents[1][0]) - float(cents[0][0]),
            float(cents[1][1]) - float(cents[0][1]),
        )
    hashes = [str(fr.get("sha256") or "") for fr in frames]
    visual_ok = (
        all(float(fr.get("roi_area_px2") or 0) >= MIN_G1_ROI_PX2 for fr in frames)
        and disp is not None
        and disp >= MIN_CENTROID_DISPLACEMENT_PX
        and len(set(hashes)) == len(hashes)
        and all(hashes)
    )
    geom_ok = bool(geometry_window.get("ok"))
    flags = validate_dyn_a_capture_flags(
        scenario=scenario,
        seed=seed,
        motion_source=motion_source,
        post_count=post_count,
        camera_pos=camera_pose.get("pos", E01_DYN_A_SCENE_CAMERA_POS),
        camera_rot=camera_pose.get("rot", E01_DYN_A_SCENE_CAMERA_ROT),
    )
    verdict = "PASS" if (visual_ok and geom_ok and flags["ok"]) else (
        "GEOMETRY_WINDOW_FAIL" if not geom_ok else "FAIL"
    )
    out = {
        "scene": "E01-Dyn-A",
        "scenario": scenario,
        "motion_source": motion_source,
        "seed": int(seed),
        "capture_steps": list(E01_DYN_A_CAPTURE_STEPS),
        "camera_pose": dict(camera_pose),
        "frames": [dict(fr) for fr in frames],
        "centroid_displacement_px": disp,
        "visual_gate_ok": visual_ok,
        "geometry_window": dict(geometry_window),
        "episode_gates": dict(episode_gates),
        "post_count": int(post_count),
        "flags": flags,
        "verdict": verdict,
        "min_g1_roi_px2": MIN_G1_ROI_PX2,
        "min_centroid_displacement_px": MIN_CENTROID_DISPLACEMENT_PX,
    }
    if extra:
        out.update(dict(extra))
    return out


def paper_scenario_sha_map(repo_root: Path | str) -> dict[str, str]:
    root = Path(repo_root)
    return {
        rel: sha256_file(root / rel)
        for rel in B0_B4_PAPER_SCENARIO_FILES
        if (root / rel).is_file()
    }


def assert_b0_b4_files_unchanged(
    repo_root: Path | str,
    expected: Mapping[str, str],
) -> None:
    got = paper_scenario_sha_map(repo_root)
    for rel, exp in expected.items():
        if got.get(rel) != exp:
            raise AssertionError(f"B0-B4 file changed: {rel}")
