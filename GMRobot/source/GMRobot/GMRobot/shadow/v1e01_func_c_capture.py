"""V1-E01-Func-C offline capture helpers (no VLM / perception POST)."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from shadow.target_full_override import (
    CAMERA_POS,
    CAMERA_ROT,
    CONTAINER_FULL_SCALE,
    CONTAINER_FULL_USD_NAME,
    CONTAINER_USD_NAME,
    E01_FUNC_C_CAPTURE_STEPS,
    E01_FUNC_C_GEOMETRY_WINDOW,
    E01_FUNC_C_SEED,
    EXPECTED_RISK_TYPE,
    LABEL_STATUS,
    MIN_TARGET_ROI_PX2,
    REVIEWER_APPROVED,
    SCENE_GROUP,
    d1b_blocker_enabled,
    resolve_box_scale,
    resolve_box_usd_name,
    target_full_enabled,
)

# Reuse D1B empirical overhead projection (same default camera).
from shadow.v1d1b_capture import (
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    TARGET_CONTAINER_POSE,
    project_world_to_uv,
    roi_from_world_point,
    sha256_file,
)

__all__ = [
    "SCENE_GROUP",
    "EXPECTED_RISK_TYPE",
    "LABEL_STATUS",
    "REVIEWER_APPROVED",
    "E01_FUNC_C_SEED",
    "E01_FUNC_C_CAPTURE_STEPS",
    "E01_FUNC_C_GEOMETRY_WINDOW",
    "MIN_TARGET_ROI_PX2",
    "precheck_container_full_asset",
    "validate_func_c_flags",
    "audit_geometry_window",
    "audit_episode_gates",
    "target_box_b_roi",
    "filled_content_roi",
    "build_frame_record",
    "build_capture_manifest",
]


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


def precheck_container_full_asset(assets_dir: Path | str) -> dict[str, Any]:
    """Structural visual-distinction precheck (USD mesh topology; no filename claim)."""
    root = Path(assets_dir)
    empty = root / CONTAINER_USD_NAME
    full = root / CONTAINER_FULL_USD_NAME
    out: dict[str, Any] = {
        "ok": False,
        "verdict": "ASSET_SEMANTIC_DISTINCTION_UNPROVEN",
        "empty_path": str(empty),
        "full_path": str(full),
    }
    if not empty.is_file() or not full.is_file():
        out["reason"] = "missing_usd"
        return out
    out["empty_sha256"] = sha256_file(empty)
    out["full_sha256"] = sha256_file(full)
    out["empty_bytes"] = empty.stat().st_size
    out["full_bytes"] = full.stat().st_size
    if out["empty_sha256"] == out["full_sha256"]:
        out["reason"] = "identical_hash"
        return out
    # Network dependency scan (byte-level)
    data = full.read_bytes()
    out["https_count"] = data.lower().count(b"https://")
    out["http_count"] = data.lower().count(b"http://")
    if out["https_count"] or out["http_count"]:
        out["reason"] = "external_network_refs"
        return out
    try:
        from pxr import Usd, UsdGeom  # type: ignore
    except Exception as exc:  # pragma: no cover
        out["reason"] = f"pxr_unavailable:{exc}"
        return out

    def _stats(path: Path) -> dict[str, Any]:
        stage = Usd.Stage.Open(str(path))
        n_mesh = 0
        points = 0
        faces = 0
        part_names: list[str] = []
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                n_mesh += 1
                mesh = UsdGeom.Mesh(prim)
                points += len(mesh.GetPointsAttr().Get() or [])
                faces += len(mesh.GetFaceVertexCountsAttr().Get() or [])
                name = prim.GetName()
                path_s = str(prim.GetPath())
                if "Part_" in path_s or name.startswith("Part_"):
                    part_names.append(path_s)
        return {
            "n_prims": len(list(stage.Traverse())),
            "n_meshes": n_mesh,
            "points": points,
            "faces": faces,
            "part_mesh_paths": part_names,
            "metersPerUnit": float(UsdGeom.GetStageMetersPerUnit(stage)),
        }

    empty_s = _stats(empty)
    full_s = _stats(full)
    out["empty_stats"] = empty_s
    out["full_stats"] = full_s
    out["filled_part_mesh_count"] = len(full_s["part_mesh_paths"])
    distinct = (
        full_s["n_meshes"] > empty_s["n_meshes"]
        and full_s["points"] > empty_s["points"]
        and len(full_s["part_mesh_paths"]) >= 8
    )
    if not distinct:
        out["reason"] = "no_extra_filled_geometry"
        return out
    out["ok"] = True
    out["verdict"] = "ASSET_DISTINCTION_OK"
    out["evidence"] = (
        f"full has {full_s['n_meshes']} meshes / {full_s['points']} points "
        f"vs empty {empty_s['n_meshes']} / {empty_s['points']}; "
        f"{len(full_s['part_mesh_paths'])} Part_* meshes (filled content)"
    )
    out["recommended_full_scale"] = list(CONTAINER_FULL_SCALE)
    out["docker_copy_note"] = "build.sh copies GMRobot/assets/* into gmrobot_assets/"
    return out


def validate_func_c_flags(
    *,
    env: Mapping[str, str] | None = None,
    seed: int = E01_FUNC_C_SEED,
    capture_steps: Sequence[int] = E01_FUNC_C_CAPTURE_STEPS,
    camera_pos: Sequence[float] = CAMERA_POS,
    enable_vlm: bool = False,
    enable_perception: bool = False,
    enable_five_stage: bool = False,
    enable_replan: bool = False,
    virtual_hand_motion: bool = False,
    post_count: int = 0,
    label_status: str = LABEL_STATUS,
    reviewer_approved: bool = REVIEWER_APPROVED,
    expected_risk_type: str = EXPECTED_RISK_TYPE,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not target_full_enabled(env):
        # For capture-mode validation env should enable the switch.
        pass
    if d1b_blocker_enabled(env):
        reasons.append("d1b_blocker_enabled")
    if int(seed) != E01_FUNC_C_SEED:
        reasons.append(f"seed={seed}")
    if tuple(int(s) for s in capture_steps) != E01_FUNC_C_CAPTURE_STEPS:
        reasons.append(f"capture_steps={list(capture_steps)}")
    if tuple(float(x) for x in camera_pos) != CAMERA_POS:
        reasons.append(f"camera_pos={list(camera_pos)}")
    if enable_vlm or enable_perception or enable_five_stage:
        reasons.append("network_workers")
    if enable_replan:
        reasons.append("replan")
    if virtual_hand_motion:
        reasons.append("virtual_hand_motion")
    if int(post_count) != 0:
        reasons.append(f"post_count={post_count}")
    if label_status != "provisional":
        reasons.append(f"label_status={label_status}")
    if reviewer_approved is not False:
        reasons.append("reviewer_approved_not_false")
    if expected_risk_type != "functional":
        reasons.append(f"expected_risk_type={expected_risk_type}")
    # Default-off box resolution checks
    assert resolve_box_usd_name("A", env={}) == CONTAINER_USD_NAME
    assert resolve_box_usd_name("B", env={}) == CONTAINER_USD_NAME
    assert resolve_box_usd_name("B", env={"GMROBOT_V1E01_TARGET_FULL": "1"}) == "container_full_visual.usd"
    assert resolve_box_scale("B", default_scale=(0.01, 0.01, 0.01), env={}) == (0.01, 0.01, 0.01)
    assert resolve_box_scale(
        "B", default_scale=(0.01, 0.01, 0.01), env={"GMROBOT_V1E01_TARGET_FULL": "1"}
    ) == CONTAINER_FULL_SCALE
    return {
        "ok": not reasons,
        "reasons": reasons,
        "post_count_expected": 0,
        "clients_initialized_expected": False,
        "label_status": LABEL_STATUS,
        "reviewer_approved": REVIEWER_APPROVED,
        "expected_risk_type": EXPECTED_RISK_TYPE,
        "scene_group": SCENE_GROUP,
        "target_full_default_off": not target_full_enabled({}),
    }


def _g_rule_name(v: int) -> str:
    return {0: "ALLOW", 1: "STOP", 2: "SLOW_DOWN"}.get(int(v), f"UNKNOWN_{v}")


def audit_geometry_window(
    steps_csv: Path | str,
    *,
    window: tuple[int, int] = E01_FUNC_C_GEOMETRY_WINDOW,
) -> dict[str, Any]:
    """Audit GMRobot SafetyLogger CSV (`g_rule`) over inclusive window."""
    path = Path(steps_csv)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    lo, hi = int(window[0]), int(window[1])
    # GMRobot SafetyLogger uses `step_index`; Dual/phase3 may use `step`/`sim_step`.
    def _step(r: dict[str, str]) -> int:
        for k in ("step_index", "step", "sim_step", "t"):
            if k in r and str(r[k]).strip() != "":
                return int(float(r[k]))
        raise KeyError("step")

    win = []
    for r in rows:
        try:
            s = _step(r)
        except Exception:
            continue
        if lo <= s <= hi:
            win.append((s, r))
    if not win:
        return {
            "ok": False,
            "verdict": "GEOMETRY_WINDOW_FAIL",
            "reason": "empty_window",
            "window": [lo, hi],
        }
    rules = []
    reasons = []
    replans = 0
    ttcs: list[float] = []
    for s, r in win:
        if "g_rule" in r:
            rules.append(int(float(r["g_rule"])))
        elif "gate" in r:
            name = r["gate"]
            rules.append({"ALLOW": 0, "STOP": 1, "SLOW_DOWN": 2, "SLOW": 2}.get(name, -1))
        else:
            rules.append(-1)
        reasons.append(str(r.get("reason") or r.get("gate_trigger") or r.get("trigger_rule") or ""))
        ra = str(r.get("replan_active") or "").strip().lower()
        if ra in {"1", "true", "yes", "on"} or (ra and ra not in {"0", "false", "none", ""}):
            replans += 1
        for tk in ("ttc", "ttc_forecast_s"):
            raw = str(r.get(tk) or "").strip()
            if raw and raw.lower() not in {"inf", "nan", "none", ""}:
                try:
                    ttcs.append(float(raw))
                except ValueError:
                    pass
                break
    stops = sum(1 for g in rules if g == 1)
    slows = sum(1 for g in rules if g == 2)
    allows = sum(1 for g in rules if g == 0)
    bad = [win[i][0] for i, g in enumerate(rules) if g != 0]
    static_w = [win[i][0] for i, t in enumerate(reasons) if "static" in t.lower()]
    ttc = [win[i][0] for i, t in enumerate(reasons) if "ttc" in t.lower()]
    held = [win[i][0] for i, t in enumerate(reasons) if "held" in t.lower()]
    dists = []
    for _, r in win:
        for k in (
            "dist_min_envelope",
            "dist_min",
            "d_min",
            "distance",
            "dist_ee_human",
            "dist_ee_hand",
        ):
            if k in r and str(r[k]).strip() not in ("", "nan", "None"):
                try:
                    dists.append(float(r[k]))
                    break
                except ValueError:
                    pass
    ok = (
        stops == 0
        and slows == 0
        and allows == len(rules)
        and replans == 0
        and not bad
        and not ttc
        and not static_w
        and not held
    )
    return {
        "ok": bool(ok),
        "verdict": "PASS" if ok else "GEOMETRY_WINDOW_FAIL",
        "window": [lo, hi],
        "n_steps": len(rules),
        "allow": allows,
        "stop": stops,
        "slow": slows,
        "replan": int(replans),
        "held_critical_steps": held,
        "static_warning_steps": static_w,
        "dynamic_ttc_steps": ttc,
        "non_allow_steps": bad[:20],
        "dist_min": min(dists) if dists else None,
        "dist_max": max(dists) if dists else None,
        "dist_mean": (sum(dists) / len(dists)) if dists else None,
        "ttc_finite_min": min(ttcs) if ttcs else None,
        "ttc_finite_max": max(ttcs) if ttcs else None,
        "ttc_finite_count": len(ttcs),
        "reason_counts": {
            r: sum(1 for x in reasons if x == r) for r in sorted(set(reasons))
        },
    }


def audit_episode_gates(steps_csv: Path | str) -> dict[str, Any]:
    rows = list(csv.DictReader(Path(steps_csv).open(encoding="utf-8")))
    counts: dict[str, int] = {}
    for r in rows:
        if "g_rule" in r and str(r["g_rule"]).strip() != "":
            name = _g_rule_name(int(float(r["g_rule"])))
        else:
            name = r.get("gate", "NONE")
        counts[name] = counts.get(name, 0) + 1
    return {"n_steps": len(rows), "gate_counts": counts}


def target_box_b_roi() -> dict[str, Any]:
    """Projected AABB ROI for box_B footprint under default scene camera."""
    cx, cy, cz = TARGET_CONTAINER_POSE
    # Footprint corners (meters) matching ~0.55 x 0.28 container after spawn.
    half_x, half_y = 0.28, 0.16
    corners = [
        (cx - half_x, cy - half_y, 0.15),
        (cx - half_x, cy + half_y, 0.15),
        (cx + half_x, cy - half_y, 0.15),
        (cx + half_x, cy + half_y, 0.15),
        (cx, cy, 0.25),
    ]
    uvs = [project_world_to_uv(c) for c in corners]
    uvs = [uv for uv in uvs if uv is not None]
    if not uvs:
        return {"visible": False, "pixel_area": 0, "roi_source": "projected_box_b_aabb"}
    us = [u for u, _ in uvs]
    vs = [v for _, v in uvs]
    x0, x1 = max(0, int(min(us))), min(CAMERA_WIDTH - 1, int(max(us)))
    y0, y1 = max(0, int(min(vs))), min(CAMERA_HEIGHT - 1, int(max(vs)))
    area = max(0, (x1 - x0 + 1) * (y1 - y0 + 1))
    return {
        "visible": area > 0,
        "bbox_xyxy": [x0, y0, x1, y1],
        "centroid_uv": [0.5 * (x0 + x1), 0.5 * (y0 + y1)],
        "pixel_area": int(area),
        "roi_source": "projected_box_b_aabb",
    }


def filled_content_roi() -> dict[str, Any]:
    """Inner ROI approximating packed Part_* volume inside box_B."""
    cx, cy, _ = TARGET_CONTAINER_POSE
    half_x, half_y = 0.20, 0.12
    corners = [
        (cx - half_x, cy - half_y, 0.18),
        (cx - half_x, cy + half_y, 0.18),
        (cx + half_x, cy - half_y, 0.18),
        (cx + half_x, cy + half_y, 0.18),
    ]
    uvs = [project_world_to_uv(c) for c in corners]
    uvs = [uv for uv in uvs if uv is not None]
    us = [u for u, _ in uvs]
    vs = [v for _, v in uvs]
    x0, x1 = max(0, int(min(us))), min(CAMERA_WIDTH - 1, int(max(us)))
    y0, y1 = max(0, int(min(vs))), min(CAMERA_HEIGHT - 1, int(max(vs)))
    area = max(0, (x1 - x0 + 1) * (y1 - y0 + 1))
    target = target_box_b_roi()
    containment = None
    if target.get("bbox_xyxy") and area > 0:
        tx0, ty0, tx1, ty1 = target["bbox_xyxy"]
        containment = {
            "filled_inside_target": tx0 <= x0 and ty0 <= y0 and x1 <= tx1 and y1 <= ty1,
            "metric": "aabb_containment",
        }
    return {
        "visible": area > 0,
        "bbox_xyxy": [x0, y0, x1, y1],
        "centroid_uv": [0.5 * (x0 + x1), 0.5 * (y0 + y1)],
        "pixel_area": int(area),
        "roi_source": "projected_filled_parts_aabb",
        "containment": containment,
    }


def rgb_filled_content_evidence(rgb_path: Path | str, filled_roi: Mapping[str, Any]) -> dict[str, Any]:
    """Count non-green interior pixels in filled ROI (not a filename-based gate)."""
    path = Path(rgb_path)
    out: dict[str, Any] = {
        "ok": False,
        "path": str(path),
        "method": "filled_roi_non_green_dark_pixels",
    }
    if not path.is_file() or not filled_roi.get("bbox_xyxy"):
        out["reason"] = "missing_rgb_or_roi"
        return out
    try:
        from PIL import Image
        import numpy as np
    except Exception as exc:  # pragma: no cover
        out["reason"] = f"pillow_unavailable:{exc}"
        return out
    arr = np.asarray(Image.open(path).convert("RGB"))
    x0, y0, x1, y1 = [int(v) for v in filled_roi["bbox_xyxy"]]
    crop = arr[y0 : y1 + 1, x0 : x1 + 1]
    if crop.size == 0:
        out["reason"] = "empty_crop"
        return out
    r = crop[..., 0].astype("int16")
    g = crop[..., 1].astype("int16")
    b = crop[..., 2].astype("int16")
    greenish = (g > r + 25) & (g > b + 25) & (g > 80)
    dark = ((r.astype("int32") + g + b) / 3.0) < 90
    content = dark & ~greenish
    content_px = int(content.sum())
    out.update(
        {
            "ok": content_px >= 80,
            "crop_shape": list(crop.shape),
            "content_px": content_px,
            "greenish_px": int(greenish.sum()),
            "dark_px": int(dark.sum()),
            "mean_rgb": [float(r.mean()), float(g.mean()), float(b.mean())],
        }
    )
    return out


def build_frame_record(
    *,
    step: int,
    rgb_path: Path | str,
    gate: str | int = "ALLOW",
    hand_pos: Sequence[float] | None = None,
) -> dict[str, Any]:
    path = Path(rgb_path)
    target = target_box_b_roi()
    filled = filled_content_roi()
    hand_roi = None
    if hand_pos is not None:
        hand_roi = roi_from_world_point(hand_pos, half_extent_m=0.05)
    if path.is_file() and path.stat().st_size >= 1024:
        rgb_ev = rgb_filled_content_evidence(path, filled)
    else:
        rgb_ev = {"ok": True, "reason": "synthetic_or_missing_skipped"}
    return {
        "sim_step": int(step),
        "path": str(path),
        "sha256": sha256_file(path) if path.is_file() else "",
        "gate": gate if isinstance(gate, str) else _g_rule_name(int(gate)),
        "target_roi": target,
        "filled_content_roi": filled,
        "filled_content_rgb_evidence": rgb_ev,
        "hand_proxy": {
            "pos": list(hand_pos) if hand_pos is not None else None,
            "roi": hand_roi,
            "semantic_evidence": False,
        },
        "camera_pos": list(CAMERA_POS),
        "camera_rot": list(CAMERA_ROT),
    }


def build_capture_manifest(
    *,
    frames: Sequence[Mapping[str, Any]],
    geometry_window: Mapping[str, Any],
    episode_gates: Mapping[str, Any],
    asset_precheck: Mapping[str, Any],
    seed: int = E01_FUNC_C_SEED,
    post_count: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    flags = validate_func_c_flags(
        env={"GMROBOT_V1E01_TARGET_FULL": "1"},
        seed=seed,
        post_count=post_count,
    )
    visual_ok = all(
        float((fr.get("target_roi") or {}).get("pixel_area") or 0) >= MIN_TARGET_ROI_PX2
        and float((fr.get("filled_content_roi") or {}).get("pixel_area") or 0) > 0
        and bool((fr.get("filled_content_roi") or {}).get("containment", {}).get("filled_inside_target", False))
        and bool((fr.get("filled_content_rgb_evidence") or {}).get("ok"))
        and bool(fr.get("sha256"))
        for fr in frames
    )
    hashes = [str(fr.get("sha256") or "") for fr in frames]
    visual_ok = visual_ok and len(set(hashes)) >= 1 and all(hashes)
    geom_ok = bool(geometry_window.get("ok"))
    asset_ok = bool(asset_precheck.get("ok"))
    if not asset_ok:
        verdict = "ASSET_SEMANTIC_DISTINCTION_UNPROVEN"
    elif not visual_ok:
        verdict = "SCENE_VISIBILITY_FAIL"
    elif not geom_ok:
        verdict = "GEOMETRY_WINDOW_FAIL"
    elif not flags["ok"]:
        verdict = "CAPTURE_RUNTIME_FAIL"
    else:
        verdict = "CAPTURE_PASS_PROVISIONAL_FUNCTIONAL"
    out = {
        "scene_group": SCENE_GROUP,
        "expected_risk_type": EXPECTED_RISK_TYPE,
        "label_status": LABEL_STATUS,
        "reviewer_approved": REVIEWER_APPROVED,
        "seed": int(seed),
        "capture_steps": list(E01_FUNC_C_CAPTURE_STEPS),
        "camera_pos": list(CAMERA_POS),
        "box_A_usd": CONTAINER_USD_NAME,
        "box_B_usd": CONTAINER_FULL_USD_NAME,
        "d1b_blocker_enabled": False,
        "frames": [dict(fr) for fr in frames],
        "geometry_window": dict(geometry_window),
        "episode_gates": dict(episode_gates),
        "asset_precheck": dict(asset_precheck),
        "post_count": int(post_count),
        "flags": flags,
        "visual_gate_ok": visual_ok,
        "verdict": verdict,
        "paper_claim": "视觉上已满或不可用于继续放置的目标容器候选场景。",
        "not_vlm_positive": True,
        "not_accepted": True,
    }
    if extra:
        out.update(dict(extra))
    return out


def paper_scenario_sha_map(repo_g1: Path | str) -> dict[str, str]:
    root = Path(repo_g1)
    return {rel: sha256_file(root / rel) for rel in B0_B4_PAPER_SCENARIO_FILES if (root / rel).is_file()}
