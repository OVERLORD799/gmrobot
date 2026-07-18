# GMDisturb — 模块接口定义

> **时效性**: 本文档已与代码同步 (2026-07-13)。若与代码矛盾，以代码为准。
> 经过 7 轮对抗性审查的逐方法交叉验证。上次同步: R7 fix batch (2026-07-13)。

> 本文档定义项目每个 Python 模块的类签名、方法签名、参数类型和返回值类型。  
> 所有接口基于 Isaac Lab 1.3.0 (`isaaclab.*`) 和两个原项目的实际 API。

## 模块状态

| 模块 | 状态 | 文件 |
|------|------|------|
| dual_env_cfg.py | ✅ IMPLEMENTED | 场景、观测、动作、命令、事件、终止 |
| g1_walk_controller.py | ✅ IMPLEMENTED | G1 行走策略加载器 (588D→12D) |
| g1_disturbance_controller.py | ✅ IMPLEMENTED | 扰动控制器 + 三档模式 + 卡住检测 + 脚本化场景 |
| g1_virtual_hand.py | ✅ IMPLEMENTED | 虚拟手 (平滑随机游走, 桌边障碍, EE 吸引器) |
| g1_arm_controller.py | ✅ IMPLEMENTED | 手臂控制器 (当前因行走策略限制不启用) |
| ur10e_controller.py | ✅ IMPLEMENTED | UR10e 状态机封装 |
| safety_adapter.py | ✅ IMPLEMENTED | G1EnvelopeAdapter + GMRobot 安全层桥接 |
| mat_event_detector.py | ✅ IMPLEMENTED | 压力垫事件检测 |
| test_metrics.py | ✅ IMPLEMENTED | Episode 指标 + CSV 输出 |
| g1_vlm_client.py | ✅ IMPLEMENTED | VLM 引导扰动 (端到端跑通, 见 project-delivery.md §3.4) |
| per_part_state.py | ✅ IMPLEMENTED | 逐零件测试协议 (Pick→Transit→Place→Reset) (R7) |
| batch_runner.py | ✅ IMPLEMENTED | 批量测试运行器 (2026-07-11) |
| run_disturbance_test.py | 🔲 REPLACED_BY | `scripts/run_phase3.py` |

---

## 1. `dual_env_cfg.py` — 联合环境配置

### 1.1 DualRobotSceneCfg

```python
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.utils import configclass

@configclass
class DualRobotSceneCfg(InteractiveSceneCfg):
    """Scene: G1 humanoid + UR10e arm + pressure mat + table + containers + parts."""

    # === Ground & Light ===
    ground: AssetBaseCfg
    dome_light: AssetBaseCfg

    # === Pressure Mat ===
    mat: AssetBaseCfg                         # 32x32 over 4m, static kinematic

    # === Robots ===
    robot_g1: ArticulationCfg                 # G1 29-DOF, prim_path={ENV_REGEX_NS}/Robot_G1
    robot_ur10e: ArticulationCfg              # UR10e 12-DOF, prim_path={ENV_REGEX_NS}/Robot_UR10e

    # === G1 Contact Sensors ===
    left_foot_sensor: ContactSensorCfg        # prim_path={ENV_REGEX_NS}/Robot_G1/left_ankle_roll_link
    right_foot_sensor: ContactSensorCfg       # prim_path={ENV_REGEX_NS}/Robot_G1/right_ankle_roll_link
    g1_contact_forces: ContactSensorCfg       # prim_path={ENV_REGEX_NS}/Robot_G1/.* — whole-body

    # === UR10e Workspace ===
    table: AssetBaseCfg                       # Seattle lab table at (0.6, 0, 0)
    container_a: AssetBaseCfg                 # Pick source at (0.75, -0.25, 0)
    container_b: AssetBaseCfg                 # Place target at (0.75, 0.25, 0)
    parts: list[RigidObjectCfg]              # 20 parts in container slots

    # === Cameras ===
    scene_camera: TiledCameraCfg             # Overhead view at (0.35, 0, 2.5)

    # === G1 Head Sensors (optional, configured for future use) ===
    # g1_head_camera: TiledCameraCfg          # Mounted on d435 body
    # g1_lidar: RayCasterCfg                  # Mounted on mid360 body
```

### 1.2 DualRobotDisturbanceEnvCfg

```python
from isaaclab.envs import ManagerBasedRLEnvCfg

@configclass
class DualRobotDisturbanceEnvCfg(ManagerBasedRLEnvCfg):
    """Combined environment config: G1 walking on mat + UR10e pick-and-place."""

    # === Simulation ===
    # sim.dt = 0.005 (200 Hz physics)
    # decimation = 4 (50 Hz control)
    # episode_length_s = 60.0 (extended for disturbance testing)

    # === Sub-configs ===
    scene: DualRobotSceneCfg
    observations: DualRobotObservationsCfg
    actions: DualRobotActionsCfg
    events: DualRobotEventsCfg
    commands: DualRobotCommandsCfg          # g1_base_velocity + ur10e_null
    terminations: DualRobotTerminationsCfg
    rewards: DualRobotRewardsCfg            # empty (no RL training)
```

