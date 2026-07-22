#!/usr/bin/env python3
"""Deterministic generator: container_full.usd → container_full_visual.usd (M1E).

Reads the tracked ``container_full.usd`` (physics-enabled, cm-scale mesh vertices)
and produces a visual-only USD with:
  - defaultPrim = /FullContainer
  - relative paths, no /World root
  - zero RigidBody / Collision / Mass / Physx APIs
  - internal FilledContent_N naming (no Part_N to avoid scene regex conflicts)
  - correct metric sizes: Container ≈ 0.38×0.61 m, filled items ≈ 0.17 m
  - deterministic output (same input → structurally identical output)

Scale chain:
  The source ``container_full.usd`` stores mesh vertices in cm-space (span ~380).
  The generator scales them so the output mesh is in meter-space at metersPerUnit=1.0:
    Container mesh: source_span * scale  → ~0.38 m  (gate: 0.38±0.04 m)
    FilledContent:  source_span * scale  → ~0.17 m  (gate: 0.17±0.02 m)
  where ``scale`` is computed from the source Container mesh extent to hit 0.38 m.
  This is **equivalent** to applying xformOp:scale=0.01 on /FullContainer/Container
  given the vertex pre-scale chain, but avoids opaque 4×4 baked matrices.

Usage:
  python generate_container_full_visual_usd.py \
      [--source container_full.usd] \
      [--output container_full_visual.usd] \
      [--meters-per-unit 1.0]

If run without arguments, uses default paths relative to this script's location.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Frozen source fingerprint — guards against silent upstream changes
# ---------------------------------------------------------------------------
FROZEN_SOURCE_SHA256 = "ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0"


def _sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Grid layout: read from source physics file's Part transforms
# ---------------------------------------------------------------------------
def _read_part_transforms(source_stage) -> list[tuple]:
    """Extract (translate, rotateXYZ) for each Part_00..Part_29 from source."""
    from pxr import UsdGeom, Gf

    result = []
    for i in range(30):
        prim = source_stage.GetPrimAtPath(f"/World/Parts/Part_{i:02d}")
        if not prim:
            raise RuntimeError(f"Part_{i:02d} not found in source")
        xform = UsdGeom.Xformable(prim)
        xf = xform.GetLocalTransformation()
        # Extract translation from transform matrix
        tx = float(xf[3][0])
        ty = float(xf[3][1])
        tz = float(xf[3][2])
        result.append((tx, ty, tz))
    return result


# ---------------------------------------------------------------------------
# Validate output structure (gate 3)
# ---------------------------------------------------------------------------
def validate_output(stage_path: Path, expected_mesh_count: int = 31) -> dict:
    """Run structural gates and return a dict of measured values."""
    from pxr import Usd, UsdGeom, UsdPhysics

    report: dict = {
        "mesh_count": 0,
        "rigid_body_api_count": 0,
        "collision_api_count": 0,
        "mass_api_count": 0,
        "physics_scene_count": 0,
        "container_x_span_m": None,
        "container_z_span_m": None,
        "filled_item_span_m": None,
        "grid_x_span_m": None,
        "grid_y_span_m": None,
        "default_prim": None,
        "meters_per_unit": None,
        "has_world_prim": False,
        "part_n_pattern_found": False,
        "nested_rb_paths": [],
    }

    stage = Usd.Stage.Open(str(stage_path))

    report["default_prim"] = str(stage.GetDefaultPrim().GetPath()) if stage.GetDefaultPrim() else None
    report["meters_per_unit"] = stage.GetMetadata("metersPerUnit")
    report["has_world_prim"] = bool(stage.GetPrimAtPath("/World"))

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            report["mesh_count"] += 1
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            report["rigid_body_api_count"] += 1
            report["nested_rb_paths"].append(str(prim.GetPath()))
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            report["collision_api_count"] += 1
        if prim.HasAPI(UsdPhysics.MassAPI):
            report["mass_api_count"] += 1
        if prim.GetTypeName() == "PhysicsScene":
            report["physics_scene_count"] += 1

    # Check for Part_N naming pattern (should be absent)
    for prim in stage.Traverse():
        name = prim.GetName()
        if name.startswith("Part_") and name[5:].isdigit():
            report["part_n_pattern_found"] = True
            break

    # Measure Container mesh world extent
    cont_mesh = stage.GetPrimAtPath("/FullContainer/Container/mesh")
    if cont_mesh and cont_mesh.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(cont_mesh)
        pts = mesh.GetPointsAttr().Get()
        if pts is not None and len(pts) > 0:
            pts_np = np.array(pts, dtype=np.float64)
            # Apply Container xform to get world-space extent
            cont_xform = UsdGeom.Xformable(stage.GetPrimAtPath("/FullContainer/Container"))
            xf = cont_xform.GetLocalTransformation()
            # Transform min/max corners. Gf.Matrix4d uses row-major; transform as row vectors
            corners = np.array([
                [pts_np[:, 0].min(), pts_np[:, 1].min(), pts_np[:, 2].min(), 1.0],
                [pts_np[:, 0].max(), pts_np[:, 1].max(), pts_np[:, 2].max(), 1.0],
            ], dtype=np.float64)
            # Convert GfMatrix4d to numpy for multiplication
            xf_np = np.array(xf, dtype=np.float64).reshape(4, 4)
            tx = corners @ xf_np.T if xf_np.shape == (4, 4) else corners
            report["container_x_span_m"] = float(abs(tx[1, 0] - tx[0, 0]))
            report["container_z_span_m"] = float(abs(tx[1, 2] - tx[0, 2]))
            # Also compute raw (local) span for reference
            report["container_raw_x_span"] = float(pts_np[:, 0].max() - pts_np[:, 0].min())

    # Measure one FilledContent item extent
    fc_mesh = stage.GetPrimAtPath("/FullContainer/FilledContents/FilledContent_00/mesh")
    if fc_mesh and fc_mesh.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(fc_mesh)
        pts = mesh.GetPointsAttr().Get()
        if pts is not None and len(pts) > 0:
            pts_np = np.array(pts, dtype=np.float64)
            report["filled_item_span_m"] = float(pts_np[:, 0].max() - pts_np[:, 0].min())

    # Measure grid extent from FilledContent positions
    pos_x = []
    pos_y = []
    for i in range(30):
        fc_prim = stage.GetPrimAtPath(f"/FullContainer/FilledContents/FilledContent_{i:02d}")
        if fc_prim:
            xf = UsdGeom.Xformable(fc_prim).GetLocalTransformation()
            pos_x.append(float(xf[3][0]))
            pos_y.append(float(xf[3][1]))
    if pos_x:
        report["grid_x_span_m"] = float(max(pos_x) - min(pos_x))
        report["grid_y_span_m"] = float(max(pos_y) - min(pos_y))

    return report


# ---------------------------------------------------------------------------
# Structural fingerprint (stable across runs even if USDC binary differs)
# ---------------------------------------------------------------------------
def structural_fingerprint(stage_path: Path) -> str:
    """Return a hash of structure metadata, not binary blob."""
    from pxr import Usd, UsdGeom, UsdPhysics

    stage = Usd.Stage.Open(str(stage_path))
    parts: list[str] = []

    parts.append(f"defaultPrim={stage.GetDefaultPrim().GetPath()}")
    parts.append(f"mpu={stage.GetMetadata('metersPerUnit')}")

    prim_paths = sorted(str(p.GetPath()) for p in stage.Traverse())
    parts.append(f"prims={len(prim_paths)}")
    for pp in prim_paths:
        parts.append(f"  {pp}")

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            pts = UsdGeom.Mesh(prim).GetPointsAttr().Get()
            if pts is not None:
                pts_np = np.array(pts, dtype=np.float64)
                # Hash of extents, not every vertex
                ext = f"{pts_np.min():.6f}_{pts_np.max():.6f}"
                parts.append(f"  extent:{prim.GetPath()}={ext}")

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Xform):
            xf = UsdGeom.Xformable(prim)
            for op in xf.GetOrderedXformOps():
                parts.append(f"  xform:{prim.GetPath()}:{op.GetOpName()}={op.Get()}")

    combined = "\n".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate(
    source_path: Path,
    output_path: Path,
    meters_per_unit: float = 1.0,
    freeze_source_hash: Optional[str] = None,
) -> dict:
    """Generate container_full_visual.usd from container_full.usd.

    Returns a dict with generation metadata.
    """
    from pxr import Sdf, Usd, UsdGeom, UsdPhysics, Vt, Gf

    # --- Validate source ---------------------------------------------------
    if not source_path.is_file():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if freeze_source_hash:
        actual = _sha256_hex(source_path)
        if actual != freeze_source_hash:
            raise ValueError(
                f"Source hash mismatch.\n"
                f"  expected: {freeze_source_hash}\n"
                f"  actual:   {actual}"
            )

    source_stage = Usd.Stage.Open(str(source_path))

    # --- Locate source meshes ----------------------------------------------
    # Container mesh path in physics file
    container_mesh_path = "/World/Container/Ref/node_/mesh_"
    container_mesh_prim = source_stage.GetPrimAtPath(container_mesh_path)
    if not container_mesh_prim or not container_mesh_prim.IsA(UsdGeom.Mesh):
        raise RuntimeError(f"Container mesh not found at {container_mesh_path}")
    container_mesh = UsdGeom.Mesh(container_mesh_prim)

    # Find all 30 part meshes
    part_meshes: list[Tuple[str, UsdGeom.Mesh]] = []
    for prim in source_stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            pp = str(prim.GetPath())
            if "/Parts/Part_" in pp:
                part_meshes.append((pp, UsdGeom.Mesh(prim)))

    if len(part_meshes) != 30:
        raise RuntimeError(f"Expected 30 part meshes, found {len(part_meshes)}")

    # --- Compute scale factor ----------------------------------------------
    # Container raw mesh extent (cm-space)
    cont_pts = np.array(container_mesh.GetPointsAttr().Get(), dtype=np.float64)
    cont_raw_x = float(cont_pts[:, 0].max() - cont_pts[:, 0].min())

    # Target: ~0.38 m world extent (mesh * scale * mpu)
    target_container_x_m = 0.38
    vertex_scale = target_container_x_m / cont_raw_x

    # Verify with parts: target ~0.17 m
    first_part_pts = np.array(part_meshes[0][1].GetPointsAttr().Get(), dtype=np.float64)
    part_raw_x = float(first_part_pts[:, 0].max() - first_part_pts[:, 0].min())
    predicted_part_m = part_raw_x * vertex_scale

    meta = {
        "source": str(source_path),
        "source_sha256": _sha256_hex(source_path),
        "container_raw_x_span": cont_raw_x,
        "part_raw_x_span": part_raw_x,
        "vertex_scale": float(vertex_scale),
        "predicted_container_m": float(cont_raw_x * vertex_scale),
        "predicted_part_m": float(predicted_part_m),
        "target_container_x_m": target_container_x_m,
        "meters_per_unit": meters_per_unit,
    }

    # --- Create output stage -----------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing file if present
    if output_path.exists():
        output_path.unlink()

    out_stage = Usd.Stage.CreateNew(str(output_path))
    UsdGeom.SetStageMetersPerUnit(out_stage, meters_per_unit)
    out_stage.SetMetadata("metersPerUnit", meters_per_unit)

    # Root prim
    root_path = Sdf.Path("/FullContainer")
    root_prim = out_stage.DefinePrim(root_path, "Xform")
    out_stage.SetDefaultPrim(root_prim)

    # --- Container prim ----------------------------------------------------
    container_prim = out_stage.DefinePrim("/FullContainer/Container", "Xform")
    container_xform = UsdGeom.Xformable(container_prim)

    # Apply the same transform as the source physics container
    # (rotate 90° around X to align door to +Z, translate)
    # But NO additional scale — the vertex data is already at meter scale
    container_xform.AddTranslateOp().Set(Gf.Vec3d(0.015, 0.0, 0.1))
    container_xform.AddRotateXYZOp().Set(Gf.Vec3f(90.0, 0.0, 0.0))

    # Container mesh with scaled vertices
    cont_mesh_prim = out_stage.DefinePrim("/FullContainer/Container/mesh", "Mesh")
    cont_mesh = UsdGeom.Mesh(cont_mesh_prim)

    # Scale vertices
    scaled_cont_pts = Vt.Vec3fArray([Gf.Vec3f(*(p * vertex_scale)) for p in cont_pts])
    cont_mesh.GetPointsAttr().Set(scaled_cont_pts)

    # Copy topology from source
    for attr_name in ["faceVertexCounts", "faceVertexIndices", "normals",
                       "primvars:st", "primvars:st:indices"]:
        src_attr = container_mesh.GetPrim().GetAttribute(attr_name)
        if src_attr.IsDefined():
            dst_attr = cont_mesh_prim.GetAttribute(attr_name)
            if dst_attr.IsDefined():
                dst_attr.Set(src_attr.Get())

    # Explicit displayColor — source has None displayColor and OmniPBR materials
    # that we do not copy. Without a color the mesh may be invisible.
    cont_mesh_prim.CreateAttribute("primvars:displayColor", Sdf.ValueTypeNames.Color3fArray)
    cont_mesh.GetDisplayColorAttr().Set([Gf.Vec3f(0.2, 0.6, 0.28)])  # container green

    # --- FilledContents prim -----------------------------------------------
    fc_root = out_stage.DefinePrim("/FullContainer/FilledContents", "Xform")

    # Read actual grid positions from source physics file
    src_positions = _read_part_transforms(source_stage)

    for idx, (path_str, src_mesh) in enumerate(part_meshes):
        fc_name = f"FilledContent_{idx:02d}"
        fc_prim = out_stage.DefinePrim(f"/FullContainer/FilledContents/{fc_name}", "Xform")
        fc_xform = UsdGeom.Xformable(fc_prim)

        # Use the actual source part position
        sx, sy, sz = src_positions[idx]
        fc_xform.AddTranslateOp().Set(Gf.Vec3d(sx, sy, sz))
        fc_xform.AddRotateXYZOp().Set(Gf.Vec3f(-90.0, -90.0, 0.0))

        # Mesh
        mesh_prim_path = f"/FullContainer/FilledContents/{fc_name}/mesh"
        mesh_prim = out_stage.DefinePrim(mesh_prim_path, "Mesh")
        dst_mesh = UsdGeom.Mesh(mesh_prim)

        src_pts = np.array(src_mesh.GetPointsAttr().Get(), dtype=np.float64)
        scaled_pts = Vt.Vec3fArray([Gf.Vec3f(*(p * vertex_scale)) for p in src_pts])
        dst_mesh.GetPointsAttr().Set(scaled_pts)

        # Copy topology
        for attr_name in ["faceVertexCounts", "faceVertexIndices", "normals",
                           "primvars:st", "primvars:st:indices"]:
            src_attr = src_mesh.GetPrim().GetAttribute(attr_name)
            if src_attr.IsDefined():
                dst_attr = mesh_prim.GetAttribute(attr_name)
                if dst_attr.IsDefined():
                    dst_attr.Set(src_attr.Get())

        # Explicit displayColor — source has None, materials not copied
        mesh_prim.CreateAttribute("primvars:displayColor", Sdf.ValueTypeNames.Color3fArray)
        dst_mesh.GetDisplayColorAttr().Set([Gf.Vec3f(0.7, 0.45, 0.22)])  # visible warm tone

    # --- Save --------------------------------------------------------------
    out_stage.GetRootLayer().Save()

    # --- Post-generation structural validation -----------------------------
    report = validate_output(output_path)
    report.update(meta)
    report["structural_fingerprint"] = structural_fingerprint(output_path)

    return report


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------
def run_gates(report: dict) -> Tuple[bool, list[str]]:
    """Return (passed, list_of_failures)."""
    failures: list[str] = []

    # Gate 3a: 31 meshes
    if report.get("mesh_count") != 31:
        failures.append(f"mesh_count={report.get('mesh_count')}, expected 31")

    # Gate 3b: 0 physics APIs
    for key in ("rigid_body_api_count", "collision_api_count", "mass_api_count"):
        if report.get(key, 0) != 0:
            failures.append(f"{key}={report.get(key)}, expected 0")

    # Gate 3b: no PhysicsScene
    if report.get("physics_scene_count", 0) != 0:
        failures.append(f"physics_scene_count={report.get('physics_scene_count')}, expected 0")

    # Gate 3c: Container world extent ~0.38×0.61 m (±10% tolerance)
    cx = report.get("container_x_span_m")
    if cx is not None:
        if not (0.34 < cx < 0.42):
            failures.append(f"container_x_span_m={cx:.4f}, expected 0.38±0.04")
    else:
        failures.append("container_x_span_m not measured")

    # Gate 3d: Filled item ~0.17 m
    fi = report.get("filled_item_span_m")
    if fi is not None:
        if not (0.15 < fi < 0.19):
            failures.append(f"filled_item_span_m={fi:.4f}, expected 0.17±0.02")
    else:
        failures.append("filled_item_span_m not measured")

    # Gate 3e: grid ~0.275×0.44 m
    gx = report.get("grid_x_span_m")
    gy = report.get("grid_y_span_m")
    if gx is not None and gy is not None:
        if not (0.24 < gx < 0.31):
            failures.append(f"grid_x_span_m={gx:.4f}, expected 0.275±0.035")
        if not (0.39 < gy < 0.49):
            failures.append(f"grid_y_span_m={gy:.4f}, expected 0.44±0.05")
    else:
        failures.append("grid spans not measured")

    # Gate 3f: defaultPrim and naming
    if report.get("default_prim") != "/FullContainer":
        failures.append(f"defaultPrim={report.get('default_prim')}, expected /FullContainer")

    if report.get("has_world_prim"):
        failures.append("has /World prim (should not)")

    if report.get("part_n_pattern_found"):
        failures.append("Part_N naming pattern found (should use FilledContent_N)")

    # Gate 3g: no nested rigid body paths (should be 0)
    if report.get("nested_rb_paths"):
        failures.append(f"nested_rb_paths={report['nested_rb_paths']}")

    return (len(failures) == 0, failures)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Generate container_full_visual.usd")
    parser.add_argument("--source", type=Path, help="Path to container_full.usd")
    parser.add_argument("--output", type=Path, help="Path for output container_full_visual.usd")
    parser.add_argument("--meters-per-unit", type=float, default=1.0)
    parser.add_argument("--freeze-hash", action="store_true",
                        help="Freeze source hash check (skip if source unknown)")
    parser.add_argument("--json", type=Path, help="Write generation report as JSON")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    # Resolve default paths
    script_dir = Path(__file__).resolve().parent
    assets_dir = script_dir.parent / "source" / "GMRobot" / "GMRobot" / "assets"

    source_path = args.source or (assets_dir / "container_full.usd")
    output_path = args.output or (assets_dir / "container_full_visual.usd")

    freeze_hash = FROZEN_SOURCE_SHA256 if args.freeze_hash else None

    try:
        report = generate(
            source_path=source_path,
            output_path=output_path,
            meters_per_unit=args.meters_per_unit,
            freeze_source_hash=freeze_hash,
        )
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    passed, failures = run_gates(report)

    if not args.quiet:
        print(f"Source: {report['source']}")
        print(f"Source SHA256: {report['source_sha256']}")
        print(f"Output: {output_path}")
        print(f"Output size: {output_path.stat().st_size / 1024**2:.1f} MB")
        print(f"\n--- Scale ---")
        print(f"  Container raw X span: {report['container_raw_x_span']:.3f} units")
        print(f"  Part raw X span:      {report['part_raw_x_span']:.3f} units")
        print(f"  Vertex scale:         {report['vertex_scale']:.6f}")
        print(f"  Predicted container:  {report['predicted_container_m']:.4f} m")
        print(f"  Predicted part:       {report['predicted_part_m']:.4f} m")
        print(f"\n--- Structural Gates ---")
        print(f"  Meshes:               {report['mesh_count']}")
        print(f"  RigidBody APIs:       {report['rigid_body_api_count']}")
        print(f"  Collision APIs:       {report['collision_api_count']}")
        print(f"  Mass APIs:            {report['mass_api_count']}")
        print(f"  Container X span:     {report.get('container_x_span_m', 'N/A'):.4f} m" if isinstance(report.get('container_x_span_m'), float) else f"  Container X span:     {report.get('container_x_span_m', 'N/A')}")
        print(f"  Filled item span:     {report.get('filled_item_span_m', 'N/A'):.4f} m" if isinstance(report.get('filled_item_span_m'), float) else f"  Filled item span:     {report.get('filled_item_span_m', 'N/A')}")
        print(f"  Grid X span:          {report.get('grid_x_span_m', 'N/A'):.4f} m" if isinstance(report.get('grid_x_span_m'), float) else f"  Grid X span:          {report.get('grid_x_span_m', 'N/A')}")
        print(f"  Grid Y span:          {report.get('grid_y_span_m', 'N/A'):.4f} m" if isinstance(report.get('grid_y_span_m'), float) else f"  Grid Y span:          {report.get('grid_y_span_m', 'N/A')}")
        print(f"  defaultPrim:          {report['default_prim']}")
        print(f"  metersPerUnit:        {report['meters_per_unit']}")
        print(f"  Structural fingerprint:{report.get('structural_fingerprint', 'N/A')[:16]}...")
        print(f"\n  GATE VERDICT: {'PASS' if passed else 'FAIL'}")
        if failures:
            for f in failures:
                print(f"    - {f}")

    if args.json:
        report["gate_passed"] = passed
        report["gate_failures"] = failures
        args.json.write_text(json.dumps(report, indent=2, default=str))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
