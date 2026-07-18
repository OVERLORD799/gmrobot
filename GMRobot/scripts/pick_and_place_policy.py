"""Scripted pick-and-place policy (no Isaac Sim dependency)."""

from __future__ import annotations

import logging

import numpy as np
from scipy.spatial.transform import Rotation as R

HOME_POSITION = np.array([0.9, 0.0, 0.4], dtype=np.float32)

APPROACH_HEIGHT = 0.40
GRASP_HEIGHT = 0.13

DEFAULT_STAGE_DURATION = 50
GRIPPER_CLOSE_DURATION = 1
GRIPPER_OPEN_DURATION = 20

GRIPPER_OPEN = 1.0
GRIPPER_CLOSED = -0.5

PLACE_ZONE_RADIUS_M = 0.08

# Grasp validation before transport (knock-off / misalignment recovery).
GRASP_XY_TOLERANCE_M = 0.06
GRASP_Z_TOLERANCE_M = 0.10
GRASP_UPRIGHT_MIN_DOT = 0.94  # ~20° max tilt from upright
PLACE_RELEASE_UPRIGHT_MIN_DOT = -1.0  # effectively disabled: any orientation allowed during place release
PLACE_RELEASE_XY_TOLERANCE_M = GRASP_XY_TOLERANCE_M * 0.65
# Relaxed Z tolerance for place release: during placement the part may
# already be resting in the container while the EE is still descending.
# Gripper re-close after commit is prevented by _release_gripper_committed.
PLACE_RELEASE_Z_TOLERANCE_M = 0.30
GRASP_MAX_REWIND_ATTEMPTS = 2
# Max VLM-triggered retries per part before falling back to skip-abort.
VLM_MAX_RETRIES = 2
# If human hand gets within this distance (m) of the held-object bounding sphere
# during carry AND the safety gate triggered STOP, treat it as a probable knock-off.
# MUST be <= safe_dist_hard_stop to filter out false positives from distant STOPS.
# Typical safe_dist_hard_stop is 0.10–0.15 m; the held sphere is ~0.04 m radius,
# so the hand centre is ~0.04 m closer to the held sphere than to the EE point
# used by the safety gate.  A value of ~0.5×safe_dist_hard_stop catches real
# knocks while rejecting most near-miss STOPS.
HAND_KNOCK_DIST_M = 0.06
# Steps to wait after a grasp disturbance before allowing commit/hold-validation,
# so the physics engine has time to propagate the knock-off before we check.
GRASP_DISTURBANCE_COOLDOWN_STEPS = 5
# Extra steps to hold at the approach (move_above) pose during grasp recovery
# rewinds, giving the controller time to servo the EE orientation to the
# correct pick yaw before descending.  Prevents "姿态不正" (misaligned
# gripper) that causes consecutive re-grasp failures.
GRASP_STABILIZE_HOLD_STEPS = 60
# Extra steps to hold at the place pose before opening the gripper,
# giving the controller time to converge after a replan detour.
PLACE_STABILIZE_HOLD_STEPS = 30
# EE above this height is treated as lift/ascent — never rewind to pick descend.
GRASP_ASCENT_COMMIT_Z_M = GRASP_HEIGHT + 0.05

ACTION_DIM = 8

DEFAULT_TOOL_QUAT = np.array([0.0, -0.70711, 0.70711, 0.0], dtype=np.float32)

DEFAULT_USER_COMMANDS = [
    {"pick": f"A@{i}", "place": f"B@{i}"} for i in range(1, 21)
]

_log = logging.getLogger(__name__)