### 1.3 DualRobotActionsCfg

```python
@configclass
class DualRobotActionsCfg:
    """20D combined action space.

    Dims 0-11:  G1 leg joints (12 DOF)
    Dims 12-19: UR10e EE pose + gripper (8D)
    """
    g1_joint_pos: WalkJointActionCfg        # asset_name="robot_g1", 12D, clip=[-100,100]
    ur10e_ee: DifferentialInverseKinematicsActionCfg  # asset_name="robot_ur10e", 8D
```

### 1.4 DualRobotObservationsCfg

```python
@configclass
class DualRobotObservationsCfg:
    """Grouped observations for both controllers.

    Obs dict structure after env.step():
      obs["g1_walker"]     → torch.Tensor (N, 588)
      obs["tactile"]       → torch.Tensor (N, 32, 32)
      obs["ur10e_policy"]  → dict[str, torch.Tensor]
      obs["ur10e_camera"]  → dict with "scene_rgb": (N, 480, 640, 3)
      obs["safety"]        → dict with ee_vel, joint_pos, joint_vel
      obs["g1_body"]       → dict with G1 body tracking (NEW)
    """
    g1_walker: ObsGroup       # 588D proprioceptive, 6-step history
    tactile: ObsGroup         # (32,32) Newton image
    ur10e_policy: ObsGroup    # ee_pose + part poses + box/slot poses
    ur10e_camera: ObsGroup    # scene RGB from overhead camera
    safety: ObsGroup          # ee_vel, joint_pos, joint_vel
    g1_body: ObsGroup         # NEW: root_pos, head_pos, hand_pos, foot_pos
```

### 1.5 G1 Body Observation Group (NEW)

```python
@configclass
class G1BodyObsGroup(ObsGroup):
    """G1 body part tracking for safety adapter — added to obs["g1_body"]."""
    g1_root_pos = ObsTerm(func=mdp.root_pos_w,
                          params={"asset_cfg": SceneEntityCfg("robot_g1")})
    g1_root_vel = ObsTerm(func=mdp.root_lin_vel_w,
                          params={"asset_cfg": SceneEntityCfg("robot_g1")})
    g1_root_ang_vel = ObsTerm(func=mdp.root_ang_vel_b,
                              params={"asset_cfg": SceneEntityCfg("robot_g1")})
    g1_head_pos = ObsTerm(func=g1_link_pos_w,
                          params={"body_name": "torso_link"})   # verify with body_names
    g1_left_hand_pos = ObsTerm(func=g1_link_pos_w,
                               params={"body_name": "left_wrist_pitch_link"})
    g1_right_hand_pos = ObsTerm(func=g1_link_pos_w,
                                params={"body_name": "right_wrist_pitch_link"})
    g1_left_foot_pos = ObsTerm(func=g1_link_pos_w,
                               params={"body_name": "left_ankle_roll_link"})
    g1_right_foot_pos = ObsTerm(func=g1_link_pos_w,
                                params={"body_name": "right_ankle_roll_link"})

    def __post_init__(self):
        self.concatenate_terms = False  # Return as dict for named access
```

---

## 2. `g1_walk_controller.py` — G1 行走策略封装

```python
import torch
import numpy as np

class G1WalkController:
    """Encapsulates the torchscript walking policy for G1.

    The policy is a fixed TorchScript model:
      Input:  (N, 588) proprioceptive observation
      Output: (N, 12)  leg joint targets (clipped to [-100, 100])

    Velocity commands are injected via env.command_manager, not through this class.
    """

    # === Constructor ===
    def __init__(self, policy_path: str, device: str = "cuda"):
        """
        Args:
            policy_path: Path to torchscript .pt file
            device: "cuda" or "cpu"
        """
        ...

    # === Public Methods ===
    def get_action(self, walker_obs: torch.Tensor) -> torch.Tensor:
        """
        Args:
            walker_obs: (N, 588) from obs["g1_walker"]
        Returns:
            (N, 12) leg joint targets, clipped to [-100, 100]
        """
        ...

    def set_velocity_command(
        self, env, vx: float, vy: float, wz: float
    ) -> None:
        """Inject velocity command into CommandManager.

        Args:
            env: Isaac Lab env instance
            vx: Forward velocity (m/s), range [-0.8, 0.8]
            vy: Lateral velocity (m/s), range [-0.5, 0.5]
            wz: Yaw rate (rad/s), range [-1.57, 1.57]
        """
        ...

    # === Properties ===
    @property
    def device(self) -> str: ...
    @property
    def policy(self) -> torch.jit.ScriptModule: ...
```

---

## 3. `g1_disturbance_controller.py` — G1 扰动行为控制

