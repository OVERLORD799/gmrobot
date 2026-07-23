#!/usr/bin/env python3
"""Unit tests for UR10 freeze helpers."""

from __future__ import annotations

import json
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motion_isolation import (  # noqa: E402
    compose_ur10_hold_action,
    hold_action_hash,
    compute_ur10_freeze_metrics,
    resolve_ur10_freeze_action_seed,
    extract_ur10_pose7_from_policy_obs,
    resolve_ur10_hold_target_from_articulation,
    resolve_ur10e_ee_action_term,
    resolve_ur10e_ee_hold_pose7_from_action_term,
    resolve_ur10e_gripper_hold_raw_from_articulation,
)


class _FakeTensor:
    def __init__(self, value: object) -> None:
        self._value = np.asarray(value, dtype=np.float32)

    def detach(self) -> "_FakeTensor":
        return self

    def cpu(self) -> "_FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self._value


class _FakeArticulationData:
    def __init__(self, joint_pos: np.ndarray) -> None:
        self.joint_pos = np.asarray(joint_pos, dtype=np.float32)


class _FakeArticulation:
    def __init__(self, joint_names: list[str], joint_pos_1xN: np.ndarray) -> None:
        self.joint_names = list(joint_names)
        self.data = _FakeArticulationData(np.asarray(joint_pos_1xN, dtype=np.float32))


class _FakeActionManager:
    def __init__(self, terms: dict[str, object]) -> None:
        self._terms = dict(terms)

    def get_term(self, name: str) -> object:
        return self._terms[name]


class _FakeEnv:
    def __init__(self, terms: dict[str, object]) -> None:
        self.unwrapped = self
        self.action_manager = _FakeActionManager(terms)


class _FakeControllerCfg:
    def __init__(self, *, command_type: str = "pose", use_relative_mode: bool = False) -> None:
        self.command_type = command_type
        self.use_relative_mode = use_relative_mode


class _FakeTermCfg:
    def __init__(self, *, scale: object = 1.0, controller: _FakeControllerCfg | None = None) -> None:
        self.scale = scale
        self.controller = controller or _FakeControllerCfg()


class _FakeAssetData:
    def __init__(self, root_pos_w: np.ndarray, root_quat_w: np.ndarray) -> None:
        self.root_pos_w = np.asarray(root_pos_w, dtype=np.float32)
        self.root_quat_w = np.asarray(root_quat_w, dtype=np.float32)


class _FakeAsset:
    def __init__(self, root_pos_w: np.ndarray, root_quat_w: np.ndarray) -> None:
        self.data = _FakeAssetData(root_pos_w, root_quat_w)


class _FakeIkTerm:
    def __init__(
        self,
        *,
        action_dim: int = 7,
        scale: object = 1.0,
        command_type: str = "pose",
        use_relative_mode: bool = False,
        root_pos_w: np.ndarray | None = None,
        root_quat_w: np.ndarray | None = None,
        ee_pos_b: np.ndarray | None = None,
        ee_quat_b: np.ndarray | None = None,
    ) -> None:
        self.action_dim = int(action_dim)
        self.cfg = _FakeTermCfg(
            scale=scale,
            controller=_FakeControllerCfg(
                command_type=command_type,
                use_relative_mode=use_relative_mode,
            ),
        )
        self._asset = _FakeAsset(
            root_pos_w if root_pos_w is not None else np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
            root_quat_w if root_quat_w is not None else np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        )
        self._ee_pos_b = np.asarray(
            ee_pos_b if ee_pos_b is not None else np.array([[0.1, -0.2, 0.3]], dtype=np.float32),
            dtype=np.float32,
        )
        self._ee_quat_b = np.asarray(
            ee_quat_b if ee_quat_b is not None else np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
            dtype=np.float32,
        )

    def _compute_frame_pose(self) -> tuple[np.ndarray, np.ndarray]:
        return self._ee_pos_b.copy(), self._ee_quat_b.copy()


class _FakeBinaryTerm:
    def __init__(self, action_dim: int = 1) -> None:
        self.action_dim = int(action_dim)


def _load_obs_fixture() -> dict:
    fixture = ROOT / "scripts" / "fixtures" / "ur10_observation_manager_snapshot.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