class SingleEnvPickAndPlacePolicy:
    """Scripted pick-and-place policy for a single environment."""

    def __init__(self):
        self.user_commands = DEFAULT_USER_COMMANDS
        self.gripper_open = GRIPPER_OPEN
        self.gripper_closed = GRIPPER_CLOSED

        self.success = False
        self.stage_sequence = []
        self.pos_traj = None
        self.yaw_traj = None
        self.gripper_traj = None
        self.time_stamps = None
        self.time_step = 0
        self._place_progress_hold = False
        self._place_progress_hold_start_step: int = -1
        self._place_stabilize_hold_steps = 0
        self._grasp_disturbance_pending = False
        self._grasp_disturbance_step = -1
        self._grasp_rewind_attempts = 0
        self._grasp_rewind_event = ""
        self._grasp_rewind_force_open = False
        self._grasp_hold_validated = False
        self._grasp_carry_aborted = False
        self._vlm_retry_count = 0
        self._release_gripper_committed = False
        self._stabilize_hold_steps: int = 0
        self._place_stabilize_hold_steps: int = 0

    def _build_stage_sequence(self, obs):
        """Build the scripted pick-and-place stage sequence from observations."""
        stage_sequence = [
            {
                "name": "start",
                "pos": HOME_POSITION.copy(),
                "yaw": 0.0,
                "gripper": self.gripper_open,
                "duration": DEFAULT_STAGE_DURATION,
            },
        ]

        for command in self.user_commands:
            pick_container, pick_slot = command["pick"].split("@")
            place_container, place_slot = command["place"].split("@")

            pick_name = f"slot_{pick_container}_{pick_slot}"
            place_name = f"slot_{place_container}_{place_slot}"

            pick_transform = np.array(obs[f"{pick_name}_T"])
            pick_pos = pick_transform[:3, 3].copy()
            pick_pos[-1] = 0.0
            pick_yaw = np.arctan2(pick_transform[1, 0], pick_transform[0, 0])

            place_transform = np.array(obs[f"{place_name}_T"])
            place_pos = place_transform[:3, 3].copy()
            place_pos[-1] = 0.0
            place_yaw = np.arctan2(place_transform[1, 0], place_transform[0, 0])

            stage_sequence += [
                {
                    "name": f"move_above_{pick_name}",
                    "pos": pick_pos + np.array([0.0, 0.0, APPROACH_HEIGHT]),
                    "yaw": -pick_yaw,
                    "gripper": self.gripper_open,
                    "duration": DEFAULT_STAGE_DURATION,
                },
                {
                    "name": f"descend_to_{pick_name}",
                    "pos": pick_pos + np.array([0.0, 0.0, GRASP_HEIGHT]),
                    "yaw": -pick_yaw,
                    "gripper": self.gripper_open,
                    "duration": DEFAULT_STAGE_DURATION,
                },
                {
                    "name": f"close_gripper_{pick_name}",
                    "pos": pick_pos + np.array([0.0, 0.0, GRASP_HEIGHT]),
                    "yaw": -pick_yaw,
                    "gripper": self.gripper_closed,
                    "duration": GRIPPER_CLOSE_DURATION,
                },
                {
                    "name": f"grasp_{pick_name}",
                    "pos": pick_pos + np.array([0.0, 0.0, GRASP_HEIGHT]),
                    "yaw": -pick_yaw,
                    "gripper": self.gripper_closed,
                    "duration": DEFAULT_STAGE_DURATION,
                },
                {
                    "name": f"lift_{pick_name}",
                    "pos": pick_pos + np.array([0.0, 0.0, APPROACH_HEIGHT]),
                    "yaw": -pick_yaw,
                    "gripper": self.gripper_closed,
                    "duration": DEFAULT_STAGE_DURATION,
                },
                {
                    "name": f"move_above_box_with_{place_name}",
                    "pos": place_pos + np.array([0.0, 0.0, APPROACH_HEIGHT]),
                    "yaw": -place_yaw,
                    "gripper": self.gripper_closed,
                    "duration": DEFAULT_STAGE_DURATION,
                },
                {
                    "name": f"descend_to_box_with_{place_name}",
                    "pos": place_pos + np.array([0.0, 0.0, GRASP_HEIGHT]),
                    "yaw": -place_yaw,
                    "gripper": self.gripper_closed,
                    "duration": DEFAULT_STAGE_DURATION,
                },
                {
                    "name": f"open_gripper_to_release_{place_name}",
                    "pos": place_pos + np.array([0.0, 0.0, GRASP_HEIGHT]),
                    "yaw": 0.0,
                    "gripper": self.gripper_open,
                    "duration": GRIPPER_OPEN_DURATION,
                },
                {
                    "name": f"lift_after_releasing_{place_name}",
                    "pos": place_pos + np.array([0.0, 0.0, APPROACH_HEIGHT]),
                    "yaw": 0.0,
                    "gripper": self.gripper_open,
                    "duration": DEFAULT_STAGE_DURATION,
                },
            ]

        return stage_sequence

    def _build_trajectory(self, stage_sequence):
        """Convert a stage sequence into waypoint trajectories and time stamps."""
        pos_traj = []
        yaw_traj = []
        gripper_traj = []
        time_stamps = []

        current_time = 0
        for stage in stage_sequence:
            pos_traj.append(stage["pos"])
            yaw_traj.append(stage["yaw"])
            gripper_traj.append(stage["gripper"])
            time_stamps.append(current_time)
            current_time += stage["duration"]

        # F17: unwrap yaw to prevent linear interpolation across the ±π
        # discontinuity.  Without this, two waypoints at e.g. +179° and -179°
        # would interpolate through 0° (wrong) instead of staying near ±180°.
        yaw_arr = np.unwrap(np.array(yaw_traj))

        return (
            np.array(pos_traj),
            yaw_arr,
            np.array(gripper_traj),
            np.array(time_stamps),
        )

    def reset(self, obs):
        """Reset the policy state using the latest observation."""
        self.success = False
        self.stage_sequence = self._build_stage_sequence(obs)
        (
            self.pos_traj,
            self.yaw_traj,
            self.gripper_traj,
            self.time_stamps,
        ) = self._build_trajectory(self.stage_sequence)
        self.time_step = 0
        self._place_progress_hold = False
        self._place_progress_hold_start_step: int = -1
        self._place_stabilize_hold_steps = 0
        self._grasp_disturbance_pending = False
        self._grasp_disturbance_step = -1
        self._grasp_rewind_attempts = 0
        self._grasp_rewind_event = ""
        self._grasp_rewind_force_open = False
        self._grasp_hold_validated = False
        self._grasp_carry_aborted = False
        self._vlm_retry_count = 0
        self._release_gripper_committed = False
        self._stabilize_hold_steps = 0

    def consume_grasp_rewind_event(self) -> str:
        """Return and clear the latest grasp rewind observability event."""
        event = self._grasp_rewind_event
        self._grasp_rewind_event = ""
        return event

    @staticmethod
    def _pose_position(pose: np.ndarray) -> np.ndarray:
        """Extract world XYZ from a 7D pose or flattened 4x4 transform."""
        arr = np.asarray(pose, dtype=np.float64).reshape(-1)
        if arr.size >= 7:
            return arr[:3].copy()
        if arr.size >= 16:
            return arr.reshape(4, 4)[:3, 3].copy()
        return arr[:3].copy()

    @staticmethod
    def _pose_upright_dot(pose: np.ndarray) -> float:
        """Dot(part_local_z, world_z); 1.0 when the part stands upright."""
        arr = np.asarray(pose, dtype=np.float64).reshape(-1)
        if arr.size >= 7:
            rot = R.from_quat(arr[3:7], scalar_first=True)
        elif arr.size >= 16:
            rot = R.from_matrix(arr.reshape(4, 4)[:3, :3])
        else:
            return 1.0
        part_z = rot.apply([0.0, 0.0, 1.0])
        return float(part_z[2])

    def is_in_grasp_window(self, step: int) -> bool:
        """True during close / hold — after EE reaches grasp height, before lift."""
        name = self.stage_name_at_step(step)
        return name.startswith("close_gripper_") or name.startswith("grasp_")

    def _is_pick_lift_stage(self, step: int) -> bool:
        """True during pick-side ascent (``lift_slot_*``), not post-release lift."""
        name = self.stage_name_at_step(step)
        return name.startswith("lift_") and not name.startswith("lift_after_releasing_")

    def _close_gripper_start_step(self, part_idx: int) -> int | None:
        prefix = f"close_gripper_slot_"
        for i, stage in enumerate(self.stage_sequence):
            if not stage["name"].startswith(prefix):
                continue
            for token in stage["name"].split("_"):
                if token.isdigit() and int(token) == part_idx:
                    return int(self.time_stamps[i])
        return None

    def _move_above_pick_start_step(self, part_idx: int) -> int | None:
        """Task step where EE arrives above pick slot for ``part_idx``."""
        prefix = "move_above_slot_"
        for i, stage in enumerate(self.stage_sequence):
            if not stage["name"].startswith(prefix):
                continue
            for token in stage["name"].split("_"):
                if token.isdigit() and int(token) == part_idx:
                    return int(self.time_stamps[i])
        return None

    def _descend_to_pick_start_step(self, part_idx: int) -> int | None:
        """Task step where EE begins descending to grasp height for ``part_idx``."""
        prefix = "descend_to_slot_"
        for i, stage in enumerate(self.stage_sequence):
            if not stage["name"].startswith(prefix):
                continue
            for token in stage["name"].split("_"):
                if token.isdigit() and int(token) == part_idx:
                    return int(self.time_stamps[i])
        return None

    def _grasp_rewind_target_step(self, part_idx: int) -> int | None:
        """Rewind to open-gripper descend so knock-off can re-close on the piece."""
        return self._descend_to_pick_start_step(part_idx)

    def is_grasp_hold_validated(self) -> bool:
        """True after lift-entry grasp check passed; suppresses rewind during carry."""
        return self._grasp_hold_validated

    def should_force_open_gripper(self) -> bool:
        """True while replaying pick descend after a failed-grasp rewind."""
        if self._grasp_hold_validated:
            return False
        if self._grasp_carry_aborted:
            return True
        return self._grasp_rewind_force_open

    def peek_action(self) -> np.ndarray:
        """Action for ``time_step + 1`` without advancing the trajectory clock."""
        action = self._action_at_step(self.time_step + 1)
        action[7] = self._gripper_for_proposed_action()
        return action

    def note_grasp_disturbance(self) -> None:
        """Latch collision/knock during grasp window; cleared on valid re-grasp."""
        if self._grasp_hold_validated or self._grasp_carry_aborted:
            return
        self._grasp_disturbance_pending = True
        self._grasp_disturbance_step = self.time_step

    def note_carry_knock_if_hit(
        self,
        dist_min_held: float | None,
        step: int,
    ) -> bool:
        """Fast physics-based knock-off detection → immediate rewind.

        Called on EVERY STOP during carry (even after grasp validation).
        If ``dist_min_held`` indicates the human hand touched the held object,
        this directly rewinds the policy clock to the pick-approach phase for
        the current part — no cooldown, no pending-flag dance.

        Rewinds to the **start** of ``move_above`` (not ``descend``) and
        inserts a stabilisation hold so the controller has time to servo the
        EE orientation to the correct pick yaw before descending.  Without this
        hold the gripper arrives at grasp height with a skewed orientation
        ("姿态不正"), causing consecutive re-grasp failures.

        This is ~300× faster than waiting for VLM confirmation and works at
        ALL carry stages (lift, transit, descend-to-place).
        """
        if self._grasp_carry_aborted:
            return False
        if dist_min_held is None:
            return False
        if float(dist_min_held) > HAND_KNOCK_DIST_M:
            return False
        if not self.is_carrying_object(step):
            return False

        # Find the rewind target for the current part.
        part_idx = self.part_index_at_step(self.time_step)
        if part_idx is None:
            return False

        # Rewind to move_above (approach height, correct pick yaw) so the
        # controller has time to stabilise orientation before descending.
        rewind_step = self._move_above_pick_start_step(part_idx)
        if rewind_step is None or rewind_step >= self.time_step:
            return False

        # Hand touched the held object — likely knock-off.
        # Execute an immediate rewind to re-pick the same part.
        self._grasp_hold_validated = False
        self._grasp_disturbance_pending = True
        self._grasp_disturbance_step = -1   # no cooldown — physics already confirmed
        self._grasp_rewind_attempts = 0
        self._grasp_rewind_force_open = True
        self._grasp_rewind_event = "knock_rewind"
        self._stabilize_hold_steps = GRASP_STABILIZE_HOLD_STEPS
        self.time_step = max(0, rewind_step - 1)
        return True

    def should_latch_grasp_disturbance(
        self,
        step: int,
        *,
        replan_active: bool = False,
    ) -> bool:
        """True when a gate STOP should latch knock-off for grasp rewind.

        Includes pick-side ``lift_*`` (ivj Part 5 mid-lift knock-off) until carry
        is validated; suppresses false positives during detour replay.
        """
        if self._grasp_hold_validated or self._grasp_carry_aborted:
            return False
        if replan_active or self._grasp_rewind_force_open:
            return False
        if self._is_pick_lift_stage(step):
            return True
        if not self.is_in_grasp_window(step):
            return False
        name = self.stage_name_at_step(step)
        if name.startswith("close_gripper_"):
            return True
        return name.startswith("grasp_") and self._is_at_grasp_depth_step(step)

    def on_replan_splice_applied(self, task_step: int) -> None:
        """Clear stale grasp rewind state after detour splice (pick approach or transit carry)."""
        phase = self.transport_phase_at_step(task_step)
        if phase not in ("approach", "transit"):
            return
        if phase == "transit" and self._grasp_hold_validated:
            return
        if self.is_in_grasp_window(task_step):
            return
        if (
            self._grasp_disturbance_pending
            and self._is_pick_lift_stage(task_step)
            and not self._grasp_hold_validated
        ):
            return
        self.clear_grasp_disturbance()

    def should_advance_empty_carry_abort(self, step: int) -> bool:
        """Allow scripted advance through entire carry/place after abort (empty claw).

        When the grasped object is confirmed lost (VLM supervisor or exhausted
        rewind), the policy clock must skip through *all* remaining carry and
        place stages — including ``descend_to_box_with_*`` and
        ``open_gripper_to_release_*`` — so the robot does not hover indefinitely
        above the target box with an open empty gripper.
        """
        if not self._grasp_carry_aborted:
            return False
        name = self.stage_name_at_step(step)
        return name.startswith((
            "lift_",
            "move_above_box_with_",
            "descend_to_box_with_",
            "open_gripper_to_release_",
            "lift_after_releasing_",
        ))

    def clear_grasp_disturbance(self) -> None:
        """Clear rewind/disturbance state without confirming a successful carry grasp."""
        self._grasp_disturbance_pending = False
        self._grasp_disturbance_step = -1
        self._grasp_rewind_attempts = 0
        self._grasp_rewind_force_open = False
        self._stabilize_hold_steps = 0

    def mark_grasp_hold_validated(self) -> None:
        """Latch successful grasp validation; stops lift/carry grasp re-checks."""
        self.clear_grasp_disturbance()
        self._grasp_hold_validated = True
        self._vlm_retry_count = 0  # new part — fresh retry budget

    def trigger_vlm_retry_current_part(self) -> bool:
        """VLM detected lost object — rewind to re-pick the **same** part.

        Unlike ``_grasp_carry_aborted`` which skips to the next part, this
        rewinds the policy clock to the approach phase of the current part so
        the robot can try picking it again.  Returns True if the rewind
        succeeded.

        Rewinds to the **start** of ``move_above`` (not ``descend``) and
        inserts a stabilisation hold so the controller has time to servo the
        EE orientation to the correct pick yaw before descending.

        After ``VLM_MAX_RETRIES`` the retry is refused and the caller should
        fall back to ``_grasp_carry_aborted``.
        """
        if self._grasp_carry_aborted:
            return False
        if self._vlm_retry_count >= VLM_MAX_RETRIES:
            return False
        part_idx = self.part_index_at_step(self.time_step)
        if part_idx is None:
            return False
        rewind_step = self._move_above_pick_start_step(part_idx)
        if rewind_step is None or rewind_step >= self.time_step:
            return False
        # Reset grasp state so the re-approach looks like a fresh pick.
        self._grasp_hold_validated = False
        self._grasp_disturbance_pending = True
        self._grasp_disturbance_step = -1   # no cooldown — VLM already confirmed loss
        self._grasp_rewind_attempts = 0
        self._grasp_rewind_force_open = True
        self._grasp_rewind_event = "vlm_retry"
        self._stabilize_hold_steps = GRASP_STABILIZE_HOLD_STEPS
        self._vlm_retry_count += 1
        self.time_step = max(0, rewind_step - 1)
        return True

    @staticmethod
    def validate_grasp_hold(
        ee_pos: np.ndarray,
        part_pose: np.ndarray | None,
        *,
        xy_tolerance_m: float = GRASP_XY_TOLERANCE_M,
        z_tolerance_m: float = GRASP_Z_TOLERANCE_M,
        upright_min_dot: float = GRASP_UPRIGHT_MIN_DOT,
        disturbance_pending: bool = False,
    ) -> bool:
        """Return True when the active part is aligned with EE for a closed grasp.

        When ``disturbance_pending`` is True the Z tolerance is always enforced —
        a part that was knocked off may bounce or rest at an unexpected height.
        """
        if part_pose is None:
            _log.warning(
                "validate_grasp_hold: part_pose missing; cannot verify grasp alignment"
            )
            return True
        part_pos = SingleEnvPickAndPlacePolicy._pose_position(part_pose)
        ee = np.asarray(ee_pos, dtype=np.float64).reshape(-1)[:3]
        delta = part_pos - ee
        if float(np.linalg.norm(delta[:2])) > xy_tolerance_m:
            return False
        ee_z = float(ee[2])
        part_z = float(part_pos[2])
        carrying = (
            ee_z > GRASP_ASCENT_COMMIT_Z_M and part_z > GRASP_ASCENT_COMMIT_Z_M
        )
        if disturbance_pending:
            # Knock-off suspected — always enforce Z, even during apparent carry.
            # The part may be bouncing or resting on a box edge above ascent Z.
            if abs(float(delta[2])) > z_tolerance_m:
                return False
        elif not carrying:
            if abs(float(delta[2])) > z_tolerance_m:
                return False
        if SingleEnvPickAndPlacePolicy._pose_upright_dot(part_pose) < upright_min_dot:
            return False
        return True

    def _scripted_ee_z(self, step: int) -> float:
        """Scripted EE Z from the precomputed trajectory at ``step``."""
        return float(self._action_at_step(step)[2])

    def _is_at_grasp_depth_step(self, step: int) -> bool:
        """True while scripted EE is still near pick grasp height (before lift blend)."""
        return self._scripted_ee_z(step) <= GRASP_ASCENT_COMMIT_Z_M

    def _should_commit_grasp_carry(
        self,
        ee_pos: np.ndarray,
        part_pose: np.ndarray | None,
        step: int,
    ) -> bool:
        """True when both EE and part are lifted — skip descend rewind during carry.

        Enforces a cooldown after disturbance so the physics engine has time to
        propagate knock-off before we commit the grasp as validated.
        """
        if self._grasp_hold_validated:
            return True
        if not self.needs_grasp_validation(step):
            return False
        if part_pose is None:
            return False
        # Wait for physics to settle after a knock-off before trusting the part pose.
        if (
            self._grasp_disturbance_step >= 0
            and step - self._grasp_disturbance_step < GRASP_DISTURBANCE_COOLDOWN_STEPS
        ):
            return False
        ee_z = float(np.asarray(ee_pos, dtype=np.float64).reshape(-1)[2])
        part_z = float(self._pose_position(part_pose)[2])
        return (
            ee_z > GRASP_ASCENT_COMMIT_Z_M
            and part_z > GRASP_ASCENT_COMMIT_Z_M
        )

    def needs_grasp_validation(self, step: int) -> bool:
        """True after knock-off latch, at grasp depth or lift boundary.

        Validates at close_gripper / early grasp (before EE rises) and at lift
        entry. Includes ``step + 1`` so validation runs before lift is proposed.

        Defers validation during the disturbance cooldown window so the physics
        engine has time to propagate knock-off before we check the part pose.
        """
        if self._grasp_hold_validated:
            return False
        if not self._grasp_disturbance_pending:
            return False
        # Wait for physics to settle — part pose may be stale on the knock frame.
        if (
            self._grasp_disturbance_step >= 0
            and step - self._grasp_disturbance_step < GRASP_DISTURBANCE_COOLDOWN_STEPS
        ):
            return False
        for check in (step, step + 1):
            name = self.stage_name_at_step(check)
            if name.startswith("close_gripper_"):
                return True
            if name.startswith("grasp_") and self._is_at_grasp_depth_step(check):
                return True
            if self._is_pick_lift_stage(check):
                return True
        return False

    def maybe_rewind_for_failed_grasp(
        self,
        ee_pos: np.ndarray,
        part_pose: np.ndarray | None,
        step: int,
    ) -> bool:
        """Rewind to pick descend when grasp is incomplete; returns True if rewound."""
        if self._grasp_hold_validated:
            return False
        if not self.needs_grasp_validation(step):
            return False
        if self._should_commit_grasp_carry(ee_pos, part_pose, step):
            self.mark_grasp_hold_validated()
            return False
        if part_pose is not None and self.validate_grasp_hold(ee_pos, part_pose):
            self.mark_grasp_hold_validated()
            return False

        if self._grasp_rewind_attempts >= GRASP_MAX_REWIND_ATTEMPTS:
            _log.warning(
                "Grasp rewind exhausted after %d attempts at task_step=%d; "
                "proceeding without re-grasp",
                GRASP_MAX_REWIND_ATTEMPTS,
                step,
            )
            self._grasp_rewind_event = "exhausted"
            self._grasp_carry_aborted = True
            self.clear_grasp_disturbance()
            return False

        part_idx = self.part_index_at_step(step)
        if part_idx is None:
            return False
        # Rewind to move_above (approach height) so the controller has time to
        # stabilise orientation before descending to re-grasp.
        rewind_step = self._move_above_pick_start_step(part_idx)
        if rewind_step is None:
            # Fallback: use descend start if move_above not found (shouldn't happen).
            rewind_step = self._grasp_rewind_target_step(part_idx)
        if rewind_step is None or rewind_step >= step:
            return False

        self.time_step = max(0, rewind_step - 1)
        self._grasp_rewind_attempts += 1
        self._grasp_rewind_force_open = True
        self._grasp_rewind_event = "rewind"
        self._stabilize_hold_steps = GRASP_STABILIZE_HOLD_STEPS
        return True

    def _gripper_at_step(self, step: int) -> float:
        """Stage-local gripper setpoint (no cross-stage interpolation bleed)."""
        if self.time_stamps is None or not self.stage_sequence:
            return float(self.gripper_open)
        idx = self._stage_index_at_step(step)
        return float(self.stage_sequence[idx]["gripper"])

    def _gripper_for_proposed_action(self) -> float:
        """Gripper for ``get_action`` / ``peek_action`` while ``time_step`` is current.

        Waypoint pose targets ``time_step + 1``, but gripper must not lead the active
        stage (avoids false open on the last descend step before release).
        """
        return self._gripper_at_step(self.time_step)

    def _script_wants_open_gripper(self, step: int) -> bool:
        carry_threshold = (self.gripper_open + self.gripper_closed) / 2.0
        return self._gripper_at_step(step) > carry_threshold

    def mark_release_gripper_open(self) -> None:
        """Latch post-release open; suppresses hold_* re-close until next pick."""
        self._release_gripper_committed = True

    def should_keep_release_gripper_open(self, target_step: int) -> bool:
        """True only after release open is explicitly committed via ``mark_release_gripper_open``."""
        del target_step  # Latch is global until the next pick close stage.
        return self._release_gripper_committed

    def _action_at_step(self, step: int) -> np.ndarray:
        """Interpolate the 8D action for a trajectory step index."""
        stage_name = self.stage_name_at_step(step)
        if stage_name.startswith("open_gripper_to_release_"):
            # Stay at grasp height for the full open stage (no Z bleed into lift_after).
            stage_pos = self.stage_sequence[self._stage_index_at_step(step)]["pos"]
            pos_x, pos_y, pos_z = stage_pos[0], stage_pos[1], stage_pos[2]
            yaw = float(self.stage_sequence[self._stage_index_at_step(step)]["yaw"])
        else:
            pos_x = np.interp(step, self.time_stamps, self.pos_traj[:, 0])
            pos_y = np.interp(step, self.time_stamps, self.pos_traj[:, 1])
            pos_z = np.interp(step, self.time_stamps, self.pos_traj[:, 2])
            yaw = np.interp(step, self.time_stamps, self.yaw_traj)
        gripper = self._gripper_at_step(step)

        base_rotation = R.from_quat(DEFAULT_TOOL_QUAT, scalar_first=True)
        yaw_rotation = R.from_euler("z", [yaw], degrees=False)
        final_rotation = base_rotation * yaw_rotation
        final_quat = np.asarray(
            final_rotation.as_quat(scalar_first=True), dtype=np.float32
        ).ravel()[:4]

        action = np.zeros(ACTION_DIM, dtype=np.float32)
        action[0] = pos_x
        action[1] = pos_y
        action[2] = pos_z
        action[3] = final_quat[0]
        action[4] = final_quat[1]
        action[5] = final_quat[2]
        action[6] = final_quat[3]
        action[7] = gripper
        return action

    def _stage_index_at_step(self, step: int) -> int:
        if self.time_stamps is None or len(self.time_stamps) == 0:
            return 0
        if not self.stage_sequence:
            return 0
        idx = int(np.searchsorted(self.time_stamps, step, side="right")) - 1
        return max(0, min(idx, len(self.stage_sequence) - 1))

    def stage_name_at_step(self, step: int) -> str:
        if not self.stage_sequence:
            return "unknown"
        return self.stage_sequence[self._stage_index_at_step(step)]["name"]

    def is_in_place_window(self, step: int) -> bool:
        name = self.stage_name_at_step(step)
        return name.startswith("descend_to_box_with_") or name.startswith(
            "open_gripper_to_release_"
        )

    def is_in_approach_or_place_window(self, step: int) -> bool:
        return self.transport_phase_at_step(step) in ("approach", "place")

    def part_index_at_step(self, step: int) -> int | None:
        """Return 1-based part index inferred from the active stage name."""
        name = self.stage_name_at_step(step)
        for token in name.split("_"):
            if token.isdigit():
                return int(token)
        idx = self._stage_index_at_step(step)
        for i in range(idx, -1, -1):
            stage_name = self.stage_sequence[i]["name"]
            for token in stage_name.split("_"):
                if token.isdigit():
                    return int(token)
        return None

    def part_stage_windows(self) -> dict[int, dict[str, int]]:
        """Map each part (1..N) to key stage start/end task steps."""
        windows: dict[int, dict[str, int]] = {}
        for i, stage in enumerate(self.stage_sequence):
            part_idx = None
            for token in stage["name"].split("_"):
                if token.isdigit():
                    part_idx = int(token)
                    break
            if part_idx is None:
                continue
            start = int(self.time_stamps[i])
            end = self._stage_end_step(i)
            entry = windows.setdefault(part_idx, {})
            name = stage["name"]
            if name.startswith("move_above_box_with_"):
                entry["approach_start"] = start
                entry["approach_end"] = end
            elif name.startswith("descend_to_box_with_"):
                entry["descend_start"] = start
                entry["descend_end"] = end
            elif name.startswith("open_gripper_to_release_"):
                entry["open_start"] = start
                entry["open_end"] = end
            elif name.startswith("lift_after_releasing_"):
                entry["cycle_end"] = end
        return windows

    def transport_phase_at_step(self, step: int) -> str:
        name = self.stage_name_at_step(step)
        if name.startswith("descend_to_box_with_") or name.startswith(
            "open_gripper_to_release_"
        ):
            return "place"
        if name.startswith("move_above_box_with_"):
            return "approach"
        # Pick-side approach: block transit replan / held_critical detour pre-grasp.
        if name.startswith(("move_above_slot_", "descend_to_slot_")):
            return "approach"
        if not self._grasp_hold_validated and (
            name.startswith("close_gripper_slot_") or name.startswith("grasp_slot_")
        ):
            return "approach"
        return "transit"

    def place_target_xy_at_step(self, step: int) -> np.ndarray | None:
        idx = self._stage_index_at_step(step)
        for i in range(idx, -1, -1):
            name = self.stage_sequence[i]["name"]
            if name.startswith(("descend_to_box_with_", "move_above_box_with_")):
                return self.stage_sequence[i]["pos"][:2].copy()
        return None

    def _stage_end_step(self, stage_idx: int) -> int:
        start = int(self.time_stamps[stage_idx])
        duration = int(self.stage_sequence[stage_idx]["duration"])
        return start + max(duration - 1, 0)

    def _place_cycle_end_step(self, stage_idx: int) -> int:
        """Last step of ``lift_after_releasing_*`` for the part containing ``stage_idx``."""
        for j in range(stage_idx, len(self.stage_sequence)):
            name = self.stage_sequence[j]["name"]
            if name.startswith("lift_after_releasing_"):
                return self._stage_end_step(j)
        return int(self.time_stamps[-1]) - 1

    def is_late_approach_to_place(self, step: int, margin_steps: int = 30) -> bool:
        """True in the final ``margin_steps`` of ``move_above_box_with_*``."""
        if not self.stage_name_at_step(step).startswith("move_above_box_with_"):
            return False
        stage_idx = self._stage_index_at_step(step)
        stage_end = self._stage_end_step(stage_idx)
        return step >= stage_end - margin_steps + 1

    def is_carrying_object(self, step: int) -> bool:
        """True during the confirmed carry window (after grasp, before release).

        Uses explicit policy stage ranges — not gripper interpolation — so held
        primitives do not activate during close/open gripper transitions.
        """
        if self._grasp_carry_aborted:
            return False
        if self.time_stamps is None or not self.stage_sequence:
            return False
        name = self.stage_name_at_step(step)
        if name.startswith("lift_after_releasing_"):
            return False
        return name.startswith(
            ("grasp_", "lift_", "move_above_box_with_", "descend_to_box_with_")
        )

    def _should_clear_place_progress_hold(
        self,
        ee_pos: np.ndarray,
        step: int,
        *,
        dist_ee_human: float | None = None,
        safe_dist_warn: float = 0.16,
        blocked_descend_z_m: float = 0.55,
    ) -> bool:
        """Return True when the temporary wait-hold latch should release."""
        name = self.stage_name_at_step(step)
        if name.startswith("lift_after_releasing_"):
            return True
        if self.transport_phase_at_step(step) == "transit":
            return True
        if float(ee_pos[2]) <= blocked_descend_z_m:
            return True
        if dist_ee_human is not None and float(dist_ee_human) >= safe_dist_warn:
            return True
        if (
            dist_ee_human is not None
            and float(dist_ee_human) >= safe_dist_warn - 0.01
            and self._place_progress_hold
        ):
            return True
        return False

    def _compute_rejoin_step(self, at_step: int, detour_duration: int) -> int:
        """Cap rejoin so approach/place detours do not skip to the next part."""
        traj_end = int(self.time_stamps[-1]) - 1
        naive = min(at_step + 3 * detour_duration, traj_end)
        phase = self.transport_phase_at_step(at_step)
        if phase == "transit":
            return naive

        stage_idx = self._stage_index_at_step(at_step)
        stage_end = self._stage_end_step(stage_idx)
        if phase == "approach":
            return min(naive, stage_end)

        cycle_end = self._place_cycle_end_step(stage_idx)
        return min(naive, stage_end, cycle_end)

    @staticmethod
    def validate_placement_xy(
        ee_xy: np.ndarray,
        target_xy: np.ndarray,
        radius_m: float = PLACE_ZONE_RADIUS_M,
    ) -> bool:
        """Return True when EE XY is within the designated place slot zone."""
        delta = ee_xy[:2] - target_xy[:2]
        return float(np.linalg.norm(delta)) <= radius_m

    def validate_placement_at_step(
        self,
        ee_pos: np.ndarray,
        step: int,
        *,
        radius_m: float = PLACE_ZONE_RADIUS_M,
    ) -> bool:
        target_xy = self.place_target_xy_at_step(step)
        if target_xy is None:
            return True
        return self.validate_placement_xy(ee_pos, target_xy, radius_m)

    def should_wait_hold_place_progress(
        self,
        ee_pos: np.ndarray,
        step: int,
        *,
        dist_ee_human: float | None = None,
        safe_dist_warn: float = 0.16,
        blocked_descend_z_m: float = 0.55,
    ) -> bool:
        """Block place-descend advance while the human hand is near the EE.

        When the EE is above *blocked_descend_z_m* at the end of a
        ``move_above_box_with_*`` stage or anywhere inside
        ``descend_to_box_with_*``, the policy clock is held so the robot
        does not descend into the hand.
        """
        if self._grasp_carry_aborted:
            return False
        if self._should_clear_place_progress_hold(
            ee_pos,
            step,
            dist_ee_human=dist_ee_human,
            safe_dist_warn=safe_dist_warn,
            blocked_descend_z_m=blocked_descend_z_m,
        ):
            self._place_progress_hold = False
        if dist_ee_human is not None and float(dist_ee_human) >= safe_dist_warn:
            self._place_progress_hold = False
            return False
        if self._place_progress_hold:
            # Timeout: force-clear after 50 steps (~1s at 50Hz) to prevent deadlock
            # when the hand never moves away (e.g., fast_sweep).
            if step - self._place_progress_hold_start_step > 50:
                self._place_progress_hold = False
                self._place_progress_hold_start_step = -1
                return False
            return True
        name = self.stage_name_at_step(step)
        if name.startswith("move_above_box_with_") and float(ee_pos[2]) > blocked_descend_z_m:
            stage_idx = self._stage_index_at_step(step)
            if step >= self._stage_end_step(stage_idx) - 5:
                self._place_progress_hold = True
                self._place_progress_hold_start_step = step
                return True
        if not self.is_in_place_window(step):
            return False
        if name.startswith("descend_to_box_with_") and float(ee_pos[2]) > blocked_descend_z_m:
            self._place_progress_hold = True
            self._place_progress_hold_start_step = step
            return True
        return False

    def gripper_hold_eval_steps(self, task_time_step: int) -> list[int]:
        """Task steps to evaluate ``should_hold_*`` for the current control tick."""
        release_step = task_time_step + 1
        steps = [release_step]
        if self.stage_name_at_step(task_time_step).startswith(
            "open_gripper_to_release_"
        ):
            steps.append(task_time_step)
        return steps

    def should_hold_open_gripper(self, ee_pos: np.ndarray, target_step: int) -> bool:
        """Re-close the gripper when EE is not aligned with the placement target.

        During ``open_gripper_to_release_*`` or ``descend_to_box_with_*`` the
        script nominally commands an open gripper.  If the EE has not yet
        reached the designated placement zone this returns True so the caller
        can override the gripper command to CLOSED, preventing a premature
        release.
        """
        if self._release_gripper_committed:
            return False
        if self.time_stamps is None or self.gripper_traj is None:
            return False
        stage = self.stage_name_at_step(target_step)
        if not (
            stage.startswith("open_gripper_to_release_")
            or stage.startswith("descend_to_box_with_")
        ):
            return False
        if not self._script_wants_open_gripper(target_step):
            return False
        return not self.validate_placement_at_step(ee_pos, target_step)

    def should_block_place_advance_while_hand_near(
        self,
        ee_pos: np.ndarray,
        target_step: int,
        *,
        dist_ee_human: float | None,
        safe_dist_warn: float,
        part_pose: np.ndarray | None = None,
    ) -> bool:
        """Block policy-clock advance during place when hand is near and EE
        is not yet aligned with the target slot."""
        if self._grasp_carry_aborted:
            return False
        for step in (target_step, target_step - 1):
            if step < 0:
                continue
            if not self.stage_name_at_step(step).startswith("open_gripper_to_release_"):
                continue
            if self.should_hold_open_gripper(ee_pos, step) or self.should_hold_release(
                ee_pos, part_pose, step
            ):
                return True
        if dist_ee_human is not None and float(dist_ee_human) >= safe_dist_warn:
            return False
        return self.should_hold_open_gripper(
            ee_pos, target_step
        ) or self.should_hold_release(ee_pos, part_pose, target_step)

    def should_hold_release(
        self,
        ee_pos: np.ndarray,
        part_pose: np.ndarray | None,
        target_step: int,
    ) -> bool:
        """Re-close the gripper when the part is not yet aligned at the
        placement target during ``open_gripper_to_release_*``."""
        if self._release_gripper_committed:
            return False
        if self.time_stamps is None or self.gripper_traj is None:
            return False
        stage = self.stage_name_at_step(target_step)
        if not stage.startswith("open_gripper_to_release_"):
            return False
        if not self._script_wants_open_gripper(target_step):
            return False
        if not self.validate_placement_at_step(ee_pos, target_step):
            return True
        if part_pose is None:
            return False
        return not self.validate_grasp_hold(
            ee_pos,
            part_pose,
            xy_tolerance_m=PLACE_RELEASE_XY_TOLERANCE_M,
            z_tolerance_m=PLACE_RELEASE_Z_TOLERANCE_M,
            upright_min_dot=PLACE_RELEASE_UPRIGHT_MIN_DOT,
        )

    def _upcoming_place_target_at_rejoin(self, rejoin_step: int) -> np.ndarray | None:
        """Place slot XY for the part whose place cycle follows ``rejoin_step``."""
        if self.time_stamps is None:
            return None
        traj_end = int(self.time_stamps[-1])
        for step in range(rejoin_step, traj_end):
            name = self.stage_name_at_step(step)
            if name.startswith(("move_above_box_with_", "descend_to_box_with_")):
                return self.place_target_xy_at_step(step)
        return None

    def _build_transit_place_realign_waypoints(
        self,
        from_pos: np.ndarray,
        place_target_xy: np.ndarray,
        *,
        approach_z: float = APPROACH_HEIGHT,
    ) -> list[tuple[str, np.ndarray]]:
        """Insert 1–2 XY convergence waypoints at approach Z after transit detour rejoin."""
        target = np.array(
            [place_target_xy[0], place_target_xy[1], approach_z], dtype=np.float32
        )
        dist_xy = float(np.linalg.norm(from_pos[:2] - target[:2]))
        if dist_xy <= PLACE_ZONE_RADIUS_M:
            return []
        if dist_xy <= PLACE_ZONE_RADIUS_M * 2.0:
            return [("replan_realign_place", target.copy())]
        mid = from_pos.copy()
        mid[2] = approach_z
        mid[0] = 0.5 * mid[0] + 0.5 * target[0]
        mid[1] = 0.5 * mid[1] + 0.5 * target[1]
        return [
            ("replan_realign_place_mid", mid),
            ("replan_realign_place", target.copy()),
        ]

    @staticmethod
    def _clamp_xy_to_place_zone(
        xy: np.ndarray,
        target_xy: np.ndarray,
        radius_m: float,
    ) -> np.ndarray:
        delta = xy[:2] - target_xy[:2]
        dist = float(np.linalg.norm(delta))
        if dist <= radius_m or dist < 1e-9:
            return xy.copy()
        scale = radius_m / dist
        out = xy.copy()
        out[0] = target_xy[0] + delta[0] * scale
        out[1] = target_xy[1] + delta[1] * scale
        return out

    def advance_time_step(self) -> None:
        """Move to the next waypoint on the precomputed trajectory."""
        # Grasp stabilisation hold: stay at current point so the controller
        # has time to servo the EE orientation before descending to pick.
        if self._stabilize_hold_steps > 0:
            self._stabilize_hold_steps -= 1
            return
        # Place stabilisation hold: hold at the pose before opening the
        # gripper so the EE yaw converges to the place slot orientation
        # after a replan detour (prevents placement misalignment).
        if self._place_stabilize_hold_steps > 0:
            self._place_stabilize_hold_steps -= 1
            return
        next_step = self.time_step + 1
        if self.stage_sequence and self.time_stamps is not None and len(self.time_stamps) > 0:
            next_name = self.stage_name_at_step(next_step)
            if next_name.startswith("close_gripper_"):
                self._release_gripper_committed = False
            if self._grasp_rewind_force_open and next_name.startswith("close_gripper_"):
                self._grasp_rewind_force_open = False
            if next_name.startswith("open_gripper_to_release_"):
                self._grasp_hold_validated = False
                self._grasp_carry_aborted = False
                # Hold at the descend pose before opening — only on stage
                # TRANSITION (not every step within the stage).
                cur_name = self.stage_name_at_step(self.time_step)
                if not cur_name.startswith("open_gripper_to_release_"):
                    self._place_stabilize_hold_steps = PLACE_STABILIZE_HOLD_STEPS
        self.time_step = next_step
        if self.time_step >= self.time_stamps[-1]:
            self.success = True

    def get_action(self, obs, *, advance: bool = True):
        """Generate the next action from the scripted trajectory.

        When ``advance=False``, returns the action for the next waypoint without
        incrementing ``time_step``. Used with the safety gate so STOP/SLOW_DOWN
        do not skip ahead in the task script.
        """
        del obs  # The action is driven by the precomputed trajectory.

        target_step = self.time_step + 1
        action = self._action_at_step(target_step)
        action[7] = self._gripper_for_proposed_action()
        if advance:
            self.advance_time_step()
        return action

    def _lateral_offset_xy(
        self,
        ee_pos: np.ndarray,
        human_hand_pos: np.ndarray,
        lateral_m: float,
    ) -> np.ndarray:
        """Offset EE in XY away from human hand."""
        delta = ee_pos[:2] - human_hand_pos[:2]
        norm = float(np.linalg.norm(delta))
        if norm < 1e-6:
            away = np.array([0.0, 1.0], dtype=np.float32)
        else:
            away = (delta / norm).astype(np.float32)
        out = ee_pos.copy()
        out[0] += away[0] * lateral_m
        out[1] += away[1] * lateral_m
        return out

    def splice_replan_detour(
        self,
        *,
        at_step: int,
        ee_pos: np.ndarray,
        human_hand_pos: np.ndarray,
        raise_m: float,
        lateral_m: float,
        detour_duration: int,
        place_target_xy: np.ndarray | None = None,
        place_zone_radius_m: float = PLACE_ZONE_RADIUS_M,
        detour_strategy: str = "raise_then_lateral",
        retreat_m: float = 0.06,
        lateral_first_raise_m: float = 0.02,
    ) -> bool:
        """Insert held-aware detour at ``at_step``; resume from same index.

        Strategies (v2): ``raise_then_lateral`` | ``lateral_first`` | ``retreat_then_arc``.
        """
        if self.time_stamps is None or self.pos_traj is None:
            return False
        if at_step < 0 or at_step >= int(self.time_stamps[-1]):
            return False
        # Never rewind task progress (stale queued replan guard).
        if at_step < self.time_step - 1:
            return False

        rejoin_step = self._compute_rejoin_step(at_step, detour_duration)
        rejoin_pos = np.array(
            [
                np.interp(rejoin_step, self.time_stamps, self.pos_traj[:, 0]),
                np.interp(rejoin_step, self.time_stamps, self.pos_traj[:, 1]),
                np.interp(rejoin_step, self.time_stamps, self.pos_traj[:, 2]),
            ],
            dtype=np.float32,
        )
        if place_target_xy is None and self.is_in_place_window(at_step):
            place_target_xy = self.place_target_xy_at_step(at_step)

        detour_waypoints = self._build_detour_waypoints(
            detour_strategy,
            ee_pos,
            human_hand_pos,
            rejoin_pos,
            raise_m=raise_m,
            lateral_m=lateral_m,
            retreat_m=retreat_m,
            lateral_first_raise_m=lateral_first_raise_m,
            place_target_xy=place_target_xy,
            place_zone_radius_m=place_zone_radius_m,
        )
        if self.transport_phase_at_step(at_step) == "transit":
            upcoming_xy = self._upcoming_place_target_at_rejoin(rejoin_step)
            if upcoming_xy is not None and len(detour_waypoints) >= 2:
                detour_end_pos = detour_waypoints[-2][1]
                realign = self._build_transit_place_realign_waypoints(
                    detour_end_pos, upcoming_xy
                )
                if realign:
                    detour_waypoints = detour_waypoints[:-1] + realign + [
                        detour_waypoints[-1]
                    ]
        rejoin_yaw = float(np.interp(rejoin_step, self.time_stamps, self.yaw_traj))
        current_gripper = self._gripper_at_step(at_step)
        carry_threshold = (self.gripper_open + self.gripper_closed) / 2.0
        detour_gripper = (
            self.gripper_closed
            if current_gripper <= carry_threshold
            else current_gripper
        )

        prefix_end = int(np.searchsorted(self.time_stamps, at_step, side="right")) - 1
        prefix_end = max(prefix_end, 0)
        insert_total = len(detour_waypoints) * detour_duration
        old_end = int(self.time_stamps[-1])

        new_pos = [self.pos_traj[i].copy() for i in range(prefix_end + 1)]
        new_yaw = [float(self.yaw_traj[i]) for i in range(prefix_end + 1)]
        new_grip = [float(self.gripper_traj[i]) for i in range(prefix_end + 1)]
        new_times = [int(self.time_stamps[i]) for i in range(prefix_end + 1)]
        new_stages = [dict(s) for s in self.stage_sequence[: prefix_end + 1]]

        t = max(at_step, int(new_times[-1]))
        for detour_name, wp_pos in detour_waypoints:
            t += detour_duration
            new_pos.append(wp_pos.copy())
            new_yaw.append(rejoin_yaw)
            new_grip.append(detour_gripper)
            new_times.append(t)
            new_stages.append(
                {
                    "name": detour_name,
                    "pos": wp_pos.copy(),
                    "yaw": rejoin_yaw,
                    "gripper": detour_gripper,
                    "duration": detour_duration,
                }
            )

        for i in range(prefix_end + 1, len(self.time_stamps)):
            new_pos.append(self.pos_traj[i].copy())
            new_yaw.append(float(self.yaw_traj[i]))
            new_grip.append(float(self.gripper_traj[i]))
            new_times.append(int(self.time_stamps[i]) + insert_total)
            new_stages.append(dict(self.stage_sequence[i]))

        self.pos_traj = np.array(new_pos, dtype=np.float32)
        self.yaw_traj = np.array(new_yaw, dtype=np.float32)
        self.gripper_traj = np.array(new_grip, dtype=np.float32)
        self.time_stamps = np.array(new_times, dtype=np.int64)
        self.stage_sequence = new_stages
        self.time_step = at_step
        return int(self.time_stamps[-1]) >= old_end + insert_total

    def _build_detour_waypoints(
        self,
        detour_strategy: str,
        ee_pos: np.ndarray,
        human_hand_pos: np.ndarray,
        rejoin_pos: np.ndarray,
        *,
        raise_m: float,
        lateral_m: float,
        retreat_m: float,
        lateral_first_raise_m: float,
        place_target_xy: np.ndarray | None,
        place_zone_radius_m: float,
    ) -> list[tuple[str, np.ndarray]]:
        """Build strategy-specific detour waypoints (held-aware v2)."""
        lateral_fn = self._lateral_offset_xy

        def _maybe_clamp(xy_pos: np.ndarray) -> np.ndarray:
            if place_target_xy is None:
                return xy_pos
            return self._clamp_xy_to_place_zone(
                xy_pos, place_target_xy, place_zone_radius_m
            )

        if detour_strategy == "lateral_first":
            lateral_xy = _maybe_clamp(lateral_fn(ee_pos, human_hand_pos, lateral_m))
            raised_lateral = lateral_xy.copy()
            raised_lateral[2] += lateral_first_raise_m
            return [
                ("replan_detour_lateral", lateral_xy),
                ("replan_detour_raise", raised_lateral),
                ("replan_detour_rejoin", rejoin_pos.copy()),
            ]

        if detour_strategy == "retreat_then_arc":
            away = ee_pos[:2] - human_hand_pos[:2]
            norm = float(np.linalg.norm(away))
            if norm < 1e-6:
                unit = np.array([0.0, 1.0], dtype=np.float32)
            else:
                unit = (away / norm).astype(np.float32)
            retreat = ee_pos.copy()
            retreat[0] -= unit[0] * retreat_m
            retreat[1] -= unit[1] * retreat_m
            arc = retreat.copy()
            arc[2] += raise_m * 0.55
            arc = _maybe_clamp(lateral_fn(arc, human_hand_pos, lateral_m * 0.85))
            return [
                ("replan_detour_retreat", retreat),
                ("replan_detour_arc", arc),
                ("replan_detour_rejoin", rejoin_pos.copy()),
            ]

        # raise_then_lateral (default / legacy)
        raised = ee_pos.copy()
        raised[2] += raise_m
        lateral = _maybe_clamp(lateral_fn(raised, human_hand_pos, lateral_m))
        return [
            ("replan_detour_raise", raised),
            ("replan_detour_lateral", lateral),
            ("replan_detour_rejoin", rejoin_pos.copy()),
        ]
