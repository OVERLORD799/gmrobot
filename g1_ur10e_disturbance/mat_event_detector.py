"""MatEventDetector — tactile pressure mat event classification.

Processes the 32×32 Newton image from the tactile pressure mat and detects:
- Footsteps (left / right) — via FK proximity
- Collision impacts — high-force isolated clusters
- Object drops — small-area clusters that appear between frames

All positions are in the world frame (mat centre = origin).  The mat covers
4 m × 4 m with 32×32 taxels (pitch = 0.125 m).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    from scipy.ndimage import label as connected_components
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORCE_THRESHOLD = 5.0        # N — minimum per-taxel force for a "contact"
COLLISION_FORCE = 50.0       # N — cluster total force suggesting collision
DROP_THRESHOLD = 30.0        # N — force change suggesting object drop (F3 fix: was 10N, too low — footsteps triggered 2377 false positives in 3000 steps)
DROP_MAX_AREA = 4            # taxels — small cluster characteristic of dropped part
FOOT_PROXIMITY = 0.3         # m — max distance from FK foot to classify as footstep
# Workspace filter for collision classification (ARCHITECTURE.md §MatEventDetector):
# collision_impact is only valid inside the UR10e operating area.
WORKSPACE_X_RANGE = (0.3, 1.0)  # m — UR10e + table + container zone in world x
WORKSPACE_Y_RANGE = (-0.5, 0.5)  # m — UR10e + table + container zone in world y (M4 fix)
MAT_SIZE = 4.0               # m
ROWS = 32
COLS = 32
TAXEL_PITCH = MAT_SIZE / COLS  # 0.125 m


# ---------------------------------------------------------------------------
# Event data class
# ---------------------------------------------------------------------------

@dataclass
class MatEvent:
    event_type: str       # "footstep_left" | "footstep_right" | "collision_impact" | "object_drop" | "unknown"
    position: tuple[float, float]  # world (x, y)
    force: float          # total cluster force (N)
    area: int             # number of taxels
    timestamp: int        # step index
    part_id: int = -1     # matched part ID for object_drop events (-1 = unmatched)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class MatEventDetector:
    """Per-step tactile event detector."""

    def __init__(self):
        if not HAS_SCIPY:
            raise ImportError(
                "scipy is required for MatEventDetector (connected-components). "
                "Install with: pip install scipy"
            )
        self._prev_image: Optional[np.ndarray] = None
        self._step = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        tactile_obs,                          # np.ndarray (32, 32) or (1, 32, 32)
        left_foot_pos: np.ndarray,            # (2,) or (3,) world XY
        right_foot_pos: np.ndarray,           # (2,) or (3,) world XY
        part_positions: dict[str, np.ndarray] | None = None,  # part_name → (3,) world pos (M2 fix)
    ) -> list[MatEvent]:
        """Run detection on the current tactile frame.

        Args:
            tactile_obs: 32×32 Newton image (squeezed if batch dim present).
            left_foot_pos: FK position of left ankle in world frame (uses [0], [1]).
            right_foot_pos: FK position of right ankle in world frame.
            part_positions: dict of part_name → (3,) world positions for
                nearest-neighbor matching of object drops (optional).

        Returns:
            List of :class:`MatEvent` objects for this frame.
        """
        self._step += 1

        # Squeeze batch dim if present
        if tactile_obs.ndim == 3 and tactile_obs.shape[0] == 1:
            tactile_obs = tactile_obs[0]

        if tactile_obs.shape != (ROWS, COLS):
            return []

        # Threshold
        binary = (tactile_obs >= FORCE_THRESHOLD).astype(np.int32)
        if not binary.any():
            self._prev_image = tactile_obs.copy()
            return []

        # Connected components
        labelled, n_features = connected_components(binary)

        events: list[MatEvent] = []
        foot_xy = {
            "left":  left_foot_pos[:2].astype(np.float32),
            "right": right_foot_pos[:2].astype(np.float32),
        }

        for feat_id in range(1, n_features + 1):
            mask = labelled == feat_id
            area = int(mask.sum())
            total_force = float(tactile_obs[mask].sum())

            # Centroid in taxel indices
            rows_idx, cols_idx = np.where(mask)
            centroid_row = rows_idx.mean()
            centroid_col = cols_idx.mean()

            # Convert to world XY (mat coordinate convention)
            wx, wy = self._taxel_to_world(centroid_row, centroid_col)

            # Classify
            etype = self._classify(
                world_xy=(wx, wy),
                foot_xy=foot_xy,
                total_force=total_force,
                area=area,
            )

            events.append(MatEvent(
                event_type=etype,
                position=(wx, wy),
                force=total_force,
                area=area,
                timestamp=self._step,
            ))

        # Frame-difference drop detection
        if self._prev_image is not None:
            diff = tactile_obs - self._prev_image
            drop_events = self._detect_drops(diff, foot_xy, part_positions)
            events.extend(drop_events)

        self._prev_image = tactile_obs.copy()
        return events

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _taxel_to_world(row: float, col: float) -> tuple[float, float]:
        """Convert taxel indices to world XY (mat centre = origin)."""
        wx = (col - COLS / 2) * TAXEL_PITCH
        wy = (row - ROWS / 2) * TAXEL_PITCH
        return (float(wx), float(wy))

    @classmethod
    def _classify(
        cls,
        world_xy: tuple[float, float],
        foot_xy: dict[str, np.ndarray],
        total_force: float,
        area: int,
    ) -> str:
        """Classify a single connected component."""
        # Check proximity to feet
        pos = np.array(world_xy, dtype=np.float32)
        for side, fpos in foot_xy.items():
            if np.linalg.norm(pos - fpos) < FOOT_PROXIMITY:
                return f"footstep_{side}"

        # Large force + in workspace → collision (R3 fix: workspace filter; M4 fix: y-axis)
        wx, wy = world_xy
        if (total_force >= COLLISION_FORCE
                and WORKSPACE_X_RANGE[0] <= wx <= WORKSPACE_X_RANGE[1]
                and WORKSPACE_Y_RANGE[0] <= wy <= WORKSPACE_Y_RANGE[1]):
            return "collision_impact"

        return "unknown"

    def _detect_drops(
        self,
        diff: np.ndarray,
        foot_xy: dict[str, np.ndarray],
        part_positions: dict[str, np.ndarray] | None = None,
    ) -> list[MatEvent]:
        """Detect object drops from frame difference.

        M2 fix (2026-07-11): when *part_positions* is provided, matches each
        object_drop to the nearest part via FK position for part_id attribution.
        """
        events: list[MatEvent] = []
        hot = diff >= DROP_THRESHOLD
        if not hot.any():
            return events

        # Pre-extract part positions for nearest-neighbor matching.
        part_xy: list[tuple[str, np.ndarray]] = []
        if part_positions:
            for name, p in part_positions.items():
                part_xy.append((name, np.array(p[:2], dtype=np.float32)))
            # Ponytail: O(drops × parts) scan; add KD-tree if >100 parts.

        labelled, n = connected_components(hot.astype(np.int32))
        for feat_id in range(1, n + 1):
            mask = labelled == feat_id
            area = int(mask.sum())
            if area > DROP_MAX_AREA:
                continue
            total_force = float(diff[mask].sum())
            rows_idx, cols_idx = np.where(mask)
            wx, wy = self._taxel_to_world(rows_idx.mean(), cols_idx.mean())

            # Exclude foot regions
            pos = np.array([wx, wy], dtype=np.float32)
            near_foot = any(
                np.linalg.norm(pos - f) < FOOT_PROXIMITY for f in foot_xy.values()
            )
            if near_foot:
                continue

            # M3 fix: only classify as object_drop within the UR10e workspace.
            if not (WORKSPACE_X_RANGE[0] <= wx <= WORKSPACE_X_RANGE[1]
                    and WORKSPACE_Y_RANGE[0] <= wy <= WORKSPACE_Y_RANGE[1]):
                continue

            # M2 fix: match drop location to nearest part.
            # R2 L9 fix: add max distance guard — a drop more than 0.5 m from
            # any known part is likely environmental noise, not a part drop.
            matched_id = -1
            if part_xy:
                best_dist = float("inf")
                for pname, ppos in part_xy:
                    d = float(np.linalg.norm(pos - ppos))
                    if d < best_dist:
                        best_dist = d
                        try:
                            matched_id = int(pname.split("_")[-1])
                        except (ValueError, IndexError):
                            matched_id = -1
                if best_dist > 0.5:  # m — beyond this, match is unreliable
                    matched_id = -1

            events.append(MatEvent(
                event_type="object_drop",
                position=(wx, wy),
                force=float(total_force),
                area=area,
                timestamp=self._step,
                part_id=matched_id,
            ))
        return events