```python
from enum import Enum
import numpy as np

class DisturbanceMode(Enum):
    """Proximity-gated behaviour tier (v2 — distance-gated, 2026-07)."""
    AGGRESSIVE = "aggressive"   # d > 0.30 m: full wander
    MODERATE = "moderate"       # 0.15–0.30 m: slow + steer away
    CAUTIOUS = "cautious"       # d < 0.15 m: retreat
    STUCK = "stuck"             # stuck recovery in progress
    IDLE = "idle"               # initial / reset state

class DisturbancePhase(Enum):
    """Internal phase within the current mode."""
    IDLE = "idle"
    WANDER = "wander"
    RETREAT = "retreat"
    STUCK_RETREAT = "stuck_retreat"
    # APPROACH_ARM = "approach_arm"  # v1 design artifact — defined but never assigned


# === G1DisturbanceController ===
class G1DisturbanceController:
    """Distance-gated velocity command generator (single class, all modes).

    Mode selection (evaluated every step)::

        AGGRESSIVE  — G1-UR10e distance > 0.30 m : full wander
        MODERATE    — 0.15–0.30 m                : slow + steer away
        CAUTIOUS    — < 0.15 m                   : retreat (speed ramp)

    Scripted mode: when *scripted_phases* is provided, the controller
    follows a fixed phase sequence.  Distance-gated safety (MODERATE /
    CAUTIOUS) and stuck detection still override the script when G1
    gets too close or gets stuck.

    Stuck detection: when cmd_speed > 0.10 m/s but actual_speed < 0.02 m/s
    for 100 steps, force a contact-force-directed retreat.
    """

    def __init__(
        self,
        *,
        workspace_x: tuple[float, float] = (0.0, 0.8),
        workspace_y: tuple[float, float] = (-0.5, 0.5),
        cautious_threshold: float = 0.15,
        moderate_threshold: float = 0.30,
        speed_aggressive: float = 0.20,
        speed_moderate: float = 0.10,
        speed_cautious: float = 0.0,
        vy_scale: float = 0.0,
        vy_bias: float = 0.0,
        vx_bias: float = 0.0,
        resample_interval: int = 200,
        scripted_phases: list[ScriptedPhase] | None = None,
        seed: int = 42,
        control_dt: float = 0.02,  # M4 fix (2026-07-10): configurable control timestep
    ):
        """
        Args:
            workspace_x: (x_min, x_max) G1 root x bounds (metres)
            workspace_y: (y_min, y_max) G1 root y bounds (metres)
            cautious_threshold: distance (m) below which G1 retreats
            moderate_threshold: distance (m) below which G1 slows + steers away
            speed_aggressive: velocity multiplier in AGGRESSIVE mode
            speed_moderate: velocity multiplier in MODERATE mode
            speed_cautious: velocity multiplier in CAUTIOUS mode (0 = stop)
            vy_scale: lateral exploration scale for velocity commands (default 0.0)
            vy_bias: constant y-offset for approach-side steering (default 0.0)
            vx_bias: constant x-offset for forward/backward approaches (default 0.0)
            resample_interval: steps between velocity schedule resamples
            scripted_phases: list of ScriptedPhase for scripted scenarios
            seed: RNG seed for reproducible stuck-recovery direction
            control_dt: control timestep for stuck-detection speed calc
        """
        ...

    def update(
        self,
        g1_root_pos: np.ndarray,      # (3,) world position of G1 root
        ur10e_ee_pos: np.ndarray,     # (3,) world position of UR10e EE
        *,
        force_retreat: bool = False,
        contact_forces: np.ndarray | None = None,  # (37, 3) net contact forces
    ) -> np.ndarray:
        """Compute the next velocity command.

        Returns:
            (3,) velocity command (vx, vy, wz).
        """
        ...

    def reset(self) -> None:
        """Reset internal state for a new episode."""
        ...

    @property
    def mode(self) -> DisturbanceMode: ...
    @property
    def phase(self) -> DisturbancePhase: ...
    @property
    def command(self) -> np.ndarray: ...
    @property
    def distance(self) -> float: ...
    @property
    def arm_motion(self) -> str: ...
    @property
    def is_stuck(self) -> bool: ...
    @property
    def stuck_count(self) -> int: ...
```

---

## 4. `g1_vlm_client.py` — VLM 引导扰动

```python
import numpy as np

# Reuse GMRobot's VLMClient
from GMRobot.vlm.client import VLMClient

class G1VLMDisturbanceController(G1DisturbanceController):
    """VLM-guided G1 disturbance — queries Qwen2.5-VL-7B for adaptive behavior."""

    # === Constructor ===
    def __init__(
        self,
        vlm_client: VLMClient,
        workspace_bounds: dict,
        refresh_interval: int = 200,          # steps (~4s at 50Hz)
        vlm_prompt: str | None = None,        # Override default prompt
    ):
        """
        Args:
            vlm_client: Configured VLMClient instance (shared with GMRobot safety VLM)
            workspace_bounds: {"x_min", "x_max", "y_min", "y_max"}
            refresh_interval: Steps between VLM queries
            vlm_prompt: Custom prompt string, uses DEFAULT_PROMPT if None
        """
        ...

    # === Public Methods ===
    def get_velocity_command(
        self, step, g1_root_pos, ur10e_ee_pos, ur10e_phase
    ) -> tuple[float, float, float]:
        """Query VLM if cache expired, return velocity from cached decision."""
        ...

    def get_arm_targets(
        self, step, g1_contact_forces, g1_is_double_support
    ) -> dict[str, float]:
        """Convert VLM arm_motion decision → joint PD targets."""
        ...

    # === Internal ===
    def _query_vlm(self, camera_rgb: np.ndarray) -> dict:
        """Send RGB to VLM, parse JSON response.

        Args:
            camera_rgb: (H, W, 3) uint8 numpy array
        Returns:
            Parsed JSON dict with keys: arm_state, gripper_has_object,
            risk_assessment, disturbance_decision
        """
        ...

    def _motion_to_targets(self, arm_motion: str, step: int) -> dict[str, float]:
        """Map VLM high-level motion string → G1 joint targets.

        Mappings:
          "wave"            → sinusoidal shoulder_pitch + fixed elbow
          "extend_forward"  → shoulder_pitch=-2.0, elbow=0.0 (both arms)
          "extend_left"     → left arm forward, right arm at rest
          "extend_right"    → right arm forward, left arm at rest
          "none"            → default position
        """
        ...

    # === Constants ===
    # DEFAULT_PROMPT: str — the full VLM prompt (see SCENARIOS.md appendix)
```

