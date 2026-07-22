"""Perception integration package (Layer 3 Stage 2 — GDINO + SAM2)."""

from .client import PerceptionClient, PerceptionClientConfig, PerceptionTrackSession
from .legacy_gateway import (
    LegacyPerceptionGateway,
    convert_legacy_ground_response,
    is_valid_track_id,
    normalize_track_id,
)
from .schema import SCHEMA_VERSION, keywords_to_text_prompt, normalize_keywords

__all__ = [
    "PerceptionClient",
    "PerceptionClientConfig",
    "PerceptionTrackSession",
    "LegacyPerceptionGateway",
    "convert_legacy_ground_response",
    "is_valid_track_id",
    "normalize_track_id",
    "SCHEMA_VERSION",
    "keywords_to_text_prompt",
    "normalize_keywords",
]