def test_compose_hold_action_and_hash_stable() -> None:
    pose7 = np.array([0.1, -0.2, 0.3, -1.0, 1.1, -0.7, 0.05], dtype=np.float32)
    hold = compose_ur10_hold_action(pose7, gripper_raw_sign=1.0)
    assert hold.shape == (8,)
    assert np.allclose(hold[:7], pose7)
    assert abs(float(hold[7]) - 1.0) < 1e-6
    assert hold_action_hash(hold) == hold_action_hash(hold.copy())


def test_extract_pose7_from_real_obs_fixture() -> None:
    obs = _load_obs_fixture()["ur10e_policy"]
    pose7, source = extract_ur10_pose7_from_policy_obs(
        {"ee_pos": _FakeTensor(obs["ee_pos"])}
    )
    assert pose7.shape == (7,)
    assert np.allclose(
        pose7,
        np.array([0.4125, -0.108, 0.365, 0.0, -0.70711, 0.70711, 0.0], dtype=np.float32),
    )
    assert "ur10_policy_obs.ee_pos" in source


def test_resolve_freeze_seed_prefers_runtime_state_8d_action() -> None:
    fixture = _load_obs_fixture()
    runtime_action = np.array(
        [0.4125, -0.108, 0.365, 0.0, -0.70711, 0.70711, 0.0, 0.8], dtype=np.float32
    )
    pose7, gripper, source = resolve_ur10_freeze_action_seed(
        ur10_state_action=runtime_action,
        ur10_policy_obs={"ee_pos": _FakeTensor(fixture["ur10e_policy"]["ee_pos"])},
    )
    assert np.allclose(pose7, runtime_action[:7])
    assert abs(gripper - 0.8) < 1e-6
    assert source == "ur10_state_action.pose7+gripper"


def test_resolve_freeze_seed_missing_schema_fails_closed() -> None:
    try:
        resolve_ur10_freeze_action_seed(
            ur10_state_action=None,
            ur10_policy_obs={"slot_A_1_T": np.eye(4, dtype=np.float32)},
        )
        raise AssertionError("expected KeyError when ee_pos schema is missing")
    except KeyError as exc:
        assert "ee_pos" in str(exc)


def test_freeze_metrics_joint_delta_and_action_norm() -> None:
    joint0 = np.zeros(7, dtype=np.float32)
    cur = np.array([0.0, 0.0, 0.01, 0.0, -0.02, 0.0, 0.0], dtype=np.float32)
    eff = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5], dtype=np.float32)
    m = compute_ur10_freeze_metrics(
        effective_action=eff,
        current_joint_pose=cur,
        initial_joint_pose=joint0,
    )
    assert abs(m["ur10_action_norm"]) < 1e-12
    assert m["ur10_arm_joint_delta_norm"] > 0.0
    assert abs(m["ur10_arm_joint_delta_max_abs"] - 0.02) < 1e-6
    assert abs(m["ur10_gripper_joint_delta"]) < 1e-12
    assert m["ur10_joint_delta_norm"] > 0.0
    assert abs(m["ur10_joint_delta_max_abs"] - 0.02) < 1e-6
    assert m["ur10_joint_delta_semantics"] == "legacy_aggregate_arm6_plus_gripper1"


def test_articulation_hold_mapping_by_joint_name_order() -> None:
    names = [
        "dummy0",
        "wrist_2_joint",
        "finger_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "shoulder_pan_joint",
        "wrist_3_joint",
    ]
    vals = np.array([[9.0, 1.2, 0.33, -0.4, 0.5, -1.1, 0.7, 2.2]], dtype=np.float32)
    art = _FakeArticulation(names, vals)
    hold7, prov, grip = resolve_ur10_hold_target_from_articulation(art)
    assert np.allclose(hold7, np.array([0.7, -0.4, 0.5, -1.1, 1.2, 2.2, 0.33], dtype=np.float32))
    assert abs(grip - 0.33) < 1e-6
    assert [row["joint_name"] for row in prov[:6]] == [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
    ]


def test_articulation_hold_missing_arm_joint_fails_closed() -> None:
    names = ["shoulder_pan_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint", "finger_joint"]
    vals = np.zeros((1, len(names)), dtype=np.float32)
    art = _FakeArticulation(names, vals)
    try:
        resolve_ur10_hold_target_from_articulation(art)
        raise AssertionError("expected KeyError for missing shoulder_lift_joint")
    except KeyError as exc:
        assert "shoulder_lift_joint" in str(exc)


