#!/usr/bin/env python3
"""Offline and end-to-end tests for pip_prebundle NumPy-only quarantine scope."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pip_prebundle_numpy_dedup import discover_all_targets, quarantine_targets  # noqa: E402


def _make_fixture(tmp_root: Path, numpy_version: str) -> tuple[Path, Path]:
    exts = tmp_root / "extscache"
    pip_root = exts / "omni.kit.pip_archive-abc.lx64.cp311" / "pip_prebundle"
    pip_root.mkdir(parents=True, exist_ok=True)

    numpy_dir = pip_root / "numpy"
    (numpy_dir / "core").mkdir(parents=True, exist_ok=True)
    (numpy_dir / "__init__.py").write_text("# fake numpy\n", encoding="utf-8")
    (numpy_dir / "core" / "_multiarray_umath.py").write_text("x=1\n", encoding="utf-8")

    numpy_libs = pip_root / "numpy.libs"
    numpy_libs.mkdir(parents=True, exist_ok=True)
    (numpy_libs / "libopenblas64_.so").write_text("fake-so\n", encoding="utf-8")
    (numpy_libs / "libblas_alias.so").symlink_to("libopenblas64_.so")

    dist_info = pip_root / f"numpy-{numpy_version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(f"Name: numpy\nVersion: {numpy_version}\n", encoding="utf-8")
    (dist_info / "top_level.txt").symlink_to("../numpy/__init__.py")

    # Non-NumPy sentinels must remain untouched.
    (pip_root / "pydantic").mkdir()
    (pip_root / "pydantic" / "__init__.py").write_text("# sentinel\n", encoding="utf-8")
    (pip_root / "typing_extensions-4.0.0.dist-info").mkdir()
    (pip_root / "typing_extensions-4.0.0.dist-info" / "METADATA").write_text(
        "Name: typing-extensions\n",
        encoding="utf-8",
    )
    return exts, pip_root


def test_only_numpy_family_is_targeted_and_quarantined() -> None:
    with tempfile.TemporaryDirectory() as td:
        exts, pip_root = _make_fixture(Path(td), "1.26.0")
        targets = discover_all_targets(exts)
        rels = sorted(t.rel for t in targets)
        assert rels == ["numpy", "numpy-1.26.0.dist-info", "numpy.libs"], rels

        qroot = exts / "quarantine"
        moved = quarantine_targets(targets, qroot)
        assert len(moved) == 3
        for item in moved:
            assert item["kind"] in {"numpy_pkg", "numpy_libs", "numpy_dist_info"}
            assert item["path_kind"] == "directory"
            assert int(item["size_bytes"]) >= 0
            assert int(item["file_count"]) >= 1
            assert len(str(item["digest"])) == 64
        assert not (pip_root / "numpy").exists()
        assert not (pip_root / "numpy.libs").exists()
        assert not (pip_root / "numpy-1.26.0.dist-info").exists()
        assert (pip_root / "pydantic").is_dir()
        assert (pip_root / "typing_extensions-4.0.0.dist-info").is_dir()


def test_end_to_end_script_fixture() -> None:
    for numpy_version in ("1.26.0", "9.9.9"):
        _run_end_to_end_variant(numpy_version)


def _run_end_to_end_variant(numpy_version: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        exts, pip_root = _make_fixture(root, numpy_version)
        report = root / "report.json"
        inv = root / "inventory.txt"
        hashes = root / "hashes.txt"
        quarantine = root / "quarantine"

        import numpy as np

        kit_site_root = Path(np.__file__).resolve().parent.parent
        script = ROOT / "scripts" / "pip_prebundle_numpy_dedup.py"
        cmd = [
            sys.executable,
            str(script),
            "--extscache-root",
            str(exts),
            "--quarantine-root",
            str(quarantine),
            "--report-json",
            str(report),
            "--inventory-txt",
            str(inv),
            "--hashes-txt",
            str(hashes),
            "--kit-site-root",
            str(kit_site_root),
        ]
        subprocess.run(cmd, check=True)

        sentinel = pip_root / "typing_extensions" / "__init__.py"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("# sentinel\n", encoding="utf-8")
        assert_script = ROOT / "scripts" / "assert_numpy_dedup_report.py"
        assert_cmd = [
            sys.executable,
            str(assert_script),
            "--report-json",
            str(report),
            "--kit-site-root",
            str(kit_site_root),
            "--require-sentinel",
            str(sentinel),
        ]
        res = subprocess.run(assert_cmd, check=True, capture_output=True, text=True)
        assert res.stdout.strip() == f"numpy-{numpy_version}.dist-info"

        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["inventory_count"] == 3
        assert payload["moved_count"] == 3
        assert payload["remaining_importable_numpy_prebundle"] == []
        moved_kinds = {x["kind"] for x in payload["moved"]}
        assert moved_kinds == {"numpy_pkg", "numpy_libs", "numpy_dist_info"}
        moved_sources = {Path(x["source"]).name for x in payload["moved"]}
        assert moved_sources == {"numpy", "numpy.libs", f"numpy-{numpy_version}.dist-info"}
        assert all(len(x["digest"]) == 64 for x in payload["moved"])

        assert (pip_root / "pydantic").is_dir()
        assert (pip_root / "typing_extensions-4.0.0.dist-info").is_dir()
        inv_text = inv.read_text(encoding="utf-8")
        assert "numpy|" in inv_text
        assert "numpy.libs|" in inv_text
        assert f"numpy-{numpy_version}.dist-info|" in inv_text


def test_dockerfile_assertion_command_matches_script_contract() -> None:
    dockerfile = ROOT / "docker" / "Dockerfile.e01-dyn-b-m1u23"
    text = dockerfile.read_text(encoding="utf-8")
    run_line = next(
        (ln for ln in text.splitlines() if ln.startswith('RUN ["/bin/bash","-lc","')),
        "",
    )
    assert run_line, "missing RUN bash -lc command"
    shell_cmd = run_line.split('RUN ["/bin/bash","-lc","', 1)[1].rsplit('"]', 1)[0]
    shell_cmd = shell_cmd.replace('\\"', '"').replace("\\\\n", "\\n")
    assert "assert_numpy_dedup_report.py --report-json" in shell_cmd
    assert "--kit-site-root /isaac-sim/kit/python/lib/python3.11/site-packages" in shell_cmd
    assert "--require-sentinel \"${PIP_ROOT}/typing_extensions/__init__.py\"" in shell_cmd

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        exts, pip_root = _make_fixture(root, "7.7.7")
        report = root / "report.json"
        inv = root / "inventory.txt"
        hashes = root / "hashes.txt"
        quarantine = root / "quarantine"
        sentinel = pip_root / "typing_extensions" / "__init__.py"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("# sentinel\n", encoding="utf-8")

        import numpy as np

        kit_site_root = Path(np.__file__).resolve().parent.parent
        dedup_script = ROOT / "scripts" / "pip_prebundle_numpy_dedup.py"
        subprocess.run(
            [
                sys.executable,
                str(dedup_script),
                "--extscache-root",
                str(exts),
                "--quarantine-root",
                str(quarantine),
                "--report-json",
                str(report),
                "--inventory-txt",
                str(inv),
                "--hashes-txt",
                str(hashes),
                "--kit-site-root",
                str(kit_site_root),
            ],
            check=True,
        )
        assert_script = ROOT / "scripts" / "assert_numpy_dedup_report.py"
        out = subprocess.run(
            [
                sys.executable,
                str(assert_script),
                "--report-json",
                str(report),
                "--kit-site-root",
                str(kit_site_root),
                "--require-sentinel",
                str(sentinel),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert out.stdout.strip() == "numpy-7.7.7.dist-info"


def main() -> None:
    test_only_numpy_family_is_targeted_and_quarantined()
    test_end_to_end_script_fixture()
    test_dockerfile_assertion_command_matches_script_contract()
    print("PASS test_pip_prebundle_numpy_dedup_unit")


if __name__ == "__main__":
    main()
