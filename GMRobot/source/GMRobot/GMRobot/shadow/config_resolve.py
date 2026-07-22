"""Resolve five-stage shadow component config paths (no CWD dependency)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


_SECRET_KEYS = ("password", "token", "secret", "authorization", "api_key", "apikey")


def _redact_path(path: str | Path) -> str:
    """Return path string without credential-looking query fragments."""
    text = str(path)
    lower = text.lower()
    for key in _SECRET_KEYS:
        if key in lower:
            # Keep directory hints only when a secret-looking token appears.
            return f"<redacted-path-containing-{key}>"
    return text


def resolve_component_config_path(
    configured: str | Path | None,
    *,
    shadow_config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    must_exist: bool = True,
) -> Path:
    """Resolve vlm_config / perception_config paths.

    Order:
      1. absolute path as-is
      2. relative to GMROBOT_ROOT
      3. relative to the shadow config file directory
      4. relative to cwd (last resort)
    """
    if configured is None or str(configured).strip() == "":
        raise FileNotFoundError("component config path is empty")

    raw = Path(str(configured)).expanduser()
    env_map = env if env is not None else dict(os.environ)
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        root = (env_map.get("GMROBOT_ROOT") or "").strip()
        if root:
            candidates.append(Path(root) / raw)
        if shadow_config_path is not None:
            candidates.append(Path(shadow_config_path).expanduser().resolve().parent / raw)
        base_cwd = Path(cwd) if cwd is not None else Path.cwd()
        candidates.append(base_cwd / raw)

    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for c in candidates:
        key = str(c)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    for c in uniq:
        if c.is_file():
            return c.resolve() if c.exists() else c

    if not must_exist:
        return uniq[0].resolve() if uniq else raw

    tried = [_redact_path(c) for c in uniq]
    raise FileNotFoundError(
        "five-stage component config not found: "
        f"configured={_redact_path(raw)}; tried={tried}"
    )


def resolve_shadow_client_configs(
    five_stage_cfg: dict[str, Any],
    *,
    shadow_config_path: str | Path,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> tuple[Path, Path]:
    """Resolve vlm_config and perception_config from a loaded shadow YAML dict."""
    vlm = resolve_component_config_path(
        five_stage_cfg.get("vlm_config") or "configs/vlm_client.yaml",
        shadow_config_path=shadow_config_path,
        env=env,
        cwd=cwd,
    )
    perc = resolve_component_config_path(
        five_stage_cfg.get("perception_config") or "configs/perception_client.yaml",
        shadow_config_path=shadow_config_path,
        env=env,
        cwd=cwd,
    )
    return vlm, perc
