"""Episode-level RNG seeding for paper-demo reproducibility.

Isaac Lab also calls ``configure_seed`` when ``env_cfg.seed`` is set, but
``run_phase3`` previously only forwarded ``--seed`` to
``G1DisturbanceController``.  This helper is the single place that documents
what we control vs what GPU PhysX may still leave non-deterministic.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any


PHYSX_NOTE = (
    "GPU PhysX / Isaac Sim may still produce frame-level non-determinism; "
    "paper runs should rely on scenario margin for statistical stability "
    "and record these seed fields for audit."
)


def apply_episode_seeds(seed: int, *, env_cfg: Any | None = None) -> dict[str, Any]:
    """Seed Python / NumPy / Torch (and optionally ``env_cfg.seed``).

    Returns a dict describing which RNGs were seeded.  Callers should also
    pass the same integer into ``G1DisturbanceController`` and
    ``G1VirtualHand``.
    """
    seed = int(seed)
    random.seed(seed)

    import numpy as np

    np.random.seed(seed)

    torch_ok = False
    cuda_ok = False
    try:
        import torch

        torch.manual_seed(seed)
        torch_ok = True
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
            cuda_ok = True
    except ImportError:
        pass

    if env_cfg is not None and hasattr(env_cfg, "seed"):
        env_cfg.seed = seed

    return {
        "seed": seed,
        "python_random": True,
        "numpy": True,
        "torch": torch_ok,
        "torch_cuda": cuda_ok,
        "env_cfg_seed": seed if env_cfg is not None else None,
        "physx_note": PHYSX_NOTE,
    }


def seed_manifest(
    *,
    seed: int,
    env_seed: int | None = None,
    controller_seed: int | None = None,
    virtual_hand_seed: int | None = None,
    applied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured seed record for stdout / JSON sidecar / batch manifest."""
    s = int(seed)
    out: dict[str, Any] = {
        "cli_seed": s,
        "env_seed": int(env_seed if env_seed is not None else s),
        "controller_seed": int(controller_seed if controller_seed is not None else s),
        "virtual_hand_seed": (
            None if virtual_hand_seed is None else int(virtual_hand_seed)
        ),
        "physx_note": PHYSX_NOTE,
    }
    if applied:
        out["applied"] = applied
    return out


def write_seed_sidecar(output_csv: str, record: dict[str, Any]) -> str:
    """Write ``*_seeds.json`` next to the episode CSV. Returns path."""
    if output_csv.endswith(".csv"):
        path = Path(output_csv[:-4] + "_seeds.json")
    else:
        path = Path(str(output_csv) + "_seeds.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return str(path)