---

## 5. `ur10e_controller.py` — UR10e 状态机适配器

> **Synced 2026-07-13.** 类名 `UR10eController`（不是 v1 设计的 `UR10eControllerAdapter`）。

```python
import numpy as np
from scripts.pick_and_place_policy import SingleEnvPickAndPlacePolicy

class UR10eController:
    """Wraps SingleEnvPickAndPlacePolicy for the combined observation dict."""

    # === Constructor ===
    def __init__(self):
        """
        Creates a SingleEnvPickAndPlacePolicy() internally.
        No arguments — the policy is self-contained.
        """
        ...

    # === Public Methods ===
    @staticmethod
    def cpu_obs(obs_dict: dict) -> dict:
        """Convert a CUDA-tensor observation dict to CPU numpy."""
        ...

    def reset(self, ur10e_policy_obs: dict) -> None:
        """Build the stage sequence from current environment observations."""
        ...

    def get_action(self, ur10e_policy_obs: dict, *, advance: bool = True) -> np.ndarray:
        """Get next UR10e action from the state machine.

        Args:
            ur10e_policy_obs: obs["ur10e_policy"] dict (may contain CUDA tensors).
            advance: if True (default), increment the policy clock after getting action.
        Returns:
            np.ndarray (8,) — [x, y, z, qw, qx, qy, qz, gripper]
        """
        ...

    def advance(self) -> None:
        """Manually advance the policy clock (use when advance=False was passed)."""
        ...

    # === Properties ===
    @property
    def success(self) -> bool:
        """True if all 20 parts have been placed."""
        ...

    @property
    def time_step(self) -> int:
        """Current policy clock step."""
        ...

    @property
    def step_counter(self) -> int:
        """Total get_action() calls (including non-advancing)."""
        ...

    @property
    def parts_placed(self) -> int:
        """Number of parts whose full pick-and-place cycle has completed.
        Computed from stage transitions, not time_step / constant."""
        ...

    @property
    def stage_name(self) -> str:
        """UR10e stage name: e.g. 'move_above_slot_3', 'descend_to_box_with_5'."""
        ...

    @property
    def transport_phase(self) -> str:
        """Transport phase for replan trigger: 'approach' | 'transit' | 'place'.
        Delegates to self._policy.transport_phase_at_step()."""
        ...

    @property
    def is_grasping(self) -> bool:
        """True when the gripper is closed and holding a part."""
        ...

    @property
    def total_parts(self) -> int:
        """Number of parts in the user command sequence."""
        ...
```

---

## 6. `safety_adapter.py` — G1 全身 → 安全层桥接

> **Synced 2026-07-13.** Actual implementation uses lazy importlib loading; no IntegratedSafetyGate wrapper class.

