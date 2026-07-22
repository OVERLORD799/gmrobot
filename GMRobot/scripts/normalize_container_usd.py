#!/usr/bin/env python3
"""Normalize container.usd: remove nested RigidBodyAPI, keep single kinematic body.

Reads GMRobot/assets/container.usd, writes container_fixed.usd (same directory).
- Removes RigidBodyAPI from /Root/Container/Ref (nested body → unpredictable physics)
- Keeps single RigidBodyAPI at /Root/Container
- Sets kinematic_enabled=True (static box — it should not move under gravity)
- No resetXformStack (not needed for a fixed kinematic body)

Frozen original: container.usd is never modified.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

FROZEN_CONTAINER_SHA256 = "ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9"


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    assets_dir = script_dir.parent / "source" / "GMRobot" / "GMRobot" / "assets"
    src = assets_dir / "container.usd"
    dst = assets_dir / "container_fixed.usd"

    if not src.is_file():
        print(f"FATAL: {src} not found", file=sys.stderr)
        return 1

    actual = hashlib.sha256(src.read_bytes()).hexdigest()
    if actual != FROZEN_CONTAINER_SHA256:
        print(f"FATAL: container.usd hash mismatch\nexpected: {FROZEN_CONTAINER_SHA256}\nactual:   {actual}", file=sys.stderr)
        return 1

    try:
        from pxr import Usd, UsdPhysics  # type: ignore
    except ImportError as exc:
        print(f"FATAL: pxr unavailable: {exc}", file=sys.stderr)
        return 1

    # Copy original to working file (PXR Export is safer for composition arcs)
    shutil.copy2(src, dst)

    stage = Usd.Stage.Open(str(dst), load=Usd.Stage.LoadAll)

    # Verify pre-normalization structure
    container_prim = stage.GetPrimAtPath("/Root/Container")
    ref_prim = stage.GetPrimAtPath("/Root/Container/Ref")
    if not container_prim or not ref_prim:
        print("FATAL: unexpected USD structure", file=sys.stderr)
        return 1

    # 1. Remove RigidBodyAPI from /Root/Container/Ref (the nested body)
    removed = ref_prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
    print(f"Removed RigidBodyAPI from /Root/Container/Ref: {removed}")

    # 2. Set /Root/Container to kinematic (static box)
    rigid = UsdPhysics.RigidBodyAPI(container_prim)
    if not rigid:
        # Apply RigidBodyAPI if missing
        rigid = UsdPhysics.RigidBodyAPI.Apply(container_prim)
        print("Applied RigidBodyAPI to /Root/Container (was missing)")
    rigid.GetKinematicEnabledAttr().Set(True)
    print("Set /Root/Container kinematic_enabled=True")

    # Keep collision on /Root/Container (needed for part placement physics)
    # Collision on /Root/Container/Ref/node_/mesh_ stays but is now child of a non-rigid prim (ok)

    stage.GetRootLayer().Save()

    # Verify post-normalization structure
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
    n_collision = sum(1 for p in stage2.Traverse() if p.HasAPI(UsdPhysics.CollisionAPI))

    print(f"Post-normalization: rigid_bodies={n_rigid}, meshes={n_mesh}, collision_apis={n_collision}")
    print(f"  RigidBodyAPI paths: {rigid_paths}")

    if n_rigid != 1:
        print(f"FATAL: expected 1 rigid body, got {n_rigid}", file=sys.stderr)
        return 1
    if rigid_paths != ["/Root/Container"]:
        print(f"FATAL: unexpected rigid body path(s): {rigid_paths}", file=sys.stderr)
        return 1

    dst_hash = hashlib.sha256(dst.read_bytes()).hexdigest()
    print(f"Output: {dst}")
    print(f"SHA256: {dst_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
