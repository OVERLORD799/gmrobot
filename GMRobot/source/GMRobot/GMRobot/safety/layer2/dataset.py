"""Load Layer 1 safety CSV logs into episode objects for Layer 2 training."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

_EPISODE_RE = re.compile(r"episode_(\d+)\.csv$")


@dataclass
class SafetyEpisode:
    """One episode CSV with parsed rows and metadata."""

    run_id: str
    episode_id: int
    csv_path: Path
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def num_rows(self) -> int:
        return len(self.rows)


def _parse_episode_id(path: Path) -> int:
    match = _EPISODE_RE.search(path.name)
    if not match:
        raise ValueError(f"Unexpected episode filename: {path.name}")
    return int(match.group(1))


def _run_id_from_path(path: Path, log_dir: Path) -> str:
    try:
        rel = path.relative_to(log_dir)
        return rel.parts[0]
    except ValueError:
        return path.parent.name


def iter_episode_csv_paths(log_dir: Path, glob_pattern: str = "**/episode_*.csv") -> Iterator[Path]:
    yield from sorted(log_dir.glob(glob_pattern))


def load_episode_csv(path: Path, *, log_dir: Path | None = None) -> SafetyEpisode:
    log_dir = log_dir or path.parent.parent
    run_id = _run_id_from_path(path, log_dir)
    episode_id = _parse_episode_id(path)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return SafetyEpisode(run_id=run_id, episode_id=episode_id, csv_path=path, rows=rows)


def load_episodes(
    log_dir: str | Path,
    *,
    min_run_id: str | None = "20260617_141625",
    glob_pattern: str = "**/episode_*.csv",
) -> list[SafetyEpisode]:
    """Glob-read episode CSVs under log_dir, optionally filtering by run timestamp."""
    root = Path(log_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"log_dir not found: {root}")

    episodes: list[SafetyEpisode] = []
    for csv_path in iter_episode_csv_paths(root, glob_pattern):
        episode = load_episode_csv(csv_path, log_dir=root)
        if min_run_id is not None and episode.run_id < min_run_id:
            continue
        if not episode.rows:
            continue
        episodes.append(episode)

    episodes.sort(key=lambda ep: (ep.run_id, ep.episode_id))
    return episodes
