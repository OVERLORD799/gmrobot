"""Box-geometry drift detection for SAM2 track evidence (V1-D4A).

Motivation (D3C finding): a SAM2 mask that leaks onto static scene content
keeps a high mask score, so score/speed/continuity validation passes on a
semantically wrong track. Mask leak has a geometric signature that rigid
object translation does not: the box *changes size* instead of moving.

Calibration (single scene, D3C dense replay, 2026-07-24):
- perfect tracker proxy (GT projected boxes, walking G1): width ratio stayed
  within [0.99, 1.00], expansion <= 4 px over 17 frames;
- drifted SAM2 track: width ratio 1.18 at frame index 3 (sim step 185,
  25 steps before IoU reached 0), growing to 1.39, expansion up to 28 px;
- sparse-gap drift (D3B phase B): width ratio 0.63, expansion 24 px.

Thresholds below separate these with wide margin but are calibrated on one
scene only; they are preliminary and must be revisited before any claim
beyond Dyn-C replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class BoxDriftConfig:
    """Geometric drift thresholds — independent from semantic confidence."""

    size_ratio_max: float = 1.15
    size_ratio_min: float = 0.85
    min_expansion_px: float = 8.0
    min_history: int = 2  # need at least reference box + one later box

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> BoxDriftConfig:
        d = dict(data or {})
        return cls(
            size_ratio_max=float(d.get("size_ratio_max", 1.15)),
            size_ratio_min=float(d.get("size_ratio_min", 0.85)),
            min_expansion_px=float(d.get("min_expansion_px", 8.0)),
            min_history=int(d.get("min_history", 2)),
        )


def _wh(box: Sequence[float]) -> tuple[float, float]:
    return float(box[2]) - float(box[0]), float(box[3]) - float(box[1])


def assess_box_drift(
    boxes: Sequence[Sequence[float] | None],
    config: BoxDriftConfig | None = None,
) -> dict[str, Any]:
    """Assess a track's box history (oldest first) for mask-leak drift.

    Returns a dict with ``drift_suspect``, the first flagged index (or None),
    and the per-history extrema used for the decision. ``None`` entries
    (missing boxes) are skipped for geometry but break nothing.
    """
    cfg = config or BoxDriftConfig()
    valid = [(i, b) for i, b in enumerate(boxes) if b is not None and len(b) == 4]
    if len(valid) < cfg.min_history:
        return {
            "drift_suspect": False,
            "first_flag_index": None,
            "reason": "insufficient_history",
            "n_boxes": len(valid),
        }
    ref_i, ref = valid[0]
    w0, h0 = _wh(ref)
    if w0 <= 0 or h0 <= 0:
        return {
            "drift_suspect": False,
            "first_flag_index": None,
            "reason": "degenerate_reference_box",
            "n_boxes": len(valid),
        }
    first_flag: int | None = None
    max_ratio = 1.0
    min_ratio = 1.0
    max_expansion = 0.0
    for i, box in valid[1:]:
        w, h = _wh(box)
        wr, hr = w / w0, h / h0
        expansion = abs(w - w0) + abs(h - h0)
        max_ratio = max(max_ratio, wr, hr)
        min_ratio = min(min_ratio, wr, hr)
        max_expansion = max(max_expansion, expansion)
        out_of_band = (
            wr > cfg.size_ratio_max
            or wr < cfg.size_ratio_min
            or hr > cfg.size_ratio_max
            or hr < cfg.size_ratio_min
        )
        if out_of_band and expansion >= cfg.min_expansion_px and first_flag is None:
            first_flag = i
    return {
        "drift_suspect": first_flag is not None,
        "first_flag_index": first_flag,
        "reason": "size_change_out_of_band" if first_flag is not None else "",
        "reference_index": ref_i,
        "max_size_ratio": max_ratio,
        "min_size_ratio": min_ratio,
        "max_expansion_px": max_expansion,
        "n_boxes": len(valid),
        "config": {
            "size_ratio_max": cfg.size_ratio_max,
            "size_ratio_min": cfg.size_ratio_min,
            "min_expansion_px": cfg.min_expansion_px,
        },
    }
