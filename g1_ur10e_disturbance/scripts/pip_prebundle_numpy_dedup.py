#!/usr/bin/env python3
"""Quarantine alternate NumPy distribution under omni.kit.pip_archive pip_prebundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TargetEntry:
    pip_prebundle_root: Path
    path: Path
    rel: str
    kind: str
    is_symlink: bool
    link_target: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


def _rel_join(rel_dir: str, name: str) -> str:
    if rel_dir == ".":
        return name
    return f"{rel_dir}/{name}"


def _sha256_directory_tree(path: Path) -> tuple[str, int, int]:
    """
    Stable digest for directory trees.
    Includes sorted relative paths, file types, file content hashes and symlink
    targets. Symlinks are recorded but never followed.
    """
    lines: list[str] = ["D|."]
    total_size = 0
    file_count = 0
    for root, dirnames, filenames in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        rel_dir = root_path.relative_to(path).as_posix()
        dirnames.sort()
        filenames.sort()
        for name in dirnames:
            child = root_path / name
            rel = _rel_join(rel_dir, name)
            if child.is_symlink():
                lines.append(f"L|{rel}|{os.readlink(child)}")
            else:
                lines.append(f"D|{rel}")
        for name in filenames:
            child = root_path / name
            rel = _rel_join(rel_dir, name)
            if child.is_symlink():
                lines.append(f"L|{rel}|{os.readlink(child)}")
                continue
            digest, size = _sha256_file(child)
            total_size += size
            file_count += 1
            lines.append(f"F|{rel}|{size}|{digest}")
    payload = ("\n".join(lines) + "\n").encode("utf-8", errors="replace")
    return _sha256_bytes(payload), total_size, file_count


def describe_path(path: Path) -> dict[str, str | int]:
    if path.is_symlink():
        target = os.readlink(path)
        return {
            "path_kind": "symlink",
            "size_bytes": int(path.lstat().st_size),
            "file_count": 0,
            "digest": _sha256_bytes(f"L|{target}".encode("utf-8", errors="replace")),
            "symlink_target": target,
        }
    if path.is_dir():
        digest, size_bytes, file_count = _sha256_directory_tree(path)
        return {
            "path_kind": "directory",
            "size_bytes": size_bytes,
            "file_count": file_count,
            "digest": digest,
            "symlink_target": "",
        }
    digest, size_bytes = _sha256_file(path)
    return {
        "path_kind": "regular_file",
        "size_bytes": size_bytes,
        "file_count": 1,
        "digest": digest,
        "symlink_target": "",
    }


def _target_kind(name: str) -> str | None:
    if name == "numpy":
        return "numpy_pkg"
    if name == "numpy.libs":
        return "numpy_libs"
    if name.startswith("numpy-") and name.endswith(".dist-info"):
        return "numpy_dist_info"
    return None


def discover_targets(pip_prebundle_root: Path) -> list[TargetEntry]:
    out: list[TargetEntry] = []
    for child in sorted(pip_prebundle_root.iterdir(), key=lambda p: p.name):
        kind = _target_kind(child.name)
        if not kind:
            continue
        out.append(
            TargetEntry(
                pip_prebundle_root=pip_prebundle_root,
                path=child,
                rel=child.name,
                kind=kind,
                is_symlink=child.is_symlink(),
                link_target=(str(child.readlink()) if child.is_symlink() else ""),
            )
        )
    return out


def discover_all_targets(extscache_root: Path) -> list[TargetEntry]:
    out: list[TargetEntry] = []
    for pip_root in sorted(extscache_root.glob("omni.kit.pip_archive-*/pip_prebundle")):
        if pip_root.is_dir():
            out.extend(discover_targets(pip_root))
    return out


def quarantine_targets(targets: list[TargetEntry], quarantine_root: Path) -> list[dict[str, str | int]]:
    moved: list[dict[str, str | int]] = []
    quarantine_root.mkdir(parents=True, exist_ok=True)
    for entry in targets:
        if not entry.path.exists() and not entry.path.is_symlink():
            continue
        desc = describe_path(entry.path)
        token = str(entry.pip_prebundle_root.parent.name).replace("/", "_")
        dst = quarantine_root / token / entry.rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry.path), str(dst))
        moved.append(
            {
                "source": str(entry.path),
                "dest": str(dst),
                "kind": entry.kind,
                "path_kind": str(desc["path_kind"]),
                "size_bytes": int(desc["size_bytes"]),
                "file_count": int(desc["file_count"]),
                "digest": str(desc["digest"]),
                "symlink_target": str(desc["symlink_target"]),
            }
        )
    return moved


def _has_importable_numpy_in_prebundle(extscache_root: Path) -> list[str]:
    remain: list[str] = []
    for pip_root in sorted(extscache_root.glob("omni.kit.pip_archive-*/pip_prebundle")):
        for name in ("numpy", "numpy.libs"):
            p = pip_root / name
            if p.exists() or p.is_symlink():
                remain.append(str(p))
        for p in sorted(pip_root.glob("numpy-*.dist-info")):
            remain.append(str(p))
    return remain


def _assert_kit_numpy() -> dict[str, str]:
    import importlib

    np = importlib.import_module("numpy")
    npr = importlib.import_module("numpy.random")
    gen = importlib.import_module("numpy.random._generator")
    mt = importlib.import_module("numpy.random._mt19937")
    return {
        "numpy_file": str(Path(np.__file__).resolve()),
        "numpy_random_file": str(Path(npr.__file__).resolve()),
        "numpy_random_generator_file": str(Path(gen.__file__).resolve()),
        "numpy_random_mt19937_file": str(Path(mt.__file__).resolve()),
        "numpy_version": str(np.__version__),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extscache-root", type=Path, default=Path("/isaac-sim/extscache"))
    ap.add_argument(
        "--quarantine-root",
        type=Path,
        default=Path("/isaac-sim/extscache/quarantine_numpy_prebundle_m1u2"),
    )
    ap.add_argument("--report-json", type=Path, required=True)
    ap.add_argument("--inventory-txt", type=Path, required=True)
    ap.add_argument("--hashes-txt", type=Path, required=True)
    ap.add_argument(
        "--kit-site-root",
        type=Path,
        default=Path("/isaac-sim/kit/python/lib/python3.11/site-packages"),
    )
    args = ap.parse_args()

    targets = discover_all_targets(args.extscache_root)
    inventory_lines: list[str] = []
    hashes_lines: list[str] = []
    for t in targets:
        if t.path.exists() or t.path.is_symlink():
            desc = describe_path(t.path)
            inventory_lines.append(
                "|".join(
                    [
                        str(t.pip_prebundle_root),
                        t.rel,
                        t.kind,
                        str(desc["path_kind"]),
                        str(desc["size_bytes"]),
                        str(desc["file_count"]),
                        str(desc["digest"]),
                        str(desc["symlink_target"]),
                    ]
                )
            )
            hashes_lines.append(f"{desc['digest']}  {t.path}")
        else:
            inventory_lines.append("|".join([str(t.pip_prebundle_root), t.rel, t.kind, "missing", "0", "0", "", ""]))

    moved = quarantine_targets(targets, args.quarantine_root)
    remain = _has_importable_numpy_in_prebundle(args.extscache_root)
    kit = _assert_kit_numpy()

    kit_root = str(args.kit_site_root.resolve())
    assert kit["numpy_file"].startswith(kit_root + "/"), kit
    assert kit["numpy_random_file"].startswith(kit_root + "/"), kit
    assert kit["numpy_random_generator_file"].startswith(kit_root + "/"), kit
    assert kit["numpy_random_mt19937_file"].startswith(kit_root + "/"), kit
    assert not remain, f"pip_prebundle numpy remains importable: {remain}"

    args.inventory_txt.parent.mkdir(parents=True, exist_ok=True)
    args.inventory_txt.write_text("\n".join(inventory_lines) + ("\n" if inventory_lines else ""), encoding="utf-8")
    args.hashes_txt.parent.mkdir(parents=True, exist_ok=True)
    args.hashes_txt.write_text("\n".join(hashes_lines) + ("\n" if hashes_lines else ""), encoding="utf-8")
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(
            {
                "extscache_root": str(args.extscache_root),
                "quarantine_root": str(args.quarantine_root),
                "inventory_count": len(targets),
                "moved_count": len(moved),
                "remaining_importable_numpy_prebundle": remain,
                "moved": moved,
                "kit_numpy": kit,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