def test_articulation_hold_gripper_mapping_prefers_first_available_gripper_joint() -> None:
    names = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
        "right_outer_knuckle_joint",
    ]
    vals = np.array([[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.88]], dtype=np.float32)
    hold7, prov, grip = resolve_ur10_hold_target_from_articulation(_FakeArticulation(names, vals))
    assert abs(grip - 0.88) < 1e-6
    assert abs(float(hold7[-1]) - 0.88) < 1e-6
    assert prov[-1]["joint_name"] == "right_outer_knuckle_joint"


def test_controller_action_differs_but_hold_uses_actual_articulation() -> None:
    proposed = np.array([99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 0.0], dtype=np.float32)
    pose7, grip, _ = resolve_ur10_freeze_action_seed(
        ur10_state_action=proposed,
        ur10_policy_obs={"ee_pos": np.zeros((1, 7), dtype=np.float32)},
    )
    assert np.allclose(pose7, proposed[:7])
    names = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
        "finger_joint",
    ]
    vals = np.array([[0.11, -0.22, 0.33, -0.44, 0.55, -0.66, 0.77]], dtype=np.float32)
    hold7, _, grip2 = resolve_ur10_hold_target_from_articulation(_FakeArticulation(names, vals))
    assert not np.allclose(hold7[:6], pose7[:6])
    assert abs(grip2 - 0.77) < 1e-6
    assert abs(grip - 0.0) < 1e-6


def test_resolve_ur10e_ee_action_term_passes_expected_contract() -> None:
    term = _FakeIkTerm(action_dim=7, scale=1.0, command_type="pose", use_relative_mode=False)
    env = _FakeEnv({"ur10e_ee": term})
    resolved, audit = resolve_ur10e_ee_action_term(env)
    assert resolved is term
    assert audit["action_dim"] == 7
    assert audit["command_type"] == "pose"
    assert audit["use_relative_mode"] is False
    assert audit["scale"] == [1.0] * 7


def test_resolve_ur10e_ee_action_term_fails_closed_on_bad_controller_cfg() -> None:
    env = _FakeEnv({"ur10e_ee": _FakeIkTerm(command_type="twist")})
    try:
        resolve_ur10e_ee_action_term(env)
        raise AssertionError("expected ValueError for command_type mismatch")
    except ValueError as exc:
        assert "command_type" in str(exc)
    env2 = _FakeEnv({"ur10e_ee": _FakeIkTerm(use_relative_mode=True)})
    try:
        resolve_ur10e_ee_action_term(env2)
        raise AssertionError("expected ValueError for use_relative_mode mismatch")
    except ValueError as exc:
        assert "use_relative_mode" in str(exc)


def test_resolve_ur10e_ee_action_term_fails_closed_on_bad_dim_or_scale() -> None:
    env = _FakeEnv({"ur10e_ee": _FakeIkTerm(action_dim=6)})
    try:
        resolve_ur10e_ee_action_term(env)
        raise AssertionError("expected ValueError for action_dim mismatch")
    except ValueError as exc:
        assert "action_dim" in str(exc)
    env2 = _FakeEnv({"ur10e_ee": _FakeIkTerm(scale=[1, 1, 1, 1, 1, 1, 0.5])})
    try:
        resolve_ur10e_ee_action_term(env2)
        raise AssertionError("expected ValueError for scale mismatch")
    except ValueError as exc:
        assert "scale" in str(exc)


def test_resolve_ur10e_ee_hold_pose7_stays_in_action_term_root_frame() -> None:
    # A non-identity world root must not leak into the absolute IK raw action:
    # DifferentialIKController compares commands with _compute_frame_pose(),
    # and both quantities are expressed in the robot root frame.
    s = np.float32(np.sqrt(0.5))
    term = _FakeIkTerm(
        root_pos_w=np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        root_quat_w=np.array([[s, 0.0, 0.0, s]], dtype=np.float32),
        ee_pos_b=np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        ee_quat_b=np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
    )
    pose7, audit = resolve_ur10e_ee_hold_pose7_from_action_term(term)
    assert np.allclose(pose7[:3], np.array([1.0, 0.0, 0.0], dtype=np.float32), atol=1e-6)
    assert np.allclose(pose7[3:], np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), atol=1e-6)
    assert "root_frame_with_body_offset" in str(audit["pose_source"])
    assert abs(float(audit["quat_norm_raw"]) - 1.0) < 1e-6


