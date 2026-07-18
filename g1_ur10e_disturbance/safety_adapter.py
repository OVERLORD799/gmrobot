"""G1EnvelopeAdapter — maps G1 body poses to GMRobot safety-layer format.

The GMRobot safety layer expects ``human_hand_pos``, ``human_hand_vel``,
``human_torso_pos``, and ``human_torso_vel``.  This adapter computes
equivalent values from the G1 humanoid's kinematic chain, enabling
the safety gate to react to G1 proximity without any GMRobot-side changes.

Phase 3 adds :meth:`build_safety_state` and :meth:`evaluate_safety` which
wire the adapter output directly into GMRobot's RuleEngine + SafetyGate,
enabling joint G1+UR10e safety testing.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np

from paths import GMROBOT_SAFETY as _GMROBOT_SAFETY_PATH


# Body parts tracked by the adapter with their approximate collision radii.
# Names must match G1 body_link names (37 bodies in g1_29dof_modified_new_91.usd).
#
# TRACKED_BODIES — all bodies for FK position + velocity tracking (metrics / logging).
# SAFETY_BODIES  — subset reported to the RuleEngine as closest-body candidates
#                  (W3 fix: only hands + head; torso/shoulders/elbows are filtered
#                  because their large radii dominate dist_min and trigger premature
#                  SLOW_DOWN even when the actual collision risk — the hands — is
#                  far from the EE).
TRACKED_BODIES = {
    "torso_link":              0.20,
    "head_link":               0.12,
    "left_shoulder_pitch_link": 0.07,
    "right_shoulder_pitch_link": 0.07,
    "left_elbow_link":         0.07,
    "right_elbow_link":        0.07,
    "left_wrist_pitch_link":   0.05,
    "right_wrist_pitch_link":  0.05,
}

SAFETY_BODIES = {
    "head_link":               0.12,
    "left_wrist_pitch_link":   0.05,
    "right_wrist_pitch_link":  0.05,
}

# =============================================================================
# GMRobot safety layer import (lazy — only when evaluate_safety is called)
# =============================================================================

_safety_imports: Optional[dict] = None


def _get_safety_imports():
    """Lazy-import GMRobot safety classes, working around transitive deps.

    The GMRobot ``safety/__init__.py`` imports ``human_motion`` which needs
    ``torch`` (not available outside the Isaac Lab conda env).  We load the
    four leaf modules directly via ``importlib``, pre-seeding ``sys.modules``
    so that intra-package relative imports (``from .config import ...``)
    resolve correctly.

    SAFETY: If the GMRobot module structure changes (renames, new internal
    deps), this function raises ``ImportError`` with a clear message listing
    the expected files.  Callers must handle this gracefully — the fallback
    is to run WITHOUT safety gating, which is acceptable for baseline
    testing but MUST be logged prominently.
    """
    global _safety_imports
    if _safety_imports is not None:
        return _safety_imports

    import importlib.util
    import sys as _sys

    _SAFETY_DIR = _GMROBOT_SAFETY_PATH
    if not os.path.isdir(_SAFETY_DIR):
        raise ImportError(
            f"GMRobot safety directory not found at '{_SAFETY_DIR}'. "
            f"Set GMROBOT_ROOT env var or install GMRobot. "
            f"Running without safety gating."
        )

    # R6 H6 fix: ensure 'safety' has __path__ so intra-package relative
    # imports (from .config import ...) work when GMRobot adds new internal
    # deps.  _get_replan_imports() has the same fix; this was missing here.
    if "safety" not in _sys.modules:
        import types as _types
        _safety_ns = _types.ModuleType("safety")
        _safety_ns.__path__ = [_SAFETY_DIR]
        _sys.modules["safety"] = _safety_ns
    elif not hasattr(_sys.modules["safety"], "__path__"):
        _sys.modules["safety"].__path__ = [_SAFETY_DIR]

    # Expected modules in dependency order.  Version check: if any file is
    # missing or has been renamed, the error message will tell the operator
    # exactly what to look for.
    _EXPECTED_MODULES = [
        ("types",        "types.py",        []),
        ("config",       "config.py",       ["types"]),
        ("ground_truth", "ground_truth.py", ["types", "config"]),
        ("gt_branches",  "gt_branches.py",  ["types", "config", "ground_truth"]),
        ("envelope",     "envelope.py",     ["types", "config", "gt_branches"]),
        ("rule_engine",  "rule_engine.py",  ["types", "config"]),
        ("gate",         "gate.py",         ["types", "config"]),
    ]

    _loaded: dict[str, object] = {}

    def _load_leaf(mod_name: str, filename: str, deps: list[str]):
        filepath = os.path.join(_SAFETY_DIR, filename)
        if not os.path.isfile(filepath):
            raise ImportError(
                f"GMRobot safety module '{filename}' not found at {_SAFETY_DIR}. "
                f"Expected modules: {[m for m, _, _ in _EXPECTED_MODULES]}. "
                f"Has GMRobot been restructured? Update _EXPECTED_MODULES in "
                f"safety_adapter.py or fix GMROBOT_ROOT."
            )
        for dep in deps:
            if f"safety.{dep}" not in _sys.modules:
                _load_leaf(dep, f"{dep}.py", [])  # deps already loaded above
        spec = importlib.util.spec_from_file_location(
            f"safety.{mod_name}", filepath
        )
        mod = importlib.util.module_from_spec(spec)
        _sys.modules[f"safety.{mod_name}"] = mod
        try:
            spec.loader.exec_module(mod)
        except (ModuleNotFoundError, FileNotFoundError) as e:
            raise ImportError(
                f"Failed to load GMRobot safety module '{mod_name}' "
                f"from {filepath}: {e}. "
                f"The GMRobot module may have new internal dependencies. "
                f"Update _EXPECTED_MODULES in safety_adapter.py."
            ) from e
        # SyntaxError, NameError, TypeError, etc. from source-code bugs
        # MUST propagate as crashes — a visible crash is safer than silent
        # ungated pass-through (run_phase3.py treats ImportError as
        # "modules unavailable" and disables the safety gate).
        return mod

    for mod_name, filename, deps in _EXPECTED_MODULES:
        if f"safety.{mod_name}" not in _sys.modules:
            _loaded[mod_name] = _load_leaf(mod_name, filename, deps)
        else:
            _loaded[mod_name] = _sys.modules[f"safety.{mod_name}"]

    # H7 fix (2026-07-13): wrap class-attribute access in try/except so that
    # GMRobot class renames produce a clean ImportError (→ ungated fallback)
    # instead of crashing on every step with AttributeError (→ permanent HOLD).
    try:
        _safety_imports = {
            "SafetyConfig": _loaded["config"].SafetyConfig,
            "load_safety_config": _loaded["config"].load_safety_config,
            "SafetyState": _loaded["types"].SafetyState,
            "GateDecision": _loaded["types"].GateDecision,
            "GateResult": _loaded["types"].GateResult,
            "EnvelopeEvaluator": _loaded["envelope"].EnvelopeEvaluator,
            "RuleEngine": _loaded["rule_engine"].RuleEngine,
            "SafetyGate": _loaded["gate"].SafetyGate,
        }
    except AttributeError as e:
        raise ImportError(
            f"GMRobot safety module structure changed — class not found: {e}. "
            f"Update _EXPECTED_MODULES in safety_adapter.py to match the "
            f"current GMRobot module layout."
        ) from e
    return _safety_imports


# =============================================================================
# GMRobot replan module import (lazy — same importlib pattern as above)
# =============================================================================

_replan_imports: Optional[dict] = None


def _get_replan_imports():
    """Lazy-import GMRobot replan modules (Phase 4a geometry replan).

    The replan package lives at ``GMRobot/safety/replan/`` and uses
    intra-package relative imports (``from ..envelope import ...``).
    We must load the full dependency chain into ``sys.modules`` with
    the correct ``safety.*`` / ``safety.replan.*`` prefixes before
    any replan module can be imported.

    Returns a dict with keys:
        GeometryReplanV0, L1WarnReplanTrigger, ReplanRuntimeState,
        ReplanTriggerConfig
    """
    global _replan_imports
    if _replan_imports is not None:
        return _replan_imports

    import importlib.util as _iu
    import sys as _sys

    _SAFETY_DIR = _GMROBOT_SAFETY_PATH
    _REPLAN_DIR = os.path.join(_SAFETY_DIR, "replan")

    # Ensure the safety package namespace exists.  If _get_safety_imports()
    # was called first, individual modules (safety.types, safety.config, …)
    # already live in sys.modules but the 'safety' package itself may be
    # absent or lack __path__.  We preserve any pre-existing module entries
    # and only add __path__ so that relative imports (from ..envelope) resolve.
    if "safety" not in _sys.modules:
        import types as _types
        _safety_ns = _types.ModuleType("safety")
        _safety_ns.__path__ = [_SAFETY_DIR]
        _sys.modules["safety"] = _safety_ns
    elif not hasattr(_sys.modules["safety"], "__path__"):
        _sys.modules["safety"].__path__ = [_SAFETY_DIR]
    if "safety.replan" not in _sys.modules:
        import types as _types
        _replan_ns = _types.ModuleType("safety.replan")
        _replan_ns.__path__ = [_REPLAN_DIR]
        _sys.modules["safety.replan"] = _replan_ns

    # Load safety modules that replan depends on (if not already loaded by
    # _get_safety_imports).  We need envelope.py in particular.
    _REQUIRED_SAFETY = [
        ("safety.types",    "types.py",    []),
        ("safety.config",   "config.py",   ["safety.types"]),
        ("safety.envelope", "envelope.py", ["safety.types", "safety.config"]),
    ]

    def _load_one(mod_name: str, filename: str, deps: list[str]):
        if mod_name in _sys.modules:
            return _sys.modules[mod_name]
        for dep in deps:
            if dep not in _sys.modules:
                _load_one(dep, f"{dep.split('.')[-1]}.py", [])
        base_dir = _REPLAN_DIR if mod_name.startswith("safety.replan") else _SAFETY_DIR
        fpath = os.path.join(base_dir, filename)
        if not os.path.isfile(fpath):
            raise FileNotFoundError(
                f"GMRobot module '{mod_name}' not found at {fpath}. "
                f"Has GMRobot been restructured?"
            )
        spec = _iu.spec_from_file_location(mod_name, fpath)
        mod = _iu.module_from_spec(spec)
        _sys.modules[mod_name] = mod
        # H8 fix (2026-07-13): catch ModuleNotFoundError/FileNotFoundError
        # (missing GMRobot internal deps) and raise ImportError with context.
        # SyntaxError/NameError/TypeError still propagate — a visible crash
        # is safer than silently loading a broken module.
        try:
            spec.loader.exec_module(mod)
        except (ModuleNotFoundError, FileNotFoundError) as e:
            raise ImportError(
                f"Failed to load GMRobot replan module '{mod_name}' "
                f"from {fpath}: {e}.  The GMRobot module may have new "
                f"internal dependencies.  Update _REPLAN_MODULES in "
                f"safety_adapter.py."
            ) from e
        return mod

    for mn, fn, deps in _REQUIRED_SAFETY:
        _load_one(mn, fn, deps)

    # Load replan modules in dependency order.
    _REPLAN_MODULES = [
        ("safety.replan.types",          "types.py",          ["safety.types", "safety.config"]),
        ("safety.replan.strategy",       "strategy.py",       ["safety.types", "safety.config", "safety.envelope", "safety.replan.types"]),
        ("safety.replan.route_conflict", "route_conflict.py", ["safety.types", "safety.config", "safety.envelope", "safety.replan.types"]),
        ("safety.replan.executor",       "executor.py",       ["safety.replan.types", "safety.replan.strategy"]),
        ("safety.replan.triggers",       "triggers.py",       ["safety.types", "safety.replan.types", "safety.replan.strategy", "safety.replan.route_conflict", "safety.config"]),
    ]

    for mn, fn, deps in _REPLAN_MODULES:
        _load_one(mn, fn, deps)

    try:
        _replan_imports = {
            "GeometryReplanV0":    _sys.modules["safety.replan.executor"].GeometryReplanV0,
            "L1WarnReplanTrigger": _sys.modules["safety.replan.triggers"].L1WarnReplanTrigger,
            "ReplanRuntimeState":  _sys.modules["safety.replan.executor"].ReplanRuntimeState,
            "ReplanTriggerConfig": _sys.modules["safety.replan.triggers"].ReplanTriggerConfig,
        }
    except AttributeError as e:
        raise ImportError(
            f"GMRobot replan module structure changed — class not found: {e}. "
            f"Update _REPLAN_MODULES in safety_adapter.py to match the "
            f"current GMRobot module layout."
        ) from e
    return _replan_imports


class G1EnvelopeAdapter:
    """Computes GMRobot-compatible safety observations from G1 FK data.

    Usage per env step::

        adapter.update(robot_g1_articulation, ur10e_ee_pos_w)
        safety_obs = adapter.as_dict()

    Phase 3 safety evaluation::

        state = adapter.build_safety_state(policy_obs, safety_obs, step_index)
        result = adapter.evaluate_safety(state)
        gated_action = adapter.apply_safety_gate(result, proposed, prev)
    """

    def __init__(
        self,
        *,
        safety_config_path: Optional[str] = None,
        control_dt: float = 0.02,
    ):
        # Per-body indices (lazy-filled on first update)
        self._body_indices: dict[str, int] = {}
        self._initialised = False

        # Current values
        # NOTE: human_hand_pos carries two geometric meanings depending on
        # which code path writes it:
        #   - adapter.update(): BODY CENTER (raw body_link_pos_w)
        #   - scenario / virtual_hand / stress: SPHERE SURFACE POINT
        # Consumers MUST use closest_body_distance (= dist_for_gating,
        # always envelope-surface distance) for gating decisions, not
        # compute their own distance from this field.
        self.human_hand_pos: np.ndarray = np.zeros(3, dtype=np.float32)
        self.human_hand_vel: np.ndarray = np.zeros(3, dtype=np.float32)
        self.human_torso_pos: np.ndarray = np.zeros(3, dtype=np.float32)
        self.human_torso_vel: np.ndarray = np.zeros(3, dtype=np.float32)
        self.closest_body_name: str = "head_link"
        self.closest_body_distance: float = float("inf")

        # Position history for finite-difference velocity.
        # Per-body tracking prevents velocity jumps when the closest body
        # changes between frames (C2 fix: left_hand→right_hand switch would
        # otherwise compute spatial distance as velocity).
        self._prev_body_positions: dict[str, np.ndarray] = {}
        self._prev_torso_pos: Optional[np.ndarray] = None
        self._dt: float = control_dt
        # === EE radius for surface-distance calculation (C1 fix) ===
        # GMRobot RuleEngine expects center-to-center distances calibrated
        # for human hands (~0.05 m radius).  G1 body parts are much larger
        # (torso 0.20 m, upper arm 0.07 m).  Reporting center distances
        # causes the safety gate to trigger too late for large bodies.
        # We subtract body radius so the reported distance is surface-to-
        # surface, matching the semantics of GMRobot's 0.13 m hard_stop.
        # ponytail: surface-distance fix; if GMRobot later adopts per-body
        # radii in its EnvelopeEvaluator, remove the subtraction here.
        self._ee_radius: float = 0.08   # matches GMRobot UR10e EE sphere

        # --- GMRobot safety layer (lazy-init) ---
        self._safety_config_path = safety_config_path
        self._rule_engine = None
        self._safety_gate = None
        self._safety_config = None
        self._safety_initialised = False

        # --- Safety evaluation history ---
        self.last_gate_result: Optional[object] = None  # GateResult
        self.safety_step_index: int = 0

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_body_indices(self, robot) -> None:
        """Resolve body names to indices once (the articulation is fixed)."""
        if self._initialised:
            return
        # Index TRACKED_BODIES (logging/metrics — missing entries are tolerable).
        for name in TRACKED_BODIES:
            idx_list, _ = robot.find_bodies(name)
            if len(idx_list) > 0:
                self._body_indices[name] = idx_list[0]
        # Index SAFETY_BODIES (safety gate — missing entries are a hard error
        # because the safety gate would silently have fewer candidates than
        # intended).  M2 fix: assert every SAFETY_BODY actually exists in the
        # articulation.
        for name in SAFETY_BODIES:
            idx_list, _ = robot.find_bodies(name)
            if len(idx_list) == 0:
                all_bodies = list(robot.body_names)
                raise RuntimeError(
                    f"SAFETY_BODIES contains '{name}' but the G1 articulation "
                    f"has no body with that name. Available bodies: {all_bodies}. "
                    f"Update SAFETY_BODIES in safety_adapter.py to use a valid body name."
                )
            self._body_indices[name] = idx_list[0]
        self._initialised = True

    def _init_safety_layer(self):
        """Lazy-init GMRobot RuleEngine + SafetyGate + EnvelopeEvaluator."""
        if self._safety_initialised:
            return
        imports = _get_safety_imports()
        if self._safety_config_path is not None:
            self._safety_config = imports["load_safety_config"](self._safety_config_path)
        else:
            self._safety_config = imports["SafetyConfig"]()
        self._rule_engine = imports["RuleEngine"](self._safety_config)
        self._envelope_evaluator = imports["EnvelopeEvaluator"](
            self._safety_config.envelope)
        self._safety_gate = imports["SafetyGate"](self._safety_config)
        self._safety_initialised = True

    # ------------------------------------------------------------------
    # Per-step update
    # ------------------------------------------------------------------

    def update(
        self,
        robot,                     # Articulation object
        ur10e_ee_pos: np.ndarray,  # (3,) world position of UR10e wrist_3_link
    ) -> None:
        """Read G1 body positions and select the closest body to the UR10e EE.

        Args:
            robot: the ``robot_g1`` articulation (Isaac Lab Articulation).
            ur10e_ee_pos: (3,) UR10e end-effector world position.
        """
        self._init_body_indices(robot)

        # Gather world positions for every tracked body
        positions: dict[str, np.ndarray] = {}
        for name, idx in self._body_indices.items():
            pos = robot.data.body_link_pos_w[0, idx].cpu().numpy()  # (3,)
            positions[name] = pos.astype(np.float32)

        # Torso
        torso_pos = positions.get("torso_link")
        if torso_pos is not None:
            if self._prev_torso_pos is not None:
                self.human_torso_vel = (torso_pos - self._prev_torso_pos) / self._dt
            self.human_torso_pos = torso_pos
            self._prev_torso_pos = torso_pos.copy()

        # Closest body to UR10e EE — compute SURFACE distance (C1 fix).
        # Only SAFETY_BODIES are candidates (W3 fix: torso/shoulders/elbows
        # filtered — their large radii dominate dist_min and cause premature
        # SLOW_DOWN even though the real collision risk is from the hands).
        # Surface distance = center distance - body radius - EE radius,
        # clamped to >= 0 (H2 fix: torso radius 0.20 + EE radius 0.08 = 0.28 m;
        # center distances below this produce negative surface distances that
        # the RuleEngine may not handle correctly).
        best_dist = float("inf")
        best_pos = None
        best_name = "head_link"
        best_vel: np.ndarray = np.zeros(3, dtype=np.float32)
        for name, radius in SAFETY_BODIES.items():
            pos = positions.get(name)
            if pos is None:
                continue
            center_dist = float(np.linalg.norm(pos - ur10e_ee_pos))
            surface_dist = max(0.0, center_dist - radius - self._ee_radius)
            if surface_dist < best_dist:
                best_dist = surface_dist
                best_pos = pos
                best_name = name

        if best_pos is not None:
            # Per-body velocity (C2 fix): compute velocity only when the
            # SAME body part was tracked last frame.  If the closest body
            # changed, velocity from the previous closest body is stale —
            # report zero instead of a spatial jump.
            prev = self._prev_body_positions.get(best_name)
            if prev is not None:
                best_vel = (best_pos - prev) / self._dt
            self._prev_body_positions[best_name] = best_pos.copy()
            self.human_hand_pos = best_pos
            self.human_hand_vel = best_vel

        self.closest_body_name = best_name
        self.closest_body_distance = best_dist

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def as_dict(self) -> dict[str, np.ndarray]:
        """Return a dict matching GMRobot's safety observation format."""
        return {
            "human_hand_pos": self.human_hand_pos,
            "human_hand_vel": self.human_hand_vel,
            "human_torso_pos": self.human_torso_pos,
            "human_torso_vel": self.human_torso_vel,
        }

    @staticmethod
    def body_radii() -> dict[str, float]:
        """Return the SAFETY_BODIES radii dict (hands + head only)."""
        return dict(SAFETY_BODIES)

    # ------------------------------------------------------------------
    # Phase 3: GMRobot safety layer integration
    # ------------------------------------------------------------------

    def build_safety_state(
        self,
        policy_obs: dict[str, np.ndarray],
        safety_obs: dict[str, np.ndarray],
        *,
        step_index: int,
        sim_time: Optional[float] = None,
    ) -> object:
        """Build a GMRobot ``SafetyState`` from adapter + UR10e observations.

        Args:
            policy_obs: UR10e policy observation dict (must contain ``ee_pos``).
            safety_obs: UR10e safety observation dict (must contain ``ee_vel``,
                ``joint_pos``, ``joint_vel``).
            step_index: current simulation step (0-indexed).
            sim_time: elapsed simulation time in seconds.  If None, computed
                as ``step_index * control_dt``.

        Returns:
            :class:`SafetyState` instance.
        """
        self._init_safety_layer()
        imports = _get_safety_imports()

        if sim_time is None:
            sim_time = step_index * self._dt

        state = imports["SafetyState"].from_runtime(
            policy_obs=policy_obs,
            safety_obs=safety_obs,
            human_hand_pos=self.human_hand_pos,
            human_hand_vel=self.human_hand_vel,
            human_torso_pos=self.human_torso_pos,
            human_torso_vel=self.human_torso_vel,
            sim_time=sim_time,
            step_index=step_index,
            control_dt=self._dt,
        )
        return state

    def evaluate_safety(
        self,
        state: object,                    # SafetyState
        *,
        held_object_active: bool = False,
        functional_risk_info: Optional[dict] = None,
        dist_for_gating: Optional[float] = None,
        dist_min_held: Optional[float] = None,
        proposed_ee_pos: Optional[np.ndarray] = None,
    ) -> object:                         # GateResult
        """Run the GMRobot RuleEngine on a SafetyState.

        Args:
            state: :class:`SafetyState` from :meth:`build_safety_state`.
            held_object_active: whether the UR10e is currently holding a part.
            functional_risk_info: optional dict with keys ``rewind_attempts``,
                ``release_in_zone``, ``max_rewinds`` for functional risk checks.
            dist_for_gating: surface distance (body surface to EE surface, m).
                When provided, enables envelope gating in the RuleEngine
                (arm/gripper/held-object proximity checks).  When None, the
                RuleEngine falls back to centre-to-centre distance from the
                EE and hand positions — losing body-radius correction.
            dist_min_held: minimum distance from held object to any human
                body (m).  Enables held-critical STOP and held-aware replan
                trigger paths.  When None, those paths are disabled.
            proposed_ee_pos: (3,) proposed EE target position.  When
                provided, the workspace boundary check uses THIS position
                instead of the current EE position — preventing the one-way
                trap where an EE pushed outside workspace can never return.

        Returns:
            :class:`GateResult` with the safety decision.
        """
        self._init_safety_layer()
        # ── Full-geometry envelope primitive check ────────────────────
        # Runs the complete ~25-primitive sweep (arm links, interpolation
        # spheres, fingertips, held object) against the human hand sphere.
        # dist_min_envelope is the true surface-gap minimum across ALL
        # robot body parts, replacing the single EE-to-hand estimate.
        # Overhead < 0.1 ms/step — negligible at 50 Hz (20 ms cycle).
        _env_result = self._envelope_evaluator.evaluate(
            state,
            held_object_active=held_object_active,
        )
        _env_dist = _env_result.dist_min_envelope
        # Merge with scenario/virtual-hand override: whichever is tighter.
        if dist_for_gating is None:
            dist_for_gating = _env_dist
        elif _env_dist is not None and float(_env_dist) < float(dist_for_gating):
            dist_for_gating = float(_env_dist)
        # Pass closest primitive info for held-object lateral boost.
        result = self._rule_engine.evaluate(
            state,
            held_object_active=held_object_active,
            functional_risk_info=functional_risk_info,
            dist_for_gating=dist_for_gating,
            dist_min_held=dist_min_held,
            proposed_ee_pos=proposed_ee_pos,
            closest_primitive_id=_env_result.closest_primitive_id,
            closest_primitive_pos=_env_result.closest_primitive_pos,
        )
        self.last_gate_result = result
        self.safety_step_index = state.step_index
        return result

    def apply_safety_gate(
        self,
        result: object,          # GateResult
        proposed: np.ndarray,    # (8,) proposed UR10e action
        prev_action: np.ndarray, # (8,) previous UR10e action
    ) -> np.ndarray:
        """Apply the safety gate decision to the proposed UR10e action.

        Args:
            result: :class:`GateResult` from :meth:`evaluate_safety`.
            proposed: proposed 8D action (ee pose 7D + gripper 1D).
            prev_action: previous step's 8D action.

        Returns:
            Gated 8D action (unchanged if ALLOW; held if STOP;
            interpolated if SLOW_DOWN).
        """
        self._init_safety_layer()
        return self._safety_gate.apply(result, proposed, prev_action)

    @property
    def safety_config(self):
        """Access the underlying GMRobot SafetyConfig (lazy-init)."""
        self._init_safety_layer()
        return self._safety_config

    @property
    def rule_engine(self):
        """Access the underlying GMRobot RuleEngine (lazy-init)."""
        self._init_safety_layer()
        return self._rule_engine