```python
import numpy as np

class G1EnvelopeAdapter:
    """Bridges G1 full-body FK state → GMRobot safety layer.

    All safety methods (RuleEngine, SafetyGate, build_safety_state,
    evaluate_safety, apply_safety_gate) are on this single class.
    There is no separate IntegratedSafetyGate wrapper.
    """

    # TRACKED_BODIES — all bodies for FK position + velocity tracking (logging/metrics).
    # SAFETY_BODIES  — subset reported to RuleEngine as closest-body candidates
    #                   (W3 fix: only hands + head; torso/shoulders/elbows filtered).
    TRACKED_BODIES = { ... }   # 8 bodies
    SAFETY_BODIES  = { ... }   # 3 bodies: head_link + left/right_wrist_pitch_link

    # === Constructor ===
    def __init__(self, *, safety_config_path: str | None = None, control_dt: float = 0.02):
        """
        Args:
            safety_config_path: Path to GMRobot safety YAML.  If None, uses defaults.
            control_dt: control timestep for finite-difference velocity.
        """
        ...

    # === Per-step update ===
    def update(self, robot, ur10e_ee_pos: np.ndarray) -> None:
        """Read G1 body positions, compute closest surface distance to UR10e EE."""
        ...

    # === Phase 3: GMRobot safety layer integration ===
    def build_safety_state(self, policy_obs, safety_obs, *, step_index, sim_time=None) -> object:
        """Build a GMRobot SafetyState from adapter + UR10e observations."""
        ...

    def evaluate_safety(self, state, *, held_object_active=False,
                        functional_risk_info=None, dist_for_gating=None,
                        dist_min_held=None) -> object:
        """Run the GMRobot RuleEngine on a SafetyState.  Returns GateResult."""
        ...

    def apply_safety_gate(self, result, proposed: np.ndarray,
                          prev_action: np.ndarray) -> np.ndarray:
        """Apply the safety gate decision to the proposed UR10e action."""
        ...

    # === Properties ===
    human_hand_pos: np.ndarray     # (3,) — world position of closest body
    human_hand_vel: np.ndarray     # (3,) — finite-difference velocity
    human_torso_pos: np.ndarray    # (3,) — torso_link world position
    human_torso_vel: np.ndarray    # (3,)
    closest_body_name: str          # name of the closest SAFETY_BODIES entry
    closest_body_distance: float    # surface-to-surface distance (m)
    safety_config: object           # GMRobot SafetyConfig (lazy-init)
    rule_engine: object             # GMRobot RuleEngine (lazy-init)


# === Module-level helpers ===

def _get_safety_imports() -> dict:
    """Lazy-import GMRobot safety classes via importlib.util.
    Returns dict with keys: SafetyConfig, load_safety_config, SafetyState,
    GateDecision, GateResult, RuleEngine, SafetyGate."""

def _get_replan_imports() -> dict:
    """Lazy-import GMRobot replan classes via importlib.util.
    Returns dict with keys: GeometryReplanV0, L1WarnReplanTrigger,
    ReplanRuntimeState, ReplanTriggerConfig."""
```
```

---

## 7. `mat_event_detector.py` — 压力垫事件分类

```python
import numpy as np
import torch

@dataclass
class MatEvent:
    """Single pressure mat event."""
    step: int
    type: str                # "footstep_left" | "footstep_right" | "object_drop"
                             # | "collision_impact" | "unknown"
    position_xy: tuple[float, float]  # World (x, y) in meters
    force_n: float           # Total normal force (Newtons)
    cluster_area: int        # Number of taxels in the cluster
    taxels: list[tuple[int, int]]  # (row, col) indices of cluster taxels


@dataclass
class Footstep:
    """Single footstep event."""
    side: str                # "left" | "right"
    position_xy: tuple[float, float]
    force_n: float
    step: int


class MatEventDetector:
    """Detect and classify events from the (32, 32) pressure mat tactile image."""

    # === Constants ===
    FORCE_THRESHOLD: float = 5.0        # N — below this is noise
    DROP_THRESHOLD: float = 10.0        # N — frame-diff transient threshold
    COLLISION_FORCE: float = 50.0       # N — minimum for collision_impact
    DROP_MAX_AREA: int = 4              # taxels — small cluster = likely object
    WORKSPACE_X_RANGE: tuple[float, float] = (0.3, 1.0)  # Where UR10e workspace is
    FOOT_PROXIMITY: float = 0.3         # m — max distance from expected foot pos

    # === Constructor ===
    def __init__(
        self,
        rows: int = 32,
        cols: int = 32,
        mat_size_x: float = 4.0,
        mat_size_y: float = 4.0,
    ):
        """
        Args:
            rows, cols: Mat resolution
            mat_size_x, mat_size_y: Mat physical size in meters
        """
        ...

    # === Core Method ===
    def detect_events(
        self,
        tactile_image: torch.Tensor,        # (N, rows, cols) — from obs["tactile"]
        g1_root_pos: np.ndarray,            # (3,) G1 pelvis world position
        g1_left_foot_pos: np.ndarray,       # (3,) from FK
        g1_right_foot_pos: np.ndarray,      # (3,) from FK
        ur10e_ee_pos: np.ndarray,           # (3,) from FK
        part_positions: dict[str, np.ndarray],  # part_name → (3,) world pos
        env_idx: int = 0,
    ) -> list[MatEvent]:
        """Full event detection pipeline.

        Steps:
        1. Find connected components (clusters of active taxels >5N)
        2. Classify each cluster by spatial proximity
        3. Detect transients via frame differencing (object drops)
        4. Return all events for this step
        """
        ...

    # === Internal Methods ===
    def _find_clusters(
        self, img: np.ndarray, threshold: float
    ) -> list[dict]:
        """Find connected components in the tactile image.

        Uses scipy.ndimage.label or simple flood-fill.
        Returns list of {mask, centroid, total_force, area}.
        """
        ...

    def _classify_cluster(
        self,
        centroid_xy: tuple[float, float],
        force: float,
        area: int,
        g1_root_pos: np.ndarray,
        g1_left_foot_pos: np.ndarray,
        g1_right_foot_pos: np.ndarray,
        ur10e_ee_pos: np.ndarray,
    ) -> str:
        """Classify a force cluster by proximity to known entities."""
        ...

    def _detect_transients(
        self, current: np.ndarray, previous: np.ndarray | None
    ) -> list[MatEvent]:
        """Detect sudden new contacts via frame differencing.

        Small-area (<4 taxels), high-force (>10N) transients near workspace
        are classified as object drops.
        """
        ...

    def _taxel_to_world(
        self, row: int, col: int
    ) -> tuple[float, float]:
        """Convert (row, col) taxel index → world (x, y) position."""
        ...

    # === Gait Tracking ===
    def get_footstep_trajectory(self) -> list[Footstep]:
        """Extract footstep sequence from accumulated events."""
        ...

    def reset(self) -> None:
        """Clear accumulated events and frame buffer for new episode."""
        ...