def test_hold_pose7_fails_closed_on_nan_and_bad_quat_norm() -> None:
    bad_nan = _FakeIkTerm(ee_pos_b=np.array([[np.nan, 0.0, 0.0]], dtype=np.float32))
    try:
        resolve_ur10e_ee_hold_pose7_from_action_term(bad_nan)
        raise AssertionError("expected ValueError for non-finite pose")
    except ValueError as exc:
        assert "non-finite" in str(exc)
    bad_q = _FakeIkTerm(ee_quat_b=np.array([[2.0, 0.0, 0.0, 0.0]], dtype=np.float32))
    try:
        resolve_ur10e_ee_hold_pose7_from_action_term(bad_q)
        raise AssertionError("expected ValueError for bad quat norm")
    except ValueError as exc:
        assert "quaternion norm" in str(exc)


def test_gripper_raw_sign_selects_open_close_and_validates_term_dim() -> None:
    joint_names = [
        "shoulder_pan_joint",
        "shoulder_lift_joint",
        "elbow_joint",
        "wrist_1_joint",
        "wrist_2_joint",
        "wrist_3_joint",
        "finger_joint",
    ]
    open_like = _FakeArticulation(joint_names, np.array([[0, 0, 0, 0, 0, 0, 0.32]], dtype=np.float32))
    env = _FakeEnv({"ur10e_ee": _FakeIkTerm(), "ur10e_gripper": _FakeBinaryTerm(1)})
    raw_open, audit_open = resolve_ur10e_gripper_hold_raw_from_articulation(env, open_like)
    assert raw_open == 1.0
    assert audit_open["selected"] == "open"
    close_like = _FakeArticulation(joint_names, np.array([[0, 0, 0, 0, 0, 0, 0.76]], dtype=np.float32))
    raw_close, audit_close = resolve_ur10e_gripper_hold_raw_from_articulation(env, close_like)
    assert raw_close == -1.0
    assert audit_close["selected"] == "close"
    bad_env = _FakeEnv({"ur10e_ee": _FakeIkTerm(), "ur10e_gripper": _FakeBinaryTerm(2)})
    try:
        resolve_ur10e_gripper_hold_raw_from_articulation(bad_env, close_like)
        raise AssertionError("expected ValueError for gripper action_dim")
    except ValueError as exc:
        assert "action_dim" in str(exc)


def test_joint_baseline_never_enters_hold_action() -> None:
    env = _FakeEnv({"ur10e_ee": _FakeIkTerm(), "ur10e_gripper": _FakeBinaryTerm(1)})
    pose7, _ = resolve_ur10e_ee_hold_pose7_from_action_term(env.action_manager.get_term("ur10e_ee"))
    art = _FakeArticulation(
        ["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint", "finger_joint"],
        np.array([[99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 0.32]], dtype=np.float32),
    )
    joint_baseline7, _, _ = resolve_ur10_hold_target_from_articulation(art)
    raw_grip, _ = resolve_ur10e_gripper_hold_raw_from_articulation(env, art)
    hold = compose_ur10_hold_action(pose7, raw_grip)
    assert np.allclose(hold[:7], pose7)
    assert not np.allclose(hold[:7], joint_baseline7)


if __name__ == "__main__":
    test_compose_hold_action_and_hash_stable()
    test_extract_pose7_from_real_obs_fixture()
    test_resolve_freeze_seed_prefers_runtime_state_8d_action()
    test_resolve_freeze_seed_missing_schema_fails_closed()
    test_freeze_metrics_joint_delta_and_action_norm()
    test_articulation_hold_mapping_by_joint_name_order()
    test_articulation_hold_missing_arm_joint_fails_closed()
    test_articulation_hold_gripper_mapping_prefers_first_available_gripper_joint()
    test_controller_action_differs_but_hold_uses_actual_articulation()
    test_resolve_ur10e_ee_action_term_passes_expected_contract()
    test_resolve_ur10e_ee_action_term_fails_closed_on_bad_controller_cfg()
    test_resolve_ur10e_ee_action_term_fails_closed_on_bad_dim_or_scale()
    test_resolve_ur10e_ee_hold_pose7_stays_in_action_term_root_frame()
    test_hold_pose7_fails_closed_on_nan_and_bad_quat_norm()
    test_gripper_raw_sign_selects_open_close_and_validates_term_dim()
    test_joint_baseline_never_enters_hold_action()
    print("PASS test_motion_isolation_unit")
