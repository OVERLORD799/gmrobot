"""Unit tests for reach_radius vs proxy_radius split."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from g1_virtual_hand import G1VirtualHand
from config_loader import load_config
from protocol_vhand import per_part_radius


def test_reach_and_proxy_are_independent():
    vh = G1VirtualHand(reach_radius=0.50, proxy_radius=0.40, seed=1, pursuit_mode=True)
    assert vh.reach_radius == 0.50
    assert vh.proxy_radius == 0.40
    assert vh.radius == 0.50  # legacy alias == reach
    vh.proxy_radius = 0.08
    assert vh.reach_radius == 0.50  # proxy change must not alter reach


def test_reach_margin_negative_when_attractor_beyond_reach():
    vh = G1VirtualHand(reach_radius=0.50, proxy_radius=0.40, seed=2, pursuit_mode=True)
    vh._attractor = np.array([0.65, 0.0], dtype=np.float32)
    head = np.array([-0.51, 0.0, 0.9], dtype=np.float32)
    vh.step(0.02, head, ee_z=0.8)
    # ||0.65 - (-0.51)|| = 1.16 > 0.50 ⇒ margin negative, clamped
    assert vh.head_to_attractor_distance() > vh.reach_radius
    assert vh.reach_margin() < 0.0
    assert vh.last_reach_clamped is True
    # Centre still within reach of head
    assert float(np.linalg.norm(vh.position[:2] - head[:2])) <= vh.reach_radius + 1e-3


def test_yaml_loads_split_radii():
    cfg = load_config(str(_ROOT / "paper_scenarios/static_occupancy_proxy_1part.yaml"))
    assert cfg.virtual_hand.reach_radius == 0.55
    assert cfg.virtual_hand.transit_proxy_radius == 0.40
    assert cfg.virtual_hand.pick_place_proxy_radius == 0.08
    # legacy property aliases
    assert cfg.virtual_hand.transit_radius == 0.40
    assert cfg.virtual_hand.default_radius == 0.55


def test_legacy_yaml_keys_still_load(tmp_path=None):
    import tempfile
    from pathlib import Path as P
    text = """
virtual_hand:
  radius: 0.48
  transit_radius: 0.41
  pick_place_radius: 0.07
  reset_radius: 0.29
disturbance:
  workspace_x: [0.0, 0.15]
  workspace_y: [-0.5, 0.5]
batch:
  max_steps: 100
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = P(tmp) / "legacy.yaml"
        p.write_text(text)
        cfg = load_config(str(p))
        assert cfg.virtual_hand.reach_radius == 0.48
        assert cfg.virtual_hand.transit_proxy_radius == 0.41
        assert per_part_radius("transit", **{
            "transit_proxy_radius": cfg.virtual_hand.transit_proxy_radius,
            "pick_place_proxy_radius": cfg.virtual_hand.pick_place_proxy_radius,
            "reset_proxy_radius": cfg.virtual_hand.reset_proxy_radius,
        }) == 0.41


if __name__ == "__main__":
    test_reach_and_proxy_are_independent()
    test_reach_margin_negative_when_attractor_beyond_reach()
    test_yaml_loads_split_radii()
    test_legacy_yaml_keys_still_load()
    print("OK")
