#!/usr/bin/env python3
"""Normalize part_5000.usd: flatten RigidBodyAPI to root prim for clean spawn.

Reads GMRobot/assets/part/part_5000.usd, writes part_fixed.usd (same directory).
- Current structure: /Root → /Root/container_part_fixed_5000 (RigidBodyAPI, Collision)
  When spawned, Isaac may add ANOTHER RigidBodyAPI at the parent path, creating nested
  rigid bodies and causing modify_mass_properties to fail.
- Fixed structure: /Root (RigidBodyAPI + MassAPI) → mesh/collision children
- No RigidBodyAPI on children — the spawn prim IS the rigid body.

Frozen original: part_5000.usd is never modified.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

FROZEN_PART_SHA256 = "71fd48abb018275ae5bf9634216898136c028d0c883deb50caa7467481991aa6"


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    assets_dir = script_dir.parent / "source" / "GMRobot" / "GMRobot" / "assets"
    src = assets_dir / "part" / "part_5000.usd"
    dst = assets_dir / "part" / "part_fixed.usd"

    if not src.is_file():
        print(f"FATAL: {src} not found", file=sys.stderr)
        return 1

    actual = hashlib.sha256(src.read_bytes()).hexdigest()
    if actual != FROZEN_PART_SHA256:
        print(f"FATAL: part_5000.usd hash mismatch\nexpected: {FROZEN_PART_SHA256}\nactual:   {actual}", file=sys.stderr)
        return 1

    try:
        from pxr import Usd, UsdGeom, UsdPhysics, Sdf  # type: ignore
    except ImportError as exc:
        print(f"FATAL: pxr unavailable: {exc}", file=sys.stderr)
        return 1

    # Copy original to working file
    shutil.copy2(src, dst)

    stage = Usd.Stage.Open(str(dst), load=Usd.Stage.LoadAll)

    root_prim = stage.GetPrimAtPath("/Root")
    part_prim = stage.GetPrimAtPath("/Root/container_part_fixed_5000")

    if not root_prim or not part_prim:
        print("FATAL: unexpected USD structure", file=sys.stderr)
        return 1

    # 1. Remove RigidBodyAPI from the child prim
    removed = part_prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
    print(f"Removed RigidBodyAPI from /Root/container_part_fixed_5000: {removed}")

    # 2. Apply RigidBodyAPI to /Root (the spawn prim itself)
    root_rigid = UsdPhysics.RigidBodyAPI.Apply(root_prim)
    root_rigid.GetRigidBodyEnabledAttr().Set(True)
    print("Applied RigidBodyAPI to /Root")

    # 3. Apply MassAPI to /Root
    mass_api = UsdPhysics.MassAPI.Apply(root_prim)
    mass_api.GetMassAttr().Set(0.2)
    print("Applied MassAPI to /Root (mass=0.2)")

    # 4. Collision: the mesh collision stays on the child mesh prim.
    # /Root/container_part_fixed_5000/node_/mesh_ has CollisionAPI.
    # This is fine — collision on a child of the rigid body root is valid.
    # No CollisionAPI on /Root itself needed.

    stage.GetRootLayer().Save()

    # Verify post-normalization
    from pxr import UsdGeom
    stage2 = Usd.Stage.Open(str(dst))
    n_rigid = 0
    rigid_paths = []
    for prim in stage2.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            try:
                if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get():
                    n_rigid += 1
                    rigid_paths.append(str(prim.GetPath()))
            except Exception:
                pass
    n_mesh = sum(1 for p in stage2.Traverse() if p.IsA(UsdGeom.Mesh))
    n_mass = sum(1 for p in stage2.Traverse() if p.HasAPI(UsdPhysics.MassAPI))
    n_collision = sum(1 for p in stage2.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI))

    print(f"Post-normalization: rigid_bodies={n_rigid}, meshes={n_mesh}, mass_apis={n_mass}, collision_apis={n_collision}")
    print(f"  RigidBodyAPI paths: {rigid_paths}")

    if n_rigid != 1:
        print(f"FATAL: expected 1 rigid body, got {n_rigid}", file=sys.stderr)
        return 1
    if "/Root" not in rigid_paths:
        print(f"FATAL: /Root should be the rigid body prim", file=sys.stderr)
        return 1
    if n_mass == 0:
        print(f"FATAL: no MassAPI found after normalization", file=sys.stderr)
        return 1

    dst_hash = hashlib.sha256(dst.read_bytes()).hexdigest()
    print(f"Output: {dst}")
    print(f"SHA256: {dst_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
