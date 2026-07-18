"""G1ArmController — sinusoidal arm joint trajectories for disturbance scenarios.

Phase 4: enables G1 to wave arms, reach forward/toward containers, and push.
The controller produces 14-D joint position offsets that are applied directly
to the G1 articulation alongside the leg walking actions.

Phase 4.1: added smooth ramp-up (0.6 s) to prevent sudden arm motions from
destabilising the robot.  Reduced extension angles to avoid table collision.

Arm motions:
    none           — arms hang at default (all zeros)
    wave           — right arm waves (elbow bent, shoulder oscillates)
    extend_forward — both arms reach forward (moderate, ramped)
    extend_left    — left arm reaches leftward
    extend_right   — right arm reaches rightward
"""

from __future__ import annotations

import numpy as np

# G1 arm joint indices in the 29-DOF articulation.
ARM_JOINT_INDICES = [11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
assert len(ARM_JOINT_INDICES) == 14, f"Expected 14 arm joints, got {len(ARM_JOINT_INDICES)}"
assert max(ARM_JOINT_INDICES) <= 28, f"Max arm joint index {max(ARM_JOINT_INDICES)} exceeds G1 29-DOF range"

# Per-arm index slices into the 14-D arm action.
_LEFT_IDX  = [0, 2, 4, 6,  8, 10, 12]   # sp, sr, sy, eb, wr, wp, wy
_RIGHT_IDX = [1, 3, 5, 7,  9, 11, 13]

# Joint limits for safety (radians) — per-joint (min, max).
# Order matches ARM_JOINT_INDICES interleaving: left shoulder_pitch,
# right shoulder_pitch, left shoulder_roll, right shoulder_roll, ...
_ARM_LIMIT_LO = np.array([
    -2.0, -2.0,   # shoulder_pitch L/R
    -1.5, -1.5,   # shoulder_roll  L/R
    -1.0, -1.0,   # shoulder_yaw   L/R
     0.0,  0.0,   # elbow          L/R
    -1.5, -1.5,   # wrist_roll     L/R
    -1.5, -1.5,   # wrist_pitch    L/R
    -1.0, -1.0,   # wrist_yaw      L/R
], dtype=np.float32)

_ARM_LIMIT_HI = np.array([
     0.5,  0.5,   # shoulder_pitch L/R
     1.5,  1.5,   # shoulder_roll  L/R
     1.0,  1.0,   # shoulder_yaw   L/R
     2.0,  2.0,   # elbow          L/R
     1.5,  1.5,   # wrist_roll     L/R
     1.5,  1.5,   # wrist_pitch    L/R
     1.0,  1.0,   # wrist_yaw      L/R
], dtype=np.float32)

# Ramp-up duration for smooth motion onset (seconds).
RAMP_DURATION = 1.0  # s — slow enough to not destabilise G1


class G1ArmController:
    """Produces 14-D arm joint position OFFSETS from default pose.

    Usage per env step::

        t = step_in_phase * 0.02   # seconds into current motion
        offsets = arm_ctrl.get_action(t, motion="extend_forward")
        arm_ctrl.apply(g1, offsets, device)
    """

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_action(self, t: float, motion: str = "none") -> np.ndarray:
        """Return (14,) arm joint offsets for the given motion and elapsed time.

        Args:
            t: seconds elapsed since the START of the **current motion**
                (NOT global step).  Used for sinusoidal phase and ramp-up.
            motion: one of "none", "wave", "extend_forward", "extend_left",
                    "extend_right".

        Returns:
            (14,) float32 array of joint position OFFSETS from default.
        """
        action = np.zeros(14, dtype=np.float32)

        if motion == "none":
            pass  # all zeros → default pose
        elif motion == "wave":
            action = self._wave(t)
        elif motion == "extend_forward":
            action = self._extend_forward(t)
        elif motion == "extend_left":
            action = self._extend_left(t)
        elif motion == "extend_right":
            action = self._extend_right(t)
        else:
            raise ValueError(f"Unknown arm motion: {motion}")

        return action

    def apply(self, g1_articulation, offsets: np.ndarray):
        """Write arm joint targets to the G1 articulation, clamped to limits."""
        import torch
        current_targets = g1_articulation.data.joint_pos_target[0].clone()
        defaults = g1_articulation.data.default_joint_pos[0]
        for i, joint_idx in enumerate(ARM_JOINT_INDICES):
            # Keep as tensor (don't .item()) — assigning Python float to CUDA
            # tensor index fails in some PyTorch versions.
            target = defaults[joint_idx] + float(offsets[i])
            lo = torch.tensor(_ARM_LIMIT_LO[i], device=target.device, dtype=target.dtype)
            hi = torch.tensor(_ARM_LIMIT_HI[i], device=target.device, dtype=target.dtype)
            target = torch.clamp(target, lo, hi)
            current_targets[joint_idx] = target
        g1_articulation.set_joint_position_target(current_targets.unsqueeze(0))

    # ------------------------------------------------------------------
    # Ramp helper
    # ------------------------------------------------------------------

    @staticmethod
    def _ramp(t: float) -> float:
        """Smooth 0→1 ramp over RAMP_DURATION seconds."""
        if t <= 0.0:
            return 0.0
        if t >= RAMP_DURATION:
            return 1.0
        # Smoothstep easing
        x = t / RAMP_DURATION
        return x * x * (3.0 - 2.0 * x)

    # ------------------------------------------------------------------
    # Motion primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _wave(t: float) -> np.ndarray:
        """Right arm wave: elbow bent, gentle shoulder oscillation."""
        a = np.zeros(14, dtype=np.float32)
        ramp = G1ArmController._ramp(t)
        phase = np.sin(t * 4.0)  # ~0.64 Hz

        # Right shoulder pitch: small oscillation, ramped
        a[_RIGHT_IDX[0]] = ramp * (-0.4 + 0.25 * phase)  # -0.65 to -0.15
        # Right elbow: bent
        a[_RIGHT_IDX[3]] = ramp * 1.0
        return a

    @staticmethod
    def _extend_forward(t: float) -> np.ndarray:
        """Both arms reach forward — gentle, ramped, with elbows bent for stability."""
        a = np.zeros(14, dtype=np.float32)
        ramp = G1ArmController._ramp(t)

        # Shoulder pitch: -0.6 max (gentle reach, won't hit table or tip G1)
        a[_LEFT_IDX[0]]  = ramp * -0.6
        a[_RIGHT_IDX[0]] = ramp * -0.6
        # Elbows: bent (keeps centre of mass closer to body)
        a[_LEFT_IDX[3]]  = ramp * 0.8
        a[_RIGHT_IDX[3]] = ramp * 0.8
        return a

    @staticmethod
    def _extend_left(t: float) -> np.ndarray:
        """Left arm reaches toward left/container-A side."""
        a = np.zeros(14, dtype=np.float32)
        ramp = G1ArmController._ramp(t)

        a[_LEFT_IDX[0]] = ramp * -0.5   # shoulder_pitch
        a[_LEFT_IDX[1]] = ramp * 0.4    # shoulder_roll
        a[_LEFT_IDX[3]] = ramp * 0.8    # elbow (bent)
        return a

    @staticmethod
    def _extend_right(t: float) -> np.ndarray:
        """Right arm reaches toward right/container-B side."""
        a = np.zeros(14, dtype=np.float32)
        ramp = G1ArmController._ramp(t)

        a[_RIGHT_IDX[0]] = ramp * -0.5  # shoulder_pitch
        a[_RIGHT_IDX[1]] = ramp * -0.4  # shoulder_roll
        a[_RIGHT_IDX[3]] = ramp * 0.8   # elbow (bent)
        return a
