#!/usr/bin/env python3
"""Offline Docker COPY coverage test for V1-M1V1."""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dyn_b_source_closure import compute_local_import_closure  # noqa: E402

DOCKERFILE = ROOT / "docker" / "Dockerfile.e01-dyn-b-clean-m1v1"
DOCKERIGNORE = ROOT / ".dockerignore"


def _dockerignore_patterns(path: Path) -> list[str]:
    pats: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            continue
        pats.append(line)
    return pats


def _is_excluded(rel_path: str, patterns: list[str]) -> bool:
    rel = rel_path.lstrip("./")
    for pat in patterns:
        p = pat.lstrip("./")
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, f"{p}/*"):
            return True
        if pat.endswith("/") and rel.startswith(pat):
            return True
        if "/" not in p and fnmatch.fnmatch(Path(rel).name, p):
            return True
    return False


def test_dockerfile_uses_clean_base_and_full_tree_copy() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM gmdisturb:b4-p010-20260721" in text
    assert "COPY . /opt/projects/g1_ur10e_disturbance" in text
    assert "pip install" not in text.lower()
    assert "conda " not in text.lower()
    assert "apt-get" not in text.lower()


def test_closure_members_not_excluded_from_context() -> None:
    report = compute_local_import_closure(ROOT / "scripts" / "run_phase3.py", ROOT)
    assert report["unresolved_local_imports"] == []
    members = report["closure_members"]
    assert "scene_camera_override.py" in members
    patterns = _dockerignore_patterns(DOCKERIGNORE)
    excluded = [m for m in members if _is_excluded(m, patterns)]
    assert excluded == [], f"closure files excluded by .dockerignore: {excluded}"


def main() -> None:
    test_dockerfile_uses_clean_base_and_full_tree_copy()
    test_closure_members_not_excluded_from_context()
    print("PASS test_e01_dyn_b_m1v1_docker_copy_coverage_unit")


if __name__ == "__main__":
    main()
