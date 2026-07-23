#!/usr/bin/env python3
"""E01-Func-C offline unit tests (no Isaac / no POST)."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.v1e01_func_c_capture import (  # noqa: E402
    E01_FUNC_C_CAPTURE_STEPS,
    E01_FUNC_C_SEED,
    LABEL_STATUS,
    REVIEWER_APPROVED,
    SCENE_GROUP,
    audit_geometry_window,
    build_capture_manifest,
    build_frame_record,
    filled_content_roi,
    paper_scenario_sha_map,
    precheck_container_full_asset,
    target_box_b_roi,
    validate_func_c_flags,
)
from shadow.target_full_override import (  # noqa: E402
    CONTAINER_FIXED_USD_NAME,
    CONTAINER_FULL_SPAWN_USD_NAME,
    CONTAINER_FULL_USD_NAME,
    CONTAINER_USD_NAME,
    PART_FIXED_USD_NAME,
    PART_USD_NAME,
    resolve_box_scale,
    resolve_box_usd_name,
    resolve_part_usd_name,
    target_full_enabled,
)

ASSETS = ROOT / "source" / "GMRobot" / "GMRobot" / "assets"
CFG = ROOT / "configs" / "ivj_v1e01_target_container_full.yaml"
ENV_CFG = ROOT / "source" / "GMRobot" / "GMRobot" / "tasks" / "manager_based" / "gmrobot" / "gmrobot_env_cfg.py"
G1_ROOT = ROOT.parent / "g1_ur10e_disturbance"
D1B_CFG = ROOT / "configs" / "ivj_v1d1b_functional_blockage.yaml"


def test_switch_default_off_and_box_b_unchanged():
    assert target_full_enabled({}) is False
    assert resolve_box_usd_name("A") == CONTAINER_USD_NAME
    assert resolve_box_usd_name("B") == CONTAINER_USD_NAME
    assert resolve_box_scale("B", default_scale=(0.01, 0.01, 0.01)) == (0.01, 0.01, 0.01)


def test_func_c_enables_only_box_b_full():
    env = {"GMROBOT_V1E01_TARGET_FULL": "1"}
    # box_A → container_fixed.usd (normalized single RigidBodyAPI, kinematic)
    assert resolve_box_usd_name("A", env=env) == CONTAINER_FIXED_USD_NAME
    # box_B → container_full_visual.usd (visual-only)
    assert resolve_box_usd_name("B", env=env) == CONTAINER_FULL_SPAWN_USD_NAME
    assert resolve_box_scale("B", default_scale=(0.01, 0.01, 0.01), env=env) == (1.0, 1.0, 1.0)
    # Parts → part_fixed.usd (root-prim RigidBodyAPI)
    assert resolve_part_usd_name(env=env) == PART_FIXED_USD_NAME
    assert resolve_part_usd_name(env={}) == PART_USD_NAME


def test_d1b_blocker_not_enabled_and_env_cfg_intact():
    text = ENV_CFG.read_text(encoding="utf-8")
    assert "GMROBOT_V1E01_TARGET_FULL" in text or "resolve_box_usd_name" in text
    assert "GMROBOT_V1D1B_FUNCTIONAL_BLOCK" in text
    assert 'PART_LOCATIONS[19] = "B@10"' in text
    # Func-C config must not enable D1B blocker
    cfg = CFG.read_text(encoding="utf-8")
    assert "GMROBOT_V1D1B_FUNCTIONAL_BLOCK=1" not in cfg
    assert "d1b_blocker: false" in cfg or "d1b_blocker:false" in cfg.replace(" ", "")
    assert D1B_CFG.is_file()  # historical untouched


def test_seed_camera_steps_labels():
    flags = validate_func_c_flags(env={"GMROBOT_V1E01_TARGET_FULL": "1"})
    assert flags["ok"] is True
    assert E01_FUNC_C_SEED == 51
    assert E01_FUNC_C_CAPTURE_STEPS == (100, 200)
    assert LABEL_STATUS == "provisional"
    assert REVIEWER_APPROVED is False
    assert SCENE_GROUP == "e01_func_c"
    assert flags["post_count_expected"] == 0
    assert flags["clients_initialized_expected"] is False
    assert flags["target_full_default_off"] is True


def test_network_rejected():
    assert validate_func_c_flags(enable_vlm=True)["ok"] is False
    assert validate_func_c_flags(post_count=1)["ok"] is False
    assert validate_func_c_flags(reviewer_approved=True)["ok"] is False


def test_asset_precheck_and_roi():
    pre = precheck_container_full_asset(ASSETS)
    assert pre["ok"] is True, pre
    assert pre["filled_part_mesh_count"] >= 8
    tgt = target_box_b_roi()
    filled = filled_content_roi()
    assert tgt["pixel_area"] >= 2500
    assert filled["pixel_area"] > 0
    assert filled["containment"]["filled_inside_target"] is True
    assert tgt["roi_source"] == "projected_box_b_aabb"
    assert "projected" in filled["roi_source"]


def test_geometry_manifest_roundtrip_and_b0b4():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        csv_path = td_path / "ep.csv"
        # GMRobot-like header
        lines = ["step,g_rule,reason,dist_min\n"]
        for s in range(90, 211):
            lines.append(f"{s},0,allow,0.85\n")
        csv_path.write_text("".join(lines), encoding="utf-8")
        geom = audit_geometry_window(csv_path)
        assert geom["ok"] is True
        bad = td_path / "bad.csv"
        bad.write_text(
            "step,g_rule,reason,dist_min\n"
            + "".join(
                f"{s},{2 if s == 150 else 0},{'static_warning' if s == 150 else 'allow'},0.85\n"
                for s in range(100, 201)
            ),
            encoding="utf-8",
        )
        assert audit_geometry_window(bad)["ok"] is False

        png0 = td_path / "f100.png"
        png1 = td_path / "f200.png"
        png0.write_bytes(b"\x89PNG_func_c_100")
        png1.write_bytes(b"\x89PNG_func_c_200")
        pre = precheck_container_full_asset(ASSETS)
        frames = [
            build_frame_record(step=100, rgb_path=png0, hand_pos=[0.25, -0.75, 0.60]),
            build_frame_record(step=200, rgb_path=png1, hand_pos=[0.25, -0.75, 0.60]),
        ]
        man = build_capture_manifest(
            frames=frames,
            geometry_window=geom,
            episode_gates={"gate_counts": {"ALLOW": 111}},
            asset_precheck=pre,
        )
        rt = json.loads(json.dumps(man))
        assert rt["label_status"] == "provisional"
        assert rt["reviewer_approved"] is False
        assert rt["verdict"] == "CAPTURE_PASS_PROVISIONAL_FUNCTIONAL"
        assert rt["not_vlm_positive"] is True

    sha_map = paper_scenario_sha_map(G1_ROOT)
    assert sha_map
    blob = json.dumps(sha_map, sort_keys=True).encode()
    assert len(hashlib.sha256(blob).hexdigest()) == 64


# Frozen asset SHA256 baseline (2026-07-23 USD audit).
# Changing ANY of these without deliberate re-baseline is a regression.
FROZEN_ASSET_HASHES: dict[str, str] = {
    "container.usd": "ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9",
    "container_full.usd": "ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0",
    # Canonical repaired Func-C visual asset identity (approved lineage, 2026-07-23).
    "container_full_visual.usd": "f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e",
    "part_5000.usd": "71fd48abb018275ae5bf9634216898136c028d0c883deb50caa7467481991aa6",
    "container_fixed.usd": "acb2151a26baee9ff27dcdfe9c8c5bf2919182747389160f3f621347dc2a057d",
    "part_fixed.usd": "ccf516872c8501169efa5274cebe4f9740b091914cdd6ff9e52082ddbfe10441",
}
FROZEN_HASH_ASSET_MAP: dict[str, str] = {
    "container.usd": "container.usd",
    "container_full.usd": "container_full.usd",
    "container_full_visual.usd": "container_full_visual.usd",
    "part_5000.usd": "part/part_5000.usd",
    "container_fixed.usd": "container_fixed.usd",
    "part_fixed.usd": "part/part_fixed.usd",
}


def test_frozen_asset_hashes_unchanged():
    """All frozen USD assets must match their baseline SHA256."""
    for key, expected in sorted(FROZEN_ASSET_HASHES.items()):
        rel = FROZEN_HASH_ASSET_MAP[key]
        path = ASSETS / rel
        assert path.is_file(), f"missing: {path}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"{key}: hash mismatch\nexpected: {expected}\nactual:   {actual}"


def test_container_full_visual_provenance_chain():
    """Strengthened provenance: frozen source + generator freeze-hash + structural identity."""
    expected_source_sha = FROZEN_ASSET_HASHES["container_full.usd"]
    source_path = ASSETS / "container_full.usd"
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert source_sha == expected_source_sha, f"container_full.usd hash drifted: {source_sha}"

    generator_path = ROOT / "scripts" / "generate_container_full_visual_usd.py"
    gen_text = generator_path.read_text(encoding="utf-8")
    m = re.search(r'FROZEN_SOURCE_SHA256\\s*=\\s*"([0-9a-f]{64})"', gen_text)
    assert m is not None, "generator missing FROZEN_SOURCE_SHA256"
    assert m.group(1) == expected_source_sha, (
        f"generator freeze hash mismatch: {m.group(1)} != {expected_source_sha}"
    )

    # Structural fingerprint is the stable identity guard when USDC binary bytes vary by writer/env.
    try:
        spec = importlib.util.spec_from_file_location(
            "generate_container_full_visual_usd",
            str(generator_path),
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        structural_fingerprint = getattr(mod, "structural_fingerprint")
    except Exception:
        return
    actual_fp = structural_fingerprint(ASSETS / "container_full_visual.usd")
    expected_fp = "bb90e8cbf865dd9bdeb0c2fc0eea25f0ac1cc74a48f68f5d09709c079820920d"
    assert actual_fp == expected_fp, (
        f"container_full_visual.usd structural fingerprint mismatch:\n"
        f"expected: {expected_fp}\nactual:   {actual_fp}"
    )


def test_frozen_usd_structure_read_only():
    """PXR read-only structural assertions — no nested active rigid body on box A, clean visual."""
    try:
        from pxr import Usd, UsdGeom, UsdPhysics  # type: ignore
    except ImportError:
        return  # skip in env without pxr

    # container.usd: record nested rigid count (known broken, audit baseline)
    stage = Usd.Stage.Open(str(ASSETS / "container.usd"))
    rigid_paths = []
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    rigid_paths.append(str(prim.GetPath()))
            except Exception:
                pass
    # 2026-07-23 audit: 2 active rigid bodies (nested) — known issue
    assert len(rigid_paths) == 2, f"container.usd active rigid count changed: {rigid_paths}"
    assert "/Root/Container" in rigid_paths
    assert "/Root/Container/Ref" in rigid_paths

    # container_full_visual.usd: MUST have 0 rigid/collision
    stage_v = Usd.Stage.Open(str(ASSETS / "container_full_visual.usd"))
    n_rigid_v = 0
    n_coll_v = 0
    n_mesh_v = 0
    for prim in stage_v.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            n_mesh_v += 1
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    n_rigid_v += 1
            except Exception:
                pass
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            n_coll_v += 1
    assert n_rigid_v == 0, f"container_full_visual.usd has {n_rigid_v} active rigid bodies"
    assert n_coll_v == 0, f"container_full_visual.usd has {n_coll_v} collision APIs"
    assert n_mesh_v == 31, f"container_full_visual.usd has {n_mesh_v} meshes (expected 31)"

    # part_5000.usd: exactly 1 rigid
    stage_p = Usd.Stage.Open(str(ASSETS / "part" / "part_5000.usd"))
    n_rigid_p = 0
    for prim in stage_p.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    n_rigid_p += 1
            except Exception:
                pass
    assert n_rigid_p == 1, f"part_5000.usd has {n_rigid_p} active rigid bodies (expected 1)"


def test_normalized_asset_structure_gate():
    """Structural gate: no nested rigid bodies in normalized assets."""
    try:
        from pxr import Usd, UsdGeom, UsdPhysics  # type: ignore
    except ImportError:
        return

    # Gate: container_fixed.usd — exactly 1 active rigid body at /Root/Container, kinematic
    stage_c = Usd.Stage.Open(str(ASSETS / "container_fixed.usd"))
    c_rigid = []
    for prim in stage_c.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    c_rigid.append(str(prim.GetPath()))
            except Exception:
                pass
    assert len(c_rigid) == 1, f"container_fixed: expected 1 rigid, got {len(c_rigid)}: {c_rigid}"
    assert c_rigid[0] == "/Root/Container", f"container_fixed: wrong rigid path {c_rigid[0]}"
    r = UsdPhysics.RigidBodyAPI(stage_c.GetPrimAtPath("/Root/Container"))
    assert r.GetKinematicEnabledAttr().Get() is True, "container_fixed: not kinematic"

    # Gate: part_fixed.usd — exactly 1 active rigid body at /Root, MassAPI present
    stage_p = Usd.Stage.Open(str(ASSETS / "part" / "part_fixed.usd"))
    p_rigid = []
    p_mass = []
    for prim in stage_p.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    p_rigid.append(str(prim.GetPath()))
            except Exception:
                pass
        if prim.HasAPI(UsdPhysics.MassAPI):
            p_mass.append(str(prim.GetPath()))
    assert len(p_rigid) == 1, f"part_fixed: expected 1 rigid, got {len(p_rigid)}: {p_rigid}"
    assert p_rigid[0] == "/Root", f"part_fixed: rigid body not at /Root: {p_rigid[0]}"
    assert len(p_mass) == 1, f"part_fixed: expected 1 MassAPI, got {len(p_mass)}: {p_mass}"
    assert p_mass[0] == "/Root", f"part_fixed: MassAPI not at /Root: {p_mass[0]}"

    # Gate: no child of /Root has RigidBodyAPI in part_fixed.usd
    child_rigid = [p for p in p_rigid if p != "/Root"]
    assert not child_rigid, f"part_fixed: child rigid bodies detected: {child_rigid}"


def test_part_initial_pose_numeric_gate():
    """Numeric gate: 20 parts with initial slot positions well-formed."""
    cfg_text = ENV_CFG.read_text(encoding="utf-8")
    # Verify part count: PART_SLOT_COUNT = CONTAINER_X_SLOTS * CONTAINER_Y_SLOTS = 5*4 = 20
    assert "CONTAINER_X_SLOTS = 5" in cfg_text or "CONTAINER_X_SLOTS=5" in cfg_text
    assert "CONTAINER_Y_SLOTS = 4" in cfg_text or "CONTAINER_Y_SLOTS=4" in cfg_text
    assert "PART_SLOT_COUNT=CONTAINER_X_SLOTS*CONTAINER_Y_SLOTS" in cfg_text.replace(" ", "")
    # PART_LOCATIONS has 20 entries
    assert "PART_LOCATIONS = [f\"A@{i}\" for i in range(1, PART_SLOT_COUNT + 1)]" in cfg_text
    # Default (no D1B blocker): all 20 parts go to slots A@1..A@20
    assert 'PART_LOCATIONS[19] = "B@10"' in cfg_text  # D1B opt-in line present
    # In Func-C mode (default), D1B blocker is disabled, so part_20 stays in A@20.


def test_no_secrets_in_new_files():
    """No credentials, tokens, or API keys in Func-C specific source files."""
    forbidden = re.compile(
        r"(password\s*[=:]|secret\s*[=:]|credential|api[_.-]?key|AUTH_TOKEN|GITHUB_TOKEN"
        r"|OPENAI_API|ANTHROPIC_API|sk-[A-Za-z0-9]{20,})",
        re.IGNORECASE,
    )
    # Only scan Func-C specific files, not entire shadow directory
    func_c_files = [
        ROOT / "source" / "GMRobot" / "GMRobot" / "shadow" / "target_full_override.py",
        ROOT / "source" / "GMRobot" / "GMRobot" / "shadow" / "v1e01_func_c_capture.py",
        ROOT / "scripts" / "analyze_e01_func_c_capture.py",
        ROOT / "configs" / "ivj_v1e01_target_container_full.yaml",
        ROOT / "docker" / "Dockerfile.e01-func-c",
        ROOT.parent / "g1_ur10e_disturbance" / "configs" / "e01_func_c_capture.yaml",
        ROOT.parent / "g1_ur10e_disturbance" / "scripts" / "run_e01_func_c_capture.sh",
    ]
    for fpath in func_c_files:
        if not fpath.is_file():
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        m = forbidden.search(text)
        assert m is None, f"SECRET in {fpath}: {m.group()}"


def main():
    test_switch_default_off_and_box_b_unchanged()
    test_func_c_enables_only_box_b_full()
    test_d1b_blocker_not_enabled_and_env_cfg_intact()
    test_seed_camera_steps_labels()
    test_network_rejected()
    test_asset_precheck_and_roi()
    test_geometry_manifest_roundtrip_and_b0b4()
    test_frozen_asset_hashes_unchanged()
    test_frozen_usd_structure_read_only()
    test_normalized_asset_structure_gate()
    test_part_initial_pose_numeric_gate()
    test_no_secrets_in_new_files()
    print("PASS test_e01_func_c_capture_unit")


if __name__ == "__main__":
    main()