```

---

## 8. `test_metrics.py` — 测试指标收集

> **Synced 2026-07-13.** v1's DisturbanceTestMetrics / StepRecord / EpisodeSummary were replaced by a simpler EpisodeMetrics dataclass + MetricsWriter. No per-step records — only per-episode CSV rows.

```python
from dataclasses import dataclass, field

@dataclass
class EpisodeMetrics:
    """Aggregated metrics for one disturbance-test episode."""

    episode_id: int = 0

    # Timing
    total_steps: int = 0
    policy_steps: int = 0           # UR10e policy clock

    # UR10e task
    parts_placed: int = 0
    parts_total: int = 20
    task_completed: bool = False

    # G1 state
    g1_fell: bool = False
    g1_root_z_min: float = 0.0
    g1_root_z_final: float = 0.0

    # Interventions (safety gate)
    tier0_stop_count: int = 0
    slowdown_count: int = 0
    replan_count: int = 0
    stuck_count: int = 0

    # D-group: disturbance effects (causal inference)
    d_stop_caused: int = 0
    d_slow_caused: int = 0
    d_replan_caused: int = 0
    d_knock_off: int = 0

    # Mat events
    footstep_count: int = 0
    collision_count: int = 0
    object_drop_count: int = 0

    # Proximity
    min_g1_ur10e_distance_m: float = float("inf")
    min_surface_distance_m: float = float("inf")
    mean_g1_ur10e_distance_m: float = 0.0

    # F-group: safety response enhanced
    f_consecutive_stop_max: int = 0
    f_replan_success: bool = False
    f_replan_failure_reason: str = ""

    # H-group: VLM decision log
    h_vlm_action: str = ""
    h_vlm_latency_ms: float = 0.0
    h_vlm_reason: str = ""

    # T1: latest safety gate state
    last_gate_decision: str = "N/A"
    last_gate_trigger: str = ""
    last_gate_distance: float = float("inf")
    last_closest_body: str = ""

    # === Methods ===
    def record_step(self, *, g1_root_z, g1_ur10e_distance, surface_distance=inf,
                    mat_events=None, gate_decision=None, gate_trigger="",
                    gate_distance=inf, closest_body="",
                    disturbance_active=False, consecutive_gate_count=0,
                    replan_success=None, replan_failure_reason="",
                    vlm_action="", vlm_latency_ms=0.0, vlm_reason="") -> None:
        """Update per-step accumulators.  All keyword-only args."""
        ...

    def finalise(self) -> None:
        """Compute derived fields after episode ends."""
        ...

    def as_dict(self) -> dict:
        """Return all fields as a flat dict for CSV writing."""
        ...

    def to_json_dict(self) -> dict:
        """JSON-serializable dict for batch runner JSONL output."""
        ...


class MetricsWriter:
    """Appends episode metrics to CSV and JSON files."""

    def __init__(self, path: str): ...
    def write(self, metrics: EpisodeMetrics) -> None: ...
```

---

## 9. `batch_runner.py` — 批量测试运行器

```python
class BatchTestRunner:
    """Runs multiple test configurations and aggregates results."""

    # === Constructor ===
    def __init__(self, config_dir: str, output_dir: str):
        """
        Args:
            config_dir: Path to batch_test_configs/ with YAML files
            output_dir: Path for results CSV/JSON/video output
        """
        ...

    # === Main ===
    def run_all(self, *, max_parallel: int = 1, timeout_s: int = 3600) -> dict:
        """Run all configs, return aggregated summary.

        For each YAML config:
          1. Load scenario + safety config
          2. Spawn run_phase3.py subprocess
          3. Run episode
          4. Parse CSV into EpisodeResult
          5. Save batch_summary.json

        Returns:
            {"runs": [...], "comparison_table": {...}}
        """
        ...

    def run_single(self, config_path: str, *, timeout_s: int = 3600) -> EpisodeResult:
        """Run a single test configuration.

        Args:
            config_path: Path to one YAML config file
            timeout_s: Per-episode timeout in seconds.
        Returns:
            EpisodeResult for this run
        """
        ...

    # === Output ===
    def generate_comparison_report(self) -> str:
        """Generate a markdown comparison table across all configs.

        Columns: config_name | knock_off_rate | recovery_rate |
                 mean_latency | intervention_rate | parts_completed
        """
        ...

    def save_batch_summary(self, path: str) -> None:
        """Save JSON summary of all runs."""
        ...
