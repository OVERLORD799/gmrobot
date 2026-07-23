#!/usr/bin/env python3
"""Unit tests for generate_container_full_visual_usd.py (M1E).

Offline tests — no VLM, no smoke, no Docker.
Covers: generator strategy, structural gates, naming rules, hash stability.

Default: off (pytest SKIP unless GMROBOT_TEST_M1E_GENERATOR=1).
Set GMROBOT_TEST_M1E_GENERATOR=1 to run the full generation tests (requires pxr + source asset).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GENERATOR = Path(__file__).resolve().parent / "generate_container_full_visual_usd.py"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "source" / "GMRobot" / "GMRobot" / "assets"
SOURCE_USD = ASSETS_DIR / "container_full.usd"

NEED_GENERATOR_TESTS = os.environ.get("GMROBOT_TEST_M1E_GENERATOR", "0") == "1"


# ---------------------------------------------------------------------------
# Static tests (always run)
# ---------------------------------------------------------------------------
class TestGeneratorStatic:
    """Tests that don't require pxr or the source asset."""

    def test_script_exists(self):
        assert GENERATOR.is_file(), f"Generator not found at {GENERATOR}"

    def test_script_is_python(self):
        content = GENERATOR.read_text()
        assert "def generate(" in content, "Missing generate() function"
        assert "def validate_output(" in content, "Missing validate_output()"
        assert "def structural_fingerprint(" in content, "Missing structural_fingerprint()"
        assert "FROZEN_SOURCE_SHA256" in content, "Missing frozen source hash"

    def test_script_hash_constant_is_valid(self):
        content = GENERATOR.read_text()
        # Extract the frozen hash
        for line in content.splitlines():
            if "FROZEN_SOURCE_SHA256" in line and "=" in line and '"' in line:
                hash_val = line.split('"')[1]
                assert len(hash_val) == 64, f"Frozen hash length {len(hash_val)} != 64"
                assert all(c in "0123456789abcdef" for c in hash_val), "Frozen hash not hex"
                break
        else:
            pytest.fail("Could not find FROZEN_SOURCE_SHA256 constant")

    def test_naming_convention(self):
        """Verify FilledContent naming, not Part_ naming."""
        content = GENERATOR.read_text()
        assert "FilledContent_" in content, "Must use FilledContent_N naming"
        # Ensure no Part_N references in output prim paths
        assert '"/FullContainer/FilledContents/Part_' not in content, \
            "Must not use Part_N in output prim paths"

    def test_no_world_root(self):
        content = GENERATOR.read_text()
        assert '"/FullContainer"' in content or "'/FullContainer'" in content, \
            "defaultPrim should be /FullContainer"
        # Should not create /World
        assert 'DefinePrim("/World"' not in content or '"/World"' not in content, \
            "Should not create /World root"

    def test_physics_api_exclusion(self):
        content = GENERATOR.read_text()
        # Should NOT Apply (create) physics APIs on output
        assert "RigidBodyAPI.Apply" not in content, "Should not apply RigidBodyAPI"
        assert "CollisionAPI.Apply" not in content, "Should not apply CollisionAPI"
        assert "MassAPI.Apply" not in content, "Should not apply MassAPI"
        # Naming check: output prims must be FilledContent, not Part_
        assert '"/FullContainer/FilledContents/Part_' not in content, \
            "Must not create Part_N under FilledContents"

    def test_gate_thresholds(self):
        """Verify gate threshold constants are present and reasonable."""
        content = GENERATOR.read_text()
        # These must be in the code for the structural gates
        assert "0.34" in content or "0.38" in content, "Container X span gate missing"
        assert "0.15" in content or "0.17" in content, "Filled item span gate missing"
        assert "0.24" in content or "0.275" in content, "Grid span gate missing"

    def test_meters_per_unit_in_output(self):
        content = GENERATOR.read_text()
        assert "metersPerUnit" in content or "meters_per_unit" in content, \
            "Must set metersPerUnit metadata"


