"""V1-D7B window-aggregate motion assessment (evidence layer v2 candidate).

Motivation (D7A boundary batch, 2026-07-24): last-frame instantaneous
``speed_px_s`` plus the D4A size-band drift heuristic did not generalize
beyond the calibration window. Idle balance sway produced 25-35 px/s
instantaneous speeds (false positive), while legitimate gait/appearance size
changes tripped the drift flag on truly dynamic sweeps (fail-closed misses).

This module decomposes the first-to-last bbox change over a tracking window
into a rigid-translation component and a scale component:

    dL = L1 - L0, dR = R1 - R0 (x edges); dT, dB likewise (y edges)
    translation = ((dL+dR)/2, (dT+dB)/2)   scale = (|dR-dL| + |dB-dT|) / 2

``translation_rate_px_s`` is robust both to sway (near-zero net translation)
and to one-sided mask trailing (growth contributes to scale, not translation).

Calibration (six archived windows, front + top-down cameras):
  dynamic lateral sweeps: 43.4 / 47.2 / 69.2 px/s translation
  static idle sway:       14.7 px/s
  threshold 25.0 px/s leaves a ~1.7x margin on each side.

Known limitation (preregistered in D7A): camera-axis depth motion (approach /
retreat) shows as scale, not translation (b2: 14.5 px/s translation, 28.8
scale). Scale is not used as a dynamic trigger here because mask leak also
manifests as scale growth; depth motion therefore remains fail-closed until a
leak-vs-approach discriminator is validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

TRANSLATION_DYNAMIC_THRESHOLD_PX_S = 25.0
CALIBRATION_DOC = "vlm-v1d7b-window-motion-eval-2026-07-24"


@dataclass(frozen=True)
class WindowMotionConfig:
    fps: float = 60.0
    translation_dynamic_threshold_px_s: float = TRANSLATION_DYNAMIC_THRESHOLD_PX_S
    min_boxes: int = 3


def assess_window_motion(
    step_box_seq: Sequence[tuple[int, Sequence[float] | None]],
    config: WindowMotionConfig | None = None,
) -> dict[str, Any]:
    """Assess aggregate motion over a tracking window.

    Args:
        step_box_seq: ordered (sim_step, box_xyxy | None) pairs.
        config: thresholds; defaults to D7B calibration.

    Returns dict with translation/scale rates and ``dynamic_by_translation``.
    Fail-closed: too few valid boxes -> not dynamic, ``valid`` False.
    """
    cfg = config or WindowMotionConfig()
    seq = [(int(s), [float(x) for x in b]) for s, b in step_box_seq if b is not None]
    base: dict[str, Any] = {
        "valid": False,
        "n_boxes": len(seq),
        "window_duration_s": None,
        "translation_rate_px_s": None,
        "scale_rate_px_s": None,
        "x_edge_asymmetry": None,
        "dynamic_by_translation": False,
        "threshold_px_s": cfg.translation_dynamic_threshold_px_s,
        "calibration_doc": CALIBRATION_DOC,
    }
    if len(seq) < cfg.min_boxes:
        base["reason"] = f"insufficient_boxes_lt_{cfg.min_boxes}"
        return base
    (s0, b0), (s1, b1) = seq[0], seq[-1]
    if s1 <= s0:
        base["reason"] = "non_positive_window"
        return base
    dur = (s1 - s0) / cfg.fps

    d_l, d_r = b1[0] - b0[0], b1[2] - b0[2]
    d_t, d_b = b1[1] - b0[1], b1[3] - b0[3]
    tx, ty = (d_l + d_r) / 2.0, (d_t + d_b) / 2.0
    translation_rate = (tx * tx + ty * ty) ** 0.5 / dur
    scale_rate = (abs(d_r - d_l) + abs(d_b - d_t)) / 2.0 / dur
    x_asym = abs(abs(d_l) - abs(d_r)) / max(abs(d_l) + abs(d_r), 1e-6)

    base.update({
        "valid": True,
        "window_duration_s": dur,
        "translation_rate_px_s": translation_rate,
        "scale_rate_px_s": scale_rate,
        "x_edge_asymmetry": x_asym,
        "dynamic_by_translation": translation_rate >= cfg.translation_dynamic_threshold_px_s,
        "reason": "",
    })
    return base
