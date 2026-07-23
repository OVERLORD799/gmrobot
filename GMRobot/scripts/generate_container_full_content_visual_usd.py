#!/usr/bin/env python3
"""Deterministic generator: part_5000.usd -> container_full_content_visual.usd.

Creates a content-only visual payload for Func-C TARGET_FULL+VISUAL_ONLY mode:
- contains only 20 FilledContent_* meshes (5x4 slots)
- no container shell prims
- no RigidBody/Collision/Mass/PhysicsScene APIs
- metersPerUnit=1 and defaultPrim=/FilledContentOnly
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, Vt  # type: ignore

FROZEN_PART_SOURCE_SHA256 = "71fd48abb018275ae5bf9634216898136c028d0c883deb50caa7467481991aa6"
CONTAINER_X_SLOTS = 5
CONTAINER_Y_SLOTS = 4
CONTAINER_X_GAP = 0.11042
CONTAINER_Y_GAP = 0.07
PART_HEIGHT = 0.17


def _sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slot_local_offset(slot_idx_zero_based: int) -> tuple[float, float, float]:
    x_idx = slot_idx_zero_based // CONTAINER_Y_SLOTS
    y_idx = slot_idx_zero_based % CONTAINER_Y_SLOTS
    x_center = 0.5 * (CONTAINER_X_SLOTS - 1) * CONTAINER_X_GAP
    y_center = 0.5 * (CONTAINER_Y_SLOTS - 1) * CONTAINER_Y_GAP
    return (
        x_idx * CONTAINER_X_GAP - x_center,
        y_idx * CONTAINER_Y_GAP - y_center,
        PART_HEIGHT,
    )


def generate(
    source_part_usd: Path,
    output_usd: Path,
    *,
    freeze_source_hash: str | None = None,
) -> dict[str, object]:
    if not source_part_usd.is_file():
        raise FileNotFoundError(f"missing source usd: {source_part_usd}")
    source_hash = _sha256_hex(source_part_usd)
    if freeze_source_hash is not None and source_hash != freeze_source_hash:
        raise ValueError(
            "source hash mismatch: "
            f"expected={freeze_source_hash} actual={source_hash}"
        )

    src_stage = Usd.Stage.Open(str(source_part_usd))
    src_mesh_prim = src_stage.GetPrimAtPath("/Root/container_part_fixed_5000/node_/mesh_")
    if not src_mesh_prim or not src_mesh_prim.IsA(UsdGeom.Mesh):
        raise RuntimeError("part source mesh not found: /Root/container_part_fixed_5000/node_/mesh_")
    src_mesh = UsdGeom.Mesh(src_mesh_prim)

    output_usd.parent.mkdir(parents=True, exist_ok=True)
    if output_usd.exists():
        output_usd.unlink()

    stage = Usd.Stage.CreateNew(str(output_usd))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.SetMetadata("metersPerUnit", 1.0)
    root = stage.DefinePrim("/FilledContentOnly", "Xform")
    stage.SetDefaultPrim(root)
    stage.DefinePrim("/FilledContentOnly/FilledContents", "Xform")

    src_points = src_mesh.GetPointsAttr().Get()
    for idx in range(CONTAINER_X_SLOTS * CONTAINER_Y_SLOTS):
        name = f"FilledContent_{idx:02d}"
        prim = stage.DefinePrim(f"/FilledContentOnly/FilledContents/{name}", "Xform")
        xf = UsdGeom.Xformable(prim)
        tx, ty, tz = _slot_local_offset(idx)
        xf.AddTranslateOp().Set(Gf.Vec3d(float(tx), float(ty), float(tz)))
        xf.AddRotateXYZOp().Set(Gf.Vec3f(-90.0, -90.0, 0.0))

        mesh_prim = stage.DefinePrim(f"{prim.GetPath()}/mesh", "Mesh")
        mesh = UsdGeom.Mesh(mesh_prim)
        mesh.GetPointsAttr().Set(Vt.Vec3fArray(src_points))
        for attr_name in [
            "faceVertexCounts",
            "faceVertexIndices",
            "normals",
            "primvars:st",
            "primvars:st:indices",
        ]:
            src_attr = src_mesh.GetPrim().GetAttribute(attr_name)
            if src_attr.IsDefined():
                dst_attr = mesh_prim.GetAttribute(attr_name)
                if dst_attr.IsDefined():
                    dst_attr.Set(src_attr.Get())
        mesh_prim.CreateAttribute("primvars:displayColor", Sdf.ValueTypeNames.Color3fArray)
        mesh.GetDisplayColorAttr().Set([Gf.Vec3f(0.7, 0.45, 0.22)])

    stage.GetRootLayer().Save()
    return validate_output(output_usd, source_hash=source_hash)


def validate_output(output_usd: Path, *, source_hash: str) -> dict[str, object]:
    stage = Usd.Stage.Open(str(output_usd))
    default_prim = str(stage.GetDefaultPrim().GetPath()) if stage.GetDefaultPrim() else ""
    meters_per_unit = float(stage.GetMetadata("metersPerUnit"))
    mesh_count = 0
    filled_count = 0
    part_numeric_count = 0
    container_name_hits = 0
    rigid_count = 0
    collision_count = 0
    mass_count = 0
    physics_scene_count = 0
    positions: list[list[float]] = []
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            mesh_count += 1
        name = prim.GetName()
        if name.startswith("FilledContent_"):
            filled_count += 1
            xf = UsdGeom.Xformable(prim).GetOrderedXformOps()
            if xf:
                v = xf[0].Get()
                positions.append([float(v[0]), float(v[1]), float(v[2])])
        if name.startswith("Part_") and name[5:].isdigit():
            part_numeric_count += 1
        if "Container" in name:
            container_name_hits += 1
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    rigid_count += 1
            except Exception:
                pass
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            collision_count += 1
        if prim.HasAPI(UsdPhysics.MassAPI):
            mass_count += 1
        if prim.GetTypeName() == "PhysicsScene":
            physics_scene_count += 1
    expected_positions = [list(_slot_local_offset(i)) for i in range(20)]
    expected_positions_sorted = sorted(expected_positions)
    positions_sorted = sorted(positions)
    slot_positions_match = positions_sorted == expected_positions_sorted
    ok = (
        default_prim == "/FilledContentOnly"
        and meters_per_unit == 1.0
        and mesh_count == 20
        and filled_count == 20
        and part_numeric_count == 0
        and container_name_hits == 0
        and rigid_count == 0
        and collision_count == 0
        and mass_count == 0
        and physics_scene_count == 0
        and slot_positions_match
    )
    return {
        "ok": bool(ok),
        "source_sha256": source_hash,
        "output_sha256": _sha256_hex(output_usd),
        "default_prim": default_prim,
        "meters_per_unit": meters_per_unit,
        "mesh_count": mesh_count,
        "filled_count": filled_count,
        "part_numeric_count": part_numeric_count,
        "container_name_hits": container_name_hits,
        "rigid_count": rigid_count,
        "collision_count": collision_count,
        "mass_count": mass_count,
        "physics_scene_count": physics_scene_count,
        "slot_positions_match": slot_positions_match,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate container_full_content_visual.usd")
    parser.add_argument("--source", type=Path, help="source part_5000.usd path")
    parser.add_argument("--output", type=Path, help="output content-only usd path")
    parser.add_argument("--freeze-hash", action="store_true", help="enforce frozen source hash")
    parser.add_argument("--json", type=Path, help="write report json")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    assets = script_dir.parent / "source" / "GMRobot" / "GMRobot" / "assets"
    source = args.source or (assets / "part" / "part_5000.usd")
    output = args.output or (assets / "container_full_content_visual.usd")
    freeze = FROZEN_PART_SOURCE_SHA256 if args.freeze_hash else None

    try:
        report = generate(source, output, freeze_source_hash=freeze)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if bool(report.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
