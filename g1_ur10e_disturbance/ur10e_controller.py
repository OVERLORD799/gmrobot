"""UR10e pick-and-place controller — wraps GMRobot's SingleEnvPickAndPlacePolicy."""

from __future__ import annotations

import numpy as np

from scripts.pick_and_place_policy import SingleEnvPickAndPlacePolicy


class UR10eController:
    """Thin wrapper around GMRobot's SingleEnvPickAndPlacePolicy.

    Manages the policy lifecycle (init, reset, per-step action, success
    detection) and handles CUDA→CPU observation conversion.
    """

    def __init__(self):
        self._policy = SingleEnvPickAndPlacePolicy()
        self._step_counter = 0
        self._parts_placed = 0
        # C4 fix: track parts_placed by watching stage-name transitions
        # instead of dividing time_step by a hardcoded constant.
        self._last_stage: str = ""
        self._completed_stages: set = set()

    # ------------------------------------------------------------------
    # Observation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def cpu_obs(obs_dict: dict) -> dict:
        """Convert a CUDA-tensor observation dict to CPU numpy, squeezing the
        batch dimension so the single-env policy receives unbatched arrays."""
        result = {}
        for k, v in obs_dict.items():
            if hasattr(v, "cpu"):
                v = v.cpu().numpy()
            if isinstance(v, np.ndarray) and v.ndim >= 2 and v.shape[0] == 1:
                v = v[0]
            result[k] = v
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self, ur10e_policy_obs: dict):
        """Build the stage sequence from the current environment observations.

        Args:
            ur10e_policy_obs: obs["ur10e_policy"] dict (may contain CUDA tensors).
        """
        self._policy.reset(self.cpu_obs(ur10e_policy_obs))
        self._step_counter = 0
        self._parts_placed = 0
        self._last_stage = ""
        self._completed_stages = set()

    def get_action(self, ur10e_policy_obs: dict, *, advance: bool = True) -> np.ndarray:
        """Return the next 8-D action ``[x, y, z, qw, qx, qy, qz, gripper]``.

        Args:
            ur10e_policy_obs: obs["ur10e_policy"] dict.
            advance: if True (default), increment the policy clock after
                     computing the action.

        Returns:
            (8,) float32 numpy array.
        """
        action = self._policy.get_action(self.cpu_obs(ur10e_policy_obs), advance=advance)
        if advance:
            self._step_counter += 1
        # R5 H5 fix: always track stage transitions — when advance=False the
        # clock is advanced later via advance(), and stage changes must still
        # be detected.  The tracker is idempotent (same-stage no-ops) so
        # calling it on every get_action is safe.
        self._track_stage()
        return action

    def advance(self):
        """Manually advance the policy clock (use when advance=False was passed)."""
        self._policy.advance_time_step()
        # R5 H5 fix: detect stage transitions that happened during the
        # externally-advanced step.  Without this, parts_placed stays at 0
        # for the entire safety-gated episode.
        self._track_stage()

    def _track_stage(self):
        """Update _completed_stages and _last_stage from current policy stage.

        Idempotent — repeated calls at the same stage are no-ops.  Transitions
        out of any ``lift_after_releasing_*`` stage increment the completed-parts
        counter (R2 L4 fix: was hardcoded to ``slot_B_`` — now works with any
        container name in ``user_commands``).
        """
        current = self.stage_name
        if "lift_after_releasing_" in self._last_stage and current != self._last_stage:
            self._completed_stages.add(self._last_stage)
        self._last_stage = current
        # Sanity: after 400 steps with no parts placed, something is wrong.
        if self._step_counter >= 400 and len(self._completed_stages) == 0:
            import warnings
            warnings.warn(
                "[GMDisturb] UR10eController: 400+ steps with 0 parts placed. "
                "Stage naming may have changed upstream — check GMRobot."
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def success(self) -> bool:
        return self._policy.success

    @property
    def time_step(self) -> int:
        return self._policy.time_step

    @property
    def step_counter(self) -> int:
        return self._step_counter

    @property
    def parts_placed(self) -> int:
        """Number of parts whose full pick-and-place cycle has completed.

        C4 fix: counts unique ``lift_after_releasing_slot_B_*`` stages that
        have been passed, rather than dividing ``time_step`` by a hardcoded
        constant (which breaks when safety interventions delay progress).
        """
        return len(self._completed_stages)

    @property
    def stage_name(self) -> str:
        return self._policy.stage_name_at_step(self._policy.time_step)

    @property
    def transport_phase(self) -> str:
        """Transport phase for replan trigger: 'approach' | 'transit' | 'place'.

        Delegates to the vendored policy's ``transport_phase_at_step``.
        """
        return self._policy.transport_phase_at_step(self._policy.time_step)

    @property
    def is_grasping(self) -> bool:
        """True when the gripper is closed and holding a part.

        The grasp spans from ``close_gripper_*`` through
        ``descend_to_box_with_*`` (i.e., before the release-open stage).
        """
        name = self.stage_name
        if "open_gripper" in name or "lift_after_releasing" in name:
            return False
        return any(
            kw in name
            for kw in ("close_gripper", "grasp_", "lift_", "move_above_box", "descend_to_box")
        )

    @property
    def total_parts(self) -> int:
        return len(self._policy.user_commands)
