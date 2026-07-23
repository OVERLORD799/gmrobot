#!/usr/bin/env python3
"""Offline static audit for Func-C visual USD payload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _asset_root() -> Path:
    return Path(__file__).resolve().parent.parent / "source" / "GMRobot" / "GMRobot" / "assets"


def audit_visual_usd(visual_usd: Path) -> dict:
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(visual_usd))
    if stage is None:
        raise RuntimeError(f"failed to open stage: {visual_usd}")

    default_prim = stage.GetDefaultPrim()
    report: dict[str, object] = {
        "path": str(visual_usd),
        "default_prim": str(default_prim.GetPath()) if default_prim else None,
        "meters_per_unit": stage.GetMetadata("metersPerUnit"),
        "instance_or_instanceable_count": 0,
        "reference_payload_inherit_count": 0,
        "part_numeric_name_count": 0,
        "filled_content_count": 0,
    }

    for prim in stage.TraverseAll():
        if prim.IsInstance() or prim.IsInstanceable():
            report["instance_or_instanceable_count"] = int(report["instance_or_instanceable_count"]) + 1
        if prim.HasAuthoredReferences() or prim.HasAuthoredPayloads() or prim.HasAuthoredInherits():
            report["reference_payload_inherit_count"] = int(report["reference_payload_inherit_count"]) + 1
        name = prim.GetName()
        if name.startswith("Part_") and name[5:].isdigit():
            report["part_numeric_name_count"] = int(report["part_numeric_name_count"]) + 1
        if name.startswith("FilledContent_"):
            report["filled_content_count"] = int(report["filled_content_count"]) + 1

    container_prim = stage.GetPrimAtPath("/FullContainer/Container")
    if not container_prim:
        raise RuntimeError("missing /FullContainer/Container")
    xform = UsdGeom.Xformable(container_prim)
    ops = xform.GetOrderedXformOps()
    report["container_ops"] = [op.GetOpName() for op in ops]
    report["container_translate"] = [float(x) for x in ops[0].Get()] if len(ops) > 0 else None
    report["container_rotate_xyz"] = [float(x) for x in ops[1].Get()] if len(ops) > 1 else None

    report["gate_passed"] = (
        report["default_prim"] == "/FullContainer"
        and float(report["meters_per_unit"]) == 1.0
        and int(report["instance_or_instanceable_count"]) == 0
        and int(report["reference_payload_inherit_count"]) == 0
        and int(report["part_numeric_name_count"]) == 0
        and int(report["filled_content_count"]) == 30
        and report["container_ops"] == ["xformOp:translate", "xformOp:rotateXYZ"]
        and report["container_translate"] == [0.015, 0.0, 0.1]
        and report["container_rotate_xyz"] == [90.0, 0.0, 0.0]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Func-C visual USD statically")
    parser.add_argument("--visual-usd", type=Path, default=_asset_root() / "container_full_visual.usd")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--usda-out", type=Path, default=None)
    args = parser.parse_args()

    report = audit_visual_usd(args.visual_usd)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    if args.usda_out is not None:
        from pxr import Sdf

        args.usda_out.parent.mkdir(parents=True, exist_ok=True)
        layer = Sdf.Layer.FindOrOpen(str(args.visual_usd))
        if layer is None:
            raise RuntimeError(f"failed to open layer: {args.visual_usd}")
        layer.Export(str(args.usda_out))

    return 0 if bool(report["gate_passed"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