```

---

## 10. `scripts/run_disturbance_test.py` — 主入口  🔲 REPLACED_BY `scripts/run_phase3.py`

> **This file has been deleted.** All functionality has moved to `scripts/run_phase3.py`.
> The interface below is kept for historical reference only. Do not use as an entry point.

```python
"""
FORMER main entry point for G1-UR10e disturbance testing — REPLACED by run_phase3.py.

Usage (historical):
    # Default mode (FK + state machine + constrained wander)
    ./isaaclab.sh -p scripts/run_disturbance_test.py \
        --task G1-UR10e-Disturbance-v0 \
        --policy /path/to/0121_walk.pt \
        --mode constrained_wander \
        --safety_config configs/safety_fusion.yaml \
        --num_steps 10000

    # VLM exploration mode
    ./isaaclab.sh -p scripts/run_disturbance_test.py \
        --task G1-UR10e-Disturbance-v0 \
        --mode vlm_guided \
        --enable_vlm \
        --vlm_config configs/vlm_client.yaml

    # Batch mode
    ./isaaclab.sh -p scripts/run_disturbance_test.py \
        --batch batch_test_configs/ \
        --output results/
"""

def parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Key arguments:
      --task: Gym task ID (default: G1-UR10e-Disturbance-v0)
      --num_envs: Number of parallel envs (default: 1)
      --policy: Path to G1 walking policy .pt file
      --mode: "scripted" | "constrained_wander" | "vlm_guided"
      --scenario: Scenario name for scripted mode (table_bump, arm_wave, ...)
      --safety_config: Path to GMRobot safety YAML
      --enable_vlm, --vlm_config: VLM-specific
      --enable_lidar: Add G1 head LiDAR sensor
      --enable_head_camera: Add G1 head camera sensor
      --headless: Run without GUI
      --record_video: Output directory for video recording
      --output: Output directory for metrics CSV/JSON
      --num_steps: Max simulation steps
      --batch: Batch config directory (enables batch mode)
      --seed: Random seed
      --device: "cuda" or "cpu"
    """
    ...

def main():
    """
    Control loop (pseudocode):

    args = parse_args()
    env_cfg = parse_env_cfg(args.task, num_envs=args.num_envs)
    env = gym.make(args.task, cfg=env_cfg)

    # Init controllers
    g1_walker = G1WalkController(args.policy, args.device)
    g1_disturbance = _create_disturbance_controller(args)  # factory
    ur10e_ctrl = UR10eControllerAdapter()
    safety_gate = IntegratedSafetyGate(SafetyConfig.from_yaml(args.safety_config))
    mat_detector = MatEventDetector()
    metrics = DisturbanceTestMetrics(args.scenario, args.safety_config)

    if args.enable_head_camera:
        _add_head_camera(env_cfg)
    if args.enable_lidar:
        _add_lidar(env_cfg)

    obs, _ = env.reset()

    while simulation_app.is_running():
        # 1. Get G1 velocity command
        vx, vy, wz = g1_disturbance.get_velocity_command(
            step, g1_root_pos, ur10e_ee_pos, ur10e_ctrl.current_phase
        )

        # 2. Inject command → CommandManager
        g1_walker.set_velocity_command(env, vx, vy, wz)

        # 3. G1 walking policy inference
        g1_action = g1_walker.get_action(obs["g1_walker"])

        # 4. G1 arm PD targets
        arm_targets = g1_disturbance.get_arm_targets(
            step, g1_contact_forces, g1_is_double_support
        )
        _write_g1_arm_joint_targets(env, arm_targets)

        # 5. UR10e action
        ur10e_action = ur10e_ctrl.get_action(obs, advance=False)

        # 6. Safety gate
        safe_ur10e_action, gate_result = safety_gate.apply(
            ur10e_action, prev_ur10e_action, g1_body_obs,
            ur10e_ee_pos, ur10e_ee_vel, ur10e_joint_pos, ur10e_joint_vel,
            arm_link_positions, sim_time, step,
        )

        # 7. Combine and step
        combined_action = torch.cat([g1_action, torch.from_numpy(safe_ur10e_action).unsqueeze(0)], dim=-1)
        obs, reward, terminated, truncated, info = env.step(combined_action)

        # 8. Mat events
        mat_events = mat_detector.detect_events(...)

        # 9. Record metrics
        metrics.record_step(...)

        # 10. Advance UR10e clock
        if gate_result.g_t != GateDecision.STOP:
            ur10e_ctrl.advance_time_step()

        # 11. Episode end check
        if terminated.any() or step >= args.num_steps:
            summary = metrics.build_episode_summary()
            metrics.save_step_csv(f"{args.output}/steps_{run_id}.csv")
            metrics.save_episode_json(f"{args.output}/episode_{run_id}.json")
            break

        step += 1
    """
    ...


# === Helpers ===
def _create_disturbance_controller(args) -> G1DisturbanceController:
    """Factory: return correct controller based on --mode."""
    ...

def _add_head_camera(env_cfg) -> None:
    """Add TiledCameraCfg to G1 d435 body in env_cfg.scene."""
    ...

def _add_lidar(env_cfg) -> None:
    """Add RayCasterCfg to G1 mid360 body in env_cfg.scene."""
    ...

def _write_g1_arm_joint_targets(env, targets: dict[str, float]) -> None:
    """Write PD targets to G1 arm joints.

    Reads current 29D joint_pos_target from robot_g1,
    overwrites arm joint entries, calls set_joint_position_target.
    """
    ...
```

---

## 11. `g1_virtual_hand.py` — G1VirtualHand

**Class:** `G1VirtualHand(radius=0.45, speed=0.12, height_mode="table", seed=42, attractor=(0.8, 0.0), pursuit_mode=False, retreat_steps=400)`

Virtual hand sphere that drifts near G1's head, providing a configurable safety-gate trigger independent of physical arm kinematics.

**Key constructor parameters:**
- `radius` (float): max XY distance from head (m). Default 0.45.
- `speed` (float): max drift speed in random-walk mode (m/s). Default 0.12.
- `height_mode` (str): "table" = track UR10e EE Z; "head" = head Z + 0.2 m.
- `pursuit_mode` (bool): when True, hand actively pursues the container corridor as a dynamic blocking point for replan testing.
- `retreat_steps` (int): steps to retreat after on_replan() (default 400 = 8 s at 50 Hz).

**Key methods:**
- `step(dt, head_pos, ee_z=None)` — advance one timestep.
- `on_replan()` — retreat hand to head for `retreat_steps` steps, cycling approach angle.
- `reset()` — clear cycle state for new episode.
- `position` (property) — world-frame XYZ of the virtual hand sphere.

**Block-retreat-reblock cycle (pursuit_mode):**
1. BLOCK: hand reaches toward container corridor (x=0.75), clamped by head reach radius.
2. REPLAN fires → `on_replan()` sets retreat counter.
3. RETREAT: hand springs back toward head for 8 s while UR10e completes detour + current part.
4. REDEPLOY: on safe stage transition (lift/move-above), hand returns to corridor at a new angle (0°, ±25°, ±40° cycled).

---

## 12. `per_part_state.py` — 逐零件测试协议 (R7)

**Class:** `PerPartTester(user_commands: list[dict[str, str]])`

四阶段逐零件循环：PICK（手跟随 EE 测 STOP）→ TRANSIT（手挡路径测 replan）→ PLACE（手跟随 EE）→ RESET（手撤回，UR10e 自由完成）。

**Phase enum:** `PICK`, `TRANSIT`, `PLACE`, `RESET`

**Key constructor parameters:**
- `user_commands`: from `SingleEnvPickAndPlacePolicy.user_commands`, e.g. `[{"pick": "A@3", "place": "B@5"}, ...]`

**Key methods:**
- `update(stage_name, ee_pos, head_pos, is_grasping)` — advance state machine
- `attractor_xy` (property) — `np.ndarray | None`, hand target position; `None` = retreat
- `phase` (property) — current `Phase`
- `part_index` (property) — 0-based part index
- `parts_total` (property) — total parts in user_commands

**Phase parameters:**
| Phase | Hand Radius | Attractor | Timeout | Purpose |
|-------|------------|-----------|---------|---------|
| PICK | 0.08 | EE XY | 900 steps | Test STOP during grasp |
| TRANSIT | 0.22 | Path midpoint + 0.10m offset | 200 steps | Test replan detour |
| PLACE | 0.08 | EE XY | 900 steps | Test STOP during place |
| RESET | unchanged | None (retreat) | 900 steps | UR10e completes freely |

**Timeout escalation:** PICK→TRANSIT (test transit), TRANSIT→RESET (stuck, retreat), PLACE→RESET, RESET→next part PICK.

**Container coordinates:** A=(0.75, -0.25), B=(0.75, 0.25). Slot Z = 0.05 + (slot_num - 1) × 0.04.

---

## 13. 交叉引用索引

| 模块 | 依赖 |
|------|------|
| `dual_env_cfg.py` | `pressure_mat_deploy.robot_cfg.G1_927_WALK_CFG`, `pressure_mat_deploy.mdp.observations`, `gmrobot.gmrobot_env_cfg.UR10E_CFG`, `gmrobot.ur10e_cfg.UR10E_CFG`, `isaaclab.envs.ManagerBasedRLEnvCfg` |
| `per_part_state.py` | `numpy`, `re` (no Isaac Lab dependency) |
| `g1_walk_controller.py` | `torch.jit`, `isaaclab.envs.ManagerBasedEnv` |
| `g1_disturbance_controller.py` | `numpy` only (no Isaac Lab dependency) |
| `g1_vlm_client.py` | `requests`, `PIL.Image`, `config_loader` (lazy) |
| `ur10e_controller.py` | `scripts.pick_and_place_policy.SingleEnvPickAndPlacePolicy` |
| `safety_adapter.py` | `importlib.util` (lazy-loads GMRobot safety + replan modules) |
| `mat_event_detector.py` | `torch`, `numpy`, `scipy.ndimage` |
| `test_metrics.py` | `csv`, `json` (no GMRobot dependency) |
| `batch_runner.py` | `test_metrics`, `yaml`, `subprocess`, `pathlib` |
| `scripts/run_phase3.py` | All of the above + `isaaclab.app.AppLauncher` |
