#!/usr/bin/env python3
"""Static local-import closure for Dyn-B runtime entrypoints."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportEdge:
    source_file: str
    import_stmt: str
    module: str
    resolved_file: str | None
    unresolved_local: bool


def _module_candidates(module: str, roots: list[Path]) -> list[Path]:
    parts = [p for p in module.split(".") if p]
    out: list[Path] = []
    for root in roots:
        py = root.joinpath(*parts).with_suffix(".py")
        pkg = root.joinpath(*parts, "__init__.py")
        out.extend([py, pkg])
    return out


def _resolve_absolute(module: str, roots: list[Path]) -> Path | None:
    for cand in _module_candidates(module, roots):
        if cand.is_file():
            return cand.resolve()
    return None


def _resolve_relative(source_file: Path, module: str | None, level: int, project_root: Path) -> Path | None:
    base = source_file.parent
    for _ in range(max(0, level - 1)):
        base = base.parent
    module_path = module.replace(".", "/") if module else ""
    py = (base / f"{module_path}.py").resolve() if module_path else (base / "__init__.py").resolve()
    pkg = (base / module_path / "__init__.py").resolve() if module_path else py
    for cand in (py, pkg):
        if cand.is_file() and project_root in cand.parents:
            return cand
    return None


def _build_local_module_index(project_root: Path) -> set[str]:
    names: set[str] = set()
    for path in project_root.rglob("*.py"):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        rel = path.relative_to(project_root)
        if rel.name == "__init__.py":
            mod = ".".join(rel.with_suffix("").parts[:-1])
            if mod:
                names.add(mod.split(".")[0])
            continue
        stem = rel.stem
        if stem:
            names.add(stem)
        if rel.parts:
            names.add(rel.parts[0])
    return names


def compute_local_import_closure(entry_file: Path, project_root: Path) -> dict[str, object]:
    roots = [project_root, project_root / "scripts"]
    local_index = _build_local_module_index(project_root)
    queue: list[Path] = [entry_file.resolve()]
    visited: set[Path] = set()
    edges: list[ImportEdge] = []
    unresolved: list[dict[str, str]] = []

    while queue:
        src = queue.pop(0)
        if src in visited:
            continue
        visited.add(src)
        tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    resolved = _resolve_absolute(imported, roots)
                    unresolved_local = resolved is None and imported.split(".")[0] in local_index
                    edges.append(
                        ImportEdge(
                            source_file=str(src),
                            import_stmt=f"import {imported}",
                            module=imported,
                            resolved_file=str(resolved) if resolved else None,
                            unresolved_local=unresolved_local,
                        )
                    )
                    if unresolved_local:
                        unresolved.append(
                            {
                                "source_file": str(src),
                                "import_stmt": f"import {imported}",
                                "module": imported,
                            }
                        )
                    if resolved and resolved not in visited and resolved not in queue:
                        queue.append(resolved)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported = ("." * node.level) + module if node.level else module
                resolved = (
                    _resolve_relative(src, module, node.level, project_root)
                    if node.level
                    else _resolve_absolute(module, roots) if module else None
                )
                unresolved_local = False
                if node.level and resolved is None:
                    unresolved_local = True
                elif not node.level and module and resolved is None and module.split(".")[0] in local_index:
                    unresolved_local = True
                edges.append(
                    ImportEdge(
                        source_file=str(src),
                        import_stmt=f"from {imported or '.'} import ...",
                        module=imported or ".",
                        resolved_file=str(resolved) if resolved else None,
                        unresolved_local=unresolved_local,
                    )
                )
                if unresolved_local:
                    unresolved.append(
                        {
                            "source_file": str(src),
                            "import_stmt": f"from {imported or '.'} import ...",
                            "module": imported or ".",
                        }
                    )
                if resolved and resolved not in visited and resolved not in queue:
                    queue.append(resolved)
                if not node.level and module:
                    for alias in node.names:
                        child_mod = f"{module}.{alias.name}"
                        child = _resolve_absolute(child_mod, roots)
                        if child and child not in visited and child not in queue:
                            queue.append(child)

    closure_members = sorted(str(p.relative_to(project_root)) for p in visited if project_root in p.parents)
    return {
        "entry_file": str(entry_file.resolve()),
        "project_root": str(project_root.resolve()),
        "closure_members": closure_members,
        "scene_camera_override_present": "scene_camera_override.py" in closure_members,
        "unresolved_local_imports": unresolved,
        "import_edges": [edge.__dict__ for edge in edges],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entry-file", required=True, help="Entrypoint Python file (e.g. scripts/run_phase3.py)")
    ap.add_argument("--project-root", default="", help="Project root; default resolved from entry file.")
    ap.add_argument("--json-out", default="", help="Optional JSON output path.")
    args = ap.parse_args()

    entry_file = Path(args.entry_file).resolve()
    project_root = Path(args.project_root).resolve() if args.project_root else entry_file.parents[1].resolve()
    report = compute_local_import_closure(entry_file=entry_file, project_root=project_root)

    text = json.dumps(report, indent=2, ensure_ascii=True)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if report["unresolved_local_imports"]:
        return 2
    if not report["scene_camera_override_present"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
