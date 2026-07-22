#!/usr/bin/env python3
"""Unit tests for shadow component config path resolution (no network)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from shadow.config_resolve import (  # noqa: E402
    resolve_component_config_path,
    resolve_shadow_client_configs,
)


class TestConfigResolve(unittest.TestCase):
    def test_gmrobot_root_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GMRobot"
            cfg = root / "configs" / "vlm_client_legacy_gateway.yaml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("backend: remote_http\nbase_url: http://127.0.0.1:18080\n")
            shadow = root / "configs" / "five_stage_shadow_legacy_gateway_v0c.yaml"
            shadow.write_text("vlm_config: configs/vlm_client_legacy_gateway.yaml\n")
            # CWD is unrelated — must still resolve via GMROBOT_ROOT
            other = Path(tmp) / "other_cwd"
            other.mkdir()
            got = resolve_component_config_path(
                "configs/vlm_client_legacy_gateway.yaml",
                shadow_config_path=shadow,
                env={"GMROBOT_ROOT": str(root)},
                cwd=other,
            )
            self.assertEqual(got, cfg.resolve())

    def test_absolute_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            abs_cfg = Path(tmp) / "abs.yaml"
            abs_cfg.write_text("x: 1\n")
            got = resolve_component_config_path(
                str(abs_cfg),
                shadow_config_path=Path(tmp) / "shadow.yaml",
                env={"GMROBOT_ROOT": "/opt/projects/GMRobot"},
                cwd=Path(tmp),
            )
            self.assertEqual(got, abs_cfg.resolve())

    def test_missing_lists_redacted_candidates(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            resolve_component_config_path(
                "configs/missing.yaml",
                shadow_config_path="/opt/projects/GMRobot/configs/shadow.yaml",
                env={"GMROBOT_ROOT": "/opt/projects/GMRobot"},
                cwd="/tmp",
            )
        msg = str(ctx.exception)
        self.assertIn("tried=", msg)
        self.assertIn("/opt/projects/GMRobot/configs/missing.yaml", msg)
        self.assertNotIn("password", msg.lower())
        self.assertNotIn("token=", msg.lower())

    def test_secretish_path_redacted_in_error(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            resolve_component_config_path(
                "configs/api_key_store.yaml",
                env={"GMROBOT_ROOT": "/opt/projects/GMRobot"},
                cwd="/tmp",
            )
        msg = str(ctx.exception)
        self.assertIn("redacted-path-containing-api_key", msg)

    def test_resolve_both_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GMRobot"
            (root / "configs").mkdir(parents=True)
            vlm = root / "configs" / "vlm_client_legacy_gateway.yaml"
            perc = root / "configs" / "perception_client_legacy_gateway.yaml"
            vlm.write_text("backend: remote_http\n")
            perc.write_text("backend: remote_http\n")
            shadow = root / "configs" / "five_stage.yaml"
            shadow.write_text(
                "vlm_config: configs/vlm_client_legacy_gateway.yaml\n"
                "perception_config: configs/perception_client_legacy_gateway.yaml\n"
            )
            v, p = resolve_shadow_client_configs(
                {
                    "vlm_config": "configs/vlm_client_legacy_gateway.yaml",
                    "perception_config": "configs/perception_client_legacy_gateway.yaml",
                },
                shadow_config_path=shadow,
                env={"GMROBOT_ROOT": str(root)},
                cwd=Path(tmp) / "gmdisturb_cwd",
            )
            self.assertEqual(v, vlm.resolve())
            self.assertEqual(p, perc.resolve())


if __name__ == "__main__":
    unittest.main()
