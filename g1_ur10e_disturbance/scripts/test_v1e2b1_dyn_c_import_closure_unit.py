#!/usr/bin/env python3
"""Unit tests for V1-E2B.1 Dyn-C import-closure prebuild checker."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v1e2b1_dyn_c_import_closure_prebuild import verify_dyn_c_import_closure  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_fixture(td: str) -> tuple[Path, Path]:
    project = Path(td) / "proj"
    _write(
        project / "scripts" / "run_phase3.py",
        "from dyn_b_per_step_audit_writer import init_dyn_b_per_step_audit_writer\n"
        "from helper_mod import build_value\n"
        "print(init_dyn_b_per_step_audit_writer, build_value)\n",
    )
    _write(
        project / "scripts" / "dyn_b_per_step_audit_writer.py",
        "from helper_mod import build_value\n"
        "def init_dyn_b_per_step_audit_writer():\n"
        "    return build_value()\n",
    )
    _write(project / "scripts" / "helper_mod.py", "def build_value():\n    return 1\n")
    dockerfile = project / "docker" / "Dockerfile.test"
    _write(
        dockerfile,
        "FROM base\n"
        "WORKDIR /opt/projects/g1_ur10e_disturbance\n"
        "COPY scripts/run_phase3.py /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py\n"
        "COPY scripts/dyn_b_per_step_audit_writer.py /opt/projects/g1_ur10e_disturbance/scripts/dyn_b_per_step_audit_writer.py\n"
        "COPY scripts/helper_mod.py /opt/projects/g1_ur10e_disturbance/scripts/helper_mod.py\n",
    )
    return project, dockerfile


def test_required_module_removed_should_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        project, dockerfile = _make_fixture(td)
        dockerfile.write_text(
            "FROM base\n"
            "WORKDIR /opt/projects/g1_ur10e_disturbance\n"
            "COPY scripts/run_phase3.py /opt/projects/g1_ur10e_disturbance/scripts/run_phase3.py\n"
            "COPY scripts/dyn_b_per_step_audit_writer.py /opt/projects/g1_ur10e_disturbance/scripts/dyn_b_per_step_audit_writer.py\n",
            encoding="utf-8",
        )
        report = verify_dyn_c_import_closure(
            project_root=project,
            dockerfile_path=dockerfile,
            entrypoints=["scripts/run_phase3.py"],
        )
        assert report["ok"] is False
        assert "scripts/helper_mod.py" in report["missing_required_files"]


def test_target_path_is_importable_and_contains_dyn_b_writer() -> None:
    with tempfile.TemporaryDirectory() as td:
        project, dockerfile = _make_fixture(td)
        report = verify_dyn_c_import_closure(
            project_root=project,
            dockerfile_path=dockerfile,
            entrypoints=["scripts/run_phase3.py"],
        )
        assert report["ok"] is True
        assert report["contains_dyn_b_per_step_audit_writer"] is True
        assert report["missing_required_files"] == []
        assert report["misplaced_required_files"] == []
        required_paths = report["required_container_paths"]
        assert required_paths["scripts/dyn_b_per_step_audit_writer.py"] == (
            "/opt/projects/g1_ur10e_disturbance/scripts/dyn_b_per_step_audit_writer.py"
        )


def main() -> None:
    test_required_module_removed_should_fail()
    test_target_path_is_importable_and_contains_dyn_b_writer()
    print("PASS test_v1e2b1_dyn_c_import_closure_unit")


if __name__ == "__main__":
    main()
