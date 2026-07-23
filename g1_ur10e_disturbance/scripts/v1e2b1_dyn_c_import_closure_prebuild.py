#!/usr/bin/env python3
"""V1-E2B.1 prebuild checker: Dyn-C Docker COPY import closure."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

from dyn_b_source_closure import compute_local_import_closure


CONTAINER_ROOT = "/opt/projects/g1_ur10e_disturbance"


def _parse_copy_line(raw: str) -> tuple[list[str], str] | None:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if not stripped.upper().startswith("COPY "):
        return None
    tokens = shlex.split(stripped)
    if not tokens or tokens[0].upper() != "COPY":
        return None
    payload = [t for t in tokens[1:] if not t.startswith("--")]
    if len(payload) < 2:
        return None
    return payload[:-1], payload[-1]


def parse_copy_plan(dockerfile_path: Path, project_root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    lines = dockerfile_path.read_text(encoding="utf-8").splitlines()
    for raw in lines:
        parsed = _parse_copy_line(raw)
        if parsed is None:
            continue
        sources, dest = parsed
        multi_src = len(sources) > 1
        for src in sources:
            host_src = (project_root / src).resolve()
            if not host_src.exists():
                continue
            if host_src.is_file():
                rel = host_src.relative_to(project_root).as_posix()
                if dest.endswith("/") or multi_src:
                    target = Path(dest) / host_src.name
                else:
                    target = Path(dest)
                mapping[rel] = target.as_posix()
                continue
            src_has_trailing = src.endswith("/")
            src_root = host_src
            for child in src_root.rglob("*"):
                if not child.is_file():
                    continue
                rel = child.relative_to(project_root).as_posix()
                rel_under_src = child.relative_to(src_root).as_posix()
                if src_has_trailing:
                    target = Path(dest) / rel_under_src
                else:
                    target = Path(dest) / src_root.name / rel_under_src
                mapping[rel] = target.as_posix()
    return mapping


def verify_dyn_c_import_closure(
    *,
    project_root: Path,
    dockerfile_path: Path,
    entrypoints: list[str],
    container_root: str = CONTAINER_ROOT,
) -> dict[str, Any]:
    copy_map = parse_copy_plan(dockerfile_path=dockerfile_path, project_root=project_root)
    required: set[str] = set()
    unresolved_locals: list[dict[str, str]] = []
    predicted_module_not_found: list[dict[str, str]] = []

    for entry_rel in entrypoints:
        closure = compute_local_import_closure(
            entry_file=project_root / entry_rel,
            project_root=project_root,
        )
        required.update(str(m) for m in closure["closure_members"])
        unresolved_locals.extend(closure["unresolved_local_imports"])  # type: ignore[arg-type]

        edges = closure["import_edges"]  # type: ignore[assignment]
        for edge in edges:
            resolved = edge.get("resolved_file")
            module = edge.get("module", "")
            if not resolved:
                continue
            resolved_path = Path(str(resolved))
            if project_root not in resolved_path.parents:
                continue
            rel = resolved_path.relative_to(project_root).as_posix()
            if rel not in copy_map:
                predicted_module_not_found.append(
                    {
                        "module": str(module),
                        "source_file": str(edge.get("source_file", "")),
                        "predicted_error": f"ModuleNotFoundError: No module named '{module}'",
                    }
                )

    missing_files = sorted(m for m in required if m not in copy_map)
    required_container_paths = {rel: copy_map[rel] for rel in sorted(required) if rel in copy_map}
    misplaced_files: list[dict[str, str]] = []
    for rel in sorted(required):
        actual = copy_map.get(rel)
        if actual is None:
            continue
        expected = f"{container_root}/{rel}"
        if Path(actual).as_posix() != Path(expected).as_posix():
            misplaced_files.append({"file": rel, "expected": expected, "actual": actual})

    predicted_unique: list[dict[str, str]] = []
    seen = set()
    for row in predicted_module_not_found:
        key = (row["module"], row["source_file"])
        if key in seen:
            continue
        seen.add(key)
        predicted_unique.append(row)

    return {
        "ok": not missing_files and not misplaced_files and not unresolved_locals,
        "project_root": str(project_root),
        "dockerfile_path": str(dockerfile_path),
        "entrypoints": entrypoints,
        "required_local_python_files": sorted(required),
        "copy_map_size": len(copy_map),
        "required_container_paths": required_container_paths,
        "missing_required_files": missing_files,
        "misplaced_required_files": misplaced_files,
        "unresolved_local_imports": unresolved_locals,
        "predicted_module_not_found": predicted_unique,
        "contains_dyn_b_per_step_audit_writer": "scripts/dyn_b_per_step_audit_writer.py" in required,
        "next_gate": "IMPORT_CLOSURE_FIX_ONLY",
        "e2b_raw_failure_status": "retained",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--dockerfile", required=True)
    ap.add_argument("--entrypoint", action="append", default=[])
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    report = verify_dyn_c_import_closure(
        project_root=Path(args.project_root).resolve(),
        dockerfile_path=Path(args.dockerfile).resolve(),
        entrypoints=args.entrypoint or ["scripts/run_phase3.py"],
    )
    text = json.dumps(report, indent=2, ensure_ascii=True)
    if args.json_out:
        out = Path(args.json_out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
