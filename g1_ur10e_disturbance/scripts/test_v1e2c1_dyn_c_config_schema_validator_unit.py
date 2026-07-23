#!/usr/bin/env python3
"""Unit tests for V1-E2C.1 Dyn-C config schema validator."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config_loader import load_config  # noqa: E402


def test_mapping_section_bool_must_fail_fast() -> None:
    bad_yaml = """\
scenario: mirrored_outer_lateral_patrol
seed: 44
virtual_hand: false
vlm: false
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(bad_yaml)
        bad_path = fh.name
    try:
        try:
            load_config(bad_path)
        except ValueError as exc:
            msg = str(exc)
            assert "config schema invalid" in msg
            assert "virtual_hand" in msg or "vlm" in msg
        else:
            raise AssertionError("expected schema fail-fast on mapping section bool")
    finally:
        Path(bad_path).unlink(missing_ok=True)


if __name__ == "__main__":
    test_mapping_section_bool_must_fail_fast()
    print("PASS test_v1e2c1_dyn_c_config_schema_validator_unit")