# ---------------------------------------------------------------------------
# Full generation tests (require pxr + source asset)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not NEED_GENERATOR_TESTS, reason="Set GMROBOT_TEST_M1E_GENERATOR=1")
class TestGeneratorFull:
    """Full generation tests requiring pxr and the source asset."""

    def test_source_asset_exists(self):
        assert SOURCE_USD.is_file(), f"Source asset not found: {SOURCE_USD}"

    def test_source_hash_matches_frozen(self):
        content = GENERATOR.read_text()
        frozen_hash = None
        for line in content.splitlines():
            if "FROZEN_SOURCE_SHA256" in line and "=" in line and '"' in line:
                frozen_hash = line.split('"')[1]
                break
        actual = hashlib.sha256(SOURCE_USD.read_bytes()).hexdigest()
        assert actual == frozen_hash, f"Source hash mismatch: {actual} != {frozen_hash}"

    def test_freeze_hash_fail_closed_on_source_change(self):
        """Freeze-hash gate must fail closed when source bytes differ."""
        with tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as src_tmp, \
             tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as out_tmp:
            src_path, out_path = Path(src_tmp.name), Path(out_tmp.name)

        try:
            src_path.write_bytes(SOURCE_USD.read_bytes() + b"\n# provenance tamper sentinel\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--source",
                    str(src_path),
                    "--output",
                    str(out_path),
                    "--freeze-hash",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            assert result.returncode != 0, "freeze-hash gate must reject tampered source"
            combined = f"{result.stdout}\n{result.stderr}"
            assert "Source hash mismatch" in combined, combined
        finally:
            src_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)

    def test_generation_creates_output(self):
        with tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "--output", str(tmp_path),
                 "--quiet", "--freeze-hash"],
                capture_output=True, text=True, timeout=300,
            )
            assert result.returncode == 0, f"Generator failed: {result.stderr}"
            assert tmp_path.is_file(), "Output file not created"
            assert tmp_path.stat().st_size > 1024, "Output file too small"
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_structure_gates(self):
        with tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "--output", str(tmp_path),
                 "--quiet", "--freeze-hash"],
                capture_output=True, text=True, timeout=300,
            )
            assert result.returncode == 0, f"Generator failed: {result.stderr}"

            # Verify with pxr
            from pxr import Usd, UsdGeom, UsdPhysics

            stage = Usd.Stage.Open(str(tmp_path))

            # 31 meshes
            n_mesh = sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))
            assert n_mesh == 31, f"Expected 31 meshes, got {n_mesh}"

            # Zero physics APIs
            for api_cls, name in [(UsdPhysics.RigidBodyAPI, "RigidBody"),
                                   (UsdPhysics.CollisionAPI, "Collision"),
                                   (UsdPhysics.MassAPI, "Mass")]:
                count = sum(1 for p in stage.Traverse() if p.HasAPI(api_cls))
                assert count == 0, f"Expected 0 {name} APIs, got {count}"

            # Default prim
            assert str(stage.GetDefaultPrim().GetPath()) == "/FullContainer", \
                f"Wrong defaultPrim: {stage.GetDefaultPrim().GetPath()}"

            # No /World
            assert not stage.GetPrimAtPath("/World"), "Has /World prim"

            # Naming: FilledContent not Part
            for prim in stage.Traverse():
                name = prim.GetName()
                assert not (name.startswith("Part_") and name[5:].isdigit()), \
                    f"Part_N naming found: {prim.GetPath()}"

            # Container extent
            from pxr import UsdGeom
            cont_mesh = stage.GetPrimAtPath("/FullContainer/Container/mesh")
            assert cont_mesh and cont_mesh.IsA(UsdGeom.Mesh), "Container mesh not found"
            pts = UsdGeom.Mesh(cont_mesh).GetPointsAttr().Get()
            import numpy as np
            pts_np = np.array(pts)
            x_span = float(pts_np[:, 0].max() - pts_np[:, 0].min())
            assert 0.34 < x_span < 0.42, f"Container X span {x_span:.4f} not in [0.34, 0.42]"

            # FilledContent item extent
            fc = stage.GetPrimAtPath("/FullContainer/FilledContents/FilledContent_00/mesh")
            assert fc and fc.IsA(UsdGeom.Mesh), "FilledContent_00 mesh not found"
            fc_pts = np.array(UsdGeom.Mesh(fc).GetPointsAttr().Get())
            fc_span = float(fc_pts[:, 0].max() - fc_pts[:, 0].min())
            assert 0.15 < fc_span < 0.19, f"FilledContent span {fc_span:.4f} not in [0.15, 0.19]"

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_deterministic_output(self):
        with tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as t1, \
             tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as t2:
            p1, p2 = Path(t1.name), Path(t2.name)

        try:
            for p in [p1, p2]:
                subprocess.run(
                    [sys.executable, str(GENERATOR), "--output", str(p),
                     "--quiet", "--freeze-hash"],
                    check=True, timeout=300,
                )
            h1 = hashlib.sha256(p1.read_bytes()).hexdigest()
            h2 = hashlib.sha256(p2.read_bytes()).hexdigest()
            assert h1 == h2, f"Binary hash differs: {h1} != {h2}"
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)

    def test_structural_fingerprint_stable(self):
        """Structural fingerprint must be stable across runs."""
        with tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as t1, \
             tempfile.NamedTemporaryFile(suffix=".usd", delete=False) as t2:
            p1, p2 = Path(t1.name), Path(t2.name)

        try:
            for p in [p1, p2]:
                subprocess.run(
                    [sys.executable, str(GENERATOR), "--output", str(p),
                     "--quiet", "--freeze-hash"],
                    check=True, timeout=300,
                )

            def fp(path):
                from pxr import Usd, UsdGeom
                import numpy as np
                stage = Usd.Stage.Open(str(path))
                parts = [f"dp={stage.GetDefaultPrim().GetPath()}",
                         f"mpu={stage.GetMetadata('metersPerUnit')}"]
                for prim in sorted(stage.Traverse(), key=lambda p: str(p.GetPath())):
                    if prim.IsA(UsdGeom.Mesh):
                        pts = UsdGeom.Mesh(prim).GetPointsAttr().Get()
                        if pts is not None:
                            pn = np.array(pts, dtype=np.float64)
                            parts.append(f"{prim.GetPath()}:{pn.min():.4f}_{pn.max():.4f}")
                return hashlib.sha256("\n".join(parts).encode()).hexdigest()

            assert fp(p1) == fp(p2), "Structural fingerprint not stable"
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Path integrity tests
# ---------------------------------------------------------------------------
class TestPathIntegrity:
    """Verify no forbidden paths or patterns."""

    def test_no_trailing_whitespace(self):
        content = GENERATOR.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            assert not line.endswith(" ") and not line.endswith("\t"), \
                f"Line {i} has trailing whitespace"

    def test_tab_characters(self):
        content = GENERATOR.read_text()
        assert "\t" not in content, "Tab characters found"
