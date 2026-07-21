"""B2/B4-Dynamic commanded trajectory prefix comparison."""

from __future__ import annotations

import csv
from pathlib import Path


_TRAJECTORY_COMPARE_COLS = (
    "disturbance_trajectory_id",
    "sweep_attempt_id",
    "sweep_progress",
    "proxy_center_x",
    "proxy_center_y",
    "proxy_center_z",
    "proxy_surface_x",
    "proxy_surface_y",
    "proxy_surface_z",
    "sweep_velocity_x",
    "sweep_velocity_y",
    "sweep_velocity_z",
)


def _read_trajectory(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def compare_trajectory_prefix(
    active_path: str | Path,
    shadow_path: str | Path,
    *,
    prefix_rows: int | None = None,
    atol: float = 1e-5,
) -> list[str]:
    """Compare active vs shadow trajectory rows up to active's last row.

    Returns a list of human-readable mismatch errors (empty == pass).
    """
    a_rows = _read_trajectory(active_path)
    s_rows = _read_trajectory(shadow_path)
    errors: list[str] = []
    if not a_rows:
        errors.append("active trajectory CSV empty")
        return errors
    if not s_rows:
        errors.append("shadow trajectory CSV empty")
        return errors
    tid_a = a_rows[0].get("disturbance_trajectory_id", "")
    tid_s = s_rows[0].get("disturbance_trajectory_id", "")
    if tid_a and tid_s and tid_a != tid_s:
        errors.append(f"trajectory_id mismatch: active={tid_a[:16]}… shadow={tid_s[:16]}…")
    n = min(len(a_rows), len(s_rows))
    if prefix_rows is not None:
        n = min(n, int(prefix_rows))
    if len(s_rows) < n:
        errors.append(
            f"shadow has fewer prefix rows ({len(s_rows)}) than active ({len(a_rows)})"
        )
    for i in range(n):
        ar, sr = a_rows[i], s_rows[i]
        for col in _TRAJECTORY_COMPARE_COLS:
            av = (ar.get(col) or "").strip()
            sv = (sr.get(col) or "").strip()
            if col.endswith("_x") or col.endswith("_y") or col.endswith("_z") or col == "sweep_progress":
                if av and sv:
                    try:
                        if abs(float(av) - float(sv)) > atol:
                            errors.append(f"row {i} {col}: active={av} shadow={sv}")
                    except ValueError:
                        if av != sv:
                            errors.append(f"row {i} {col}: active={av} shadow={sv}")
                elif av != sv:
                    errors.append(f"row {i} {col}: active={av!r} shadow={sv!r}")
            else:
                if av != sv:
                    errors.append(f"row {i} {col}: active={av!r} shadow={sv!r}")
    return errors
