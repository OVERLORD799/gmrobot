"""Kalman-filter hand trajectory prediction (S13 P2 / W9-P2).

Provides a constant-acceleration Kalman filter that fuses L1 3D hand
observations (50 Hz) with optional SAM2 /track 2D observations (~5 Hz)
to produce a predicted trajectory 0.5–2 s ahead.

Predicted positions are consumed by the replan trigger to initiate
predictive splice *before* the hand enters the envelope hard zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# State dimension: [x, y, z, vx, vy, vz, ax, ay, az]
_STATE_DIM = 9
# Observation: [x, y, z] from L1 (3D) or [x, y] from SAM2 (2D)
_OBS_DIM_3D = 3
_OBS_DIM_2D = 2
# Process noise scale (m/s² per sqrt(Hz)) — tuned for human hand motion.
_DEFAULT_PROCESS_NOISE = 1.5
# Measurement noise for L1 3D observations (m).
_DEFAULT_MEAS_NOISE_3D = 0.02
# Measurement noise for SAM2 2D observations (m in world-frame XY).
_DEFAULT_MEAS_NOISE_2D = 0.05


@dataclass
class HandTrajectoryFilterConfig:
    """Kalman filter parameters for hand trajectory prediction."""

    dt: float = 0.02  # control period (50 Hz)
    process_noise: float = _DEFAULT_PROCESS_NOISE
    meas_noise_3d: float = _DEFAULT_MEAS_NOISE_3D
    meas_noise_2d: float = _DEFAULT_MEAS_NOISE_2D
    # Prediction horizons in seconds (0 = disabled).
    prediction_horizons_s: list[float] = field(
        default_factory=lambda: [0.2, 0.5, 1.0]
    )


@dataclass
class HandTrajectoryPrediction:
    """Per-step prediction output (serialisable to CSV shadow columns)."""

    predicted_pos_at_0_2s: np.ndarray | None = None  # 3D
    predicted_pos_at_0_5s: np.ndarray | None = None
    predicted_pos_at_1_0s: np.ndarray | None = None
    # Filter covariance trace (uncertainty proxy, smaller = more confident).
    filter_cov_trace: float = 0.0
    # Position uncertainty at each horizon (1-sigma, m).  None when not computed.
    # Values > 0.10 m indicate the prediction is unreliable for gating decisions.
    uncertainty_0_2s: float | None = None
    uncertainty_0_5s: float | None = None
    uncertainty_1_0s: float | None = None
    # Number of observations received since last reset.
    filter_obs_count: int = 0
    ok: bool = False


class HandTrajectoryFilter:
    """Constant-acceleration Kalman filter for 3D hand trajectory.

    Fuses L1 3D position observations (every step) with optional
    SAM2 2D position observations (sparse, when /track returns).

    Usage per step::

        filt = HandTrajectoryFilter()
        pred = filt.update(human_hand_pos_3d)
        # Optionally fuse SAM2:
        if track_center_xy is not None:
            pred = filt.update_2d(track_center_xy)
        # Predict at horizon:
        pos_0_5s = filt.predict_at(0.5)
    """

    def __init__(self, config: HandTrajectoryFilterConfig | None = None):
        self.config = config or HandTrajectoryFilterConfig()
        self._dt = self.config.dt
        self._x: np.ndarray | None = None  # state estimate [9,]
        self._P: np.ndarray | None = None  # covariance [9,9]
        self._obs_count: int = 0
        self._F: np.ndarray | None = None  # state transition (cached)
        self._H3: np.ndarray | None = None  # 3D observation matrix
        self._H2: np.ndarray | None = None  # 2D observation matrix
        self._Q: np.ndarray | None = None   # process noise covariance
        self._R3: np.ndarray | None = None  # 3D measurement noise
        self._R2: np.ndarray | None = None  # 2D measurement noise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._x = None
        self._P = None
        self._obs_count = 0

    def update(self, pos_3d: np.ndarray) -> HandTrajectoryPrediction:
        """Fuse a 3D position observation (L1, every step)."""
        z = np.asarray(pos_3d, dtype=np.float64).reshape(-1)[:3]
        self._ensure_init(z)
        self._predict()
        self._update_3d(z)
        self._obs_count += 1
        return self._build_prediction()

    def update_2d(self, center_xy: tuple[float, float] | np.ndarray) -> HandTrajectoryPrediction:
        """Fuse a 2D position observation (SAM2 /track, sparse)."""
        z = np.asarray(center_xy, dtype=np.float64).reshape(-1)[:2]
        if self._x is None:
            # Cannot initialise from 2D alone — ignore until 3D arrives.
            return HandTrajectoryPrediction()
        self._predict()
        self._update_2d(z)
        self._obs_count += 1
        return self._build_prediction()

    def predict_at(self, horizon_s: float) -> np.ndarray | None:
        """Return predicted 3D position at ``horizon_s`` seconds ahead."""
        if self._x is None:
            return None
        k = max(1, int(round(horizon_s / self._dt)))
        Fk = np.linalg.matrix_power(self._F, k)
        x_pred = Fk @ self._x
        return x_pred[:3].copy()

    def predict_at_with_uncertainty(
        self, horizon_s: float
    ) -> tuple[np.ndarray, float] | None:
        """Return (predicted 3D position, 1-sigma position uncertainty in metres).

        The uncertainty is the sqrt of the trace of the position sub-block of the
        projected covariance matrix::

            P_k = F^k @ P @ (F^k)^T + Σ_{i=0}^{k-1} F^i @ Q @ (F^i)^T

        For horizons > 0.5 s the accumulation of process noise (Q) dominates,
        so the uncertainty grows with √k.  Callers should treat predictions
        where ``uncertainty > 0.10 m`` as low-confidence for gating.
        """
        if self._x is None or self._P is None:
            return None
        k = max(1, int(round(horizon_s / self._dt)))
        Fk = np.linalg.matrix_power(self._F, k)
        x_pred = Fk @ self._x

        # Project covariance: P_k = F^k @ P @ (F^k)^T + process noise accumulation.
        Pk = Fk @ self._P @ Fk.T
        for i in range(k):
            Fi = np.linalg.matrix_power(self._F, i)
            Pk += Fi @ self._Q @ Fi.T

        # Position uncertainty: sqrt of trace of the 3×3 position block.
        pos_var = float(np.trace(Pk[:3, :3]))
        uncertainty = float(np.sqrt(max(pos_var, 0.0)))
        return x_pred[:3].copy(), uncertainty

    @property
    def state(self) -> np.ndarray | None:
        return self._x.copy() if self._x is not None else None

    @property
    def obs_count(self) -> int:
        return self._obs_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_init(self, z: np.ndarray) -> None:
        if self._x is not None:
            return
        dt = self._dt
        # State transition (constant acceleration)
        self._F = np.eye(_STATE_DIM, dtype=np.float64)
        for i in range(3):
            self._F[i, i + 3] = dt
            self._F[i, i + 6] = 0.5 * dt * dt
            self._F[i + 3, i + 6] = dt

        # Observation matrices
        self._H3 = np.zeros((_OBS_DIM_3D, _STATE_DIM), dtype=np.float64)
        self._H3[0, 0] = self._H3[1, 1] = self._H3[2, 2] = 1.0

        self._H2 = np.zeros((_OBS_DIM_2D, _STATE_DIM), dtype=np.float64)
        self._H2[0, 0] = self._H2[1, 1] = 1.0

        # Process noise (continuous white-noise jerk model, discretised)
        q = self.config.process_noise
        dt2 = dt * dt
        dt3 = dt2 * dt
        G = np.zeros((_STATE_DIM, 3), dtype=np.float64)
        for i in range(3):
            G[i, i] = dt3 / 6.0
            G[i + 3, i] = dt2 / 2.0
            G[i + 6, i] = dt
        self._Q = (q * q) * (G @ G.T)

        # Measurement noise
        r3 = self.config.meas_noise_3d
        self._R3 = np.eye(_OBS_DIM_3D, dtype=np.float64) * (r3 * r3)
        r2 = self.config.meas_noise_2d
        self._R2 = np.eye(_OBS_DIM_2D, dtype=np.float64) * (r2 * r2)

        # Initialise state from first observation
        self._x = np.zeros(_STATE_DIM, dtype=np.float64)
        self._x[:3] = z
        self._P = np.eye(_STATE_DIM, dtype=np.float64)
        self._P[3:, 3:] *= 0.5  # lower confidence in unobserved velocity/accel

    def _predict(self) -> None:
        self._x = self._F @ self._x
        self._P = self._F @ self._P @ self._F.T + self._Q

    def _update(self, z: np.ndarray, H: np.ndarray, R: np.ndarray) -> None:
        y = z - H @ self._x  # innovation
        S = H @ self._P @ H.T + R
        # H6: regularized inverse + Joseph stabilized covariance update.
        _eps = np.eye(S.shape[0]) * 1e-8
        try:
            K = self._P @ H.T @ np.linalg.inv(S + _eps)
        except np.linalg.LinAlgError:
            return  # singular — skip update, keep current state
        self._x = self._x + K @ y
        # Joseph form: guarantees symmetry and positive-definiteness.
        I_KH = np.eye(_STATE_DIM) - K @ H
        self._P = I_KH @ self._P @ I_KH.T + K @ R @ K.T

    def _update_3d(self, z: np.ndarray) -> None:
        self._update(z, self._H3, self._R3)

    def _update_2d(self, z: np.ndarray) -> None:
        self._update(z, self._H2, self._R2)

    def _build_prediction(self) -> HandTrajectoryPrediction:
        cfg = self.config
        pred = HandTrajectoryPrediction(
            filter_cov_trace=float(np.trace(self._P)) if self._P is not None else 0.0,
            filter_obs_count=self._obs_count,
            ok=self._x is not None,
        )
        horizons = cfg.prediction_horizons_s
        if len(horizons) >= 1 and horizons[0] > 0:
            result = self.predict_at_with_uncertainty(horizons[0])
            if result is not None:
                pred.predicted_pos_at_0_2s, pred.uncertainty_0_2s = result
        if len(horizons) >= 2 and horizons[1] > 0:
            result = self.predict_at_with_uncertainty(horizons[1])
            if result is not None:
                pred.predicted_pos_at_0_5s, pred.uncertainty_0_5s = result
        if len(horizons) >= 3 and horizons[2] > 0:
            result = self.predict_at_with_uncertainty(horizons[2])
            if result is not None:
                pred.predicted_pos_at_1_0s, pred.uncertainty_1_0s = result
        return pred
