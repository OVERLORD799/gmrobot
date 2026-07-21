"""Unit tests for episode seed closed-loop + virtual-hand reach clamp."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from seed_utils import apply_episode_seeds, seed_manifest, write_seed_sidecar
from g1_virtual_hand import G1VirtualHand


def test_apply_episode_seeds_sets_python_numpy_and_env_cfg():
    cfg = SimpleNamespace(seed=None)
    applied = apply_episode_seeds(123, env_cfg=cfg)
    assert cfg.seed == 123
    assert applied["seed"] == 123
    assert applied["python_random"] is True
    assert applied["numpy"] is True
    # Deterministic enough for python random after seeding.
    assert random.random() == random.Random(123).random()
    # Reset for other tests — re-seed a fixed value.
    apply_episode_seeds(42)


def test_seed_manifest_and_sidecar(tmp_path: Path | None = None):
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = str(Path(tmp) / "ep.csv")
        rec = seed_manifest(
            seed=42,
            env_seed=42,
            controller_seed=42,
            virtual_hand_seed=42,
            applied={"torch": False},
        )
        assert rec["cli_seed"] == 42
        assert rec["env_seed"] == 42
        assert rec["controller_seed"] == 42
        assert rec["virtual_hand_seed"] == 42
        assert "physx_note" in rec
        path = write_seed_sidecar(csv_path, rec)
        assert path.endswith("_seeds.json")
        loaded = json.loads(Path(path).read_text())
        assert loaded["cli_seed"] == 42


def test_virtual_hand_stores_seed_and_flags_reach_clamp():
    vh = G1VirtualHand(reach_radius=0.40, seed=99, pursuit_mode=True)
    assert vh.seed == 99
    # Attractor beyond head_x + reach must clamp.
    vh._attractor = np.array([0.65, 0.0], dtype=np.float32)
    head = np.array([0.10, 0.0, 0.9], dtype=np.float32)  # reach_x = 0.50
    vh.step(0.02, head, ee_z=0.8)
    assert vh.last_reach_clamped is True
    assert float(vh.position[0]) <= head[0] + vh.reach_radius + 1e-4


def test_virtual_hand_no_clamp_when_attractor_inside_reach():
    vh = G1VirtualHand(reach_radius=0.40, seed=7, pursuit_mode=True)
    vh._attractor = np.array([0.30, 0.0], dtype=np.float32)
    head = np.array([0.10, 0.0, 0.9], dtype=np.float32)  # reach_x = 0.50
    for _ in range(40):
        vh.step(0.02, head, ee_z=0.8)
    assert vh.last_reach_clamped is False


if __name__ == "__main__":
    test_apply_episode_seeds_sets_python_numpy_and_env_cfg()
    test_seed_manifest_and_sidecar()
    test_virtual_hand_stores_seed_and_flags_reach_clamp()
    test_virtual_hand_no_clamp_when_attractor_inside_reach()
    print("OK")
